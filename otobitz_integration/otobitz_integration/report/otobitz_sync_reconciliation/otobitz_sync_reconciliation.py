# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import add_days, nowdate

from otobitz_integration.otobitz_integration.sync.reconciliation import get_reconciliation_rows


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date = filters.from_date or add_days(nowdate(), -30)
	to_date = filters.to_date or nowdate()

	columns = [
		{"label": "Tanggal", "fieldname": "date", "fieldtype": "Date", "width": 100},
		{"label": "WO di-fetch (OtoBitz)", "fieldname": "fetched", "fieldtype": "Int", "width": 160},
		{"label": "Sales Order dibuat", "fieldname": "created", "fieldtype": "Int", "width": 160},
		{"label": "Selisih", "fieldname": "gap", "fieldtype": "Int", "width": 100},
	]

	data = get_reconciliation_rows(from_date, to_date)
	return columns, data
