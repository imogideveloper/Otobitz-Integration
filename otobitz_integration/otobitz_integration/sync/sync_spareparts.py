# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""masterdata_sparepart -> Item (stock item, Item Group "OtoBitz Spare Part").

The source list repeats the same `kodepart` once per branch it's priced at
(each row carries its own `pricelist`/`cogs`/`kodecabang`). Phase 1 syncs the
Item master once per unique `kodepart` and only keeps the last-seen price/cogs
as informational fields (`custom_otobitz_last_price/cogs`) - per-branch Item
Price records are deferred to Phase 2, once Warehouse-per-branch exists.
"""

from frappe.utils import flt

from otobitz_integration.otobitz_integration.api.client import call_api
from otobitz_integration.otobitz_integration.sync.common import (
	as_bool,
	clean,
	get_or_create_item_group,
	get_or_create_uom,
	safe_name,
	upsert_safe,
)

ITEM_GROUP = "OtoBitz Spare Part"


def sync_spareparts() -> dict:
	response = call_api("masterdata_sparepart")
	rows = response.get("data-sparepart") or []
	item_group = get_or_create_item_group(ITEM_GROUP)

	created = updated = failed = 0
	seen = set()
	for row in rows:
		item_code = clean(row.get("kodepart"))
		if not item_code or item_code in seen:
			continue
		seen.add(item_code)

		values = {
			"item_name": safe_name(row.get("namapart")) or item_code,
			"item_group": item_group,
			"stock_uom": get_or_create_uom(row.get("satuan")),
			"is_stock_item": 1,
			"disabled": 0 if as_bool(row.get("aktif")) else 1,
			"custom_otobitz_part_code": item_code,
			"custom_otobitz_last_price": flt(row.get("pricelist")),
			"custom_otobitz_last_cogs": flt(row.get("cogs")),
		}

		_, was_created, was_updated, was_failed = upsert_safe(
			"Item",
			{"item_code": item_code},
			values,
			ignore_mandatory=True,
			# stock_uom is never re-set on an update - see upsert()'s
			# docstring for why (mixed-case UOM spelling across branches was
			# tripping Item's UOM-conversion-table validation on every
			# re-sync).
			create_only_fields={"stock_uom"},
		)
		created += was_created
		updated += was_updated
		failed += was_failed

	return {"fetched": len(rows), "created": created, "updated": updated, "failed": failed}
