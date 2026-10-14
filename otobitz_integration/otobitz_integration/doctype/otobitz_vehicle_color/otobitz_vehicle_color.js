// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

frappe.ui.form.on("OtoBitz Vehicle Color", {
	refresh(frm) {
		frm.page.set_indicator(frm.doc.aktif ? __("Aktif") : __("Tidak Aktif"), frm.doc.aktif ? "green" : "red");
		frm.dashboard.set_headline_alert(
			__("Data ini disinkronkan otomatis dari OtoBitz dan hanya dapat diubah dari sana."),
			"blue"
		);
	},
});
