# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""penerimaanuangmukabooking -> Payment Entry (Receive), unallocated advance.

Unlike `penerimaanuang`, `noreferensi` here is a booking code ("BKS-xxx"),
not a Sales Invoice's `nofaktur` - this money is collected *before* the Work
Order (and therefore the Invoice) exists, so there's nothing to reference
yet. It's booked as a pure advance against the Customer (no `references`
row); whoever reconciles it later links it to the eventual Sales Invoice by
hand, the same way any other ERPNext customer advance gets used.

One `nomor` (a single cash/QRIS receipt) can cover SEVERAL distinct
bookings/vehicles at once, each its own row with the same `nomor` but a
different `noreferensi` (confirmed live, nomor 003-IS261100103: 3 rows, one
per vehicle plate, nilaipenerimaan 2575500/944350/2040000 - OtoBitz's own
Odoo sync has the identical bug this fixes, where only one of the three ever
shows up). `noreferensi` - not `nomor` - is therefore the real per-booking
identity: dedup and `custom_otobitz_receipt_number` key off it, while `nomor`
(the shared receipt) still lands on `reference_no` so every Payment Entry
split off one receipt stays visibly grouped together.

This endpoint also doesn't carry a customer id/code anywhere - only
`namacustomer` as free text. Resolving the Customer is therefore a best-
effort exact-name match against `customer_name`; a receipt whose name
doesn't match an existing Customer exactly (new customer, spelling
variant, duplicate name) is skipped and logged rather than guessed at or
used to create a new, likely-duplicate Customer record.
"""

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import get_bank_cash_account
from frappe.utils import add_days, cint, flt, get_first_day, getdate, nowdate

from otobitz_integration.otobitz_integration.api.client import OtoBitzAPIError, call_api
from otobitz_integration.otobitz_integration.sync.common import (
	clean,
	log_failed_sync,
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


def sync_booking(date_range: tuple[str, str] | None = None) -> dict:
	tanggalawal, tanggalakhir = date_range or get_sync_window()

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
			# noreferensi is the real per-booking identity (see module
			# docstring) - nomor alone is shared by every allocation under
			# the same receipt, so using it as the dedup key silently
			# drops every allocation after the first. Falls back to nomor
			# only for the rare row that has no noreferensi at all, rather
			# than skipping it outright.
			allocation_ref = clean(row.get("noreferensi")) or nomor
			if not allocation_ref:
				continue
			try:
				was_created = _sync_one_booking(allocation_ref, nomor, row)
				created += was_created
				updated += not was_created
				frappe.db.commit()
				resolve_failed_sync("penerimaanuangmukabooking", allocation_ref)
				frappe.db.commit()
			except Exception as exc:
				frappe.db.rollback()
				frappe.log_error(title=f"OtoBitz sync: failed to sync booking advance {allocation_ref}")
				log_failed_sync("penerimaanuangmukabooking", allocation_ref, str(exc), row)
				frappe.db.commit()
				failed += 1

	if date_range is None:
		frappe.db.set_single_value("OtoBitz Settings", WATERMARK_FIELD, nowdate(), update_modified=False)
	frappe.db.commit()

	return {"fetched": fetched, "created": created, "updated": updated, "failed": failed}


def _sync_one_booking(allocation_ref: str, nomor: str, row: dict) -> bool:
	existing = frappe.db.get_value("Payment Entry", {"custom_otobitz_receipt_number": allocation_ref})

	if (row.get("status") or "").strip().lower() == "batal":
		if existing and frappe.db.get_value("Payment Entry", existing, "docstatus") == 1:
			frappe.get_doc("Payment Entry", existing).cancel()
		return False

	if existing:
		return False

	_create_advance_payment_entry(allocation_ref, nomor, row)
	return True


def _create_advance_payment_entry(allocation_ref: str, nomor: str, row: dict) -> str:
	customer_name = clean(row.get("namacustomer"))
	customer = customer_name and frappe.db.get_value("Customer", {"customer_name": customer_name})
	if not customer:
		frappe.throw(f"No Customer found matching name {customer_name!r} (booking advance {allocation_ref})")

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
	# The per-booking identity (see module docstring), NOT the shared
	# receipt number - this is what makes dedup correct when one receipt
	# covers several bookings.
	pe.custom_otobitz_receipt_number = allocation_ref
	if branch:
		pe.custom_otobitz_branch = branch
	if mode_of_payment:
		pe.mode_of_payment = mode_of_payment
		bank_cash = get_bank_cash_account(pe, None)
		if bank_cash and bank_cash.get("account"):
			pe.paid_to = bank_cash["account"]

	# ERPNext hard-requires reference_no/reference_date whenever the paid-to
	# account is type "Bank" (validate_transaction_reference(), not a
	# mandatory-field check - ignore_mandatory above doesn't cover it). Same
	# fix as sync_penerimaan.py's _create_payment_entry() - this endpoint has
	# no separate bank-transfer-reference field either, so the receipt's own
	# number/date stand in for it. Deliberately the shared `nomor`, not
	# `allocation_ref` - every Payment Entry split off the same receipt
	# carries the same reference_no, so they still show up grouped together
	# even though each has its own custom_otobitz_receipt_number.
	pe.reference_no = nomor
	pe.reference_date = pe.posting_date

	pe.insert(ignore_permissions=True, ignore_mandatory=True)
	pe.submit()
	return pe.name


@frappe.whitelist()
def backfill_split_booking_advances(from_date=None, to_date=None, dry_run=1) -> dict:
	"""One-off repair for the bug fixed above: every receipt that already
	synced BEFORE this fix only ever got ONE Payment Entry per `nomor` (the
	first row `sync_booking()` happened to see), silently dropping every
	other allocation under the same receipt - real money already received
	that's missing from the books, not just a display/rounding gap, so
	unlike most other OtoBitz data-quality findings this one is worth
	correcting retroactively (see [[otobitz-no-retroactive-fix]]-style
	findings for why that's normally NOT the default here).

	dry_run=1 (default): reports what it WOULD do, writes nothing - review
	this first. dry_run=0: actually creates the missing Payment Entries and
	re-keys the one pre-fix entry (if any) from the old shared `nomor` to
	its own correct `noreferensi`, so it stops being invisible to the new
	dedup check.

	The pre-fix entry never stored `noreferensi` at all, so it's matched to
	one specific allocation row by party + posting_date + paid_amount -
	first match wins, and each existing entry can only be claimed by one
	row, so two allocations that happen to share an amount can't both grab
	the same Payment Entry."""
	frappe.only_for("System Manager")
	dry_run = cint(dry_run)
	from_date = str(getdate(from_date) if from_date else getdate("2026-09-01"))
	to_date = str(getdate(to_date) if to_date else getdate(nowdate()))

	report = {
		"from_date": from_date,
		"to_date": to_date,
		"dry_run": bool(dry_run),
		"receipts_with_split": 0,
		"already_ok": 0,
		"rekeyed": 0,
		"created": 0,
		"created_amount": 0.0,
		"errors": [],
		"details": [],
	}

	for chunk_start, chunk_end in _iter_date_chunks(from_date, to_date):
		try:
			response = call_api("penerimaanuangmukabooking", {"tanggalawal": chunk_start, "tanggalakhir": chunk_end})
		except OtoBitzAPIError as exc:
			report["errors"].append(f"{chunk_start}..{chunk_end}: {exc}")
			continue

		by_nomor: dict[str, list[dict]] = {}
		for row in response.get("data-penerimaanbooking") or []:
			nomor = clean(row.get("nomor"))
			if nomor:
				by_nomor.setdefault(nomor, []).append(row)

		for nomor, group in by_nomor.items():
			if len(group) < 2:
				continue
			report["receipts_with_split"] += 1
			claimed = set()

			for row in group:
				allocation_ref = clean(row.get("noreferensi")) or nomor
				amount = flt(row.get("nilaipenerimaan"))
				customer_name = clean(row.get("namacustomer"))
				customer = customer_name and frappe.db.get_value("Customer", {"customer_name": customer_name})
				posting_date = getdate(row.get("tanggal"))

				# Already correctly keyed - a post-fix sync run already handled this one.
				if frappe.db.exists("Payment Entry", {"custom_otobitz_receipt_number": allocation_ref}):
					report["already_ok"] += 1
					continue

				candidate = None
				if customer:
					matches = frappe.get_all(
						"Payment Entry",
						filters={
							"custom_otobitz_receipt_number": nomor,
							"party": customer,
							"paid_amount": amount,
							"posting_date": posting_date,
						},
						pluck="name",
						limit=5,
					)
					candidate = next((m for m in matches if m not in claimed), None)

				if candidate:
					claimed.add(candidate)
					report["details"].append(
						{"nomor": nomor, "allocation_ref": allocation_ref, "action": "rekey", "pe": candidate, "amount": amount}
					)
					report["rekeyed"] += 1
					if not dry_run:
						frappe.db.set_value("Payment Entry", candidate, "custom_otobitz_receipt_number", allocation_ref)
					continue

				# Genuinely missing - this allocation never got a Payment Entry at all.
				report["details"].append(
					{
						"nomor": nomor,
						"allocation_ref": allocation_ref,
						"action": "create",
						"amount": amount,
						"customer": customer_name,
					}
				)
				report["created"] += 1
				report["created_amount"] += amount
				if not dry_run:
					try:
						_create_advance_payment_entry(allocation_ref, nomor, row)
						frappe.db.commit()
					except Exception as exc:
						frappe.db.rollback()
						report["errors"].append(f"{allocation_ref}: {exc}")

	if not dry_run:
		frappe.db.commit()
	return report
