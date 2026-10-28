// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

frappe.query_reports["OtoBitz Sync Reconciliation"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("Dari Tanggal"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.get_today(), -30),
		},
		{
			fieldname: "to_date",
			label: __("Sampai Tanggal"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
	],
	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "gap" && data && data.gap > 5) {
			value = `<span style="color: var(--red-600); font-weight: 700">${value}</span>`;
		}
		return value;
	},
};
