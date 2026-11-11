// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

frappe.ui.form.on("Master Vehicle", {
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
					{
						fieldname: "customer",
						label: __("Pemilik Baru"),
						fieldtype: "Link",
						options: "Customer",
						reqd: 1,
						get_query: () => ({ filters: { name: ["!=", frm.doc.customer || ""] } }),
					},
					{ fieldname: "date", label: __("Tanggal"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
					{ fieldname: "note", label: __("Catatan"), fieldtype: "Small Text" },
				],
				(v) => {
					frappe.call({
						method: "otobitz_integration.otobitz_integration.doctype.master_vehicle.master_vehicle.change_owner",
						args: { vehicle: frm.doc.name, customer: v.customer, date: v.date, note: v.note },
						freeze: true,
						callback: () => frm.reload_doc(),
					});
				},
				__("Ganti Pemilik"),
				__("Simpan")
			);
		});

		mv_render_owner_history_button(frm);
	},
});

function mv_render_owner_history_button(frm) {
	const history = (frm.doc.owner_history || []).slice().reverse();

	$(frm.wrapper).find(".mv-owner-history-btn").remove();
	const $btn = frm.page.add_inner_button(__("Riwayat Data Pemilik"), () => {
		mv_show_owner_history_dialog(frm, history);
	});
	$btn.addClass("mv-owner-history-btn");
	if (!history.length) {
		$btn.prop("disabled", true).css({ opacity: 0.5, cursor: "not-allowed" });
		$btn.attr("title", __("Belum ada riwayat perubahan pemilik untuk kendaraan ini"));
	}
}

function mv_show_owner_history_dialog(frm, history) {
	const esc = frappe.utils.escape_html;

	const current_html = frm.doc.customer
		? `<div style="display:flex;align-items:center;justify-content:space-between;border:1px solid var(--border-color);border-radius:8px;padding:12px 14px;margin-bottom:14px">
			<div style="font-weight:600">${esc(frm.doc.customer)}</div>
			<span class="indicator-pill green">${__("PEMILIK SAAT INI")}</span>
		</div>`
		: `<div style="color:var(--text-muted);margin-bottom:14px">${__("Belum ada pemilik")}</div>`;

	const rows_html = history
		.map(
			(r) => `<tr>
				<td>${esc(r.customer_name || r.customer || "")}</td>
				<td>${r.from_date ? frappe.datetime.str_to_user(r.from_date) : "-"}</td>
				<td>${r.to_date ? frappe.datetime.str_to_user(r.to_date) : __("sekarang")}</td>
				<td>${esc(r.source || "")}</td>
				<td>${esc(r.notes || "")}</td>
			</tr>`
		)
		.join("");

	const history_html = history.length
		? `<div style="color:var(--text-muted);font-size:var(--text-sm);margin-bottom:6px">${__("PEMILIK SEBELUMNYA")}</div>
			<table class="table table-bordered">
				<thead><tr>
					<th>${__("Pemilik")}</th>
					<th>${__("Dari")}</th>
					<th>${__("Sampai")}</th>
					<th>${__("Sumber")}</th>
					<th>${__("Catatan")}</th>
				</tr></thead>
				<tbody>${rows_html}</tbody>
			</table>`
		: "";

	const d = new frappe.ui.Dialog({
		title: __("Riwayat Pemilik"),
		fields: [{ fieldname: "body", fieldtype: "HTML" }],
	});
	d.fields_dict.body.$wrapper.html(current_html + history_html);
	d.show();
}
