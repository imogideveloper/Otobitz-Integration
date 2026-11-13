# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""masterdata_oppnt -> Purchase Order.

A Purchase Order to a Supplier for parts bought from a non-TAM (third-party)
supplier for a specific Work Order - structurally identical to
masterdata_orderpekerjaanluar (same top-level row shape, same `nomor_so`/
`nopolisi` linkage back to the Sales Order, same "no qty/discount breakdown,
one row = one item" detail shape), just for PARTS instead of outsourced
labor: confirmed live (2026-11-13) against both endpoints for the same date -
orderpekerjaanluar's supplier was "PT HERIROMADIALI" with service-style item
codes ("JP0004"), while oppnt's was "PT CARVIO MITRA PARTINDO" with
part-style names ("WATERPUMP CALYA", "BUSI EVALIA ZK AR6AP"). The response
key is still "data-opl" even on this different endpoint - not renamed on
OtoBitz's side.

Detail row fields are renamed from orderpekerjaanluar's: `nomor_pembelian`
instead of `nomoropl`, `kode_pekerjaan` instead of `kodeopl`, `nama_pekerjaan`
instead of `namaopl` - `hargabeli` unchanged.

Unlike every other order-sync module here, the item codes this endpoint
sends (`kode_pekerjaan`) don't exist in ANY master-data catalog this
integration already syncs - confirmed live: not in masterdata_sparepart's
222k official TAM parts, not in masterdata_pekerjaanluar's 567 OPL job codes
either. There is no dedicated "non-TAM parts catalog" endpoint to sync ahead
of time, so the Item is created on demand from the order row's own data
(code + name + price is all each row carries, but that's also everything
sync_pekerjaanluar.sync_pekerjaanluar() uses to create an Item) rather than
left to resolve against a master sync that doesn't exist.

Plain PPN tax template (not orderpekerjaanluar's PPN+PPh23 combo) - PPh23 is
an Indonesian withholding tax on services/labor, not goods, and this is a
goods (part) purchase.
"""

import frappe
from frappe.utils import add_days, flt, get_first_day, getdate, nowdate

from otobitz_integration.otobitz_integration.api.client import OtoBitzAPIError, call_api
from otobitz_integration.otobitz_integration.sync.common import (
	clean,
	create_purchase_order,
	get_or_create_item_group,
	get_or_create_uom,
	log_failed_sync,
	log_po_detail_row,
	renew_sync_lock,
	resolve_failed_sync,
	safe_name,
	upsert_safe,
)

WATERMARK_FIELD = "last_oppnt_sync_date"
OVERLAP_DAYS = 3
CHUNK_DAYS = 2
TAXES_AND_CHARGES_TEMPLATE = "Purchase Tax - O"
# Kept distinct from "OtoBitz Spare Part" (the official TAM catalog, stock
# items) - these are ad-hoc, one-off non-TAM parts with no real inventory
# cycle, same non-stock treatment as "OtoBitz Service" gives OPL job codes.
ITEM_GROUP = "OtoBitz Spare Part Non TAM"


def get_sync_window() -> tuple[str, str]:
	last_sync_date = frappe.db.get_single_value("OtoBitz Settings", WATERMARK_FIELD)
	if last_sync_date and getdate(last_sync_date).year > 2000:
		start = add_days(getdate(last_sync_date), -OVERLAP_DAYS)
	else:
		start = get_first_day(nowdate())
	return str(start), nowdate()


def _iter_date_chunks(start: str, end: str):
	chunk_start = getdate(start)
	end = getdate(end)
	while chunk_start <= end:
		chunk_end = min(add_days(chunk_start, CHUNK_DAYS - 1), end)
		yield str(chunk_start), str(chunk_end)
		chunk_start = add_days(chunk_end, 1)


def sync_oppnt(date_range: tuple[str, str] | None = None) -> dict:
	tanggalawal, tanggalakhir = date_range or get_sync_window()

	fetched = created = updated = failed = 0
	for chunk_start, chunk_end in _iter_date_chunks(tanggalawal, tanggalakhir):
		renew_sync_lock()
		try:
			response = call_api("masterdata_oppnt", {"tanggalawal": chunk_start, "tanggalakhir": chunk_end})
		except OtoBitzAPIError:
			frappe.log_error(title=f"OtoBitz sync: giving up on masterdata_oppnt {chunk_start}..{chunk_end}")
			failed += 1
			continue

		rows = response.get("data-opl") or []
		fetched += len(rows)

		for i, row in enumerate(rows):
			if i % 20 == 0:
				renew_sync_lock()
			nomor = clean(row.get("nomor"))
			if not nomor:
				continue
			# Raw archive, independent of whatever happens below - see
			# log_po_detail_row()'s docstring in common.py.
			log_po_detail_row("masterdata_oppnt", nomor, row)
			frappe.db.commit()
			try:
				was_created = _sync_one_order(nomor, row)
				created += was_created
				updated += not was_created
				frappe.db.commit()
				resolve_failed_sync("masterdata_oppnt", nomor)
				frappe.db.commit()
			except Exception as exc:
				frappe.db.rollback()
				frappe.log_error(title=f"OtoBitz sync: failed to sync oppnt {nomor}")
				log_failed_sync("masterdata_oppnt", nomor, str(exc), row)
				frappe.db.commit()
				failed += 1

	if date_range is None:
		frappe.db.set_single_value("OtoBitz Settings", WATERMARK_FIELD, nowdate(), update_modified=False)
	frappe.db.commit()

	return {"fetched": fetched, "created": created, "updated": updated, "failed": failed}


def _sync_one_order(nomor: str, row: dict) -> bool:
	existing = frappe.db.get_value("Purchase Order", {"custom_otobitz_order_number": nomor})

	if (row.get("batal") or "").strip().lower() == "t":
		if existing and frappe.db.get_value("Purchase Order", existing, "docstatus") == 1:
			frappe.get_doc("Purchase Order", existing).cancel()
		return False

	if existing:
		return False

	_create_order(nomor, row)
	return True


def _get_or_create_part_item(kode_pekerjaan: str, nama_pekerjaan: str | None, hargabeli) -> str | None:
	"""Same values sync_pekerjaanluar() uses to create an OPL job Item -
	code, name, last price - just applied per-order instead of from its own
	master-data batch, since this endpoint has no master-data equivalent to
	sync ahead of time (see module docstring)."""
	item_code = clean(kode_pekerjaan)
	if not item_code:
		return None

	if not frappe.db.exists("Item", item_code):
		item_group = get_or_create_item_group(ITEM_GROUP)
		values = {
			"item_name": safe_name(nama_pekerjaan) or item_code,
			"item_group": item_group,
			"stock_uom": get_or_create_uom("Units"),
			"is_stock_item": 0,
			"disabled": 0,
			"custom_otobitz_part_code": item_code,
			"custom_otobitz_last_cogs": flt(hargabeli),
		}
		name, _, _, failed = upsert_safe(
			"Item", {"item_code": item_code}, values, ignore_mandatory=True, create_only_fields={"stock_uom"}
		)
		if failed or not name:
			return None
		return name

	return item_code


def _create_order(nomor: str, row: dict) -> str:
	supplier = frappe.db.get_value("Supplier", {"custom_otobitz_supplier_no": clean(row.get("kodesupplier"))})
	if not supplier:
		frappe.throw(f"Supplier {row.get('kodesupplier')!r} not found for order {nomor}")

	branch = frappe.db.get_value("Branch", {"custom_otobitz_branch_code": clean(row.get("kodecabang"))})
	company = frappe.db.get_single_value("OtoBitz Settings", "default_company")
	sales_order = frappe.db.get_value("Sales Order", {"custom_otobitz_wo_number": clean(row.get("nomor_so"))})

	items = []
	for detail in row.get("detail") or []:
		item_code = _get_or_create_part_item(
			detail.get("kode_pekerjaan"), detail.get("nama_pekerjaan"), detail.get("hargabeli")
		)
		if not item_code:
			continue
		rate = flt(detail.get("hargabeli"))
		items.append({
			"item_code": item_code,
			"qty": 1,
			"price_list_rate": rate,
			"rate": rate,
			"schedule_date": getdate(row.get("tanggal")),
		})

	return create_purchase_order(
		order_number=nomor,
		company=company,
		supplier=supplier,
		transaction_date=getdate(row.get("tanggal")),
		items=items,
		branch=branch,
		sales_order=sales_order,
		taxes_and_charges_template=TAXES_AND_CHARGES_TEMPLATE,
		source_document=nomor,
	)
