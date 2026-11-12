// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

// 1 OtoBitz PO Detail row is already the WHOLE order (header + every detail
// line, as one JSON blob) - unlike OtoBitz SO Detail, there's no sibling-row
// join needed here, so this dashboard is built entirely client-side from
// this one record's own raw_data.
//
// Two source endpoints share this doctype (masterdata_orderparts and
// masterdata_orderpekerjaanluar) with slightly different `detail[]` shapes:
// orderparts rows carry kodepart/namapart/qty/harga/total/discperitem;
// orderpekerjaanluar rows only carry kodeopl/namaopl/hargabeli (a flat
// external-labor cost, no qty/discount breakdown) - po_item_row() below
// normalizes both into the same 6-column table.

function pod_rupiah(value) {
	return frappe.format(flt(value), { fieldtype: "Currency" });
}

function pod_dash(value) {
	return value === null || value === undefined || value === "" ? "-" : frappe.utils.escape_html(String(value));
}

function pod_fmt_datetime(value) {
	if (!value) return "-";
	const m = String(value).match(/^(\d{4})-(\d{2})-(\d{2})(?: (\d{2}:\d{2}:\d{2}))?/);
	if (!m) return frappe.utils.escape_html(String(value));
	const date = `${m[3]}-${m[2]}-${m[1]}`;
	return m[4] ? `${date} ${m[4]}` : date;
}

function pod_field_box(label, valueHtml, opts) {
	opts = opts || {};
	return `
		<div class="wo-field ${opts.span2 ? "wo-field-span2" : ""}">
			<div class="wo-field-label">${frappe.utils.escape_html(label)}</div>
			<div class="wo-field-value ${opts.align_right ? "text-right" : ""} ${opts.bold ? "wo-field-bold" : ""}">${valueHtml}</div>
		</div>`;
}

function pod_check_chip(ok, label) {
	const icon = ok ? "✓" : "✕";
	return `<span class="wo-chip ${ok ? "wo-chip-ok" : "wo-chip-fail"}">${icon} ${frappe.utils.escape_html(label)}</span>`;
}

// Shared .wo-* dashboard classes - same id/content as OtoBitz SO Detail's own
// injector, so whichever of the two doctype scripts loads first in a given
// session is the one that actually adds the <style> tag; the other's call is
// just a no-op (getElementById guard). Not calling SO Detail's own function
// directly - a plain top-level `function` in one doctype's JS does land in
// the same global scope once Desk has bundled/loaded it, but there's no
// guarantee that file has loaded yet in every session (e.g. a PO Detail
// opened cold, OtoBitz SO Detail never touched this session) - keeping this
// copy fully self-contained avoids that ordering trap.
function pod_inject_style() {
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

// Normalizes one detail[] entry (either shape) into {kode, nama, qty, harga, diskon, total}.
function pod_item_row(d) {
	if ("kodepart" in d) {
		return {
			kode: d.kodepart,
			nama: d.namapart,
			qty: flt(d.qty) || 1,
			harga: flt(d.harga),
			diskon: flt(d.discperitem),
			total: flt(d.total),
		};
	}
	return {
		kode: d.kodeopl,
		nama: d.namaopl,
		qty: 1,
		harga: flt(d.hargabeli),
		diskon: 0,
		total: flt(d.hargabeli),
	};
}

function pod_render(frm) {
	const field = frm.fields_dict.po_summary_html;
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

	pod_inject_style();

	const detail = h.detail || [];
	const items = detail.map(pod_item_row);
	const sum_total = items.reduce((a, it) => a + it.total, 0);
	const dpp = flt(h.dpp);
	const ppn = flt(h.ppn);
	const total = flt(h.total);
	const tolerance = Math.max(2, items.length);
	const item_dpp_match = Math.abs(sum_total - dpp) <= tolerance;
	const total_match = Math.abs(dpp + ppn - total) <= tolerance;
	const cancelled = (h.batal || "").trim().toLowerCase() === "t";

	frm.page.set_indicator(cancelled ? __("Dibatalkan") : __("Aktif"), cancelled ? "red" : "green");

	const checks = `
		<div class="wo-checks">
			${pod_check_chip(item_dpp_match, __("Σ Item = DPP"))}
			${pod_check_chip(total_match, __("DPP + PPN = Total"))}
		</div>`;

	const order_section = `
		<div class="wo-section">
			<div class="wo-section-title">${__("Order")}</div>
			<div class="wo-grid">
				${pod_field_box(__("Nomor Order"), pod_dash(h.nomor))}
				${pod_field_box(__("Tanggal"), pod_fmt_datetime(h.tanggal))}
				${pod_field_box(__("Endpoint"), pod_dash(h.endpoint || frm.doc.endpoint))}
				${pod_field_box(__("Status"), cancelled ? __("Dibatalkan") : __("Aktif"))}
				${h.nomor_so ? pod_field_box(__("Nomor SO Terkait"), pod_dash(h.nomor_so)) : ""}
				${h.nopolisi ? pod_field_box(__("Nomor Polisi"), pod_dash(h.nopolisi)) : ""}
				${cancelled ? pod_field_box(__("Tanggal Batal"), pod_fmt_datetime(h.tglbatal)) : ""}
			</div>
		</div>`;

	const supplier_section = `
		<div class="wo-section">
			<div class="wo-section-title">${__("Supplier & Cabang")}</div>
			<div class="wo-grid">
				${pod_field_box(__("Kode Supplier"), pod_dash(h.kodesupplier))}
				${pod_field_box(__("Nama Supplier"), pod_dash(h.namasupplier), { span2: true })}
				${pod_field_box(__("Kode Cabang"), pod_dash(h.kodecabang || h.kode_cabang))}
				${pod_field_box(__("Cabang"), pod_dash(h.namacabang), { span2: true })}
			</div>
		</div>`;

	const items_rows = items
		.map(
			(it, i) => `
			<tr>
				<td>${i + 1}</td>
				<td>${pod_dash(it.kode)}</td>
				<td>${pod_dash(it.nama)}</td>
				<td class="text-right">${it.qty.toLocaleString("id-ID")}</td>
				<td class="text-right">${pod_rupiah(it.harga)}</td>
				<td class="text-right">${pod_rupiah(it.diskon)}</td>
				<td class="text-right">${pod_rupiah(it.total)}</td>
			</tr>`
		)
		.join("");

	const items_section = `
		<div class="wo-section">
			<div class="wo-section-title">${__("Items")}</div>
			<div class="wo-table-wrap">
				<table class="table table-bordered wo-item-table">
					<thead>
						<tr>
							<th>${__("No.")}</th><th>${__("Kode")}</th><th>${__("Nama")}</th>
							<th class="text-right">${__("Qty")}</th><th class="text-right">${__("Harga")}</th>
							<th class="text-right">${__("Diskon")}</th><th class="text-right">${__("Total")}</th>
						</tr>
					</thead>
					<tbody>${items_rows}</tbody>
					<tfoot>
						<tr>
							<td colspan="2"><b>${__("Total")}</b></td>
							<td class="text-muted">${__("{0} item", [items.length])}</td>
							<td></td><td></td><td></td>
							<td class="text-right"><b>${pod_rupiah(sum_total)}</b></td>
						</tr>
					</tfoot>
				</table>
			</div>
		</div>`;

	const totals_section = `
		<div class="wo-section" style="max-width:360px;margin-left:auto">
			<div class="wo-totals">
				<div class="wo-totals-row"><span>${__("DPP")}</span><span>${pod_rupiah(dpp)}</span></div>
				<div class="wo-totals-row"><span>${__("PPN")}</span><span>${pod_rupiah(ppn)}</span></div>
				<div class="wo-totals-row wo-totals-grand"><span>${__("Total")}</span><span>${pod_rupiah(total)}</span></div>
			</div>
		</div>`;

	field.$wrapper.html(`<div class="wo-summary">${checks}${order_section}${supplier_section}${items_section}${totals_section}</div>`);
}

frappe.ui.form.on("OtoBitz PO Detail", {
	refresh(frm) {
		pod_render(frm);
	},
});
