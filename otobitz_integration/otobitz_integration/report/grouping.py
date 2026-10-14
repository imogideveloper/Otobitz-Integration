# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""Shared nested-grouping engine for OtoBitz's three summary reports (Sales
Order, Sales Invoice, Payment Entry).

Each report lets the user tick any combination of Tahun/Bulan/Hari/Cabang/
Status as checkboxes, in whatever order they tick them - not a hardcoded
single dropdown field like Frappe's native Report View "Add Group" button
(which only supports one grouping field at a time, with no nesting). Checked
boxes are nested in a fixed, sensible priority order (time-based first, then
organizational), and rendered as a collapsible tree using Frappe's standard
tree report mechanism (`name_field`/`parent_field` in the report's .js,
matching how core reports like Trial Balance group accounts).
"""

from __future__ import annotations

import frappe
from frappe.utils import flt

# Fixed nesting order: calendar dimensions first (outermost), then
# organizational ones - this is the one sensible default order; a checked box
# always nests at this position relative to the other checked boxes,
# regardless of the order they were ticked in.
GROUP_DEFINITIONS = [
	("group_by_tahun", "custom_tahun", "Tahun"),
	("group_by_bulan", "custom_bulan", "Bulan"),
	# "tanggal" is a deliberate alias, not a real column on any of the three
	# source doctypes (Sales Order uses transaction_date, Sales Invoice/
	# Payment Entry use posting_date) - each report's query aliases its own
	# date field to "tanggal" so this one definition works for all three.
	("group_by_hari", "tanggal", "Tanggal"),
	("group_by_cabang", "custom_otobitz_branch", "Cabang"),
	("group_by_status", "status", "Status"),
	("group_by_metode", "mode_of_payment", "Metode Pembayaran"),
]


def get_active_groups(filters: dict, available_fieldnames: set[str]) -> list[tuple[str, str]]:
	"""Returns the active (fieldname, label) pairs, in fixed nesting order,
	for whichever GROUP_DEFINITIONS both exist on this doctype and were
	ticked in the filters."""
	return [
		(fieldname, label)
		for filter_key, fieldname, label in GROUP_DEFINITIONS
		if filters.get(filter_key) and fieldname in available_fieldnames
	]


def base_columns() -> list[dict]:
	return [
		{"fieldname": "row_id", "label": "row_id", "fieldtype": "Data", "hidden": 1},
		{"fieldname": "parent_row_id", "label": "parent_row_id", "fieldtype": "Data", "hidden": 1},
		{"fieldname": "label", "label": "Keterangan", "fieldtype": "Data", "width": 320},
	]


def build_tree(rows: list, group_order: list[tuple[str, str]], detail_builder) -> list[dict]:
	"""Turns a flat list of docs into report rows.

	`detail_builder(row)` returns the dict for one leaf/detail row (minus
	row_id/parent_row_id/label/indent, which this function fills in).
	With no active groups, every row is a flat top-level detail row."""
	data: list[dict] = []

	if not group_order:
		for row in rows:
			detail = detail_builder(row)
			detail.update({"row_id": row.name, "parent_row_id": "", "indent": 0})
			data.append(detail)
		return data

	_recurse(rows, group_order, 0, "", data, detail_builder)
	return data


def _recurse(rows, group_order, level, parent_id, data, detail_builder):
	fieldname, label_prefix = group_order[level]

	buckets: dict = {}
	order: list = []
	for row in rows:
		key = row.get(fieldname)
		key = key if key not in (None, "") else "(Kosong)"
		if key not in buckets:
			buckets[key] = []
			order.append(key)
		buckets[key].append(row)

	for key in order:
		bucket_rows = buckets[key]
		node_id = f"{parent_id}|{fieldname}:{key}" if parent_id else f"{fieldname}:{key}"
		data.append(
			{
				"row_id": node_id,
				"parent_row_id": parent_id or "",
				"label": f"{label_prefix}: {key}",
				"count": len(bucket_rows),
				"grand_total": sum(flt(r.get("grand_total") or r.get("paid_amount")) for r in bucket_rows),
				"indent": level,
			}
		)
		if level + 1 < len(group_order):
			_recurse(bucket_rows, group_order, level + 1, node_id, data, detail_builder)
		else:
			for row in bucket_rows:
				detail = detail_builder(row)
				detail.update({"row_id": row.name, "parent_row_id": node_id, "indent": level + 1})
				data.append(detail)
