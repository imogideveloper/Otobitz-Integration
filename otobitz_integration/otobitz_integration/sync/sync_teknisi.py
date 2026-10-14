# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""masterdata_teknisi -> Employee.

OtoBitz doesn't send gender (mandatory on ERPNext's Employee doctype) or any
other HR-specific data for technicians - they're synced with
`ignore_mandatory=True` and only the fields OtoBitz actually provides.
"""

import frappe

from otobitz_integration.otobitz_integration.api.client import call_api
from otobitz_integration.otobitz_integration.sync.common import clean, get_or_create_branch, safe_name, upsert_safe


def sync_teknisi() -> dict:
	response = call_api("masterdata_teknisi")
	rows = response.get("data-teknisi") or []

	settings = frappe.get_cached_doc("OtoBitz Settings")
	company = settings.default_company
	if not company:
		frappe.throw(frappe._("Set Default Company in OtoBitz Settings before syncing Teknisi."))

	created = updated = failed = 0
	for row in rows:
		kode = clean(row.get("kode"))
		if not kode:
			continue

		branch = get_or_create_branch(row.get("kodecabang"), row.get("namacabang"))
		values = {
			"employee_name": safe_name(row.get("nama")) or kode,
			"first_name": safe_name(row.get("nama")) or kode,
			"company": company,
			"branch": branch,
			"custom_otobitz_teknisi_code": kode,
		}

		_, was_created, was_updated, was_failed = upsert_safe(
			"Employee", {"custom_otobitz_teknisi_code": kode}, values, ignore_mandatory=True
		)
		created += was_created
		updated += was_updated
		failed += was_failed

	return {"fetched": len(rows), "created": created, "updated": updated, "failed": failed}
