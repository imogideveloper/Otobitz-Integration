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
	"custom_otobitz_nofaktur",
	"customer",
	"posting_date as tanggal",
	"custom_tahun",
	"custom_bulan",
	"custom_otobitz_branch",
	"status",
	"grand_total",
	"outstanding_amount",
]

AVAILABLE_GROUPS = {"custom_tahun", "custom_bulan", "tanggal", "custom_otobitz_branch", "status"}


def execute(filters=None):
	filters = filters or {}

	# docstatus 1 only (the original filter here) silently hid every
	# Cancelled invoice from this report entirely - including the ones
	# _replace_stale_invoice()/_create_historical_cancelled_invoice() in
	# sync_service_orders.py deliberately keep around (not delete) so a
	# Work Order's cancelled-and-reissued invoice history stays visible
	# and auditable. Reported live: no way to see how much money that
	# represents in total. custom_otobitz_nofaktur, not
	# custom_otobitz_wo_number, is the identity filter here because
	# those same two functions clear wo_number off a cancelled invoice
	# (it has a UNIQUE constraint the still-active replacement invoice
	# needs to claim) but always leave nofaktur alone.
	conditions = {"custom_otobitz_nofaktur": ["is", "set"], "docstatus": ["in", [1, 2]]}
	if filters.get("company"):
		conditions["company"] = filters["company"]
	if filters.get("from_date") and filters.get("to_date"):
		conditions["posting_date"] = ["between", [filters["from_date"], filters["to_date"]]]
	if filters.get("branch"):
		conditions["custom_otobitz_branch"] = filters["branch"]
	if filters.get("status"):
		conditions["status"] = filters["status"]

	rows = frappe.get_all("Sales Invoice", filters=conditions, fields=FIELDS)

	# See the same precompute's own comment in otobitz_sales_order_summary.py -
	# grouping.py's _recurse() rolls up each Cabang/Bulan/etc node's "Cancel"
	# total straight from this.
	for row in rows:
		row["_cancel_amount"] = flt(row.grand_total) if row.status == "Cancelled" else 0

	group_order = get_active_groups(filters, AVAILABLE_GROUPS)
	columns = _columns()
	data = build_tree(rows, group_order, _detail_row)
	return columns, data


def _detail_row(row):
	return {
		"label": row.custom_otobitz_nofaktur or row.custom_otobitz_wo_number,
		"customer": row.customer,
		"status": row.status,
		"count": 1,
		"grand_total": row.grand_total,
		"cancel_total": row.get("_cancel_amount") or 0,
		"outstanding_amount": row.outstanding_amount,
	}


def _columns():
	return base_columns() + [
		{"fieldname": "customer", "label": "Customer", "fieldtype": "Data", "width": 180},
		{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 110},
		{"fieldname": "count", "label": "Jumlah SI", "fieldtype": "Int", "width": 90},
		{"fieldname": "cancel_total", "label": "Cancel", "fieldtype": "Currency", "width": 130},
		{"fieldname": "grand_total", "label": "Total", "fieldtype": "Currency", "width": 150},
		{"fieldname": "outstanding_amount", "label": "Sisa Tagihan", "fieldtype": "Currency", "width": 150},
	]
