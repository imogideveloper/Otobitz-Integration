// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

frappe.listview_settings["OtoBitz Service Menu"] = {
	get_indicator(doc) {
		return doc.aktif
			? [__("Aktif"), "green", "aktif,=,1"]
			: [__("Tidak Aktif"), "gray", "aktif,=,0"];
	},
};
