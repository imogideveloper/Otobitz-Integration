import frappe
from frappe.utils import add_months, today


def set_next_service_date(doc, method=None):
	# ponytail: only fills when empty, so a value synced from OtoBitz wins.
	if not doc.get("custom_next_service_date"):
		doc.custom_next_service_date = add_months(today(), 1)
