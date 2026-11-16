import frappe
from frappe.model.naming import getseries

HO_BRANCHES = ("HEAD OFFICE", "AIO HO OTOXPERT AUTO2000", "HO OTOXPERT AUTO2000")

# Odoo bank journals -> payment prefix (journal code + "/"), keyed by the GL
# account number of the bank account. Odoo's BCA journal code itself ends in
# "/", hence "BCA//". GOPAY QRIS is left out: its Odoo numbers carry a year
# (GQRIS/2025/...) and it has no 2026 payments to match.
BANK_JOURNAL_PREFIX = {
	"1005102001": "BCA/",   # Bank BCA - 6591000729 (single slash, per management)
	"1005101001": "PMT/",   # Bank Permata - 00702442141
	"1003104002": "UOB/",   # BANK UOB 2534
}


def set_branch_naming_series(doc, method=None):
	"""Odoo-style payment numbering: {branch_code}-{journal prefix}{counter},
	e.g. 106-PMT/20188, 101-BCA//273921, 000-BCA//273509 (HO = 000).

	Same decoupled-counter approach as Purchase Order / Purchase Invoice
	(see purchase_order.py) - set doc.name directly. Unlike those, the Odoo
	counter belongs to the journal, shared by every branch, so it is keyed by
	journal only. Falls back to the stock ACC-PAY series when the bank account
	has no Odoo journal (e.g. cash) or the entry has no branch yet.
	"""
	bank = doc.paid_to if doc.payment_type == "Receive" else doc.paid_from
	account_number = bank and frappe.db.get_value("Account", bank, "account_number")
	prefix = BANK_JOURNAL_PREFIX.get(account_number)

	branch = doc.get("custom_otobitz_branch")
	if branch in HO_BRANCHES:
		branch_code = "000"
	else:
		branch_code = branch and frappe.db.get_value("Branch", branch, "custom_otobitz_branch_code")

	if not prefix or not branch_code:
		doc.naming_series = "ACC-PAY-.YYYY.-"
		return

	counter = getseries(f"PE-{account_number}-", 0)
	doc.name = f"{branch_code}-{prefix}{counter}"


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
