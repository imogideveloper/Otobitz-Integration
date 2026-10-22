# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""penerimaanuangmukabooking -> Payment Entry (Receive), unallocated advance.

Unlike `penerimaanuang`, `noreferensi` here is a booking code ("BKS-xxx"),
not a Sales Invoice's `nofaktur` - this money is collected *before* the Work
Order (and therefore the Invoice) exists, so there's nothing to reference
yet. It's booked as a pure advance against the Customer (no `references`
row); whoever reconciles it later links it to the eventual Sales Invoice by
hand, the same way any other ERPNext customer advance gets used.

This endpoint also doesn't carry a customer id/code anywhere - only
`namacustomer` as free text. Resolving the Customer is therefore a best-
effort exact-name match against `customer_name`; a receipt whose name
doesn't match an existing Customer exactly (new customer, spelling
variant, duplicate name) is skipped and logged rather than guessed at or
used to create a new, likely-duplicate Customer record.
"""

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import get_bank_cash_account
from frappe.utils import add_days, flt, get_first_day, getdate, nowdate

from otobitz_integration.otobitz_integration.api.client import OtoBitzAPIError, call_api
from otobitz_integration.otobitz_integration.sync.common import (
	clean,
	log_failed_sync,
	mark_otobitz_cancelled,
	renew_sync_lock,
	resolve_failed_sync,
	set_period_fields,
)

WATERMARK_FIELD = "last_booking_sync_date"
OVERLAP_DAYS = 3
CHUNK_DAYS = 2


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


def sync_booking() -> dict:
	tanggalawal, tanggalakhir = get_sync_window()

	fetched = created = updated = failed = 0
	for chunk_start, chunk_end in _iter_date_chunks(tanggalawal, tanggalakhir):
		renew_sync_lock()
		try:
			response = call_api("penerimaanuangmukabooking", {"tanggalawal": chunk_start, "tanggalakhir": chunk_end})
		except OtoBitzAPIError:
			frappe.log_error(title=f"OtoBitz sync: giving up on penerimaanuangmukabooking {chunk_start}..{chunk_end}")
			failed += 1
			continue

		rows = response.get("data-penerimaanbooking") or []
		fetched += len(rows)

		for i, row in enumerate(rows):
			if i % 20 == 0:
				renew_sync_lock()
			nomor = clean(row.get("nomor"))
			if not nomor:
				continue
			try:
				was_created = _sync_one_booking(nomor, row)
				created += was_created
				updated += not was_created
				frappe.db.commit()
				resolve_failed_sync("penerimaanuangmukabooking", nomor)
				frappe.db.commit()
			except Exception as exc:
				frappe.db.rollback()
				frappe.log_error(title=f"OtoBitz sync: failed to sync booking advance {nomor}")
				log_failed_sync("penerimaanuangmukabooking", nomor, str(exc), row)
				frappe.db.commit()
				failed += 1

	frappe.db.set_single_value("OtoBitz Settings", WATERMARK_FIELD, nowdate(), update_modified=False)
	frappe.db.commit()

	return {"fetched": fetched, "created": created, "updated": updated, "failed": failed}


def _sync_one_booking(nomor: str, row: dict) -> bool:
	existing = frappe.db.get_value("Payment Entry", {"custom_otobitz_receipt_number": nomor})

	if (row.get("status") or "").strip().lower() == "batal":
		if existing and frappe.db.get_value("Payment Entry", existing, "docstatus") == 1:
			frappe.get_doc("Payment Entry", existing).cancel()
			mark_otobitz_cancelled("Payment Entry", existing)
		return False

	if existing:
		return False

	_create_advance_payment_entry(nomor, row)
	return True


def _create_advance_payment_entry(nomor: str, row: dict) -> str:
	customer_name = clean(row.get("namacustomer"))
	customer = customer_name and frappe.db.get_value("Customer", {"customer_name": customer_name})
	if not customer:
		frappe.throw(f"No Customer found matching name {customer_name!r} (booking advance {nomor})")

	company = frappe.db.get_single_value("OtoBitz Settings", "default_company")
	mode_of_payment = frappe.db.get_value(
		"Mode of Payment", {"custom_otobitz_payment_code": clean(row.get("paymentmetode"))}
	)
	branch = frappe.db.get_value("Branch", {"custom_otobitz_branch_code": clean(row.get("kode_cabang"))})
	amount = flt(row.get("nilaipenerimaan"))

	pe = frappe.new_doc("Payment Entry")
	pe.payment_type = "Receive"
	pe.party_type = "Customer"
	pe.party = customer
	pe.company = company
	pe.posting_date = getdate(row.get("tanggal"))
	set_period_fields(pe, pe.posting_date)
	pe.paid_amount = amount
	pe.received_amount = amount
	pe.custom_otobitz_receipt_number = nomor
	if branch:
		pe.custom_otobitz_branch = branch
	if mode_of_payment:
		pe.mode_of_payment = mode_of_payment
		bank_cash = get_bank_cash_account(pe, None)
		if bank_cash and bank_cash.get("account"):
			pe.paid_to = bank_cash["account"]

	pe.insert(ignore_permissions=True, ignore_mandatory=True)
	pe.submit()
	return pe.name
