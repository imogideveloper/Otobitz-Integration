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

		// Sync Now / Sync Ulang dari Tanggal / Benerin Nama Customer are all
		// enqueued server-side now (see otobitz_settings.py's docstrings) -
		// never run them synchronously in-request, even in developer_mode:
		// confirmed live that a sync spanning several endpoints/days can
		// outlast gunicorn's 120s worker timeout, which SIGKILLs the
		// worker mid-sync with zero progress saved and nothing useful
		// shown in the browser (just a silently-reset request). The call
		// here only enqueues, so it returns almost instantly - no freeze
		// needed, and there's no inline result to show, just a "queued"
		// toast. Progress is visible in the OtoBitz Sync Log list / the
		// Ringkasan OtoBitz counts above after a refresh.
		frm.add_custom_button(__("Sync Now"), () => {
			frm.call("sync_now").then(() => frappe.show_alert({ message: __("Sync sudah diantrikan."), indicator: "green" }));
		});

		frm.add_custom_button(__("Benerin Nama Customer"), () => {
			frappe.confirm(
				__(
					"Cek ulang semua nama Customer yang masih acak (gagal didekripsi) ke OtoBitz, dan perbaiki Sales Order/Sales Invoice yang masih kebawa nama lama? Bisa makan waktu agak lama di background."
				),
				() => {
					frm.call("fix_customer_names").then(() =>
						frappe.show_alert({ message: __("Sudah diantrikan - cek OtoBitz Sync Log / Error Log beberapa saat lagi."), indicator: "green" }, 7)
					);
				}
			);
		});

		frm.add_custom_button(__("Benerin Nama Customer per Tanggal"), () => {
			if (!frm.doc.fix_customer_names_from_date) {
				frappe.msgprint(__("Pilih tanggal dulu di field \"Dari Tanggal\" (bagian Benerin Nama Customer)."));
				return;
			}
			const from_label = frappe.datetime.str_to_user(frm.doc.fix_customer_names_from_date);
			const range_label = !frm.doc.fix_customer_names_to_date || frm.doc.fix_customer_names_to_date === frm.doc.fix_customer_names_from_date
				? __("persis tanggal {0}", [from_label])
				: __("dari tanggal {0} sampai {1}", [from_label, frappe.datetime.str_to_user(frm.doc.fix_customer_names_to_date)]);
			frappe.confirm(
				__(
					"Cek ulang nama Customer buat yang transaksi {0}, dan perbaiki Sales Order/Sales Invoice yang masih kebawa nama lama? Jalan di background.",
					[range_label]
				),
				() => {
					frm.call("fix_customer_names_for_date").then(() =>
						frappe.show_alert({ message: __("Sudah diantrikan - cek OtoBitz Sync Log / Error Log beberapa saat lagi."), indicator: "green" }, 7)
					);
				}
			);
		});

		frm.add_custom_button(__("Sync Ulang dari Tanggal"), () => {
			if (!frm.doc.manual_sync_from_date) {
				frappe.msgprint(__("Pilih tanggal dulu di field \"Sync Ulang dari Tanggal\"."));
				return;
			}
			const from_label = frappe.datetime.str_to_user(frm.doc.manual_sync_from_date);
			let range_label;
			if (!frm.doc.manual_sync_to_date) {
				range_label = __("dari tanggal {0} sampai hari ini", [from_label]);
			} else if (frm.doc.manual_sync_to_date === frm.doc.manual_sync_from_date) {
				range_label = __("persis tanggal {0} aja", [from_label]);
			} else {
				range_label = __("dari tanggal {0} sampai {1}", [from_label, frappe.datetime.str_to_user(frm.doc.manual_sync_to_date)]);
			}
			frappe.confirm(
				__(
					"Sinkronisasi ulang Sales Order, Payment Entry, Journal Entry, dan Purchase Order {0}? Jalan di background, bisa makan waktu beberapa menit.",
					[range_label]
				),
				() => {
					frm.call("sync_from_date").then(() =>
						frappe.show_alert({ message: __("Sudah diantrikan - cek OtoBitz Sync Log beberapa saat lagi."), indicator: "green" })
					);
				}
			);
		});

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
