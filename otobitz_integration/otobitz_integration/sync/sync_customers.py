# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""masterdata_customerpage -> Customer (paginated bulk sync).

Confirmed live: 81k+ rows across 8000+ pages at the default page size, so this
alone can run past the OtoBitz token's 5-minute lifetime - it's the real-world
case the centralized `call_api()` token refresh in api/client.py exists for.

A customer can own more than one vehicle in the source system (several rows
share the same `idcustomer`); Phase 1 keeps one ERPNext Customer per
`idcustomer`. This sync used to also cache "whichever vehicle was seen last"
onto a handful of custom_otobitz_* fields on Customer itself, but that was
pure duplication of OtoBitz Vehicle (kept properly up to date per-vehicle,
keyed by norangka, via common.get_or_create_vehicle() on every Work Order) -
those fields are now hidden on the Customer form and no longer written here.

`datacustomerbynumber` (single-customer lookup by number) is a different,
on-demand endpoint and is not part of this bulk sync - deferred to Phase 2.
"""

import frappe

from otobitz_integration.otobitz_integration.api.client import OtoBitzAPIError, call_api
from otobitz_integration.otobitz_integration.sync.common import (
	clean,
	clean_or_none,
	looks_garbled,
	renew_sync_lock,
	safe_name,
	upsert_safe,
	valid_npwp_or_none,
)

PAGE_SIZE = 200


def sync_customers() -> dict:
	fetched = created = updated = failed = 0
	page = 1
	total_pages = 1

	while page <= total_pages:
		renew_sync_lock()
		try:
			# call_api() already retries network-level failures a few times;
			# this only catches the case it gives up entirely on one page -
			# the walk must continue past it, not abort the other ~400 pages.
			response = call_api("masterdata_customerpage", {"page": page, "per_page": PAGE_SIZE})
		except OtoBitzAPIError:
			frappe.log_error(title=f"OtoBitz sync: giving up on masterdata_customerpage page {page}")
			failed += 1
			page += 1
			continue

		paging = response.get("paging") or {}
		total_pages = paging.get("total_pages") or total_pages
		rows = response.get("data-customer") or []

		for row in rows:
			fetched += 1
			idcustomer = clean(row.get("idcustomer"))
			if not idcustomer:
				continue

			# OtoBitz has, for a small number of customers, sent `nama`/`npwp`
			# replaced with masked/garbled text instead of the real value
			# (confirmed incident 2026-11-11: 9 live Customers corrupted this
			# way). looks_garbled()/valid_npwp_or_none() catch that shape and
			# the row is treated as if the field were absent, rather than
			# overwriting a previously-good customer_name/tax_id with garbage.
			name = safe_name(row.get("nama"))
			# None here means "don't touch customer_name at all" (key left out
			# of values below) - distinct from "" / falsy, which would still
			# fall back to idcustomer.
			customer_name = name or idcustomer
			if name and looks_garbled(name):
				frappe.log_error(title=f"OtoBitz sync: garbled nama skipped for {idcustomer}", message=name)
				# Only fall back to idcustomer as the name for a brand-new
				# customer - on an update this must stay unset so the
				# existing good customer_name is left untouched.
				customer_name = None if frappe.db.exists("Customer", {"custom_otobitz_customer_id": idcustomer}) else idcustomer

			raw_npwp = row.get("npwp")
			tax_id = valid_npwp_or_none(raw_npwp)
			if clean_or_none(raw_npwp) and not tax_id:
				frappe.log_error(title=f"OtoBitz sync: garbled/invalid npwp skipped for {idcustomer}", message=str(raw_npwp))

			values = {
				"customer_name": customer_name,
				"customer_type": "Individual" if (row.get("statuscustomer") or "").strip() == "Perorangan" else "Company",
				"tax_id": tax_id,
				"custom_otobitz_customer_id": idcustomer,
			}
			values = {k: v for k, v in values.items() if v is not None}

			# upsert_safe, not upsert: with 80k+ rows one malformed record
			# must never abort the rest of the pagination walk.
			_, was_created, was_updated, was_failed = upsert_safe(
				"Customer", {"custom_otobitz_customer_id": idcustomer}, values, ignore_mandatory=True
			)
			created += was_created
			updated += was_updated
			failed += was_failed

		frappe.db.commit()
		page += 1

	return {"fetched": fetched, "created": created, "updated": updated, "failed": failed}
