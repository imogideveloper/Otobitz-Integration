# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""penerimaanuang -> Payment Entry (Receive), linked to the Sales Invoice
created by sync_service_orders.py.

`noreferensi` on a penerimaanuang row matches `nofaktur` on the originating
Work Order - stamped onto the Sales Invoice as `custom_otobitz_nofaktur` for
exactly this join. A row with no matching Sales Invoice (e.g. the invoice
hasn't synced yet, or predates this app) is skipped and logged, not guessed
at - it'll resolve itself once that invoice exists and this endpoint's
incremental window reaches this row again (3-day overlap, same as
otoxpertsoandpart).

One `nomor` (a single cash/QRIS receipt) can settle SEVERAL invoices at
once, each its own row sharing that `nomor` but a different `noreferensi` -
same bug class as sync_booking.py's penerimaanuangmukabooking: confirmed
live, nomor 003-IS261100056 carried 2 rows (nofaktur SV-003-261100112 and
SV-003-261100113, Rp115,000 each), and dedup keyed on `nomor` alone silently
dropped the second payment entirely.

`custom_otobitz_receipt_number` therefore stores `nofaktur` (the invoice
this specific row settles), NOT the shared `nomor` - confirmed the hard way
live: the field carries a UNIQUE database constraint, so a first attempt at
storing the shared `nomor` here succeeds for whichever invoice is processed
first, and every other invoice under the same receipt then fails outright
with a duplicate-key IntegrityError on insert, not a dedup false-positive.
`nomor` still lands on `reference_no` so every Payment Entry split off one
receipt stays visibly grouped together, same as sync_booking.py's
allocation_ref/nomor split.

The paid-to account comes from the Mode of Payment's own configured default
account for this Company (standard ERPNext setup under Mode of Payment >
Accounts) rather than OtoBitz's raw `kodeaccount` - that field is the source
system's own chart of accounts, not ours, and isn't something this sync can
safely map on its own.
"""

import time
from collections import defaultdict

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import get_bank_cash_account, get_payment_entry
from frappe.utils import add_days, cint, flt, get_first_day, getdate, now_datetime, nowdate

from otobitz_integration.otobitz_integration.api.client import OtoBitzAPIError, call_api
from otobitz_integration.otobitz_integration.sync.common import (
	clean,
	log_failed_sync,
	log_receipt_detail_row,
	renew_sync_lock,
	resolve_failed_sync,
	set_period_fields,
	sync_so_payment_status,
)

WATERMARK_FIELD = "last_penerimaan_sync_date"
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


def sync_penerimaan(date_range: tuple[str, str] | None = None) -> dict:
	tanggalawal, tanggalakhir = date_range or get_sync_window()

	fetched = created = updated = failed = 0
	for chunk_start, chunk_end in _iter_date_chunks(tanggalawal, tanggalakhir):
		renew_sync_lock()
		try:
			response = call_api("penerimaanuang", {"tanggalawal": chunk_start, "tanggalakhir": chunk_end})
		except OtoBitzAPIError:
			frappe.log_error(title=f"OtoBitz sync: giving up on penerimaanuang {chunk_start}..{chunk_end}")
			failed += 1
			continue

		rows = response.get("data-penerimaanuang") or []
		fetched += len(rows)

		for i, row in enumerate(rows):
			if i % 20 == 0:
				renew_sync_lock()
			nomor = clean(row.get("nomor"))
			if not nomor:
				continue
			# Raw archive, independent of whatever happens below - see
			# log_receipt_detail_row()'s docstring in common.py.
			log_receipt_detail_row("penerimaanuang", row)
			frappe.db.commit()
			# Failed Sync's own record_key - nomor ALONE collides whenever one
			# receipt settles more than one invoice (see module docstring),
			# which would make a second row's failure silently overwrite the
			# first's tracking instead of queuing its own retry.
			record_key = f"{nomor}|{clean(row.get('noreferensi')) or ''}"
			try:
				was_created = _sync_one_receipt(nomor, row)
				created += was_created
				updated += not was_created
				# Per-row commit: a later row's rollback must never wipe out
				# rows already synced earlier in this same chunk - this is
				# the exact bug that silently dropped hundreds of Sales
				# Orders before it was caught (see sync_service_orders.py).
				frappe.db.commit()
				resolve_failed_sync("penerimaanuang", record_key)
				frappe.db.commit()
			except Exception as exc:
				frappe.db.rollback()
				frappe.log_error(title=f"OtoBitz sync: failed to sync receipt {record_key}")
				log_failed_sync("penerimaanuang", record_key, str(exc), row)
				frappe.db.commit()
				failed += 1

	if date_range is None:
		frappe.db.set_single_value("OtoBitz Settings", WATERMARK_FIELD, nowdate(), update_modified=False)
	frappe.db.commit()

	return {"fetched": fetched, "created": created, "updated": updated, "failed": failed}


def _sync_one_receipt(nomor: str, row: dict) -> bool:
	"""Returns True if a new Payment Entry was created (False if it already
	existed - cancellations and re-syncs of an existing receipt are no-ops,
	not updates, since OtoBitz payment receipts aren't expected to change
	amount after the fact).

	Resolves the Sales Invoice first, before the existence check, so the
	dedup key is `nofaktur` (unique per invoice) rather than `nomor` (shared
	across every invoice one receipt settles - see module docstring for why
	that was briefly tried and rejected: custom_otobitz_receipt_number has a
	unique DB constraint, so it can only ever hold one value per column
	regardless of dedup logic)."""
	nofaktur = clean(row.get("noreferensi"))
	si_name = nofaktur and _resolve_sales_invoice(nofaktur)
	is_cancel = (row.get("status") or "").strip().lower() == "batal"

	if not si_name:
		if is_cancel:
			return False  # nothing to cancel if the invoice can't even be resolved
		frappe.throw(f"No Sales Invoice found for nofaktur {nofaktur!r} (receipt {nomor})")

	existing = _existing_payment_entry(nofaktur)

	if is_cancel:
		if existing and frappe.db.get_value("Payment Entry", existing, "docstatus") == 1:
			frappe.get_doc("Payment Entry", existing).cancel()
		return False

	if existing:
		return False

	pe_name = _create_payment_entry(nomor, si_name, nofaktur, row)
	return bool(pe_name)


def _existing_payment_entry(nofaktur: str) -> str | None:
	return frappe.db.get_value("Payment Entry", {"custom_otobitz_receipt_number": nofaktur})


def _find_pe_by_invoice_reference(si_name: str) -> str | None:
	"""Any Payment Entry already linked to this invoice via its own Payment
	Entry Reference row - used by the backfill to find a pre-fix entry
	that's still keyed by the old shared `nomor` instead of the correct
	per-invoice `nofaktur`, so it gets rekeyed instead of mistaken for
	missing and recreated as a duplicate payment."""
	rows = frappe.db.sql(
		"""
		select ref.parent
		from `tabPayment Entry Reference` ref
		where ref.reference_doctype = 'Sales Invoice' and ref.reference_name = %(si_name)s
		limit 1
		""",
		{"si_name": si_name},
	)
	return rows[0][0] if rows else None


def _resolve_sales_invoice(nofaktur: str) -> str | None:
	"""Direct nofaktur match first; if that's not found, the invoice this
	receipt's `noreferensi` names may since have been voided and reissued
	under a different nofaktur at the OtoBitz end (same Work Order, new
	invoice number - confirmed live: `statuswo` for several of these flips
	to "BATAL INVOICE" with a new `nofaktur` on the current API response,
	while our side still only knows the original one). The Work Order number
	isn't on the penerimaanuang row itself, but OtoBitz SO Detail's raw
	archive still has the row that was fetched carrying this exact (now
	stale) nofaktur, which gives us nomorwo - and from there, whatever Sales
	Invoice currently exists for that Work Order (the reissued one)."""
	si_name = frappe.db.get_value("Sales Invoice", {"custom_otobitz_nofaktur": nofaktur})
	if si_name:
		return si_name

	so_detail = frappe.db.sql(
		"""select nomorwo from `tabOtoBitz SO Detail` where raw_data like %s limit 1""",
		(f"%{nofaktur}%",),
	)
	if not so_detail:
		return None
	return frappe.db.get_value("Sales Invoice", {"custom_otobitz_wo_number": so_detail[0][0]})


def _create_payment_entry(nomor: str, si_name: str, nofaktur: str, row: dict) -> str | None:
	amount = flt(row.get("nilaipenerimaan"))
	if amount <= 0:
		# Zero-amount rows exist for non-cash administrative entries from this
		# same endpoint (e.g. "PENYELESAIAN PPH 23" tax-withholding
		# settlements, keterangan-only) - no real money moved, so there's
		# nothing to record; a no-op, not a failure.
		return None

	si_outstanding = flt(frappe.db.get_value("Sales Invoice", si_name, "outstanding_amount"))
	if si_outstanding <= 0:
		# The invoice is already fully settled - this row is a trivial
		# residual/rounding receipt from OtoBitz's own side (seen as low as
		# Rp 11) with nothing left to allocate against. Recording it would
		# need a dedicated advance account (none configured on this Company),
		# and it isn't real new money owed - skipped rather than guessed at.
		return None

	mode_of_payment = frappe.db.get_value(
		"Mode of Payment", {"custom_otobitz_payment_code": clean(row.get("paymentmetode"))}
	)
	branch = frappe.db.get_value("Branch", {"custom_otobitz_branch_code": clean(row.get("kode_cabang"))})

	# Deliberately NOT passing party_amount=amount here: when nilaipenerimaan
	# exceeds the invoice's real outstanding amount (cash rounding at the till
	# is common - e.g. paying 268250 cash against a 267850.04 invoice),
	# get_payment_entry stuffs party_amount straight into the single
	# reference's own `outstanding_amount` field instead of clamping to the
	# invoice's actual outstanding - silently defeating any attempt to cap the
	# allocation against it afterwards. Left at its default, the reference is
	# allocated exactly the invoice's real outstanding amount; the leftover
	# cash is carried as paid_amount's own unallocated remainder (a customer
	# advance), which is the correct place for a genuine overpayment to sit.
	pe = get_payment_entry("Sales Invoice", si_name)
	pe.posting_date = getdate(row.get("tanggal")) or pe.posting_date
	set_period_fields(pe, pe.posting_date)
	pe.paid_amount = amount
	pe.received_amount = amount
	# nofaktur (unique per invoice), NOT the shared nomor - see module
	# docstring and _sync_one_receipt()'s own docstring for why.
	pe.custom_otobitz_receipt_number = nofaktur
	if branch:
		pe.custom_otobitz_branch = branch
	if mode_of_payment:
		pe.mode_of_payment = mode_of_payment
		bank_cash = get_bank_cash_account(pe, None)
		if bank_cash and bank_cash.get("account"):
			pe.paid_to = bank_cash["account"]

	# ERPNext hard-requires reference_no/reference_date whenever the paid-to
	# account is type "Bank" (validate_transaction_reference(), not a
	# mandatory-field check - ignore_mandatory below doesn't cover it). This
	# endpoint has no separate bank-transfer-reference field distinct from
	# the receipt itself, so the receipt's own OtoBitz number/date stands in
	# for it - same fields already stamped elsewhere on this doc, not a new
	# source of truth. Harmless to set unconditionally (Cash accounts don't
	# require it, but having it doesn't hurt).
	pe.reference_no = nomor
	pe.reference_date = pe.posting_date

	# `nilaipenerimaan` can be LESS than the invoice's outstanding amount too
	# (an installment/partial payment, or a bulk receipt the branch recorded
	# against one invoice while it actually covers several - the module
	# docstring's cash-rounding note above only covers the overpayment
	# direction). get_payment_entry()'s default reference allocation is
	# always the invoice's full outstanding amount, which is wrong in this
	# direction: it tries to allocate more than what's actually being paid,
	# which ERPNext's own balance check rejects outright ("Difference Amount
	# must be zero") rather than silently accepting it. Clamping to
	# whichever is smaller is correct for both directions at once - it only
	# ever reduces the allocation from its full-outstanding default, never
	# raises it, so the already-handled overpayment case (amount > outstanding)
	# is untouched by this and still leaves its own excess as an unallocated
	# customer advance.
	for ref in pe.references:
		ref.allocated_amount = min(amount, ref.outstanding_amount)

	pe.insert(ignore_permissions=True, ignore_mandatory=True)
	pe.submit()
	sync_so_payment_status(si_name)
	return pe.name


@frappe.whitelist()
def backfill_split_penerimaan(from_date=None, to_date=None, dry_run=1) -> dict:
	"""One-off repair for the bug fixed above: a receipt that settles
	several invoices at once only ever got ONE Payment Entry pre-fix
	(whichever invoice sync_penerimaan() happened to process first for that
	`nomor`), silently dropping the rest - real money already received
	that's missing from the books.

	Any entry already keyed by the old shared `nomor` instead of the correct
	per-invoice `nofaktur` (a genuinely pre-fix entry, or one created by an
	earlier run of this same backfill before the unique-constraint issue was
	found - confirmed live: 3 of 5 missing payments on 2026-11-07 created
	fine, the other 2 failed outright with a duplicate-key error on
	custom_otobitz_receipt_number, since two DIFFERENT invoices under the
	same receipt both need their own row there) is found unambiguously via
	its own Payment Entry Reference row (reference_name = si_name - this
	endpoint, unlike sync_booking.py's unallocated advances, always links
	straight to one specific invoice, no amount/party/date heuristic
	needed) and rekeyed rather than mistaken for missing. dry_run=1
	(default) reports only; dry_run=0 actually rekeys/creates."""
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
		"skipped_zero_or_settled": 0,
		"errors": [],
		"details": [],
	}

	# See sync_booking.py's backfill_split_booking_advances() for why this
	# pacing exists - hitting one endpoint repeatedly with zero delay got
	# rate-limited hard enough in practice to look like a hang.
	cooldown = frappe.db.get_single_value("OtoBitz Settings", "light_endpoint_cooldown_seconds") or 20

	for chunk_index, (chunk_start, chunk_end) in enumerate(_iter_date_chunks(from_date, to_date)):
		if chunk_index:
			time.sleep(cooldown)
		try:
			response = call_api("penerimaanuang", {"tanggalawal": chunk_start, "tanggalakhir": chunk_end})
		except OtoBitzAPIError as exc:
			report["errors"].append(f"{chunk_start}..{chunk_end}: {exc}")
			continue

		by_nomor: dict[str, list[dict]] = {}
		for row in response.get("data-penerimaanuang") or []:
			nomor = clean(row.get("nomor"))
			if nomor:
				by_nomor.setdefault(nomor, []).append(row)

		for nomor, group in by_nomor.items():
			if len(group) < 2:
				continue
			report["receipts_with_split"] += 1

			for row in group:
				if (row.get("status") or "").strip().lower() == "batal":
					continue
				nofaktur = clean(row.get("noreferensi"))
				si_name = nofaktur and _resolve_sales_invoice(nofaktur)
				if not si_name:
					report["errors"].append(f"{nomor}/{nofaktur}: no Sales Invoice found")
					continue

				if _existing_payment_entry(nofaktur):
					report["already_ok"] += 1
					continue

				amount = flt(row.get("nilaipenerimaan"))

				pe_name = _find_pe_by_invoice_reference(si_name)
				if pe_name:
					report["details"].append(
						{"nomor": nomor, "nofaktur": nofaktur, "si_name": si_name, "amount": amount, "action": "rekey", "pe": pe_name}
					)
					report["rekeyed"] += 1
					if not dry_run:
						frappe.db.set_value("Payment Entry", pe_name, "custom_otobitz_receipt_number", nofaktur)
						frappe.db.commit()
					continue

				report["details"].append(
					{"nomor": nomor, "nofaktur": nofaktur, "si_name": si_name, "amount": amount, "action": "create"}
				)
				if dry_run:
					report["created"] += 1
					report["created_amount"] += amount
					continue
				try:
					pe_name = _create_payment_entry(nomor, si_name, nofaktur, row)
					frappe.db.commit()
					if pe_name:
						report["created"] += 1
						report["created_amount"] += amount
					else:
						report["skipped_zero_or_settled"] += 1
				except Exception as exc:
					frappe.db.rollback()
					report["errors"].append(f"{nofaktur}: {exc}")

	if not dry_run:
		frappe.db.commit()
	return report


@frappe.whitelist()
def cleanup_missing_invoice_failures(min_age_days: int = 7, dry_run: int = 1) -> dict:
	"""Maintenance tool for the "Sales Invoice belum ada saat sync payment"
	Failed Sync category: once a penerimaanuang row's own date rolls more
	than OVERLAP_DAYS=3 days behind the sync's moving window, sync_penerimaan()
	never fetches that row again - its Failed Sync record just sits there
	forever, even once the missing Sales Invoice is genuinely never coming.
	Confirmed live: nofaktur SV-101-260400098 was retried 890 times between
	2026-10-27 and 2026-11-06, then never again (rolled out of the window) -
	no Sales Invoice with that nofaktur exists, and OtoBitz SO Detail's own
	raw archive has zero rows mentioning it anywhere, meaning the underlying
	Work Order was never even fetched by otoxpertsoandpart in the first
	place, not just "not yet".

	For every such Failed Sync row older than `min_age_days` (comfortably
	past the 3-day retry window, so the regular hourly sync has already
	given up on it on its own):
	  1. Re-run _resolve_sales_invoice() right now, in case the invoice has
	     since appeared through some other path (a later full resync, a
	     manual fix, ...) - if so, actually finish the payment sync instead
	     of leaving it to rot.
	  2. If still missing, delete the Failed Sync row outright - this old,
	     it is confirmed never coming back (see this function's own
	     docstring above), and leaving it keeps burying the OTHER failure
	     categories that ARE still actionable (missing Approval Setting,
	     unresolvable Items, ...) under a wall of permanently-dead noise.

	Rows younger than `min_age_days` are left completely alone - the regular
	hourly sync is still actively retrying those on its own, no need to
	second-guess it early.

	dry_run=1 (default): reports only, deletes/resyncs nothing. dry_run=0:
	actually resyncs the ones that resolve and deletes the ones confirmed
	gone."""
	import json

	frappe.only_for("System Manager")
	dry_run = cint(dry_run)
	cutoff = add_days(now_datetime(), -cint(min_age_days))

	report = {
		"min_age_days": cint(min_age_days),
		"dry_run": bool(dry_run),
		"checked": 0,
		"resynced": 0,
		"resynced_amount": 0.0,
		"deleted": 0,
		"errors": [],
		"details": [],
	}

	rows = frappe.get_all(
		"OtoBitz Failed Sync",
		filters={
			"endpoint": "penerimaanuang",
			"error_category": "Sales Invoice belum ada saat sync payment",
			"first_failed_at": ["<", cutoff],
		},
		fields=["name", "record_key", "raw_data"],
	)

	for fs in rows:
		report["checked"] += 1
		try:
			row = json.loads(fs.raw_data) if fs.raw_data else {}
		except Exception:
			report["errors"].append(f"{fs.name}: raw_data not valid JSON")
			continue

		record_key = fs.record_key or ""
		nomor = clean(row.get("nomor")) or (record_key.split("|")[0] if record_key else None)
		nofaktur = clean(row.get("noreferensi"))
		if not nomor or not nofaktur:
			report["errors"].append(f"{fs.name}: missing nomor/noreferensi on the archived row")
			continue

		si_name = _resolve_sales_invoice(nofaktur)
		if si_name:
			report["details"].append(
				{"failed_sync": fs.name, "nomor": nomor, "nofaktur": nofaktur, "action": "resync", "sales_invoice": si_name}
			)
			report["resynced"] += 1
			report["resynced_amount"] += flt(row.get("nilaipenerimaan"))
			if not dry_run:
				try:
					_sync_one_receipt(nomor, row)
					frappe.db.commit()
					resolve_failed_sync("penerimaanuang", record_key)
					frappe.db.commit()
				except Exception as exc:
					frappe.db.rollback()
					report["errors"].append(f"{fs.name}: {exc}")
			continue

		report["details"].append({"failed_sync": fs.name, "nomor": nomor, "nofaktur": nofaktur, "action": "delete"})
		report["deleted"] += 1
		if not dry_run:
			frappe.delete_doc("OtoBitz Failed Sync", fs.name, ignore_permissions=True, force=True)
			frappe.db.commit()

	return report
