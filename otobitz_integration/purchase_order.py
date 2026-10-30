import frappe
from frappe.model.naming import getseries
from frappe.utils import flt, now_datetime

WF = "PO Approval Workflow"

def set_branch_naming_series(doc, method=None):
	"""Odoo-style PO numbering: {branch_code}-P{counter}, e.g. 503-P30255.

	Same decoupled-counter approach as Sales Invoice's
	set_branch_naming_series (see sales_invoice.py) - set doc.name directly,
	keyed only by branch code, so the counter never resets. Falls back to
	the stock naming_series when the PO has no branch yet.
	"""
	branch_code = doc.custom_otobitz_branch and frappe.db.get_value(
		"Branch", doc.custom_otobitz_branch, "custom_otobitz_branch_code"
	)
	if not branch_code:
		doc.naming_series = "PUR-ORD-.YYYY.-"
		return

	series_key = f"{branch_code}-P-"
	counter = getseries(series_key, 5)
	doc.name = f"{branch_code}-P{counter}"


def _child(dt, po, field, **v):
	frappe.get_doc({"doctype": dt, "parent": po.name, "parenttype": "Purchase Order", "parentfield": field, **v}).insert(ignore_permissions=True)


def track(po, method=None):
	"""Append Approval History row when workflow_state changes. Runs before save so rows persist with the doc.

	Matrix rows are added manually by the user and their approval_status is
	driven by approval.apply_approval_action - this only logs the coarse
	workflow_state transition, it does not touch custom_approval_matrix.
	"""
	if not po.workflow_state:
		return
	before = po.get_doc_before_save()
	old = before.workflow_state if before else None
	if old == po.workflow_state:
		return
	role = frappe.db.get_value("Workflow Transition", {"parent": WF, "state": old, "next_state": po.workflow_state}, "allowed") if old else None
	po.append("custom_approval_history", {"role": role, "user": frappe.session.user, "date": now_datetime(), "state": po.workflow_state})

	# Confirmation Date used to be stamped only from client JS
	# (after_workflow_action in the PO form script), which only fires when a
	# human clicks the workflow action button in that exact form session -
	# an API-driven transition, a bulk action, or the user navigating away
	# before frm.reload_doc() finishes all skip it entirely (confirmed: POs
	# exist with workflow_state=Approved and this field still empty). This
	# hook already observes every old->new workflow_state transition
	# regardless of how it was triggered, so it's the reliable place to set
	# it instead - fill-only-if-empty, same pattern as the other
	# auto-defaulted dates in this app (see sales_invoice.py).
	if po.workflow_state == "Approved" and not po.custom_confirmation_date:
		po.custom_confirmation_date = now_datetime()


def refresh_advance(po_name):
	"""Rebuild Advance Payment table + Sisa Uang Muka from submitted Payment Entries."""
	if not frappe.db.exists("Purchase Order", po_name):
		return
	po = frappe.get_doc("Purchase Order", po_name)
	frappe.db.delete("PO Advance Payment", {"parent": po_name})
	rows = frappe.db.sql(
		"""select pe.name, pe.posting_date, pe.party, pe.paid_from, pe.mode_of_payment, pe.paid_from_account_currency cur, r.allocated_amount
		from `tabPayment Entry Reference` r join `tabPayment Entry` pe on pe.name = r.parent
		where r.reference_doctype = 'Purchase Order' and r.reference_name = %s and pe.docstatus = 1 and pe.payment_type = 'Pay'
		order by pe.posting_date, pe.creation""", po_name, as_dict=True)
	paid = 0
	for i, r in enumerate(rows, 1):
		paid += flt(r.allocated_amount)
		_child("PO Advance Payment", po, "custom_advance_payments", idx=i, payment_name=r.name, payment=r.name, payment_date=r.posting_date,
			partner=r.party, payment_journal=r.paid_from, payment_method=r.mode_of_payment, amount=r.allocated_amount,
			currency=r.cur, advance_paid=r.allocated_amount, total_amount=po.grand_total, state="Posted")
	billed = sum(flt(i.billed_amt) for i in po.items)
	# ponytail: Sisa = advance paid - billed amount; ignores advances already allocated to bills, add if reconciliation is needed
	frappe.db.set_value("Purchase Order", po_name, "custom_sisa_uang_muka", max(paid - billed, 0), update_modified=False)


def track_on_submit(po, method=None):
	"""Confirmation Date + Approval History for a PO submitted directly
	(insert() -> submit(), the path every sync module uses - no Workflow
	Action button involved), where track() above never fires.

	Frappe's own Document._validate() (not this app's code) only moves
	workflow_state from empty to the submitted Workflow State's name
	*after* the `validate` hook has already run - so track()'s guard
	(`if not po.workflow_state: return`) always bails on these, forever,
	not just for POs synced before some fix: every synced PO takes this
	exact path. on_submit runs once workflow_state is final and the row
	is already saved, so this writes straight to the DB instead of
	appending through the in-memory doc (which would need another save).
	Guarded by "no existing history row" so a PO that *did* go through a
	real workflow transition (track() already logged it) isn't double
	logged.
	"""
	if not po.workflow_state or frappe.db.exists("PO Approval History", {"parent": po.name, "parenttype": "Purchase Order"}):
		return
	role = frappe.db.get_value("Workflow Transition", {"parent": WF, "next_state": po.workflow_state}, "allowed")
	_child("PO Approval History", po, "custom_approval_history", role=role, user=frappe.session.user, date=now_datetime(), state=po.workflow_state)
	if po.workflow_state == "Approved" and not po.custom_confirmation_date:
		frappe.db.set_value("Purchase Order", po.name, "custom_confirmation_date", now_datetime(), update_modified=False)


def on_payment_entry(pe, method=None):
	for r in pe.get("references") or []:
		if r.reference_doctype == "Purchase Order":
			refresh_advance(r.reference_name)


def on_purchase_invoice(pi, method=None):
	for po in {i.purchase_order for i in pi.items if i.purchase_order}:
		refresh_advance(po)


@frappe.whitelist()
def backfill_confirmation_date() -> dict:
	"""One-off: track()'s custom_confirmation_date stamp (see above) only
	fires on a workflow_state *transition* - every PO that was already
	sitting at workflow_state=Approved before that hook shipped never had a
	save happen afterward, so it's permanently stuck empty regardless of how
	long the hook has existed. The exact moment of that Draft->Approved
	transition is still recoverable from the Version doctype (Frappe's own
	change log) - each Version row's `data` is a JSON blob with a `changed`
	list of [fieldname, old, new] tuples; walked in creation order so a PO
	that bounced through multiple states (e.g. rejected then re-approved)
	gets the actual transition instead of an earlier/later one. Falls back
	to the document's own `creation` timestamp on the rare PO with no
	matching Version row (confirmed: a 300-row sample from prod had 100%
	coverage, so this fallback is a safety net, not the common path)."""
	frappe.only_for("System Manager")
	import json

	po_rows = frappe.get_all(
		"Purchase Order",
		filters={"workflow_state": "Approved", "custom_confirmation_date": ["is", "not set"]},
		fields=["name", "creation"],
	)
	checked = fixed = 0
	for i, po_row in enumerate(po_rows):
		if i % 50 == 0:
			frappe.db.commit()
		checked += 1
		versions = frappe.get_all(
			"Version", filters={"ref_doctype": "Purchase Order", "docname": po_row.name}, fields=["data", "creation"], order_by="creation asc"
		)
		approved_at = None
		for v in versions:
			try:
				data = json.loads(v.data)
			except (TypeError, ValueError):
				continue
			for change in data.get("changed", []):
				if len(change) >= 3 and change[0] == "workflow_state" and change[2] == "Approved":
					approved_at = v.creation
					break
			if approved_at:
				break
		frappe.db.set_value(
			"Purchase Order", po_row.name, "custom_confirmation_date", approved_at or po_row.creation, update_modified=False
		)
		fixed += 1
	frappe.db.commit()
	return {"checked": checked, "fixed": fixed}


@frappe.whitelist()
def backfill_naming_series() -> dict:
	"""One-off: set_branch_naming_series() (above) only started applying to
	Purchase Orders created after it shipped (2026-10-23 21:49:59) - every
	PO synced before that is stuck on the stock PUR-ORD-.YYYY.- naming
	series instead of {branch_code}-P{counter} (confirmed: every single one
	of 1419 prod POs predates that deploy). Renames each in creation order
	(oldest first) so the counter sequence reads chronologically, same as
	if they'd been named correctly from the start. frappe.rename_doc()
	handles updating every Link field across the system that points at the
	old name (Sales Order Item.purchase_order, Purchase Invoice
	Item.purchase_order, etc.) - confirmed via DocField scan this app
	doesn't store any PO name as a plain-text reference anywhere that
	would be missed. force=True bypasses Purchase Order's own
	allow_rename=0 (not block-worthy here: a rename only changes the
	primary key, nothing about the document's content or its accounting
	postings, which are keyed by voucher_no at the GL Entry level and
	updated the same way any other rename updates Link fields)."""
	frappe.only_for("System Manager")
	po_rows = frappe.get_all(
		"Purchase Order",
		filters={"naming_series": "PUR-ORD-.YYYY.-", "custom_otobitz_branch": ["is", "set"]},
		fields=["name", "custom_otobitz_branch"],
		order_by="creation asc",
	)
	checked = fixed = skipped = failed = 0
	for po_row in po_rows:
		checked += 1
		branch_code = frappe.db.get_value("Branch", po_row.custom_otobitz_branch, "custom_otobitz_branch_code")
		if not branch_code:
			skipped += 1
			continue
		new_name = f"{branch_code}-P{getseries(f'{branch_code}-P-', 5)}"
		try:
			frappe.rename_doc("Purchase Order", po_row.name, new_name, force=True, show_alert=False, rebuild_search=False)
			frappe.db.set_value("Purchase Order", new_name, "naming_series", None, update_modified=False)
			frappe.db.commit()
			fixed += 1
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"OtoBitz: failed to backfill naming series for Purchase Order {po_row.name}")
			failed += 1
	return {"checked": checked, "fixed": fixed, "skipped": skipped, "failed": failed}
