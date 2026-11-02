# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""pengeluaranuang -> Journal Entry (Contra) or Payment Entry (Pay).

Checked against 95 real rows spanning a full month (2026-09-01..2026-10-01):
100% of them were `jenisterima == "PEMBAYARAN SETORAN TUNAI"` with
`namasupplier` empty - branch cash being deposited into a bank account, not a
payment to an external party. That makes this a Contra entry (Cash account
credited, Bank account debited), not a Payment Entry with a Supplier, unlike
its sibling `penerimaanuang`.

A row where `namasupplier` IS populated (an actual supplier payment) goes to
Payment Entry instead (see `_create_payment_entry` below) - but this path is
UNTESTED against real data: as of 2026-11-02, a `namasupplier`-populated row
has never been observed from this endpoint (still 0 across 208 rows spanning
2026-09-01..2026-11-01), and the Odoo side this integration mirrors
(`groow_oto_integration`, model `account.payment`) has its own
`oto_pengeluaran_uang_id`/`oto_pengeluaran_uang_ref` link fields for exactly
this case but has NEVER populated them either (0 of 3340 real Supplier
Payments in Odoo) - every one of those was entered by a human directly in
Odoo, not synced from this endpoint. So there's no real example anywhere,
in either system, to verify field mapping against. In particular: there is
no `kodesupplier`/similar code on this endpoint's rows (only the free-text
`namasupplier`), so the Supplier is resolved by matching `supplier_name`
directly - unlike every other sync module here, which matches suppliers by
a stable OtoBitz code (`custom_otobitz_supplier_no`). This is a real gap:
a name match can mismatch on typos/case or match an unrelated Supplier that
happens to share a name. Revisit once a real `namasupplier` row exists to
confirm against.

The destination Bank account is a placeholder ("Bank - O") stamped on every
Contra entry, since none of those rows name a specific bank - point this at
a real per-branch bank account once one exists in the Chart of Accounts.
"""

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import get_bank_cash_account
from frappe.utils import add_days, flt, get_first_day, getdate, nowdate

from otobitz_integration.otobitz_integration.api.client import OtoBitzAPIError, call_api
from otobitz_integration.otobitz_integration.sync.common import (
	clean,
	log_failed_sync,
	renew_sync_lock,
	resolve_failed_sync,
	set_period_fields,
)

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
				resolve_failed_sync("pengeluaranuang", nomor)
				frappe.db.commit()
			except Exception as exc:
				frappe.db.rollback()
				frappe.log_error(title=f"OtoBitz sync: failed to sync expense {nomor}")
				log_failed_sync("pengeluaranuang", nomor, str(exc), row)
				frappe.db.commit()
				failed += 1

	frappe.db.set_single_value("OtoBitz Settings", WATERMARK_FIELD, nowdate(), update_modified=False)
	frappe.db.commit()

	return {"fetched": fetched, "created": created, "updated": updated, "failed": failed}


def _sync_one_expense(nomor: str, row: dict) -> bool:
	"""Returns True if a new Journal Entry/Payment Entry was created (False if
	it already existed - cancellations and re-syncs of an existing entry are
	no-ops). Branches on `namasupplier`: empty -> Contra Entry (cash deposit,
	the only case ever observed in real data), populated -> Payment Entry
	(Pay) - see the module docstring for why that second path is untested."""
	is_supplier_payment = bool(clean(row.get("namasupplier")))
	doctype = "Payment Entry" if is_supplier_payment else "Journal Entry"
	existing = frappe.db.get_value(doctype, {"custom_otobitz_receipt_number": nomor})

	if (row.get("status") or "").strip().lower() == "batal":
		if existing and frappe.db.get_value(doctype, existing, "docstatus") == 1:
			frappe.get_doc(doctype, existing).cancel()
		return False

	if existing:
		return False

	if is_supplier_payment:
		_create_payment_entry(nomor, row)
	else:
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


def _create_payment_entry(nomor: str, row: dict) -> str:
	"""Supplier payment branch of `_sync_one_expense` - see the module
	docstring for why this is untested against real data.

	No Purchase Invoice/Purchase Order reference is attached (unlike
	sync_penerimaan.py's Payment Entry, which always references a Sales
	Invoice): this endpoint's rows carry no PO/PI number for the supplier
	payment case, so the Payment Entry is posted unreconciled, same as a
	plain advance/on-account payment. Reconciling it against a bill is left
	as a manual follow-up until a real row reveals what reference field (if
	any) OtoBitz actually sends here."""
	company = frappe.db.get_single_value("OtoBitz Settings", "default_company")
	branch = frappe.db.get_value("Branch", {"custom_otobitz_branch_code": clean(row.get("kode_cabang"))})
	amount = flt(row.get("nilaipembayaran"))
	remark = clean(row.get("keterangan")) or clean(row.get("memo")) or nomor

	# Matched by name, not by a stable OtoBitz code - see the module
	# docstring's "real gap" note. `namasupplier` is the only identifier this
	# endpoint gives for the payee in this case.
	supplier_name = clean(row.get("namasupplier"))
	supplier = frappe.db.get_value("Supplier", {"supplier_name": supplier_name})
	if not supplier:
		frappe.throw(f"No Supplier found matching namasupplier {supplier_name!r} (expense {nomor})")

	mode_of_payment = frappe.db.get_value(
		"Mode of Payment", {"custom_otobitz_payment_code": clean(row.get("kodeaccount"))}
	)

	pe = frappe.new_doc("Payment Entry")
	pe.payment_type = "Pay"
	pe.party_type = "Supplier"
	pe.party = supplier
	pe.company = company
	pe.posting_date = getdate(row.get("tanggal"))
	pe.paid_amount = amount
	pe.received_amount = amount
	pe.custom_otobitz_receipt_number = nomor
	if branch:
		pe.custom_otobitz_branch = branch
	if mode_of_payment:
		pe.mode_of_payment = mode_of_payment
	set_period_fields(pe, pe.posting_date)

	bank_cash = get_bank_cash_account(pe, None)
	if bank_cash and bank_cash.get("account"):
		pe.paid_from = bank_cash["account"]

	pe.insert(ignore_permissions=True, ignore_mandatory=True)
	pe.submit()
	return pe.name
