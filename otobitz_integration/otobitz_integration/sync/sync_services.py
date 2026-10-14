# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""masterdata_jasaservice + masterdata_pekerjaanluar -> Item (non-stock,
Item Group "OtoBitz Service"). Both source lists repeat the same code once
per vehicle category (jasaservice) or branch (pekerjaanluar) it's priced for,
so both are deduped to one Item per code, same last-seen-price simplification
as sync_spareparts.py.
"""

from frappe.utils import flt

from otobitz_integration.otobitz_integration.api.client import call_api
from otobitz_integration.otobitz_integration.sync.common import (
	as_bool,
	clean,
	get_or_create_branch,
	get_or_create_item_group,
	get_or_create_uom,
	safe_name,
	upsert_safe,
)

ITEM_GROUP = "OtoBitz Service"


def sync_jasaservice() -> dict:
	response = call_api("masterdata_jasaservice")
	rows = response.get("data-jasa") or []
	item_group = get_or_create_item_group(ITEM_GROUP)

	created = updated = failed = 0
	seen = set()
	for row in rows:
		item_code = clean(row.get("kodejasa"))
		if not item_code or item_code in seen:
			continue
		seen.add(item_code)

		values = {
			"item_name": safe_name(row.get("namajasa")) or item_code,
			"item_group": item_group,
			"stock_uom": get_or_create_uom("Nos"),
			"is_stock_item": 0,
			"disabled": 0 if as_bool(row.get("aktif")) else 1,
			"custom_otobitz_service_code": item_code,
			"custom_otobitz_last_price": flt(row.get("harga")),
		}

		_, was_created, was_updated, was_failed = upsert_safe(
			"Item",
			{"item_code": item_code},
			values,
			ignore_mandatory=True,
			create_only_fields={"stock_uom"},
		)
		created += was_created
		updated += was_updated
		failed += was_failed

	return {"fetched": len(rows), "created": created, "updated": updated, "failed": failed}


def sync_pekerjaanluar() -> dict:
	response = call_api("masterdata_pekerjaanluar")
	rows = response.get("data-pekerjaan") or []
	item_group = get_or_create_item_group(ITEM_GROUP)

	created = updated = failed = 0
	seen = set()
	for row in rows:
		item_code = clean(row.get("kodeopl"))
		if not item_code or item_code in seen:
			continue
		seen.add(item_code)

		get_or_create_branch(row.get("kodecabang"), row.get("namacabang"))

		values = {
			"item_name": safe_name(row.get("namaopl")) or item_code,
			"item_group": item_group,
			"stock_uom": get_or_create_uom("Nos"),
			"is_stock_item": 0,
			"disabled": 0 if as_bool(row.get("aktif")) else 1,
			"custom_otobitz_service_code": item_code,
			"custom_otobitz_last_price": flt(row.get("hargajual")),
			"custom_otobitz_last_cogs": flt(row.get("hargabeli")),
		}

		_, was_created, was_updated, was_failed = upsert_safe(
			"Item",
			{"item_code": item_code},
			values,
			ignore_mandatory=True,
			create_only_fields={"stock_uom"},
		)
		created += was_created
		updated += was_updated
		failed += was_failed

	return {"fetched": len(rows), "created": created, "updated": updated, "failed": failed}
