# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class OtoBitzSODetail(Document):
	pass


# Keys that describe the Work Order as a whole (customer, vehicle, payment,
# totals, ...) - every sibling row sharing a Nomor WO (1 row = 1 item, per
# this doctype's design) should carry an identical value for all of these.
# get_wo_summary() uses this list to flag it instead of silently trusting
# that rows sharing a nomorwo truly belong together.
#
# noreferensi and subtotalppn are deliberately NOT in this list - confirmed
# live (2026-11-12, WO SO-503-261100107) that both vary per item row:
# noreferensi is a per-line procurement/service reference (not always equal
# to nomorwo), and subtotalppn is that item's own subtotal+PPN, not a
# WO-level total - see get_wo_summary()'s use of it below.
_HEADER_KEYS = [
	"nomorwo", "tanggal", "statuswo", "nofaktur", "tglfaktur", "nomorbooking", "idbooking", "booking",
	"jenisservice", "referensi", "saran", "jenissaran", "nama_regularcheck", "intervalsrv", "leadtime",
	"ths", "garansi", "returnjob", "inventaris", "tglbatal", "userbatal", "keteranganbatal",
	"kode_cabang", "namacabang", "kodesubcabang", "kodecompany", "kodegrup", "teknisi", "kodeteknisi",
	"nama", "customerid", "pic", "nohppic", "nohp", "notlp", "email", "pemakai", "title", "jeniscustomer",
	"alamat", "alamat1", "kelurahan", "kecamatan", "kota", "kodepos", "provinsi", "namatagihan", "nik",
	"npwp", "statusjual",
	"nopolisi", "norangka", "nomesin", "tipe", "kodetipe", "namawarna", "kodewarna", "jeniskendaraan",
	"kategorikendaraan", "tahunpembuatan", "odemeter", "statusjeniskendaraan",
	"dpp", "ppn", "grandtotal", "rounding",
	"nilaipiutang", "nilaiuangmuka", "nilaipenerimaan", "sisapiutang",
	"kodepayment", "namapaymentmetode", "kodevoucher", "namavoucher",
]


@frappe.whitelist()
def get_wo_summary(nomorwo):
	"""Join every OtoBitz SO Detail row sharing this Nomor WO back into one
	Work Order: the shared header (customer, vehicle, payment, ...) plus the
	full item list, with the three cross-checks a human would otherwise have
	to do by eye - do the header fields actually agree across the rows, does
	the item subtotal add up to the WO's own dpp, does item+tax add up to
	grandtotal. Per-item subtotal+PPN comes straight from each row's own
	subtotalppn (confirmed per-item, not a WO-level total); the WO's blended
	tax rate (ppn/dpp) is only a fallback for the rare row missing it."""
	rows = frappe.get_all(
		"OtoBitz SO Detail",
		filters={"nomorwo": nomorwo},
		fields=["name", "raw_data"],
		order_by="creation asc",
	)
	if not rows:
		return None

	parsed = []
	for r in rows:
		try:
			data = json.loads(r.raw_data or "{}")
		except ValueError:
			data = {}
		parsed.append({"name": r.name, "data": data})

	header = parsed[0]["data"]
	header_consistent = True
	for p in parsed[1:]:
		if any(p["data"].get(key) != header.get(key) for key in _HEADER_KEYS):
			header_consistent = False
			break

	dpp = flt(header.get("dpp"))
	ppn = flt(header.get("ppn"))
	grandtotal = flt(header.get("grandtotal"))
	rounding = flt(header.get("rounding"))
	tax_rate = (ppn / dpp) if dpp else 0

	items = []
	sum_subtotal = 0.0
	sum_subtotal_ppn = 0.0
	for p in parsed:
		d = p["data"]
		subtotal = flt(d.get("subtotal"))
		subtotal_ppn = flt(d.get("subtotalppn")) or (subtotal * (1 + tax_rate))
		sum_subtotal += subtotal
		sum_subtotal_ppn += subtotal_ppn
		items.append(
			{
				"name": p["name"],
				"kodereferensi": d.get("kodereferensi"),
				"namareferensi": d.get("namareferensi"),
				"jenisdoc": d.get("jenisdoc"),
				"qty": flt(d.get("qty")),
				"harga": flt(d.get("harga")),
				"discperitem": flt(d.get("discperitem")),
				"subtotal": subtotal,
				"subtotal_ppn": subtotal_ppn,
			}
		)

	# grandtotal = sum(item subtotalppn) + the WO's own rounding adjustment
	# (confirmed live: several WOs carry a non-zero "rounding", e.g. 10, that
	# otherwise shows up as a ~10 rupiah "mismatch"). On top of that, each
	# item's subtotalppn is independently rounded to the nearest rupiah by
	# OtoBitz before we ever see it, so summing several of them can still
	# drift a rupiah or two from grandtotal even after rounding is accounted
	# for - bounding the leftover tolerance by item count keeps this a real
	# discrepancy check rather than one that never fires on anything but a
	# 1-item WO.
	grandtotal_tolerance = max(2, len(items))

	return {
		"header": header,
		"items": items,
		"header_consistent": header_consistent,
		"dpp_match": abs(sum_subtotal - dpp) < 2,
		"grandtotal_match": abs((sum_subtotal_ppn + rounding) - grandtotal) <= grandtotal_tolerance,
		"sum_subtotal": sum_subtotal,
		"sum_subtotal_ppn": sum_subtotal_ppn,
		"dpp": dpp,
		"grandtotal": grandtotal,
	}
