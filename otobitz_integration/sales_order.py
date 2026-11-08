import frappe
from frappe.utils import add_months, today


def set_next_service_date(doc, method=None):
	# ponytail: only fills when empty, so a value synced from OtoBitz wins.
	if not doc.get("custom_next_service_date"):
		doc.custom_next_service_date = add_months(today(), 1)


def set_default_payment_terms(doc, method=None):
	"""Payment Terms defaults to Immediate Payment, same as the Sales Invoice
	(see sales_invoice.set_default_payment_terms) and Odoo. Fill-only-if-empty:
	a chosen template or an existing schedule always wins. Hooked on
	before_validate because ERPNext builds the payment schedule inside its own
	validate.
	"""
	if doc.docstatus == 0 and not doc.get("payment_terms_template") and not doc.get("payment_schedule"):
		if frappe.db.exists("Payment Terms Template", "Immediate Payment"):
			doc.payment_terms_template = "Immediate Payment"
