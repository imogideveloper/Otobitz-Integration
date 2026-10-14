# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""pengeluaranuang -> Journal Entry (Contra).

Checked against 95 real rows spanning a full month (2026-09-01..2026-10-01):
100% of them were `jenisterima == "PEMBAYARAN SETORAN TUNAI"` with
`namasupplier` empty - branch cash being deposited into a bank account, not a
payment to an external party. That makes this a Contra entry (Cash account
credited, Bank account debited), not a Payment Entry with a Supplier, unlike
its sibling `penerimaanuang`.

A row where `namasupplier` IS populated (an actual supplier payment) has
never been observed in real data - rather than guess at untested mapping
logic for a case with zero real examples, such a row is logged and skipped;
it'll need its own design once one actually shows up.

The destination Bank account is a placeholder ("Bank - O") stamped on every
entry, since none of these rows name a specific bank - point this at a real
per-branch bank account once one exists in the Chart of Accounts.
"""

import frappe
from frappe.utils import add_days, flt, get_first_day, getdate, nowdate

from otobitz_integration.otobitz_integration.api.client import OtoBitzAPIError, call_api
from otobitz_integration.otobitz_integration.sync.common import clean, renew_sync_lock, set_period_fields

WATERMARK_FIELD = "last_pengeluaran_sync_date"
OVERLAP_DAYS = 3
CHUNK_DAYS = 2
PLACEHOLDER_BANK_ACCOUNT = "Bank - O"


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


def sync_pengeluaran() -> dict:
	tanggalawal, tanggalakhir = get_sync_window()

	fetched = created = updated = failed = 0
	for chunk_start, chunk_end in _iter_date_chunks(tanggalawal, tanggalakhir):
		renew_sync_lock()
		try:
			response = call_api("pengeluaranuang", {"tanggalawal": chunk_start, "tanggalakhir": chunk_end})
		except OtoBitzAPIError:
			frappe.log_error(title=f"OtoBitz sync: giving up on pengeluaranuang {chunk_start}..{chunk_end}")
			failed += 1
			continue

		rows = response.get("data-pengeluaranuang") or []
		fetched += len(rows)

		for i, row in enumerate(rows):
			if i % 20 == 0:
				renew_sync_lock()
			nomor = clean(row.get("nomor"))
			if not nomor:
				continue
			try:
				was_created = _sync_one_expense(nomor, row)
				created += was_created
				updated += not was_created
				# Per-row commit - see sync_service_orders.py for why this
				# matters: a later row's rollback must never wipe out rows
				# already synced earlier in this same chunk.
				frappe.db.commit()
			except Exception:
				frappe.db.rollback()
				frappe.log_error(title=f"OtoBitz sync: failed to sync expense {nomor}")
				failed += 1

	frappe.db.set_single_value("OtoBitz Settings", WATERMARK_FIELD, nowdate(), update_modified=False)
	frappe.db.commit()

	return {"fetched": fetched, "created": created, "updated": updated, "failed": failed}


def _sync_one_expense(nomor: str, row: dict) -> bool:
	"""Returns True if a new Journal Entry was created (False if it already
	existed - cancellations and re-syncs of an existing entry are no-ops)."""
	existing = frappe.db.get_value("Journal Entry", {"custom_otobitz_receipt_number": nomor})

	if (row.get("status") or "").strip().lower() == "batal":
		if existing and frappe.db.get_value("Journal Entry", existing, "docstatus") == 1:
			frappe.get_doc("Journal Entry", existing).cancel()
		return False

	if existing:
		return False

	if clean(row.get("namasupplier")):
		# Never observed in real data (see module docstring) - skip rather
		# than silently mis-posting a supplier payment as a cash contra.
		frappe.log_error(
			title=f"OtoBitz sync: pengeluaranuang {nomor} has namasupplier set - skipped, needs its own handling"
		)
		return False

	_create_journal_entry(nomor, row)
	return True


def _create_journal_entry(nomor: str, row: dict) -> str:
	company = frappe.db.get_single_value("OtoBitz Settings", "default_company")
	branch = frappe.db.get_value("Branch", {"custom_otobitz_branch_code": clean(row.get("kode_cabang"))})
	amount = flt(row.get("nilaipembayaran"))
	cash_account = frappe.db.get_value("Company", company, "default_cash_account")
	remark = clean(row.get("keterangan")) or clean(row.get("memo")) or nomor

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Contra Entry"
	je.company = company
	je.posting_date = getdate(row.get("tanggal"))
	je.user_remark = remark
	je.custom_otobitz_receipt_number = nomor
	if branch:
		je.custom_otobitz_branch = branch
	set_period_fields(je, je.posting_date)

	je.append("accounts", {"account": cash_account, "credit_in_account_currency": amount})
	je.append("accounts", {"account": PLACEHOLDER_BANK_ACCOUNT, "debit_in_account_currency": amount})

	je.insert(ignore_permissions=True, ignore_mandatory=True)
	je.submit()
	return je.name
