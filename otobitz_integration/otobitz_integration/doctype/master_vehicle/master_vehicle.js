// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

frappe.ui.form.on("Master Vehicle", {
	refresh(frm) {
		frm.page.set_indicator(
			frm.doc.customer ? __("Terhubung Customer") : __("Belum Terhubung"),
			frm.doc.customer ? "green" : "orange"
		);
		frm.dashboard.set_headline_alert(
			__("Data kendaraan ini disinkronkan otomatis dari OtoBitz dan hanya dapat diubah dari sana."),
			"blue"
		);

		if (!frm.is_new()) mv_render_owner_history_button(frm);
	},
});

function mv_render_owner_history_button(frm) {
	frappe.call({
		method: "otobitz_integration.otobitz_integration.doctype.master_vehicle.master_vehicle.get_owner_history",
		args: { vehicle: frm.doc.name },
		callback(r) {
			const data = r.message || {};
			const has_history = (data.history || []).length > 0;

			$(frm.wrapper).find(".mv-owner-history-btn").remove();
			const $btn = frm.page.add_inner_button(__("Riwayat Data Pemilik"), () => {
				mv_show_owner_history_dialog(data);
			});
			$btn.addClass("mv-owner-history-btn");
			if (!has_history) {
				$btn.prop("disabled", true).css({ opacity: 0.5, cursor: "not-allowed" });
				$btn.attr("title", __("Belum ada riwayat perubahan pemilik untuk kendaraan ini"));
			}
		},
	});
}

function mv_show_owner_history_dialog(data) {
	const current = data.current;
	const history = data.history || [];

	const current_html = current
		? `<div style="display:flex;align-items:center;justify-content:space-between;border:1px solid var(--border-color);border-radius:8px;padding:12px 14px;margin-bottom:14px">
			<div>
				<div style="font-weight:600">${frappe.utils.escape_html(current.customer_name || current.name)}</div>
				<div style="color:var(--text-muted);font-size:var(--text-sm)">${frappe.utils.escape_html(current.mobile_no || "")}</div>
			</div>
			<span class="indicator-pill green">${__("PEMILIK SAAT INI")}</span>
		</div>`
		: `<div style="color:var(--text-muted);margin-bottom:14px">${__("Belum ada pemilik")}</div>`;

	const rows_html = history
		.map(
			(h) => `<tr>
				<td>${frappe.utils.escape_html(h.previous_owner_name || h.previous_owner)}</td>
				<td>${frappe.utils.escape_html(h.previous_owner_phone || "-")}</td>
				<td>${frappe.datetime.str_to_user(h.creation)}</td>
				<td>${frappe.utils.escape_html(h.changed_by_name || h.owner)}</td>
			</tr>`
		)
		.join("");

	const history_html = history.length
		? `<div style="color:var(--text-muted);font-size:var(--text-sm);margin-bottom:6px">${__(
				"PEMILIK SEBELUMNYA"
		  )}</div>
			<table class="table table-bordered">
				<thead><tr>
					<th>${__("Pemilik")}</th>
					<th>${__("Telepon")}</th>
					<th>${__("Tgl Diubah")}</th>
					<th>${__("Oleh")}</th>
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
