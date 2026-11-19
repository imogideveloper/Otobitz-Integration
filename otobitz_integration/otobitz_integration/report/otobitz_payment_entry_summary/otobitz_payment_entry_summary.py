# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt

from otobitz_integration.otobitz_integration.report.grouping import (
	base_columns,
	build_tree,
	get_active_groups,
)

FIELDS = [
	"name",
	"custom_otobitz_receipt_number",
	"party",
	"posting_date as tanggal",
	"custom_tahun",
	"custom_bulan",
	"custom_otobitz_branch",
	"mode_of_payment",
	"paid_amount",
	"docstatus",
]

AVAILABLE_GROUPS = {"custom_tahun", "custom_bulan", "tanggal", "custom_otobitz_branch", "mode_of_payment"}


def execute(filters=None):
	filters = filters or {}

	# docstatus 1 only (the original filter here) silently hid every
	# Cancelled Payment Entry from this report - see the same fix's own
	# comment in otobitz_sales_invoice_summary.py.
	# _replace_stale_invoice() in sync_service_orders.py cancels the
	# Payment Entry on a superseded invoice right along with it, and that
	# money is real - it just needs sync_penerimaan.py's own retry to
	# re-attach to whichever invoice is now the valid one, not something
	# this report should make invisible in the meantime.
	conditions = {"custom_otobitz_receipt_number": ["is", "set"], "docstatus": ["in", [1, 2]]}
	if filters.get("company"):
		conditions["company"] = filters["company"]
	if filters.get("from_date") and filters.get("to_date"):
		conditions["posting_date"] = ["between", [filters["from_date"], filters["to_date"]]]
	if filters.get("branch"):
		conditions["custom_otobitz_branch"] = filters["branch"]
	if filters.get("mode_of_payment"):
		conditions["mode_of_payment"] = filters["mode_of_payment"]

	rows = frappe.get_all("Payment Entry", filters=conditions, fields=FIELDS)

	group_order = get_active_groups(filters, AVAILABLE_GROUPS)
	columns = _columns()
	data = build_tree(rows, group_order, _detail_row)
	return columns, data, None, None, _report_summary(rows)


def _report_summary(rows):
	cancelled = [r for r in rows if r.docstatus == 2]
	active = [r for r in rows if r.docstatus != 2]
	return [
		{
			"label": "Pembayaran Aktif",
			"value": sum(flt(r.paid_amount) for r in active),
			"datatype": "Currency",
			"indicator": "Green",
		},
		{"label": "Jumlah Pembayaran Aktif", "value": len(active), "datatype": "Int"},
		{
			"label": "Pembayaran Dibatalkan",
			"value": sum(flt(r.paid_amount) for r in cancelled),
			"datatype": "Currency",
			"indicator": "Red",
		},
		{"label": "Jumlah Pembayaran Dibatalkan", "value": len(cancelled), "datatype": "Int"},
	]


def _detail_row(row):
	return {
		"label": row.custom_otobitz_receipt_number,
		"customer": row.party,
		"status": row.mode_of_payment,
		"count": 1,
		"grand_total": row.paid_amount,
	}


def _columns():
	return base_columns() + [
		{"fieldname": "customer", "label": "Customer", "fieldtype": "Data", "width": 180},
		{"fieldname": "status", "label": "Metode Pembayaran", "fieldtype": "Data", "width": 150},
		{"fieldname": "count", "label": "Jumlah", "fieldtype": "Int", "width": 90},
		{"fieldname": "grand_total", "label": "Total Diterima", "fieldtype": "Currency", "width": 160},
	]
