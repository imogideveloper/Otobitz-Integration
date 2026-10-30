# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""masterdata_orderpekerjaanluar -> Purchase Order.

A Purchase Order to a Supplier for outsourced ("pekerjaan luar") labor on a
specific Work Order - `nomor_so` links back to the Sales Order this cost was
incurred for, stamped onto `custom_otobitz_sales_order` purely for
traceability (not resolved as a dependency - a missing/not-yet-synced Sales
Order doesn't block this Purchase Order from being created).

Each `detail` row only carries `hargabeli` (no explicit qty or discount
breakdown, unlike orderparts) - qty is always 1 per row.
"""

import frappe
from frappe.utils import add_days, flt, get_first_day, getdate, nowdate

from otobitz_integration.otobitz_integration.api.client import OtoBitzAPIError, call_api
from otobitz_integration.otobitz_integration.sync.common import (
	clean,
	create_purchase_order,
	log_failed_sync,
	renew_sync_lock,
	resolve_failed_sync,
)

WATERMARK_FIELD = "last_orderpekerjaanluar_sync_date"
OVERLAP_DAYS = 3
CHUNK_DAYS = 2
TAXES_AND_CHARGES_TEMPLATE = "Purchase Tax - O"


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


def sync_orderpekerjaanluar() -> dict:
	tanggalawal, tanggalakhir = get_sync_window()

	fetched = created = updated = failed = 0
	for chunk_start, chunk_end in _iter_date_chunks(tanggalawal, tanggalakhir):
		renew_sync_lock()
		try:
			response = call_api(
				"masterdata_orderpekerjaanluar", {"tanggalawal": chunk_start, "tanggalakhir": chunk_end}
			)
		except OtoBitzAPIError:
			frappe.log_error(title=f"OtoBitz sync: giving up on masterdata_orderpekerjaanluar {chunk_start}..{chunk_end}")
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
			try:
				was_created = _sync_one_order(nomor, row)
				created += was_created
				updated += not was_created
				frappe.db.commit()
				resolve_failed_sync("masterdata_orderpekerjaanluar", nomor)
				frappe.db.commit()
			except Exception as exc:
				frappe.db.rollback()
				frappe.log_error(title=f"OtoBitz sync: failed to sync order pekerjaan luar {nomor}")
				log_failed_sync("masterdata_orderpekerjaanluar", nomor, str(exc), row)
				frappe.db.commit()
				failed += 1

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


def _create_order(nomor: str, row: dict) -> str:
	supplier = frappe.db.get_value("Supplier", {"custom_otobitz_supplier_no": clean(row.get("kodesupplier"))})
	if not supplier:
		frappe.throw(f"Supplier {row.get('kodesupplier')!r} not found for order {nomor}")

	branch = frappe.db.get_value("Branch", {"custom_otobitz_branch_code": clean(row.get("kodecabang"))})
	company = frappe.db.get_single_value("OtoBitz Settings", "default_company")
	sales_order = frappe.db.get_value("Sales Order", {"custom_otobitz_wo_number": clean(row.get("nomor_so"))})

	items = []
	for detail in row.get("detail") or []:
		item_code = clean(detail.get("kodeopl"))
		if not item_code or not frappe.db.exists("Item", item_code):
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

@frappe.whitelist()
def backfill_source_document() -> dict:
	"""One-off: custom_source_document only started getting set on new
	Purchase Orders once _create_order() above passed it through - every PO
	already synced before that fix is stuck empty. custom_otobitz_sales_order
	is only ever set by THIS sync (sync_orderparts.py never touches it), so
	it's a reliable "came from Pekerjaan Luar" marker to backfill against
	without re-calling the API - custom_source_document is just the same
	order_number value these rows already have in custom_otobitz_order_number."""
	frappe.only_for("System Manager")
	po_names = frappe.get_all(
		"Purchase Order",
		filters={
			"custom_otobitz_sales_order": ["is", "set"],
			"custom_source_document": ["in", ["", None]],
		},
		pluck="name",
	)
	fixed = 0
	for name in po_names:
		order_number = frappe.db.get_value("Purchase Order", name, "custom_otobitz_order_number")
		if order_number:
			frappe.db.set_value("Purchase Order", name, "custom_source_document", order_number, update_modified=False)
			fixed += 1
	frappe.db.commit()
	return {"checked": len(po_names), "fixed": fixed}
