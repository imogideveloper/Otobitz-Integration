// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

// Two independent views built from raw_data:
// 1. wo_summary_html (top of form, always built) - joins every sibling row
//    sharing this record's Nomor WO (1 row = 1 item, per this doctype's
//    design) back into one Work Order view: header info, a combined items
//    table, totals, and the three cross-checks a human would otherwise have
//    to eyeball (header fields actually matching across rows, item subtotal
//    summing to dpp, item+tax summing to grandtotal).
// 2. raw_data_table (collapsed "Data Mentah" section) - this ONE row's raw
//    JSON only, as a labeled key/value table instead of a flat blob. Kept
//    as the "inspect exactly what OtoBitz sent for this row" power tool.

const SOD_LABELS = {
	nomorwo: "Nomor WO", tanggal: "Tanggal", statuswo: "Status WO", nofaktur: "No. Faktur",
	tglfaktur: "Tanggal Faktur", nomorbooking: "Nomor Booking", idbooking: "ID Booking",
	booking: "Booking", jenisservice: "Jenis Service", referensi: "Referensi",
	keterangan: "Keterangan", saran: "Saran", jenissaran: "Jenis Saran",
	nama_regularcheck: "Regular Check", intervalsrv: "Interval Servis", leadtime: "Lead Time",
	ths: "THS", garansi: "Garansi", returnjob: "Return Job", inventaris: "Inventaris",
	tglbatal: "Tanggal Batal", userbatal: "User Batal", keteranganbatal: "Keterangan Batal",
	noreferensi: "No. Referensi",

	kode_cabang: "Kode Cabang", namacabang: "Cabang", kodesubcabang: "Kode Sub Cabang",
	kodecompany: "Kode Company", kodegrup: "Kode Grup", teknisi: "Teknisi", kodeteknisi: "Kode Teknisi",

	nama: "Nama Customer", customerid: "ID Customer", pic: "PIC", nohppic: "No. HP PIC",
	nohp: "No. HP", notlp: "No. Telp", email: "Email", pemakai: "Pemakai", title: "Title",
	jeniscustomer: "Jenis Customer", alamat: "Alamat", alamat1: "Alamat (Lengkap)",
	kelurahan: "Kelurahan", kecamatan: "Kecamatan", kota: "Kota", kodepos: "Kode Pos",
	provinsi: "Provinsi", namatagihan: "Nama Tagihan", nik: "NIK", npwp: "NPWP",
	statusjual: "Status Jual",

	nopolisi: "Nomor Polisi", norangka: "Nomor Rangka", nomesin: "Nomor Mesin",
	tipe: "Tipe Kendaraan", kodetipe: "Kode Tipe", namawarna: "Warna", kodewarna: "Kode Warna",
	jeniskendaraan: "Jenis Kendaraan", kategorikendaraan: "Kategori Kendaraan",
	tahunpembuatan: "Tahun Pembuatan", odemeter: "Odometer", statusjeniskendaraan: "Status Jenis Kendaraan",

	kodereferensi: "Kode Item", namareferensi: "Nama Item", jenisdoc: "Jenis (Part/Jasa)",
	qty: "Qty", harga: "Harga Satuan", discperitem: "Diskon", persendiscperitem: "Diskon (%)",
	subtotal: "Subtotal Item", kodeservicemenu: "Kode Service Menu", keluhan: "Keluhan",

	dpp: "DPP", ppn: "PPN", subtotalppn: "Subtotal PPN", grandtotal: "Grand Total",
	hpp: "HPP", cogsmaster: "COGS Master", hargappn: "Harga PPN", rounding: "Pembulatan",
	nilaipiutang: "Nilai Piutang", nilaiuangmuka: "Nilai Uang Muka",
	nilaipenerimaan: "Nilai Penerimaan", sisapiutang: "Sisa Piutang",
	kodepayment: "Kode Payment", namapaymentmetode: "Metode Payment",
	kodevoucher: "Kode Voucher", namavoucher: "Nama Voucher",
};

const SOD_AMOUNT_FIELDS = new Set([
	"dpp", "ppn", "subtotalppn", "grandtotal", "hpp", "cogsmaster", "hargappn", "rounding",
	"harga", "discperitem", "subtotal", "nilaipiutang", "nilaiuangmuka", "nilaipenerimaan", "sisapiutang",
]);

const SOD_GROUPS = [
	{ title: "Work Order & Faktur", keys: [
		"nomorwo", "tanggal", "statuswo", "nofaktur", "tglfaktur", "nomorbooking", "idbooking", "booking",
		"jenisservice", "referensi", "keterangan", "saran", "jenissaran", "nama_regularcheck",
		"intervalsrv", "leadtime", "ths", "garansi", "returnjob", "inventaris",
		"tglbatal", "userbatal", "keteranganbatal", "noreferensi",
	] },
	{ title: "Cabang & Teknisi", keys: [
		"kode_cabang", "namacabang", "kodesubcabang", "kodecompany", "kodegrup", "teknisi", "kodeteknisi",
	] },
	{ title: "Customer", keys: [
		"nama", "customerid", "pic", "nohppic", "nohp", "notlp", "email", "pemakai", "title",
		"jeniscustomer", "alamat", "alamat1", "kelurahan", "kecamatan", "kota", "kodepos",
		"provinsi", "namatagihan", "nik", "npwp", "statusjual",
	] },
	{ title: "Kendaraan", keys: [
		"nopolisi", "norangka", "nomesin", "tipe", "kodetipe", "namawarna", "kodewarna",
		"jeniskendaraan", "kategorikendaraan", "tahunpembuatan", "odemeter", "statusjeniskendaraan",
	] },
	{ title: "Item", keys: [
		"kodereferensi", "namareferensi", "jenisdoc", "qty", "harga", "discperitem",
		"persendiscperitem", "subtotal", "kodeservicemenu", "keluhan",
	] },
	{ title: "Total & Pembayaran", keys: [
		"dpp", "ppn", "subtotalppn", "grandtotal", "hpp", "cogsmaster", "hargappn", "rounding",
		"nilaipiutang", "nilaiuangmuka", "nilaipenerimaan", "sisapiutang",
		"kodepayment", "namapaymentmetode", "kodevoucher", "namavoucher",
	] },
];

function sod_humanize(key) {
	return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function sod_rupiah(value) {
	return frappe.format(flt(value), { fieldtype: "Currency" });
}

function sod_format_value(key, value) {
	if (value === null || value === undefined || value === "") return "<span class=\"text-muted\">-</span>";
	if (SOD_AMOUNT_FIELDS.has(key) && !isNaN(parseFloat(value))) {
		return sod_rupiah(value);
	}
	return frappe.utils.escape_html(String(value));
}

// ---- 1. Raw Data (Tabel): this one row's own JSON, flat & grouped ----

function sod_render_table(frm) {
	const field = frm.fields_dict.raw_data_table;
	if (!field) return;

	let data;
	try {
		data = JSON.parse(frm.doc.raw_data || "{}");
	} catch (e) {
		field.$wrapper.html(`<div class="text-muted">${__("Raw Data bukan JSON yang valid")}</div>`);
		return;
	}

	const seen = new Set();
	const sections = [];
	SOD_GROUPS.forEach((group) => {
		const rows = group.keys.filter((k) => k in data);
		rows.forEach((k) => seen.add(k));
		if (rows.length) sections.push({ title: group.title, keys: rows });
	});
	const leftover = Object.keys(data).filter((k) => !seen.has(k));
	if (leftover.length) sections.push({ title: __("Lainnya"), keys: leftover });

	const html = sections
		.map((s) => `
			<div class="sod-group">
				<div class="sod-group-title">${frappe.utils.escape_html(s.title)}</div>
				<table class="table table-bordered sod-table">
					<tbody>
						${s.keys
							.map(
								(k) => `
							<tr>
								<td class="sod-label">${frappe.utils.escape_html(SOD_LABELS[k] || sod_humanize(k))}</td>
								<td class="${SOD_AMOUNT_FIELDS.has(k) ? "text-right" : ""}">${sod_format_value(k, data[k])}</td>
							</tr>`
							)
							.join("")}
					</tbody>
				</table>
			</div>`)
		.join("");

	field.$wrapper.html(`<div class="sod-table-wrap">${html}</div>`);
}

// ---- 2. Ringkasan WO: join every sibling row for this Nomor WO ----

function sod_fmt_datetime(value) {
	if (!value) return "-";
	const m = String(value).match(/^(\d{4})-(\d{2})-(\d{2})(?: (\d{2}:\d{2}:\d{2}))?/);
	if (!m) return frappe.utils.escape_html(String(value));
	const date = `${m[3]}-${m[2]}-${m[1]}`;
	return m[4] ? `${date} ${m[4]}` : date;
}

function sod_fmt_number(value) {
	const n = parseFloat(value);
	if (isNaN(n)) return "-";
	return n.toLocaleString("id-ID");
}

function sod_dash(value) {
	return value === null || value === undefined || value === "" ? "-" : frappe.utils.escape_html(String(value));
}

function sod_field_box(label, valueHtml, opts) {
	opts = opts || {};
	return `
		<div class="wo-field ${opts.span2 ? "wo-field-span2" : ""}">
			<div class="wo-field-label">${frappe.utils.escape_html(label)}</div>
			<div class="wo-field-value ${opts.align_right ? "text-right" : ""} ${opts.bold ? "wo-field-bold" : ""}">${valueHtml}</div>
		</div>`;
}

function sod_jenisdoc_badge(jenisdoc) {
	const cls = (jenisdoc || "").toLowerCase() === "jasa" ? "wo-badge-jasa" : "wo-badge-part";
	return `<span class="wo-badge ${cls}">${frappe.utils.escape_html(jenisdoc || "-")}</span>`;
}

function sod_check_chip(ok, label) {
	const icon = ok ? "✓" : "✕";
	return `<span class="wo-chip ${ok ? "wo-chip-ok" : "wo-chip-fail"}">${icon} ${frappe.utils.escape_html(label)}</span>`;
}

function sod_render_wo_summary(frm) {
	const field = frm.fields_dict.wo_summary_html;
	if (!field) return;
	if (!frm.doc.nomorwo) {
		field.$wrapper.html("");
		return;
	}
	if (frm._wo_summary_nomorwo === frm.doc.nomorwo) return;
	frm._wo_summary_nomorwo = frm.doc.nomorwo;

	frappe.call({
		method: "otobitz_integration.otobitz_integration.doctype.otobitz_so_detail.otobitz_so_detail.get_wo_summary",
		args: { nomorwo: frm.doc.nomorwo },
		callback(r) {
			if (!r.message) return;
			sod_inject_style();
			field.$wrapper.html(sod_build_wo_summary_html(frm, r.message));
			field.$wrapper.find(".wo-item-row").on("click", function () {
				const name = $(this).attr("data-name");
				if (name && name !== frm.doc.name) frappe.set_route("otobitz-so-detail", name);
			});
		},
	});
}

function sod_build_wo_summary_html(frm, res) {
	const h = res.header;

	const indicator_color = (h.statuswo || "").toUpperCase() === "FAKTUR" ? "green" : "orange";

	const checks = `
		<div class="wo-checks">
			${sod_check_chip(res.header_consistent, __("Header sama di {0} baris JSON", [res.items.length]))}
			${sod_check_chip(res.dpp_match, __("Σ Subtotal = DPP"))}
			${sod_check_chip(res.grandtotal_match, __("Σ Item + PPN = Grand Total"))}
		</div>`;

	const work_order = `
		<div class="wo-section">
			<div class="wo-section-title">${__("Work Order")}</div>
			<div class="wo-grid">
				${sod_field_box(__("Nomor WO"), sod_dash(h.nomorwo))}
				${sod_field_box(__("Tanggal"), sod_fmt_datetime(h.tanggal))}
				${sod_field_box(__("Status WO"), sod_dash(h.statuswo))}
				${sod_field_box(__("No. Faktur"), sod_dash(h.nofaktur))}
				${sod_field_box(__("Tanggal Faktur"), sod_fmt_datetime(h.tglfaktur))}
				${sod_field_box(__("No. Referensi"), sod_dash(h.noreferensi))}
				${sod_field_box(__("Jenis Service"), sod_dash(h.jenisservice))}
				${sod_field_box(__("Referensi"), sod_dash(h.referensi))}
				${sod_field_box(__("Regular Check"), sod_dash(h.nama_regularcheck))}
				${sod_field_box(__("Saran"), sod_dash(h.saran))}
				${sod_field_box(__("Interval Servis"), sod_dash(h.intervalsrv))}
				${sod_field_box(__("Lead Time"), sod_dash(h.leadtime))}
				${sod_field_box(__("Booking / Nomor Booking"), `${sod_dash(h.booking)} · ${sod_dash(h.nomorbooking)}`)}
				${sod_field_box(__("THS / Garansi / Return Job"), `${sod_dash(h.ths)} · ${sod_dash(h.garansi)} · ${sod_dash(h.returnjob)}`)}
				${sod_field_box(__("Inventaris"), sod_dash(h.inventaris))}
			</div>
		</div>`;

	const cabang = `
		<div class="wo-section">
			<div class="wo-section-title">${__("Cabang & Teknisi")}</div>
			<div class="wo-grid">
				${sod_field_box(__("Kode Cabang"), sod_dash(h.kode_cabang))}
				${sod_field_box(__("Cabang"), sod_dash(h.namacabang), { span2: true })}
				${sod_field_box(__("Kode Sub Cabang"), sod_dash(h.kodesubcabang))}
				${sod_field_box(__("Kode Company / Grup"), `${sod_dash(h.kodecompany)} · ${sod_dash(h.kodegrup)}`)}
				${sod_field_box(__("Teknisi"), `${sod_dash(h.teknisi)}${h.kodeteknisi ? " (" + frappe.utils.escape_html(h.kodeteknisi) + ")" : ""}`, { span2: true })}
			</div>
		</div>`;

	const customer_kendaraan = `
		<div class="wo-section wo-section-split">
			<div class="wo-section-half">
				<div class="wo-section-title">${__("Customer")}</div>
				<div class="wo-grid wo-grid-1">
					${sod_field_box(__("Nama Customer"), sod_dash(h.nama))}
					${sod_field_box(__("ID Customer"), sod_dash(h.customerid))}
					${sod_field_box(__("PIC"), sod_dash(h.pic))}
					${sod_field_box(__("No. HP PIC"), sod_dash(h.nohppic))}
					${sod_field_box(__("Jenis Customer"), sod_dash(h.jeniscustomer))}
					${sod_field_box(__("Pemakai"), sod_dash(h.pemakai))}
					${sod_field_box(__("Alamat"), `${sod_dash(h.alamat)}${h.alamat1 ? ", " + frappe.utils.escape_html(h.alamat1) : ""}`)}
					${sod_field_box(__("Nama Tagihan"), sod_dash(h.namatagihan))}
					${sod_field_box(__("NPWP"), sod_dash(h.npwp))}
				</div>
			</div>
			<div class="wo-section-half">
				<div class="wo-section-title">${__("Kendaraan")}</div>
				<div class="wo-grid wo-grid-1">
					${sod_field_box(__("Nomor Polisi"), sod_dash(h.nopolisi))}
					${sod_field_box(__("Tipe Kendaraan"), sod_dash(h.tipe))}
					${sod_field_box(__("Nomor Rangka"), sod_dash(h.norangka))}
					${sod_field_box(__("Nomor Mesin"), sod_dash(h.nomesin))}
					${sod_field_box(__("Warna"), `${sod_dash(h.namawarna)}${h.kodewarna ? " (" + frappe.utils.escape_html(h.kodewarna) + ")" : ""}`)}
					${sod_field_box(__("Tahun Pembuatan"), sod_dash(h.tahunpembuatan))}
					${sod_field_box(__("Odometer"), sod_fmt_number(h.odemeter), { align_right: true })}
					${sod_field_box(__("Kode Tipe / Kategori"), `${sod_dash(h.kodetipe)} · ${sod_dash(h.kategorikendaraan)}`)}
				</div>
			</div>
		</div>`;

	const items_rows = res.items
		.map(
			(it, i) => `
			<tr class="wo-item-row" data-name="${frappe.utils.escape_html(it.name)}">
				<td>${i + 1}</td>
				<td>${sod_dash(it.kodereferensi)}</td>
				<td>${sod_dash(it.namareferensi)}</td>
				<td>${sod_jenisdoc_badge(it.jenisdoc)}</td>
				<td class="text-right">${sod_fmt_number(it.qty)}</td>
				<td class="text-right">${sod_rupiah(it.harga)}</td>
				<td class="text-right">${sod_rupiah(it.discperitem)}</td>
				<td class="text-right">${sod_rupiah(it.subtotal)}</td>
				<td class="text-right">${sod_rupiah(it.subtotal_ppn)}</td>
			</tr>`
		)
		.join("");

	const sum_qty = res.items.reduce((a, it) => a + flt(it.qty), 0);
	const sum_disc = res.items.reduce((a, it) => a + flt(it.discperitem), 0);

	const items = `
		<div class="wo-section">
			<div class="wo-section-title-row">
				<div class="wo-section-title">${__("Items")}</div>
				<div class="wo-section-hint text-muted">${__("Klik baris buat lihat detail")}</div>
			</div>
			<div class="wo-table-wrap">
				<table class="table table-bordered wo-item-table">
					<thead>
						<tr>
							<th>${__("No.")}</th><th>${__("Kode Item")}</th><th>${__("Nama Item")}</th>
							<th>${__("Jenis")}</th><th class="text-right">${__("Qty")}</th>
							<th class="text-right">${__("Harga Satuan")}</th><th class="text-right">${__("Diskon")}</th>
							<th class="text-right">${__("Subtotal")}</th><th class="text-right">${__("Subtotal + PPN")}</th>
						</tr>
					</thead>
					<tbody>${items_rows}</tbody>
					<tfoot>
						<tr>
							<td colspan="2"><b>${__("Total")}</b></td>
							<td class="text-muted">${__("{0} item", [res.items.length])}</td>
							<td></td>
							<td class="text-right"><b>${sod_fmt_number(sum_qty)}</b></td>
							<td></td>
							<td class="text-right"><b>${sod_rupiah(sum_disc)}</b></td>
							<td class="text-right"><b>${sod_rupiah(res.sum_subtotal)}</b></td>
							<td class="text-right"><b>${sod_rupiah(res.sum_subtotal_ppn)}</b></td>
						</tr>
					</tfoot>
				</table>
			</div>
		</div>`;

	const total = `
		<div class="wo-section wo-section-split">
			<div class="wo-section-half">
				<div class="wo-section-title">${__("Total & Pembayaran")}</div>
				<div class="wo-grid wo-grid-1">
					${sod_field_box(__("Kode Payment"), sod_dash(h.kodepayment))}
					${sod_field_box(__("Metode Payment"), sod_dash(h.namapaymentmetode))}
					${sod_field_box(__("Kode Voucher"), sod_dash(h.kodevoucher))}
					${sod_field_box(__("Nama Voucher"), sod_dash(h.namavoucher))}
				</div>
			</div>
			<div class="wo-section-half">
				<div class="wo-totals">
					<div class="wo-totals-row"><span>${__("DPP")}</span><span>${sod_rupiah(h.dpp)}</span></div>
					<div class="wo-totals-row"><span>${__("PPN")}</span><span>${sod_rupiah(h.ppn)}</span></div>
					<div class="wo-totals-row"><span>${__("Pembulatan")}</span><span>${sod_rupiah(h.rounding)}</span></div>
					<div class="wo-totals-row wo-totals-grand"><span>${__("Grand Total")}</span><span>${sod_rupiah(h.grandtotal)}</span></div>
					<div class="wo-totals-row"><span>${__("Nilai Piutang")}</span><span>${sod_rupiah(h.nilaipiutang)}</span></div>
					<div class="wo-totals-row"><span>${__("Nilai Uang Muka")}</span><span>${sod_rupiah(h.nilaiuangmuka)}</span></div>
					<div class="wo-totals-row"><span>${__("Nilai Penerimaan")}</span><span>${sod_rupiah(h.nilaipenerimaan)}</span></div>
					<div class="wo-totals-row wo-totals-grand"><span>${__("Sisa Piutang")}</span><span>${sod_rupiah(h.sisapiutang)}</span></div>
				</div>
			</div>
		</div>`;

	return `<div class="wo-summary">${checks}${work_order}${cabang}${customer_kendaraan}${items}${total}</div>`;
}

function sod_inject_style() {
	if (document.getElementById("sod-table-style")) return;
	const s = document.createElement("style");
	s.id = "sod-table-style";
	s.textContent = `
.sod-table-wrap{display:flex;flex-wrap:wrap;gap:16px}
.sod-group{flex:1 1 360px;min-width:300px}
.sod-group-title{font-weight:600;font-size:13px;margin-bottom:6px;color:var(--text-color)}
.sod-table{margin-bottom:0;font-size:12px}
.sod-table td{padding:4px 8px;vertical-align:top}
.sod-table .sod-label{width:45%;color:var(--text-muted);white-space:nowrap}

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

frappe.ui.form.on("OtoBitz SO Detail", {
	refresh(frm) {
		sod_inject_style();
		sod_render_table(frm);
		sod_render_wo_summary(frm);
		if (frm.doc.statuswo) {
			frm.page.set_indicator(frm.doc.statuswo, frm.doc.statuswo.toUpperCase() === "FAKTUR" ? "green" : "orange");
		}
	},
	raw_data_view(frm) {
		sod_render_table(frm);
	},
});
