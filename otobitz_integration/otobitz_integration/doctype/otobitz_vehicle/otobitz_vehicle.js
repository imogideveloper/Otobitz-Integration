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

// Custom Quick Entry layout: Frappe's default Quick Entry always stacks
// fields one per row even though the doctype itself has Column Breaks -
// this override (the same pattern ERPNext itself uses, e.g. ItemQuickEntryForm)
// lays them out two per row instead, matching the reference design.
frappe.ui.form.OtoBitzVehicleQuickEntryForm = class extends frappe.ui.form.QuickEntryForm {
	render_dialog() {
		this.mandatory = [
			{fieldname: "nopolisi", fieldtype: "Data", label: __("Nomor Polisi")},
			{fieldname: "col_br_1", fieldtype: "Column Break"},
			{fieldname: "nomesin", fieldtype: "Data", label: __("Nomor Mesin")},
			{fieldname: "norangka", fieldtype: "Data", label: __("Nomor Rangka (Chassis)"), reqd: 1},
			{fieldname: "col_br_2", fieldtype: "Column Break"},
			{fieldname: "last_odometer", fieldtype: "Int", label: __("Last Odometer")},
			{fieldname: "sec_br_1", fieldtype: "Section Break"},
			{fieldname: "vehicle_type", fieldtype: "Link", options: "OtoBitz Vehicle Type", label: __("Vehicle Type")},
			{fieldname: "col_br_3", fieldtype: "Column Break"},
			{fieldname: "vehicle_color", fieldtype: "Link", options: "OtoBitz Vehicle Color", label: __("Vehicle Color")},
			{fieldname: "tahunpembuatan", fieldtype: "Data", label: __("Tahun Pembuatan")},
			{fieldname: "col_br_4", fieldtype: "Column Break"},
			{fieldname: "customer", fieldtype: "Link", options: "Customer", label: __("Customer"), reqd: 1},
		];
		super.render_dialog();
	}
};
