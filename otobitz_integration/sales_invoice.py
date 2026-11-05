import frappe
from frappe.model.naming import getseries
from frappe.utils import flt, now_datetime


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


def set_default_payment_reference(doc, method=None):
	"""Payment Reference defaults to this invoice's own number - same
	fill-only-if-empty pattern as sales_order.set_next_service_date, so a
	manually entered or externally synced reference always wins. Runs on
	validate (not autoname): doc.name is only final by the time autoname
	finishes (set_branch_naming_series above), so validate is the first hook
	where it's safe to read.
	"""
	if not doc.get("custom_payment_reference"):
		doc.custom_payment_reference = doc.name


def set_default_accounting_date(doc, method=None):
	"""Accounting Date mirrors Invoice Date (posting_date) unless the user
	picked a different value - same fill-only-if-empty pattern as the other
	defaults in this file.
	"""
	if not doc.get("custom_accounting_date"):
		doc.custom_accounting_date = doc.posting_date


def set_default_payment_terms(doc, method=None):
	"""Due Date (the Payment Terms Template link) defaults to Immediate Payment,
	as in Odoo. Hooked on before_validate because ERPNext builds the payment
	schedule inside its own validate, which runs before doc_events validate.
	Fill-only-if-empty: a chosen template or an existing schedule always wins.
	The Property Setter default covers the desk form; this covers invoices
	created through code (OtoBitz sync).
	"""
	if doc.docstatus == 0 and not doc.get("payment_terms_template") and not doc.get("payment_schedule"):
		if frappe.db.exists("Payment Terms Template", "Immediate Payment"):
			doc.payment_terms_template = "Immediate Payment"


def populate_journal_items(doc, method=None):
	"""Mirror the invoice's real GL Entries into custom_journal_items for
	Odoo-style display (same idea as purchase_invoice.populate_journal_items).
	GL Entry has no Branch / Analytic Tags column, so Branch comes from the
	invoice itself and Analytic Tags is derived from each line's cost_center.
	Runs on_submit, after ERPNext's own make_gl_entries(). Display only: it
	reads the ledger and never writes to it.
	"""
	frappe.db.delete("SI Journal Item", {"parent": doc.name, "parenttype": "Sales Invoice"})
	rows = frappe.db.sql(
		"""select account, debit, credit, cost_center, remarks
		from `tabGL Entry`
		where voucher_type = 'Sales Invoice' and voucher_no = %s and is_cancelled = 0
		order by creation, name""",
		doc.name, as_dict=True,
	)
	# The HPP journal entry (create_cogs_entry below) is part of this invoice's
	# Odoo-style journal, so its lines are listed right after the invoice's own.
	cogs_je = _cogs_entry_names(doc.name)
	if cogs_je:
		rows += frappe.db.sql(
			"""select account, debit, credit, cost_center, remarks
			from `tabGL Entry`
			where voucher_type = 'Journal Entry' and voucher_no in %s and is_cancelled = 0
			order by creation, name""",
			(cogs_je,), as_dict=True,
		)
	branch_label = doc.get("custom_otobitz_branch") or ""
	for i, r in enumerate(rows, 1):
		remarks = r.remarks if r.remarks and r.remarks != "No Remarks" else ""
		frappe.get_doc({
			"doctype": "SI Journal Item", "parent": doc.name, "parenttype": "Sales Invoice",
			"parentfield": "custom_journal_items", "idx": i,
			"account": r.account, "branch": branch_label, "label": remarks,
			"analytic_tags": r.cost_center or "", "debit": r.debit, "credit": r.credit,
		}).insert(ignore_permissions=True)


COGS_ACCOUNT_NUMBER = "4000200002"
INTERIM_STOCK_ACCOUNT_NUMBER = "1260500999"


def _cogs_remark(si_name: str) -> str:
	return f"HPP {si_name}"


def _cogs_entry_names(si_name: str) -> list:
	return frappe.get_all(
		"Journal Entry",
		filters={"user_remark": _cogs_remark(si_name), "docstatus": 1},
		pluck="name",
	)


def _hpp_lines(doc) -> list:
	"""Sparepart lines of this invoice's Work Order with a cost, straight from
	OtoBitz's own archived payload (OtoBitz SO Detail): (item_code, qty, hpp).
	Only jenisdoc == 'Part' carries stock cost - Jasa has hpp 0 and OPL
	(outside labour) is not a stock item, so neither is included.
	"""
	import json

	wo = doc.get("custom_otobitz_wo_number")
	if not wo:
		return []
	lines = []
	for raw in frappe.get_all("OtoBitz SO Detail", filters={"nomorwo": wo}, pluck="raw_data"):
		try:
			h = json.loads(raw)
		except (TypeError, ValueError):
			continue
		qty, hpp = flt(h.get("qty")), flt(h.get("hpp"))
		if h.get("jenisdoc") == "Part" and qty > 0 and hpp > 0:
			lines.append((h.get("kodereferensi"), qty, hpp))
	return lines


def create_cogs_entry(doc, method=None):
	"""HPP / Interim Stock like Odoo: per sparepart line Dr Cost of Sales
	(4000200002) / Cr Interim Stock (1260500999), amount = qty x OtoBitz hpp.
	Stock itself is kept by OtoBitz, so ERPNext's own stock-based COGS never
	fires (update_stock = 0); this books the cost as a separate Journal Entry
	tied to the invoice by its remark, cancelled with it. Fill-once: skipped if
	one already exists. A failure is logged and never blocks the invoice.
	"""
	try:
		if _cogs_entry_names(doc.name):
			return
		lines = _hpp_lines(doc)
		if not lines:
			return
		cogs = frappe.db.get_value("Account", {"account_number": COGS_ACCOUNT_NUMBER, "company": doc.company})
		interim = frappe.db.get_value("Account", {"account_number": INTERIM_STOCK_ACCOUNT_NUMBER, "company": doc.company})
		if not cogs or not interim:
			return
		cost_centers = {i.item_code: i.cost_center for i in doc.items}
		default_cc = doc.items[0].cost_center if doc.items else None
		accounts = []
		for item_code, qty, hpp in lines:
			amount = flt(qty * hpp, 2)
			cc = cost_centers.get(item_code) or default_cc
			label = f"[{item_code}] HPP"
			accounts.append({"account": cogs, "debit_in_account_currency": amount, "cost_center": cc, "user_remark": label})
			accounts.append({"account": interim, "credit_in_account_currency": amount, "cost_center": cc, "user_remark": label})
		je = frappe.get_doc({
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": doc.company,
			"posting_date": doc.posting_date,
			"title": _cogs_remark(doc.name),
			"user_remark": _cogs_remark(doc.name),
			"custom_otobitz_branch": doc.get("custom_otobitz_branch"),
			"accounts": accounts,
		})
		from otobitz_integration.otobitz_integration.sync.common import set_period_fields

		set_period_fields(je, je.posting_date)
		je.insert(ignore_permissions=True)
		je.submit()
	except Exception:
		frappe.log_error(title=f"HPP entry failed for {doc.name}")


def cancel_cogs_entry(doc, method=None):
	"""Cancel the HPP journal entry together with its invoice."""
	for name in _cogs_entry_names(doc.name):
		frappe.get_doc("Journal Entry", name).cancel()
