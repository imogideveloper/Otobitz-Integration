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
	"custom_otobitz_receipt_number",
	"party",
	"posting_date as tanggal",
	"custom_tahun",
	"custom_bulan",
	"custom_otobitz_branch",
	"mode_of_payment",
	"paid_amount",
]

AVAILABLE_GROUPS = {"custom_tahun", "custom_bulan", "tanggal", "custom_otobitz_branch", "mode_of_payment"}


def execute(filters=None):
	filters = filters or {}

	conditions = {"custom_otobitz_receipt_number": ["is", "set"], "docstatus": 1}
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
	return columns, data


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
