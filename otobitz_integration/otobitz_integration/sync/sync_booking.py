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

This endpoint itself doesn't carry a customer id/code anywhere - only
`namacustomer` as free text. The booking it belongs to does, though:
`masterdata_bookingservicepernomor` (looked up here by the same
`noreferensi`/`allocation_ref`, a "BKS-..." number both endpoints share)
carries `nomor_customer`, a stable code confirmed live to be the exact
same code space as `otoxpertsoandpart`'s own `customerid` (a customer
already created from a Work Order and a customer only ever seen here so
far both resolve/get-or-created by that one shared field,
custom_otobitz_customer_id - no duplicate Customer either way). That
lookup, fired once per booking right alongside its first advance Payment
Entry, is now the PRIMARY way the Customer below gets resolved; the old
free-text exact-name match against `customer_name` only still runs as a
fallback, for whenever the detail lookup itself can't be done (the
endpoint down, or this booking's own number genuinely not found there).

That same lookup also carries a real item `detail[]` array and the
booking's own `nomorso` once OtoBitz converts it into a Work Order -
enough to build a DRAFT Sales Order (parts, customer, vehicle) the moment
the advance payment comes in, before there's a Work Order to sync at all.
Reported live: "kedepannya kalau ada ini [booking] akan membuat SO draft,
detail dari part nya customer nya dan lainnya ... sudah ada kan di
endpoint itu" - see `_create_draft_sales_order_from_booking()` below.
"""

import time

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import get_bank_cash_account
from erpnext.controllers.accounts_controller import get_taxes_and_charges
from frappe.utils import add_days, cint, flt, get_first_day, getdate, nowdate

from otobitz_integration.otobitz_integration.api.client import OtoBitzAPIError, call_api
from otobitz_integration.otobitz_integration.sync.common import (
	IMOGIBOT_USER,
	clean,
	log_booking_detail_row,
	log_failed_sync,
	renew_sync_lock,
	resolve_failed_sync,
	safe_name,
	set_period_fields,
	upsert,
)
from otobitz_integration.otobitz_integration.sync.sync_service_orders import (
	TAXES_AND_CHARGES_TEMPLATE,
	_pin_oto_taxes,
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
	# See sync_service_orders.py's identical variable for why this matters:
	# a chunk-level failure (the whole day's API call never came back) must
	# cap how far the watermark below is allowed to advance, or that day is
	# silently never retried again.
	first_unfetched_chunk_start: str | None = None
	for chunk_start, chunk_end in _iter_date_chunks(tanggalawal, tanggalakhir):
		renew_sync_lock()
		try:
			response = call_api("penerimaanuangmukabooking", {"tanggalawal": chunk_start, "tanggalakhir": chunk_end})
		except OtoBitzAPIError:
			frappe.log_error(title=f"OtoBitz sync: giving up on penerimaanuangmukabooking {chunk_start}..{chunk_end}")
			failed += 1
			if first_unfetched_chunk_start is None:
				first_unfetched_chunk_start = chunk_start
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
			# Raw archive, independent of whatever happens below - see
			# log_booking_detail_row()'s docstring in common.py.
			log_booking_detail_row(allocation_ref, nomor, row)
			frappe.db.commit()
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
		new_watermark = (
			str(add_days(getdate(first_unfetched_chunk_start), -1)) if first_unfetched_chunk_start else nowdate()
		)
		frappe.db.set_single_value("OtoBitz Settings", WATERMARK_FIELD, new_watermark, update_modified=False)
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

	# One shared lookup - see the module docstring - feeds the Customer
	# into BOTH the Payment Entry below (replacing the old name-match as
	# the primary path, not just a nice-to-have for the draft SO) and the
	# draft Sales Order. Never raises (see _fetch_booking_detail()'s own
	# docstring): a lookup miss just falls back to _create_advance_payment_entry()'s
	# own old name-match, same as before this existed.
	booking_detail = _fetch_booking_detail(allocation_ref)
	resolved_customer = _resolve_booking_customer(booking_detail) if booking_detail else None

	_create_advance_payment_entry(allocation_ref, nomor, row, customer_override=resolved_customer)
	# Best-effort, never fatal to this booking's Payment Entry - see that
	# function's own docstring for why it swallows its own errors instead
	# of raising.
	_create_draft_sales_order_from_booking(allocation_ref, detail=booking_detail, customer=resolved_customer)
	return True


def _create_advance_payment_entry(
	allocation_ref: str, nomor: str, row: dict, customer_override: str | None = None
) -> str:
	# customer_override - resolved from masterdata_bookingservicepernomor's
	# own stable nomor_customer, via _sync_one_booking() - is now the
	# PRIMARY path (fixes the real "Customer tidak ditemukan berdasarkan
	# nama" Failed Sync category this module's own docstring used to
	# document as a hard limitation). The old free-text name match below
	# only still runs as a fallback, for whenever that lookup itself
	# genuinely can't be done (the detail endpoint down, or this booking's
	# own number not found there for some reason).
	customer = customer_override
	if not customer:
		customer_name = clean(row.get("namacustomer"))
		customer = customer_name and frappe.db.get_value("Customer", {"customer_name": customer_name})
	if not customer:
		frappe.throw(f"No Customer found matching name {clean(row.get('namacustomer'))!r} (booking advance {allocation_ref})")

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
	# Already existed as a Select field on Payment Entry (with exactly this
	# endpoint's own name as one of its options) but nothing ever actually
	# set it - see sync_penerimaan.py's own _create_payment_entry() for the
	# same fix. A booking advance's own Payment Entry Reference table is
	# always empty (there's no invoice yet to allocate against), which is
	# the other visible tell, but this field says so directly instead of
	# making anyone infer it.
	pe.custom_otobitz_endpoint = "penerimaanuangmukabooking"
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


def _fetch_booking_detail(nomor_booking: str) -> dict | None:
	"""The one record masterdata_bookingservicepernomor returns for this
	booking's own "BKS-..." number - note this is NOT the same kind of
	`nomor` penerimaanuangmukabooking itself uses (that one is the shared
	cash/QRIS receipt number, confirmed live to return "Data not found"
	here). Returns None (not a throw) on a lookup miss/failure, same stance
	as _resolve_customer_info() in sync_service_orders.py - this whole
	draft-SO feature is a nice-to-have on top of the advance payment, never
	something worth failing that payment's own sync over."""
	try:
		response = call_api("masterdata_bookingservicepernomor", {"nomor": nomor_booking})
	except OtoBitzAPIError:
		frappe.log_error(title=f"OtoBitz sync: masterdata_bookingservicepernomor failed for booking {nomor_booking}")
		return None
	rows = response.get("data-booking") or []
	return rows[0] if rows else None


def _resolve_booking_customer(detail: dict) -> str | None:
	"""Get-or-create the Customer from this booking's own `nomor_customer` -
	the same stable OtoBitz code space as otoxpertsoandpart's `customerid`
	(both keyed here on the same custom_otobitz_customer_id field), unlike
	penerimaanuangmukabooking's own rows which only ever carry a free-text
	name. A booking whose customer already exists (created earlier from a
	real Work Order, or an earlier booking) is matched and reused here
	rather than risking a second, duplicate Customer for the same person."""
	customer_code = clean(detail.get("nomor_customer"))
	if not customer_code:
		return None
	values = {
		"customer_name": safe_name(detail.get("nama_customer")) or customer_code,
		"customer_type": "Individual",
		"custom_otobitz_customer_id": customer_code,
	}
	name, _, _ = upsert("Customer", {"custom_otobitz_customer_id": customer_code}, values, ignore_mandatory=True)
	return name


def _build_booking_item_rows(detail_rows: list) -> tuple[list[dict], list[str]]:
	"""Item rows for the draft Sales Order below, from this booking's own
	planned `detail[]` array - a simpler version of sync_service_orders.py's
	own _build_item_rows(): a booking estimate carries no discperitem/
	subtotalppn/jenisdoc at all, just kodereferensi/qty/harga/subtotal, so
	none of that function's OtoBitz-rounding-quirk corrections apply here.
	Returns (item_rows, unresolved_item_codes) - same meaning as there, a
	part code genuinely missing from the Item master, not a line with no
	code at all."""
	item_rows = []
	unresolved_item_codes = []
	for row in detail_rows:
		item_code = clean(row.get("kodereferensi"))
		if not item_code:
			continue
		if not frappe.db.exists("Item", item_code):
			unresolved_item_codes.append(item_code)
			continue
		stock_uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Units"
		qty = flt(row.get("qty"))
		subtotal = flt(row.get("subtotal"))
		if qty < 0.01:
			# Same free/bundled-line guard as sync_service_orders.py's own
			# _build_item_rows() - force qty to 1 at a rate equal to the
			# line's own subtotal (0 for a genuinely free line) instead of
			# multiplying a real per-unit price into a qty that rounds away
			# to nothing.
			qty = 1
			rate = subtotal
		elif subtotal:
			rate = subtotal / qty
		else:
			rate = flt(row.get("harga"))
		item_rows.append(
			{
				"item_code": item_code,
				"qty": qty,
				"rate": rate,
				"price_list_rate": rate,
				"uom": stock_uom,
				"conversion_factor": 1,
			}
		)
	return item_rows, unresolved_item_codes


def _create_draft_sales_order_from_booking(
	allocation_ref: str, detail: dict | None = None, customer: str | None = None
) -> str | None:
	"""Builds a DRAFT Sales Order (docstatus=0) for this booking's own
	planned parts/jasa and customer, the moment OtoBitz reports its first
	advance payment - see the module docstring for why
	masterdata_bookingservicepernomor is what makes this possible at all.

	`detail`/`customer`, when passed in, are the SAME lookup
	_sync_one_booking() already did for the Payment Entry itself - avoids
	a second identical API call for what would otherwise be the exact same
	booking number. Still re-fetches/re-resolves on its own (unchanged
	behavior) when called without them, e.g. from a future manual backfill.

	Only fires once per booking: `custom_otobitz_booking_number` is unique,
	so a booking that already has a draft (or had one created by an
	earlier sync pass) is skipped outright, no API call spent at all. Also
	skipped - deliberately, not an error - once the booking's own `nomorso`
	is set: that means OtoBitz has already converted it into a real Work
	Order, which sync_service_orders.py's regular otoxpertsoandpart sync
	will turn into the real, SUBMITTED Sales Order on its own (keyed by
	that same number as `nomorwo`) - a draft here too would just be a
	second, disconnected document for the same job. Likewise skipped for a
	cancelled booking (`statusbatal` != "TIDAK BATAL").

	This is a forward-looking plan only, built once, from whatever OtoBitz
	reports as planned at the moment of the first advance payment - it is
	NOT kept in sync with the booking afterwards, and is NOT automatically
	linked to or reconciled against the real Sales Order once one exists.
	Both documents end up independently real (the draft stays a Draft,
	untouched); treating them as the same job is left to whoever reviews
	them.

	Never raises - any failure here (the detail lookup itself, an
	unresolvable part code, a bad Customer) is logged and swallowed rather
	than rolling back the Payment Entry _sync_one_booking() just created
	right before calling this."""
	if frappe.db.exists("Sales Order", {"custom_otobitz_booking_number": allocation_ref}):
		return None
	try:
		if detail is None:
			detail = _fetch_booking_detail(allocation_ref)
		if not detail:
			return None
		if clean(detail.get("nomorso")):
			return None
		if (detail.get("statusbatal") or "").strip().upper() != "TIDAK BATAL":
			return None

		if not customer:
			customer = _resolve_booking_customer(detail)
		if not customer:
			return None

		item_rows, unresolved_item_codes = _build_booking_item_rows(detail.get("detail") or [])
		if not item_rows:
			return None

		company = frappe.db.get_single_value("OtoBitz Settings", "default_company")
		booking_date = getdate(detail.get("tanggalbooking") or detail.get("tanggal") or nowdate())

		so = frappe.new_doc("Sales Order")
		so.customer = customer
		so.company = company
		so.transaction_date = booking_date
		so.delivery_date = booking_date
		so.custom_otobitz_booking_number = allocation_ref
		so.custom_salesperson = IMOGIBOT_USER
		set_period_fields(so, so.transaction_date)
		# Same reasoning as sync_service_orders.py's own Sales Orders - this
		# integration never creates a Delivery Note.
		so.skip_delivery_note = 1
		so.custom_plat_nomor = clean(detail.get("nopolisi"))
		so.custom_keluhan = clean(detail.get("keluhan"))
		so.custom_pengguna = clean(detail.get("nohppic"))
		vehicle_type_code = clean(detail.get("kodetipe"))
		if vehicle_type_code and frappe.db.exists("OtoBitz Vehicle Type", vehicle_type_code):
			vehicle_type_info = frappe.db.get_value(
				"OtoBitz Vehicle Type", vehicle_type_code, ["nama", "brand"], as_dict=True
			)
			if vehicle_type_info.nama:
				so.custom_vehicle_type = vehicle_type_info.nama
			if vehicle_type_info.brand:
				so.custom_vehicle_manufacture = vehicle_type_info.brand

		for item_row in item_rows:
			so.append("items", item_row)

		# Pins PPN/Pembulatan to this booking's own dpp/ppn/grandtotal, same
		# as every other OtoBitz-sourced document here - see
		# [[otobitz-trust-source-numbers]]. A part missing from the Item
		# master (unresolved_item_codes) understates net_total the same
		# known way _build_item_rows() itself documents; not re-guarded
		# against here since this is a draft estimate, not a final invoice.
		so.taxes_and_charges = TAXES_AND_CHARGES_TEMPLATE
		so.set("taxes", [])
		so.extend("taxes", get_taxes_and_charges("Sales Taxes and Charges Template", TAXES_AND_CHARGES_TEMPLATE))
		_pin_oto_taxes(so, detail, company)

		so.insert(ignore_permissions=True, ignore_mandatory=True)
		# Deliberately left as a Draft - unlike every other Sales Order this
		# app creates (always submitted immediately): this is a plan, not
		# yet a sale OtoBitz itself has committed to billing.
		if unresolved_item_codes:
			frappe.get_doc(
				{
					"doctype": "Comment",
					"comment_type": "Info",
					"reference_doctype": "Sales Order",
					"reference_name": so.name,
					"content": (
						f"OtoBitz: booking {allocation_ref} - part belum ada di Item master, "
						f"tidak ikut masuk ke draft ini: {', '.join(unresolved_item_codes)}"
					),
				}
			).insert(ignore_permissions=True)
		return so.name
	except Exception:
		frappe.log_error(title=f"OtoBitz sync: failed to draft Sales Order for booking {allocation_ref}")
		return None


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

	# No overlap with the scheduled sync's own cooldown logic (orchestrator.py
	# only paces between DIFFERENT endpoints within one run, not repeated
	# calls to the SAME one) - this backfill hits one endpoint many times in
	# a row with no pacing at all otherwise, which got rate-limited hard
	# enough in practice to look like a hang (confirmed live: a 16-day/8-
	# chunk run on penerimaanuang never returned). Reuses the same "light"
	# cooldown setting the regular sync paces lighter endpoints with.
	cooldown = frappe.db.get_single_value("OtoBitz Settings", "light_endpoint_cooldown_seconds") or 20

	for chunk_index, (chunk_start, chunk_end) in enumerate(_iter_date_chunks(from_date, to_date)):
		if chunk_index:
			time.sleep(cooldown)
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
