# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class OtoBitzSODetail(Document):
	pass


def get_permission_query_conditions(user=None) -> str:
	"""Registered in hooks.py - restricts every List View/Report View/REST
	`get_list` of this doctype to `is_wo_summary_row=1` rows, so one Work
	Order's several raw item rows (full fidelity, still all archived - see
	log_so_detail_rows() in common.py) show up as a single row there instead
	of one per item. Internal lookups that genuinely need every row
	(get_wo_summary/get_status_snapshots below, log_so_detail_rows itself) all
	go through frappe.get_all(), which always runs with ignore_permissions=True
	and so never hits this condition at all - only the actual "list this
	doctype" path does."""
	return "`tabOtoBitz SO Detail`.`is_wo_summary_row` = 1"


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
def get_wo_summary(nomorwo, nofaktur=None):
	"""Join OtoBitz SO Detail item rows back into one Work Order: the shared
	header (customer, vehicle, payment, ...) plus the full item list, with
	the three cross-checks a human would otherwise have to do by eye - do
	the header fields actually agree across the rows, does the item
	subtotal add up to the WO's own dpp, does item+tax add up to grandtotal.
	Per-item subtotal+PPN comes straight from each row's own subtotalppn
	(confirmed per-item, not a WO-level total); the WO's blended tax rate
	(ppn/dpp) is only a fallback for the rare row missing it.

	`nofaktur`, when given, scopes this to ONE invoice attempt instead of
	every row sharing this nomorwo - confirmed live, SO-302-261100180:
	invoice SV-302-261100203 got cancelled and reissued as SV-302-261100204,
	4 of its 5 item codes shared between them. Without this filter, viewing
	EITHER invoice's own "OtoBitz SO Detail" page merged in the OTHER
	invoice's items too - every shared item code double-counted, and the
	cancelled invoice's page showed the reissued invoice's items instead of
	its own (its own DPP/PPN/grandtotal came from a header-field overlay
	already built for exactly this in otobitz_so_detail.js - see its own
	comment there - but the Items table underneath still came from here,
	unscoped, so the two never actually agreed with each other). Left
	optional (not required) for any other caller still expecting every
	attempt merged together."""
	filters = {"nomorwo": nomorwo}
	if nofaktur:
		filters["nofaktur"] = nofaktur
	rows = frappe.get_all(
		"OtoBitz SO Detail",
		filters=filters,
		fields=["name", "raw_data", "kodereferensi"],
		order_by="creation asc",
	)
	# Rows with no kodereferensi at all are header-only status snapshots
	# (e.g. the "BATAL INVOICE" marker row for a NOW-superseded invoice
	# attempt - see log_so_detail_rows() in common.py), not a real item of
	# the CURRENT invoice this summary is about. Including one here would
	# wrongly fail header_consistent/dpp_match/grandtotal_match against
	# the figures of an invoice that no longer applies - get_status_snapshots()
	# below is the dedicated way to look at those, not this join.
	rows = [r for r in rows if r.kodereferensi]
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


@frappe.whitelist()
def get_status_snapshots(nomorwo):
	"""Every header-only status snapshot archived for this Work Order
	(kodereferensi blank - see log_so_detail_rows()'s own docstring in
	common.py for what sends one: OtoBitz's "BATAL INVOICE" marker row
	for an invoice attempt that's since been superseded) - powers the
	Raw Data toggle on this form's own JS (otobitz_so_detail.js) so a
	cancelled invoice's actual payload is directly viewable there,
	instead of only ever being inferable from a Sales Order Comment.
	Excludes the real item rows get_wo_summary() above already covers, same
	as before - and now also excludes the "is_wo_summary_row" FAKTUR summary
	row log_so_detail_rows()/_upsert_wo_summary_row() in common.py create for
	the CURRENT invoice attempt (also kodereferensi-blank, since it's a
	header-only aggregate too): that one already IS "Invoice saat ini
	(aktif)", the default the toggle in otobitz_so_detail.js shows with no
	selection - listing it again here as a second, redundant snapshot option
	would be confusing, so only a non-FAKTUR (i.e. actually-superseded)
	status row belongs here."""
	frappe.only_for("System Manager")
	rows = frappe.get_all(
		"OtoBitz SO Detail",
		filters={"nomorwo": nomorwo},
		fields=["name", "nofaktur", "statuswo", "kodereferensi", "tanggal"],
		order_by="creation desc",
	)
	return [r for r in rows if not r.kodereferensi and (r.statuswo or "").strip().upper() != "FAKTUR"]
