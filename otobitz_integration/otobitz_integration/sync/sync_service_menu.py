# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""masterdata_servicemenu -> OtoBitz Service Menu (+ child table Detail rows).

The source `detail` rows repeat the parent's own `kode_regularcheck`/
`namaregular` on every row (identical to the parent's `kode`/`nama`), so those
two are dropped from the child table - keeping only the columns that actually
vary per detail row.
"""

import frappe
from frappe.utils import flt

from otobitz_integration.otobitz_integration.api.client import call_api
from otobitz_integration.otobitz_integration.sync.common import as_bool, clean


def sync_service_menu() -> dict:
	response = call_api("masterdata_servicemenu")
	rows = response.get("data-servicemenu") or []

	created = updated = failed = 0
	for row in rows:
		kode = clean(row.get("kode"))
		if not kode:
			continue

		try:
			is_new = _upsert_one(row, kode)
			# Commit per-row: frappe.db.rollback() in the except branch below
			# rolls back the *entire* open transaction, not just this row -
			# without committing successes as they happen, one bad row near
			# the end would wipe out every good row synced before it.
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"OtoBitz sync: failed to upsert OtoBitz Service Menu {kode}")
			failed += 1
			continue

		created += is_new
		updated += not is_new

	return {"fetched": len(rows), "created": created, "updated": updated, "failed": failed}


def _upsert_one(row: dict, kode: str) -> bool:
	"""Returns True if a new OtoBitz Service Menu was created, False if an
	existing one was updated."""
	detail_rows = [
		{
			"kode_model": clean(d.get("kode_model")),
			"namamodel": clean(d.get("namamodel")),
			"transmisi": clean(d.get("transmisi")),
			"kode_referensi": clean(d.get("kode_referensi")),
			"namaref": clean(d.get("namaref")),
			"jenis": clean(d.get("jenis")),
			"harga": flt(d.get("harga")),
			"qty": flt(d.get("qty")),
			"subtotal": flt(d.get("subtotal")),
		}
		for d in row.get("detail") or []
	]

	if frappe.db.exists("OtoBitz Service Menu", kode):
		doc = frappe.get_doc("OtoBitz Service Menu", kode)
		is_new = False
	else:
		doc = frappe.new_doc("OtoBitz Service Menu")
		doc.kode = kode
		is_new = True

	doc.nama = clean(row.get("nama")) or kode
	doc.jenis = clean(row.get("jenis"))
	doc.aktif = as_bool(row.get("aktif"))
	doc.set("detail", [])
	for detail_row in detail_rows:
		doc.append("detail", detail_row)

	if is_new:
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)

	return is_new
