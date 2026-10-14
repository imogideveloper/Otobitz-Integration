# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

import frappe

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

	conditions = {"custom_otobitz_wo_number": ["is", "set"], "docstatus": 1}
	if filters.get("company"):
		conditions["company"] = filters["company"]
	if filters.get("from_date") and filters.get("to_date"):
		conditions["transaction_date"] = ["between", [filters["from_date"], filters["to_date"]]]
	if filters.get("branch"):
		conditions["custom_otobitz_branch"] = filters["branch"]
	if filters.get("status"):
		conditions["status"] = filters["status"]

	rows = frappe.get_all("Sales Order", filters=conditions, fields=FIELDS)

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
	}


def _columns():
	return base_columns() + [
		{"fieldname": "customer", "label": "Customer", "fieldtype": "Data", "width": 180},
		{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 130},
		{"fieldname": "count", "label": "Jumlah SO", "fieldtype": "Int", "width": 90},
		{"fieldname": "grand_total", "label": "Total", "fieldtype": "Currency", "width": 160},
	]
