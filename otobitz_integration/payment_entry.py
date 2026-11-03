import frappe

HO_BRANCHES = ("HEAD OFFICE", "AIO HO OTOXPERT AUTO2000")


def set_branch_cash_account(doc, method=None):
	"""Cash payments go to the branch's own "Cash On Hand <branch>" account
	(Odoo: one cash journal per branch, matched the invoice branch in 597/597
	sampled payments). Branch comes from the entry, else its first reference.
	ponytail: matches account by name "Cash On Hand <branch>"; add a Branch->Account
	link field if names ever drift.
	"""
	side = "paid_to" if doc.payment_type == "Receive" else "paid_from" if doc.payment_type == "Pay" else None
	if not side or not doc.get(side):
		return
	if frappe.db.get_value("Account", doc.get(side), "account_type") != "Cash":
		return
	branch = doc.get("custom_otobitz_branch")
	if not branch:
		for r in doc.get("references") or []:
			branch = frappe.db.get_value(r.reference_doctype, r.reference_name, "custom_otobitz_branch")
			if branch:
				break
	if not branch:
		return
	acc = frappe.db.get_value(
		"Account",
		{"company": doc.company, "account_type": "Cash", "is_group": 0, "account_name": ["like", f"Cash On Hand {branch}"]},
	)
	if not acc and branch in HO_BRANCHES:  # Odoo: head office cash = 1002100000
		acc = frappe.db.get_value("Account", {"company": doc.company, "account_number": "1002100000"})
	if acc:
		doc.set(side, acc)
		doc.custom_otobitz_branch = branch
