// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

frappe.query_reports["OtoBitz Sales Invoice Summary"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "from_date",
			label: __("Dari Tanggal"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
		},
		{
			fieldname: "to_date",
			label: __("Sampai Tanggal"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "branch",
			label: __("Cabang"),
			fieldtype: "Link",
			options: "Branch",
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "\nUnpaid\nOverdue\nPaid",
		},
		{
			fieldname: "group_by_tahun",
			label: __("Kelompokkan per Tahun"),
			fieldtype: "Check",
		},
		{
			fieldname: "group_by_bulan",
			label: __("Kelompokkan per Bulan"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "group_by_hari",
			label: __("Kelompokkan per Hari"),
			fieldtype: "Check",
		},
		{
			fieldname: "group_by_cabang",
			label: __("Kelompokkan per Cabang"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "group_by_status",
			label: __("Kelompokkan per Status"),
			fieldtype: "Check",
		},
	],
	tree: true,
	name_field: "row_id",
	parent_field: "parent_row_id",
	initial_depth: 1,
};
