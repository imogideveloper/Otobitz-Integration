// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

frappe.ui.form.on("OtoBitz Vehicle", {
	refresh(frm) {
		frm.page.set_indicator(
			frm.doc.customer ? __("Terhubung Customer") : __("Belum Terhubung"),
			frm.doc.customer ? "green" : "orange"
		);
		frm.dashboard.set_headline_alert(
			__("Data kendaraan ini disinkronkan otomatis dari OtoBitz. Pemilik dapat diganti lewat tombol Ganti Pemilik, dan setiap pergantian tercatat di Riwayat Pemilik."),
			"blue"
		);
		if (frm.is_new()) return;
		frm.add_custom_button(__("Ganti Pemilik"), () => {
			frappe.prompt(
				[
					{fieldname: "customer", label: __("Pemilik Baru"), fieldtype: "Link", options: "Customer", reqd: 1,
						get_query: () => ({filters: {name: ["!=", frm.doc.customer || ""]}})},
					{fieldname: "date", label: __("Tanggal"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1},
					{fieldname: "note", label: __("Catatan"), fieldtype: "Small Text"},
				],
				(v) => {
					frappe.call({
						method: "otobitz_integration.otobitz_integration.doctype.otobitz_vehicle.otobitz_vehicle.change_owner",
						args: {vehicle: frm.doc.name, customer: v.customer, date: v.date, note: v.note},
						freeze: true,
						callback: () => frm.reload_doc(),
					});
				},
				__("Ganti Pemilik"),
				__("Simpan")
			);
		});
		frm.add_custom_button(__("Riwayat Pemilik"), () => {
			const rows = (frm.doc.owner_history || []).slice().reverse();
			const esc = frappe.utils.escape_html;
			const body = rows.length
				? `<table class="table table-bordered"><thead><tr><th>${__("Pemilik")}</th><th>${__("Dari")}</th><th>${__("Sampai")}</th><th>${__("Sumber")}</th><th>${__("Catatan")}</th></tr></thead><tbody>` +
				  rows.map(r => `<tr><td>${esc(r.customer_name || r.customer || "")}</td><td>${r.from_date ? frappe.datetime.str_to_user(r.from_date) : "-"}</td><td>${r.to_date ? frappe.datetime.str_to_user(r.to_date) : __("sekarang")}</td><td>${esc(r.source || "")}</td><td>${esc(r.notes || "")}</td></tr>`).join("") +
				  "</tbody></table>"
				: `<p class="text-muted">${__("Belum ada riwayat pemilik.")}</p>`;
			frappe.msgprint({title: __("Riwayat Pemilik"), message: body, wide: true});
		});
	},
});
