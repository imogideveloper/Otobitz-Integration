// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

frappe.ui.form.on("OtoBitz Vehicle", {
	refresh(frm) {
		frm.page.set_indicator(
			frm.doc.customer ? __("Terhubung Customer") : __("Belum Terhubung"),
			frm.doc.customer ? "green" : "orange"
		);
		frm.dashboard.set_headline_alert(
			__("Data kendaraan ini disinkronkan otomatis dari OtoBitz dan hanya dapat diubah dari sana."),
			"blue"
		);
	},
});
