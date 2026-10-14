# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""masterdata_customerpage -> Customer (paginated bulk sync).

Confirmed live: 81k+ rows across 8000+ pages at the default page size, so this
alone can run past the OtoBitz token's 5-minute lifetime - it's the real-world
case the centralized `call_api()` token refresh in api/client.py exists for.

A customer can own more than one vehicle in the source system (several rows
share the same `idcustomer`); Phase 1 keeps one ERPNext Customer per
`idcustomer` and the vehicle custom fields simply reflect whichever row was
seen last in the page walk (documented limitation, not a bug).

`datacustomerbynumber` (single-customer lookup by number) is a different,
on-demand endpoint and is not part of this bulk sync - deferred to Phase 2.
"""

import frappe

from otobitz_integration.otobitz_integration.api.client import OtoBitzAPIError, call_api
from otobitz_integration.otobitz_integration.sync.common import (
	clean,
	clean_or_none,
	renew_sync_lock,
	safe_name,
	upsert_safe,
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

			tax_id = clean_or_none(row.get("npwp"))

			# Guard against a kodetipe/kodewarna the corresponding master sync
			# hasn't (yet) created - a Link field would otherwise reject the
			# whole row and abort this customer's upsert.
			vehicle_type = clean(row.get("kodetipe"))
			if vehicle_type and not frappe.db.exists("OtoBitz Vehicle Type", vehicle_type):
				vehicle_type = None
			vehicle_color = clean(row.get("kodewarna"))
			if vehicle_color and not frappe.db.exists("OtoBitz Vehicle Color", vehicle_color):
				vehicle_color = None

			values = {
				"customer_name": safe_name(row.get("nama")) or idcustomer,
				"customer_type": "Individual" if (row.get("statuscustomer") or "").strip() == "Perorangan" else "Company",
				"tax_id": tax_id,
				"custom_otobitz_customer_id": idcustomer,
				"custom_otobitz_nopolisi": clean(row.get("nopolisi")),
				"custom_otobitz_norangka": clean(row.get("norangka")),
				"custom_otobitz_nomesin": clean(row.get("nomesin")),
				"custom_otobitz_vehicle_type": vehicle_type,
				"custom_otobitz_vehicle_color": vehicle_color,
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
