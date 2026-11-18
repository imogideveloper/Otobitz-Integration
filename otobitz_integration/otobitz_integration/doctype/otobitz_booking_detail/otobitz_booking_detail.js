// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

// Same flat header-dashboard approach as OtoBitz Receipt Detail's own JS
// (rcd_render in otobitz_receipt_detail.js) - one row here is already the
// whole allocation, no items table to join. Kept as its own self-contained
// copy rather than a shared helper, same reasoning as every other OtoBitz
// *_Detail doctype's JS in this app.

function obd_rupiah(value) {
	return frappe.format(flt(value), { fieldtype: "Currency" });
}

function obd_dash(value) {
	return value === null || value === undefined || value === "" ? "-" : frappe.utils.escape_html(String(value));
}

function obd_fmt_datetime(value) {
	if (!value) return "-";
	const m = String(value).match(/^(\d{4})-(\d{2})-(\d{2})(?: (\d{2}:\d{2}:\d{2}))?/);
	if (!m) return frappe.utils.escape_html(String(value));
	const date = `${m[3]}-${m[2]}-${m[1]}`;
	return m[4] && m[4] !== "00:00:00" ? `${date} ${m[4]}` : date;
}

function obd_field_box(label, valueHtml, opts) {
	opts = opts || {};
	return `
		<div class="wo-field ${opts.span2 ? "wo-field-span2" : ""}">
			<div class="wo-field-label">${frappe.utils.escape_html(label)}</div>
			<div class="wo-field-value ${opts.align_right ? "text-right" : ""} ${opts.bold ? "wo-field-bold" : ""}">${valueHtml}</div>
		</div>`;
}

// Same shared .wo-* class names as OtoBitz Receipt Detail/SO Detail/PO
// Detail - harmless if the style tag is injected more than once across
// doctypes since the id guard is per-doctype-file (sod-table-style is
// otobitz_receipt_detail.js's own id, so this needs its own).
function obd_inject_style() {
	if (document.getElementById("obd-table-style")) return;
	const s = document.createElement("style");
	s.id = "obd-table-style";
	s.textContent = `
.wo-summary{display:flex;flex-direction:column;gap:20px;padding-bottom:8px}
.wo-section-title{font-weight:600;font-size:13px;margin-bottom:10px;color:var(--text-color)}
.wo-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px 20px}
.wo-field-span2{grid-column:span 2}
.wo-field{display:flex;flex-direction:row;align-items:center;gap:10px}
.wo-field-label{font-size:11px;color:var(--text-muted);flex:0 0 140px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wo-field-value{flex:1 1 auto;min-width:0;background:var(--control-bg, #f4f5f6);border-radius:6px;padding:6px 10px;font-size:13px;min-height:18px;word-break:break-word}
.wo-field-value.wo-field-bold{font-weight:600}
.wo-totals{background:var(--control-bg, #f4f5f6);border-radius:8px;padding:12px 16px}
.wo-totals-row{display:flex;justify-content:space-between;gap:16px;padding:4px 0;font-size:13px}
.wo-totals-row.wo-totals-grand{border-top:1px solid var(--border-color);margin-top:4px;padding-top:8px;font-weight:700;font-size:14px}
`;
	document.head.appendChild(s);
}

function obd_render(frm) {
	const field = frm.fields_dict.booking_summary_html;
	if (!field) return;

	let h;
	try {
		h = JSON.parse(frm.doc.raw_data || "{}");
	} catch (e) {
		field.$wrapper.html(`<div class="text-muted">${__("Raw Data bukan JSON yang valid")}</div>`);
		return;
	}
	if (!h || !Object.keys(h).length) {
		field.$wrapper.html("");
		return;
	}

	obd_inject_style();

	const cancelled = (h.status || "").trim().toLowerCase() === "batal";
	frm.page.set_indicator(cancelled ? __("Dibatalkan") : __("Aktif"), cancelled ? "red" : "green");

	const main_section = `
		<div class="wo-section">
			<div class="wo-section-title">${__("Uang Muka Booking")}</div>
			<div class="wo-grid">
				${obd_field_box(__("Nomor Kuitansi"), obd_dash(h.nomor))}
				${obd_field_box(__("No Referensi (Booking)"), obd_dash(h.noreferensi))}
				${obd_field_box(__("Tanggal"), obd_fmt_datetime(h.tanggal))}
				${obd_field_box(__("Status"), cancelled ? __("Dibatalkan") : __("Aktif"))}
				${obd_field_box(__("Keterangan"), obd_dash(h.keterangan || h.memo), { span2: true })}
			</div>
		</div>`;

	const cabang_section = `
		<div class="wo-section">
			<div class="wo-section-title">${__("Cabang")}</div>
			<div class="wo-grid">
				${obd_field_box(__("Kode Cabang"), obd_dash(h.kode_cabang || h.kodecabang))}
				${obd_field_box(__("Cabang"), obd_dash(h.namacabang), { span2: true })}
			</div>
		</div>`;

	const party_section = `
		<div class="wo-section">
			<div class="wo-section-title">${__("Customer")}</div>
			<div class="wo-grid">
				${obd_field_box(__("Nama Customer"), obd_dash(h.namacustomer), { span2: true })}
				${obd_field_box(__("Metode Payment"), obd_dash(h.paymentmetode))}
			</div>
		</div>`;

	const totals_section = `
		<div class="wo-section" style="max-width:360px;margin-left:auto">
			<div class="wo-totals">
				<div class="wo-totals-row wo-totals-grand"><span>${__("Nilai Penerimaan")}</span><span>${obd_rupiah(h.nilaipenerimaan ?? h.nilai)}</span></div>
			</div>
		</div>`;

	field.$wrapper.html(`<div class="wo-summary">${main_section}${cabang_section}${party_section}${totals_section}</div>`);
}

frappe.ui.form.on("OtoBitz Booking Detail", {
	refresh(frm) {
		obd_render(frm);
	},
});
