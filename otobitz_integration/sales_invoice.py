import frappe
from frappe.model.naming import getseries
from frappe.utils import now_datetime


def set_branch_naming_series(doc, method=None):
	"""Odoo-style invoice numbering: {branch_code}-INV/{MM}/{YYYY}/{counter}.

	The counter must never reset on month/year rollover (confirmed with the
	user - Odoo's own counter keeps climbing), but MM/YYYY still appear in
	the number as the invoice's creation date. Frappe's usual naming_series
	ties the counter to the whole resolved prefix (so .MM./.YYYY. in the
	pattern would reset it every month) - setting doc.name directly here,
	keyed only by the branch code, decouples the counter from the date part.

	Falls back to the Sales Invoice default (ACC-SINV-.YYYY.-) when the
	invoice has no branch - confirmed by the user this shouldn't normally
	happen (every invoice is expected to have one), but a document can't be
	saved at all without a name, so this keeps a working fallback rather
	than hard-blocking on it here.
	"""
	branch_code = doc.custom_otobitz_branch and frappe.db.get_value(
		"Branch", doc.custom_otobitz_branch, "custom_otobitz_branch_code"
	)
	if not branch_code:
		doc.naming_series = "ACC-SINV-.YYYY.-"
		return

	now = now_datetime()
	series_key = f"{branch_code}-INV-"
	counter = getseries(series_key, 5)
	doc.name = f"{branch_code}-INV/{now.strftime('%m')}/{now.strftime('%Y')}/{counter}"
