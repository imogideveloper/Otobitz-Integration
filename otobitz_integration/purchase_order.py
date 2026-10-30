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
