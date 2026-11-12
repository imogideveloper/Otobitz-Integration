// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

// 1 OtoBitz Receipt Detail row is already the whole transaction (no detail[]
// array to join, unlike PO Detail's orders or SO Detail's per-WO items), so
// this is a flat header dashboard built client-side from raw_data - no
// items table, no cross-row validation needed.
//
// penerimaanuang and pengeluaranuang share this doctype but disagree on the
// amount fieldname (nilaipenerimaan vs nilaipembayaran, confirmed live on
// real rows of each) and on which "other party" field is populated
// (namacustomer for a receipt, namasupplier for a payment - empty/absent
// for a plain cash deposit/"Setoran", which pengeluaranuang also covers).

function rcd_rupiah(value) {
	return frappe.format(flt(value), { fieldtype: "Currency" });
}

function rcd_dash(value) {
	return value === null || value === undefined || value === "" ? "-" : frappe.utils.escape_html(String(value));
}

function rcd_fmt_datetime(value) {
	if (!value) return "-";
	const m = String(value).match(/^(\d{4})-(\d{2})-(\d{2})(?: (\d{2}:\d{2}:\d{2}))?/);
	if (!m) return frappe.utils.escape_html(String(value));
	const date = `${m[3]}-${m[2]}-${m[1]}`;
	return m[4] && m[4] !== "00:00:00" ? `${date} ${m[4]}` : date;
}

function rcd_field_box(label, valueHtml, opts) {
	opts = opts || {};
	return `
		<div class="wo-field ${opts.span2 ? "wo-field-span2" : ""}">
			<div class="wo-field-label">${frappe.utils.escape_html(label)}</div>
			<div class="wo-field-value ${opts.align_right ? "text-right" : ""} ${opts.bold ? "wo-field-bold" : ""}">${valueHtml}</div>
		</div>`;
}

// Same shared .wo-* classes as OtoBitz SO Detail/PO Detail - see
// otobitz_po_detail.js's pod_inject_style() for why each doctype keeps its
// own self-contained copy instead of calling another file's function.
function rcd_inject_style() {
	if (document.getElementById("sod-table-style")) return;
	const s = document.createElement("style");
	s.id = "sod-table-style";
	s.textContent = `
.wo-summary{display:flex;flex-direction:column;gap:20px;padding-bottom:8px}
.wo-checks{display:flex;flex-wrap:wrap;gap:8px}
.wo-chip{font-size:12px;font-weight:500;padding:3px 10px;border-radius:999px;display:inline-flex;align-items:center;gap:4px}
.wo-chip-ok{background:var(--bg-green, #e6f4ea);color:var(--text-on-light-green, #137333)}
.wo-chip-fail{background:var(--bg-red, #fce8e6);color:var(--text-on-light-red, #c5221f)}
.wo-section-title{font-weight:600;font-size:13px;margin-bottom:10px;color:var(--text-color)}
.wo-section-title-row{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px}
.wo-section-hint{font-size:11px}
.wo-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px 20px}
.wo-grid-1{grid-template-columns:1fr}
.wo-section-split{display:grid;grid-template-columns:1fr 1fr;gap:24px}
.wo-field-span2{grid-column:span 2}
.wo-field{display:flex;flex-direction:row;align-items:center;gap:10px}
.wo-field-label{font-size:11px;color:var(--text-muted);flex:0 0 140px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wo-field-value{flex:1 1 auto;min-width:0;background:var(--control-bg, #f4f5f6);border-radius:6px;padding:6px 10px;font-size:13px;min-height:18px;word-break:break-word}
.wo-field-value.wo-field-bold{font-weight:600}
.wo-badge{font-size:11px;font-weight:500;padding:1px 8px;border-radius:10px;display:inline-block}
.wo-badge-part{background:var(--bg-blue, #e8f0fe);color:var(--text-on-light-blue, #1a73e8)}
.wo-badge-jasa{background:var(--bg-purple, #f3e8fd);color:var(--text-on-light-purple, #8430ce)}
.wo-table-wrap{overflow-x:auto}
.wo-item-table{margin-bottom:0;font-size:12px}
.wo-item-table th{white-space:nowrap;font-size:11px}
.wo-item-row{cursor:pointer}
.wo-item-row:hover{background:var(--control-bg, #f4f5f6)}
.wo-totals{background:var(--control-bg, #f4f5f6);border-radius:8px;padding:12px 16px}
.wo-totals-row{display:flex;justify-content:space-between;gap:16px;padding:4px 0;font-size:13px}
.wo-totals-row.wo-totals-grand{border-top:1px solid var(--border-color);margin-top:4px;padding-top:8px;font-weight:700;font-size:14px}
`;
	document.head.appendChild(s);
}

function rcd_render(frm) {
	const field = frm.fields_dict.receipt_summary_html;
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

	rcd_inject_style();

	const cancelled = (h.status || "").trim().toLowerCase() !== "tidak batal" && !!(h.status || "").trim();
	const amount = h.nilaipenerimaan ?? h.nilaipembayaran ?? h.nilai;
	const is_pengeluaran = (frm.doc.endpoint || h.endpoint) === "pengeluaranuang" || "nilaipembayaran" in h;

	frm.page.set_indicator(cancelled ? __("Dibatalkan") : __("Aktif"), cancelled ? "red" : "green");

	const main_section = `
		<div class="wo-section">
			<div class="wo-section-title">${__("Transaksi")}</div>
			<div class="wo-grid">
				${rcd_field_box(__("Nomor"), rcd_dash(h.nomor))}
				${rcd_field_box(__("Tanggal"), rcd_fmt_datetime(h.tanggal))}
				${rcd_field_box(__("Status"), cancelled ? __("Dibatalkan") : __("Aktif"))}
				${rcd_field_box(__("Jenis"), rcd_dash(h.jenisterima))}
				${rcd_field_box(__("Keterangan"), rcd_dash(h.keterangan || h.memo), { span2: true })}
			</div>
		</div>`;

	const cabang_section = `
		<div class="wo-section">
			<div class="wo-section-title">${__("Cabang")}</div>
			<div class="wo-grid">
				${rcd_field_box(__("Kode Cabang"), rcd_dash(h.kode_cabang || h.kodecabang))}
				${rcd_field_box(__("Cabang"), rcd_dash(h.namacabang), { span2: true })}
			</div>
		</div>`;

	const party_rows = [
		rcd_field_box(__("No Referensi (Faktur)"), rcd_dash(h.noreferensi)),
		h.namacustomer ? rcd_field_box(__("Nama Customer"), rcd_dash(h.namacustomer)) : "",
		h.namasupplier ? rcd_field_box(__("Nama Supplier"), rcd_dash(h.namasupplier)) : "",
		rcd_field_box(__("Kode Account"), rcd_dash(h.kodeaccount)),
		rcd_field_box(__("Nama Account"), rcd_dash(h.namaaccount)),
		h.paymentmetode ? rcd_field_box(__("Metode Payment"), rcd_dash(h.paymentmetode)) : "",
		h.namapayment ? rcd_field_box(__("Nama Payment"), rcd_dash(h.namapayment)) : "",
	].join("");

	const payment_section = `
		<div class="wo-section">
			<div class="wo-section-title">${__(is_pengeluaran ? "Pembayaran / Setoran" : "Pembayaran / Penerimaan")}</div>
			<div class="wo-grid">${party_rows}</div>
		</div>`;

	const totals_section = `
		<div class="wo-section" style="max-width:360px;margin-left:auto">
			<div class="wo-totals">
				<div class="wo-totals-row wo-totals-grand"><span>${__(is_pengeluaran ? "Nilai Pembayaran" : "Nilai Penerimaan")}</span><span>${rcd_rupiah(amount)}</span></div>
			</div>
		</div>`;

	field.$wrapper.html(`<div class="wo-summary">${main_section}${cabang_section}${payment_section}${totals_section}</div>`);
}

frappe.ui.form.on("OtoBitz Receipt Detail", {
	refresh(frm) {
		rcd_render(frm);
	},
});
