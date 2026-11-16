import frappe
from frappe.model.naming import getseries
from frappe.utils import nowdate


def assign_manual_customer_id(doc, method=None):
	"""Give every Customer made by hand an OtoBitz-style customer id.

	OtoBitz ids look like C000049042. Customers synced from OtoBitz always arrive
	with theirs (both sync upserts set `custom_otobitz_customer_id` before insert),
	so this only runs for the ones staff create in ERPNext: C + two-digit year +
	a 7-digit counter, e.g. C260000001. The counter is a Frappe Series (atomic, never
	reused), and the id is also checked against existing customers, so it cannot
	collide with an OtoBitz id.
	"""
	if doc.get("custom_otobitz_customer_id"):
		return
	doc.custom_otobitz_customer_id = next_manual_customer_id()


def next_manual_customer_id() -> str:
	prefix = "C" + nowdate()[2:4]
	while True:
		candidate = prefix + getseries(prefix, 7)
		if not frappe.db.exists("Customer", {"custom_otobitz_customer_id": candidate}):
			return candidate


def assign_missing_ids():
	"""One-off: give an id to existing customers that have none (made by hand before
	this feature). Not run automatically."""
	n = 0
	for name in frappe.get_all(
		"Customer", filters={"custom_otobitz_customer_id": ["in", ["", None]]}, pluck="name"
	):
		frappe.db.set_value("Customer", name, "custom_otobitz_customer_id", next_manual_customer_id(), update_modified=False)
		n += 1
	return n
