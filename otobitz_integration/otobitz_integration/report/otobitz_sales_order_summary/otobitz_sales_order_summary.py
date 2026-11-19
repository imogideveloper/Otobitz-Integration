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
	"custom_otobitz_wo_number",
	"customer",
	"transaction_date as tanggal",
	"custom_tahun",
	"custom_bulan",
	"custom_otobitz_branch",
	"status",
	"grand_total",
]

# The logical group-able field names available on this report's own output -
# not the same as FIELDS, since FIELDS can contain "real_field as alias"
# strings (see the grouping.py module docstring for why "tanggal" is aliased).
AVAILABLE_GROUPS = {"custom_tahun", "custom_bulan", "tanggal", "custom_otobitz_branch", "status"}


def execute(filters=None):
	filters = filters or {}

	# docstatus 1 only (the original filter here) silently hid every
	# Cancelled Work Order's Sales Order from this report - see the same
	# fix's own comment in otobitz_sales_invoice_summary.py. Sales
	# Order's own custom_otobitz_wo_number is never cleared on cancel
	# (unlike Sales Invoice's), so that identity filter stays as-is here.
	conditions = {"custom_otobitz_wo_number": ["is", "set"], "docstatus": ["in", [1, 2]]}
	if filters.get("company"):
		conditions["company"] = filters["company"]
	if filters.get("from_date") and filters.get("to_date"):
		conditions["transaction_date"] = ["between", [filters["from_date"], filters["to_date"]]]
	if filters.get("branch"):
		conditions["custom_otobitz_branch"] = filters["branch"]
	if filters.get("status"):
		conditions["status"] = filters["status"]

	rows = frappe.get_all("Sales Order", filters=conditions, fields=FIELDS)

	# Precomputed onto each raw row (not just the leaf dict _detail_row
	# builds below) because grouping.py's own _recurse() rolls up each
	# Cabang/Bulan/etc node's "Cancel" total straight from these same raw
	# rows, the same way it already does for grand_total/paid_amount - so
	# the group-level figure is always the real sum of its own Cancelled
	# rows underneath it, not a second query that could drift.
	for row in rows:
		row["_cancel_amount"] = flt(row.grand_total) if row.status == "Cancelled" else 0

	group_order = get_active_groups(filters, AVAILABLE_GROUPS)
	columns = _columns()
	data = build_tree(rows, group_order, _detail_row)
	return columns, data


def _detail_row(row):
	return {
		"label": row.custom_otobitz_wo_number,
		"customer": row.customer,
		"status": row.status,
		"count": 1,
		"grand_total": row.grand_total,
		"cancel_total": row.get("_cancel_amount") or 0,
	}


def _columns():
	return base_columns() + [
		{"fieldname": "customer", "label": "Customer", "fieldtype": "Data", "width": 180},
		{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 130},
		{"fieldname": "count", "label": "Jumlah SO", "fieldtype": "Int", "width": 90},
		{"fieldname": "cancel_total", "label": "Cancel", "fieldtype": "Currency", "width": 140},
		{"fieldname": "grand_total", "label": "Total", "fieldtype": "Currency", "width": 160},
	]
