import frappe


def follow_item_cost_center(doc, method=None):
	"""Odoo-style: the invoice's rounding entry follows the cost center of the
	invoice lines instead of the company's default round-off cost center.

	ERPNext posts the Round Off GL Entry to the invoice header cost_center, or
	to Company.round_off_cost_center ("Main - AIO") when the header is empty.
	OtoBitz invoices only carry cost centers on the lines, so every Round Off
	landed in "Main - AIO". Runs on_submit right after ERPNext's make_gl_entries
	and only re-points the cost center of those Round Off rows: no amount,
	account or other GL row is touched. Cost center of the first line is used,
	same as the HPP entry (sales_invoice.create_cogs_entry).
	"""
	round_off_account, default_cc = frappe.get_cached_value(
		"Company", doc.company, ["round_off_account", "round_off_cost_center"]
	) or (None, None)
	if not round_off_account or not default_cc:
		return
	target = next((i.cost_center for i in doc.get("items") or [] if i.get("cost_center")), None)
	if not target or target == default_cc:
		return
	frappe.db.sql(
		"""update `tabGL Entry` set cost_center = %s
		where voucher_type = %s and voucher_no = %s and account = %s
		and cost_center = %s and is_cancelled = 0""",
		(target, doc.doctype, doc.name, round_off_account, default_cc),
	)
