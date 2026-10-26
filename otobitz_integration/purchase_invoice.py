import frappe
from frappe.model.naming import getseries
from frappe.utils import now_datetime

WF = "PI Approval Workflow"


def set_branch_naming_series(doc, method=None):
	"""Odoo-style invoice numbering: {branch_code}-BPH/{MM}/{YYYY}/{counter}.

	Same decoupled-counter approach as Sales Invoice / Purchase Order (see
	sales_invoice.py / purchase_order.py) - counter keyed only by branch code
	so it never resets on month/year rollover. Falls back to the stock
	ACC-PINV-.YYYY.- naming series when the PI has no branch yet.
	"""
	branch_code = doc.custom_otobitz_branch and frappe.db.get_value(
		"Branch", doc.custom_otobitz_branch, "custom_otobitz_branch_code"
	)
	if not branch_code:
		doc.naming_series = "ACC-PINV-.YYYY.-"
		return

	now = now_datetime()
	series_key = f"{branch_code}-BPH-"
	counter = getseries(series_key, 5)
	doc.name = f"{branch_code}-BPH/{now.strftime('%m')}/{now.strftime('%Y')}/{counter}"


def track(doc, method=None):
	"""Append Approval History row when workflow_state changes - mirrors
	purchase_order.track(). Matrix rows are added manually per document;
	their approval_status is driven by approval.apply_approval_action."""
	if not doc.workflow_state:
		return
	before = doc.get_doc_before_save()
	old = before.workflow_state if before else None
	if old == doc.workflow_state:
		return
	role = frappe.db.get_value("Workflow Transition", {"parent": WF, "state": old, "next_state": doc.workflow_state}, "allowed") if old else None
	doc.append("custom_approval_history", {"role": role, "user": frappe.session.user, "date": now_datetime(), "state": doc.workflow_state})


def populate_journal_items(doc, method=None):
	"""Mirror the PI's real GL Entries into custom_journal_items for
	Odoo-style display. GL Entry has no Branch/Analytic Tags columns (Branch
	isn't an accounting dimension in this codebase) - Branch is taken from
	the PI document itself (every GL line of one PI shares the same branch);
	Analytic Tags is a display-only derivation from each GL line's
	cost_center. Runs on_submit, after ERPNext's own make_gl_entries() has
	already written the GL Entry rows this reads.
	"""
	frappe.db.delete("SI Journal Item", {"parent": doc.name, "parenttype": "Purchase Invoice"})
	rows = frappe.db.sql(
		"""select account, debit, credit, cost_center, remarks
		from `tabGL Entry`
		where voucher_type = 'Purchase Invoice' and voucher_no = %s and is_cancelled = 0
		order by creation""",
		doc.name, as_dict=True,
	)
	branch_label = doc.custom_otobitz_branch or ""
	for i, r in enumerate(rows, 1):
		frappe.get_doc({
			"doctype": "SI Journal Item", "parent": doc.name, "parenttype": "Purchase Invoice",
			"parentfield": "custom_journal_items", "idx": i,
			"account": r.account, "branch": branch_label, "label": r.remarks or "",
			"analytic_tags": r.cost_center or "", "debit": r.debit, "credit": r.credit,
		}).insert(ignore_permissions=True)
