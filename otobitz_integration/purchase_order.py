import frappe
from frappe.utils import flt, now_datetime

WF = "PO Approval Workflow"
PENDING = {"Pending Approval": "Pending", "Approved": "Approved", "Rejected": "Rejected"}


def _child(dt, po, field, **v):
	frappe.get_doc({"doctype": dt, "parent": po.name, "parenttype": "Purchase Order", "parentfield": field, **v}).insert(ignore_permissions=True)


def track(po, method=None):
	"""Append Approval History row (+ Approval Matrix once) when workflow_state changes. Runs before save so rows persist with the doc."""
	if not po.workflow_state:
		return
	before = po.get_doc_before_save()
	old = before.workflow_state if before else None
	if old == po.workflow_state:
		return
	role = frappe.db.get_value("Workflow Transition", {"parent": WF, "state": old, "next_state": po.workflow_state}, "allowed") if old else None
	po.append("custom_approval_history", {"role": role, "user": frappe.session.user, "date": now_datetime(), "state": po.workflow_state})
	if not po.get("custom_approval_matrix"):
		appr = frappe.db.get_value("Workflow Transition", {"parent": WF, "next_state": "Approved"}, "allowed")
		po.append("custom_approval_matrix", {"sequence": 1, "role": appr, "minimum_approval": 1, "minimum_amount": 0, "maximum_amount": 0})
	for m in po.get("custom_approval_matrix"):
		m.approval_status = PENDING.get(po.workflow_state, "")


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
