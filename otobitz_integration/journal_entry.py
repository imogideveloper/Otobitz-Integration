import frappe
from frappe.model.naming import getseries
from frappe.utils import getdate

from otobitz_integration.payment_entry import HO_BRANCHES


def set_branch_naming_series(doc, method=None):
	"""Journal Entry number = {branch_code}-JV-{year}-{counter}, e.g.
	503-JV-2026-00012: the stock ERPNext "ACC-JV-.YYYY.-" number with its
	"ACC" prefix replaced by the branch code (as Odoo starts every number
	with the branch; HO = 000). Everything after the prefix is ERPNext's own
	default (5-digit counter), kept per branch and year the way a series
	prefix is. Falls back to the stock ACC-JV series when the entry has no
	branch (manual entries), and leaves amended documents to ERPNext.
	"""
	if doc.get("amended_from"):
		return
	branch = doc.get("custom_otobitz_branch")
	if branch in HO_BRANCHES:
		branch_code = "000"
	else:
		branch_code = branch and frappe.db.get_value("Branch", branch, "custom_otobitz_branch_code")
	if not branch_code:
		doc.naming_series = "ACC-JV-.YYYY.-"
		return
	year = getdate(doc.get("posting_date")).year
	counter = getseries(f"{branch_code}-JV-{year}-", 5)
	doc.name = f"{branch_code}-JV-{year}-{counter}"
