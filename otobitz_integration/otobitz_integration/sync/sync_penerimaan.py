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

The paid-to account comes from the Mode of Payment's own configured default
account for this Company (standard ERPNext setup under Mode of Payment >
Accounts) rather than OtoBitz's raw `kodeaccount` - that field is the source
system's own chart of accounts, not ours, and isn't something this sync can
safely map on its own.
"""

from collections import defaultdict

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import get_bank_cash_account, get_payment_entry
from frappe.utils import add_days, flt, get_first_day, getdate, nowdate

from otobitz_integration.otobitz_integration.api.client import OtoBitzAPIError, call_api
from otobitz_integration.otobitz_integration.sync.common import (
	clean,
	log_failed_sync,
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


def sync_penerimaan() -> dict:
	tanggalawal, tanggalakhir = get_sync_window()

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
			try:
				was_created = _sync_one_receipt(nomor, row)
				created += was_created
				updated += not was_created
				# Per-row commit: a later row's rollback must never wipe out
				# rows already synced earlier in this same chunk - this is
				# the exact bug that silently dropped hundreds of Sales
				# Orders before it was caught (see sync_service_orders.py).
				frappe.db.commit()
				resolve_failed_sync("penerimaanuang", nomor)
				frappe.db.commit()
			except Exception as exc:
				frappe.db.rollback()
				frappe.log_error(title=f"OtoBitz sync: failed to sync receipt {nomor}")
				log_failed_sync("penerimaanuang", nomor, str(exc), row)
				frappe.db.commit()
				failed += 1

	frappe.db.set_single_value("OtoBitz Settings", WATERMARK_FIELD, nowdate(), update_modified=False)
	frappe.db.commit()

	return {"fetched": fetched, "created": created, "updated": updated, "failed": failed}


def _sync_one_receipt(nomor: str, row: dict) -> bool:
	"""Returns True if a new Payment Entry was created (False if it already
	existed - cancellations and re-syncs of an existing receipt are no-ops,
	not updates, since OtoBitz payment receipts aren't expected to change
	amount after the fact)."""
	existing = frappe.db.get_value("Payment Entry", {"custom_otobitz_receipt_number": nomor})

	if (row.get("status") or "").strip().lower() == "batal":
		if existing and frappe.db.get_value("Payment Entry", existing, "docstatus") == 1:
			frappe.get_doc("Payment Entry", existing).cancel()
		return False

	if existing:
		return False

	_create_payment_entry(nomor, row)
	return True


def _create_payment_entry(nomor: str, row: dict) -> str:
	nofaktur = clean(row.get("noreferensi"))
	si_name = nofaktur and frappe.db.get_value("Sales Invoice", {"custom_otobitz_nofaktur": nofaktur})
	if not si_name:
		frappe.throw(f"No Sales Invoice found for nofaktur {nofaktur!r} (receipt {nomor})")

	mode_of_payment = frappe.db.get_value(
		"Mode of Payment", {"custom_otobitz_payment_code": clean(row.get("paymentmetode"))}
	)
	branch = frappe.db.get_value("Branch", {"custom_otobitz_branch_code": clean(row.get("kode_cabang"))})
	amount = flt(row.get("nilaipenerimaan"))

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
	pe.custom_otobitz_receipt_number = nomor
	if branch:
		pe.custom_otobitz_branch = branch
	if mode_of_payment:
		pe.mode_of_payment = mode_of_payment
		bank_cash = get_bank_cash_account(pe, None)
		if bank_cash and bank_cash.get("account"):
			pe.paid_to = bank_cash["account"]

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
