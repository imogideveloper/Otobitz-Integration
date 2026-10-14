// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

function render_otobitz_dashboard(frm, data) {
	const stat = (label, value, color) => `
		<div style="flex:1 1 140px; border:1px solid var(--border-color); border-radius:var(--border-radius); padding:10px 12px;">
			<div style="font-size:12px; color:var(--text-muted);">${label}</div>
			<div style="font-size:20px; font-weight:600; color:${color || "var(--text-color)"};">${value}</div>
		</div>`;

	const html = `
		<div style="display:flex; flex-wrap:wrap; gap:10px; margin-bottom:10px;">
			${stat(__("Kategori Kendaraan Aktif"), data.vehicle_category_active)}
			${stat(__("Tipe Kendaraan Aktif"), data.vehicle_type_active)}
			${stat(__("Warna Kendaraan Aktif"), data.vehicle_color_active)}
			${stat(__("Menu Servis Aktif"), data.service_menu_active)}
			${stat(__("Total Kendaraan"), data.vehicle_total)}
		</div>
		<div style="display:flex; flex-wrap:wrap; gap:10px;">
			${stat(__("Sync Sukses (7 hari)"), data.sync_success_7d, "var(--green-600)")}
			${stat(__("Sync Partial (7 hari)"), data.sync_partial_7d, "var(--orange-600)")}
			${stat(__("Sync Gagal (7 hari)"), data.sync_failed_7d, "var(--red-600)")}
		</div>`;

	frm.get_field("dashboard_html").$wrapper.html(html);
}

frappe.ui.form.on("OtoBitz Settings", {
	refresh(frm) {
		frm.call("get_dashboard_summary").then((r) => r.message && render_otobitz_dashboard(frm, r.message));

		frm.add_custom_button(__("Sync Now"), () => frm.call("sync_now").then(() => frm.reload_doc()));

		frm.add_custom_button(__("Look Up Work Order"), () => {
			if (!frm.doc.lookup_wo_number) {
				frappe.msgprint(__("Enter a Work Order Number (nomorwo) first."));
				return;
			}
			frappe.dom.freeze(__("Looking up {0}...", [frm.doc.lookup_wo_number]));
			frm.call("lookup_wo")
				.then((r) => {
					frappe.dom.unfreeze();
					const data = r.message;
					if (!data || !data.found) {
						frappe.msgprint(__("No Work Order found for that number."));
						return;
					}
					let msg = data.created
						? __("Created Sales Order {0}", [data.sales_order])
						: __("Sales Order {0} already existed, re-checked", [data.sales_order]);
					if (data.sales_invoice) {
						msg += "<br>" + __("Sales Invoice: {0}", [data.sales_invoice]);
					}
					frappe.msgprint({ title: __("Done"), message: msg, indicator: "green" });
				})
				.catch(() => frappe.dom.unfreeze());
		});
	},
});
