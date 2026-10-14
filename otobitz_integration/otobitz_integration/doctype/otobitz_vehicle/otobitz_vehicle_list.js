// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

frappe.listview_settings["OtoBitz Vehicle"] = {
	get_indicator(doc) {
		return doc.customer
			? [__("Terhubung Customer"), "green", "customer,is,set"]
			: [__("Belum Terhubung"), "orange", "customer,is,not set"];
	},
};
