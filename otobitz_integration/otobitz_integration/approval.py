"""Shared multi-tier sequential approval engine for Purchase Order + Purchase Invoice.

Matrix rows (custom_approval_matrix, doctype PO Approval Matrix) are added
manually per document. Tiers are gated by `sequence`: tier N only becomes
actionable once every earlier tier's approval_status is "Approved". A tier
is satisfied once distinct approvers (logged in PO Approval History,
doctype custom_approval_history) reach minimum_approval.

Real enforcement lives here, server-side, in apply_approval_action - not in
the Frappe Workflow engine (kept only for the coarse Draft/Pending
Approval/Approved/Rejected state used by list views) and not in client
JS (which can only hide buttons, not stop a direct API call).
"""

import frappe
from frappe.utils import now_datetime

WORKFLOW_BY_DOCTYPE = {
	"Purchase Order": "PO Approval Workflow",
	"Purchase Invoice": "PI Approval Workflow",
}


def get_matrix_rows(doc):
	return sorted(doc.get("custom_approval_matrix") or [], key=lambda r: r.sequence or 0)


def active_tier(doc):
	"""First matrix row (by sequence) not yet Approved, or None if all are."""
	for row in get_matrix_rows(doc):
		if row.approval_status != "Approved":
			return row
	return None


def eligible_users(row):
	"""row.users is a comma/newline-separated list of emails - Frappe child
	tables (istable:1) cannot themselves hold a Table/Table MultiSelect
	field, so this can't be a proper child table; a plain text list parsed
	here is the simplest fieldtype that still lets the engine enforce
	eligibility server-side instead of being purely decorative."""
	raw = row.get("users") or ""
	return {u.strip() for u in raw.replace("\n", ",").split(",") if u.strip()}


def is_user_eligible(row, user):
	if user in eligible_users(row):
		return True
	if row.role and row.role in frappe.get_roles(user):
		return True
	return False


def tier_satisfied(row):
	return (row.approved_count or 0) >= max(row.minimum_approval or 0, 1)


def can_act(doc, user, row):
	return row is active_tier(doc) and row.approval_status != "Approved" and is_user_eligible(row, user)


@frappe.whitelist()
def apply_approval_action(doctype, docname, row_name, action, signature=None):
	if doctype not in WORKFLOW_BY_DOCTYPE:
		frappe.throw(f"Approval matrix is not available for {doctype}")
	if action not in ("Approve", "Reject"):
		frappe.throw("Invalid action")

	doc = frappe.get_doc(doctype, docname)
	if doc.docstatus != 1:
		frappe.throw("Approval actions can only be taken on a submitted document")

	row = next((r for r in get_matrix_rows(doc) if r.name == row_name), None)
	if not row:
		frappe.throw("Approval matrix row not found")
	if row is not active_tier(doc):
		frappe.throw("This tier is not yet active - earlier tiers must be fully approved first")

	user = frappe.session.user
	if not is_user_eligible(row, user) and "System Manager" not in frappe.get_roles(user):
		frappe.throw("You are not eligible to act on this approval tier")

	action_label = "Approved" if action == "Approve" else "Rejected"

	already = frappe.db.exists(
		"PO Approval History",
		{"parent": doc.name, "parenttype": doctype, "matrix_row": row.name, "user": user, "action": "Approved"},
	)
	if already and action == "Approve":
		frappe.throw("You have already approved this tier")

	history_row = doc.append("custom_approval_history", {
		"role": row.role,
		"user": user,
		"date": now_datetime(),
		"state": doc.workflow_state,
		"action": action_label,
		"matrix_row": row.name,
		"digital_signature": signature,
	})

	if action == "Reject":
		row.approval_status = "Rejected"
		_advance_workflow(doc, "Reject")
	else:
		approved_count = frappe.db.count(
			"PO Approval History",
			{"parent": doc.name, "parenttype": doctype, "matrix_row": row.name, "action": "Approved"},
		) + 1  # +1: this row hasn't been persisted to the DB yet, count it in-flight
		# distinct users, not raw row count - a user can't inflate the count by re-approving (blocked above)
		row.approved_count = approved_count
		if tier_satisfied(row):
			row.approval_status = "Approved"
			rows = get_matrix_rows(doc)
			if rows and row.sequence == rows[-1].sequence:
				_advance_workflow(doc, "Approve")
		else:
			row.approval_status = "In Progress"

	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"status": row.approval_status, "workflow_state": doc.workflow_state, "history_row": history_row.name}


def _advance_workflow(doc, action):
	"""Move the coarse Workflow state. Falls back to a direct db_set if the
	Workflow Transition lookup / apply fails - mirrors imogi_finance's
	apply_expense_action reasoning that Workflow sync can lag or mismatch."""
	wf = WORKFLOW_BY_DOCTYPE.get(doc.doctype)
	try:
		from frappe.model.workflow import apply_workflow
		apply_workflow(doc, action)
	except Exception:
		state = "Approved" if action == "Approve" else "Rejected"
		doc.db_set("workflow_state", state, update_modified=False)
		status = "To Receive and Bill" if doc.doctype == "Purchase Order" else "Submitted"
		if action == "Approve":
			doc.db_set("status", status, update_modified=False)
