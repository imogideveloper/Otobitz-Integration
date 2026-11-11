import frappe
from frappe.model.naming import getseries


def set_manual_customer_id(doc, method=None):
	"""Customers synced from OtoBitz always arrive with custom_otobitz_customer_id
	already set (e.g. "C000182606") before insert - see sync_customers.py's
	upsert(), which populates it via doc.update(values) ahead of doc.insert().
	A Customer created any other way (Desk, quick-entry dialog) still needs an
	ID in that same field, so this fills a "C26-00001"-style one instead,
	whose "C26" prefix can never collide with the API's own ids."""
	if doc.get("custom_otobitz_customer_id"):
		return
	doc.custom_otobitz_customer_id = "C26-" + getseries("C26-", 5)
