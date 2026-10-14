# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""masterdata_kategorikendaraan / masterdata_tipekendaraan / masterdata_warna
-> the OtoBitz Vehicle Category/Type/Color lookup doctypes. These have no
ERPNext-standard equivalent (ERPNext is not an automotive-vertical ERP).
"""

from otobitz_integration.otobitz_integration.api.client import call_api
from otobitz_integration.otobitz_integration.sync.common import as_bool, clean, upsert_safe


def sync_vehicle_categories() -> dict:
	response = call_api("masterdata_kategorikendaraan")
	rows = response.get("data-kategori") or []

	created = updated = failed = 0
	for row in rows:
		kode = clean(row.get("kode"))
		if not kode:
			continue
		values = {
			"nama": clean(row.get("nama")) or kode,
			"frt": clean(row.get("frt")),
			"aktif": as_bool(row.get("aktif")),
		}
		_, was_created, was_updated, was_failed = upsert_safe("OtoBitz Vehicle Category", {"kode": kode}, values)
		created += was_created
		updated += was_updated
		failed += was_failed

	return {"fetched": len(rows), "created": created, "updated": updated, "failed": failed}


def sync_vehicle_types() -> dict:
	response = call_api("masterdata_tipekendaraan")
	rows = response.get("data-tipe") or []

	created = updated = failed = 0
	for row in rows:
		kode = clean(row.get("kode"))
		if not kode:
			continue
		values = {
			"nama": clean(row.get("nama")) or kode,
			"vehicle_category": clean(row.get("kodekategori")),
			"transmisi": clean(row.get("transmisi")),
			"brand": clean(row.get("brand")),
			"aktif": as_bool(row.get("aktif")),
		}
		_, was_created, was_updated, was_failed = upsert_safe("OtoBitz Vehicle Type", {"kode": kode}, values)
		created += was_created
		updated += was_updated
		failed += was_failed

	return {"fetched": len(rows), "created": created, "updated": updated, "failed": failed}


def sync_vehicle_colors() -> dict:
	response = call_api("masterdata_warna")
	rows = response.get("data-warna") or []

	created = updated = failed = 0
	for row in rows:
		kode = clean(row.get("kode"))
		if not kode:
			continue
		values = {
			"nama": clean(row.get("nama")) or kode,
			"aktif": as_bool(row.get("aktif")),
		}
		_, was_created, was_updated, was_failed = upsert_safe("OtoBitz Vehicle Color", {"kode": kode}, values)
		created += was_created
		updated += was_updated
		failed += was_failed

	return {"fetched": len(rows), "created": created, "updated": updated, "failed": failed}
