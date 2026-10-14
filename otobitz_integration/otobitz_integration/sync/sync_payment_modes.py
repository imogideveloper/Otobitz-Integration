# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""masterdata_paymentmetode -> Mode of Payment."""

from otobitz_integration.otobitz_integration.api.client import call_api
from otobitz_integration.otobitz_integration.sync.common import as_bool, clean, safe_name, upsert_safe


def sync_payment_modes() -> dict:
	response = call_api("masterdata_paymentmetode")
	rows = response.get("data-paymentmetode") or []

	created = updated = failed = 0
	for row in rows:
		kode = clean(row.get("kode"))
		if not kode:
			continue

		values = {
			"mode_of_payment": safe_name(row.get("nama")) or kode,
			"enabled": as_bool(row.get("aktif")),
			"custom_otobitz_payment_code": kode,
		}

		_, was_created, was_updated, was_failed = upsert_safe(
			"Mode of Payment", {"custom_otobitz_payment_code": kode}, values, ignore_mandatory=True
		)
		created += was_created
		updated += was_updated
		failed += was_failed

	return {"fetched": len(rows), "created": created, "updated": updated, "failed": failed}
