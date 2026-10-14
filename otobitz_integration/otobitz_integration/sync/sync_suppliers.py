# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""masterdata_supplier + masterdata_vendor -> Supplier.

Both source lists land on the same ERPNext Supplier doctype, but they are
different id spaces in OtoBitz (`nomor` for suppliers, `kode` for vendors), so
each gets its own idempotency custom field rather than sharing one.
"""

from otobitz_integration.otobitz_integration.api.client import call_api
from otobitz_integration.otobitz_integration.sync.common import (
	as_bool,
	clean,
	clean_email,
	clean_or_none,
	clean_phone,
	get_or_create_branch,
	safe_name,
	upsert_safe,
)


def sync_suppliers() -> dict:
	response = call_api("masterdata_supplier")
	rows = response.get("data-supplier") or []

	created = updated = failed = 0
	for row in rows:
		branch = get_or_create_branch(row.get("kodecabang"), row.get("namacabang"))
		values = {
			"supplier_name": safe_name(row.get("nama")),
			"supplier_details": clean(row.get("alamat")),
			"mobile_no": clean_phone(row.get("nohp")),
			"tax_id": clean_or_none(row.get("npwp")),
			"disabled": 0 if as_bool(row.get("aktif")) else 1,
			"email_id": clean_email(row.get("email")),
			"custom_otobitz_branch_code": branch,
		}
		values = {k: v for k, v in values.items() if v is not None or k == "disabled"}

		_, was_created, was_updated, was_failed = upsert_safe(
			"Supplier",
			{"custom_otobitz_supplier_no": clean(row.get("nomor"))},
			values,
		)
		created += was_created
		updated += was_updated
		failed += was_failed

	return {"fetched": len(rows), "created": created, "updated": updated, "failed": failed}


def sync_vendors() -> dict:
	response = call_api("masterdata_vendor")
	rows = response.get("data-vendor") or []

	created = updated = failed = 0
	for row in rows:
		values = {
			"supplier_name": safe_name(row.get("nama")),
			"tax_id": clean_or_none(row.get("npwp")),
			"disabled": 0 if as_bool(row.get("aktif")) else 1,
		}
		values = {k: v for k, v in values.items() if v is not None or k == "disabled"}

		_, was_created, was_updated, was_failed = upsert_safe(
			"Supplier",
			{"custom_otobitz_vendor_code": clean(row.get("kode"))},
			values,
		)
		created += was_created
		updated += was_updated
		failed += was_failed

	return {"fetched": len(rows), "created": created, "updated": updated, "failed": failed}
