# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""Manual retry for the "OtoBitz Failed Sync" queue (see log_failed_sync()/
resolve_failed_sync() in common.py).

Every per-record sync function across the sync_*.py modules follows the same
shape - `_sync_one_x(record_key: str, raw_data) -> bool` - so retrying a
queued failure is just calling the same function again with the raw_data
that was stored when it failed, instead of re-fetching from the OtoBitz API
(which may not even return this record again once it's rolled out of the
sync's own rolling date window). This reuses those *exact* functions rather
than duplicating their logic, so a retry behaves identically to how the
record would have been synced the first time around.
"""

import json

import frappe

from otobitz_integration.otobitz_integration.sync.common import log_failed_sync, resolve_failed_sync
from otobitz_integration.otobitz_integration.sync.sync_booking import _sync_one_booking
from otobitz_integration.otobitz_integration.sync.sync_orderparts import _sync_one_order as _sync_one_orderpart
from otobitz_integration.otobitz_integration.sync.sync_orderpekerjaanluar import (
	_sync_one_order as _sync_one_orderpekerjaanluar,
)
from otobitz_integration.otobitz_integration.sync.sync_pengeluaran import _sync_one_expense
from otobitz_integration.otobitz_integration.sync.sync_penerimaan import _sync_one_receipt
from otobitz_integration.otobitz_integration.sync.sync_service_orders import _sync_one_wo

# endpoint -> the per-record sync function to call again with the queued
# raw_data. sync_service_orders is the only one keyed on a list of line-item
# rows (one Work Order can have many); every other endpoint is one row per
# record - same distinction the original sync loops make.
_DISPATCH = {
	"otoxpertsoandpart": _sync_one_wo,
	"penerimaanuang": _sync_one_receipt,
	"pengeluaranuang": _sync_one_expense,
	"penerimaanuangmukabooking": _sync_one_booking,
	"masterdata_orderparts": _sync_one_orderpart,
	"masterdata_orderpekerjaanluar": _sync_one_orderpekerjaanluar,
}


@frappe.whitelist()
def retry_failed_syncs(names) -> dict:
	"""Bulk-retry one or more "OtoBitz Failed Sync" rows (by name). Returns a
	per-row outcome so the caller (the List View bulk action) can report
	exactly what happened rather than a single pass/fail for the whole
	batch - one bad row in a multi-select shouldn't hide whether the others
	actually went through."""
	frappe.only_for("System Manager")

	if isinstance(names, str):
		names = json.loads(names)

	results = []
	for name in names:
		doc = frappe.get_doc("OtoBitz Failed Sync", name)
		sync_fn = _DISPATCH.get(doc.endpoint)
		if not sync_fn:
			results.append({"name": name, "record_key": doc.record_key, "ok": False, "message": f"Gak ada handler retry buat endpoint {doc.endpoint!r}"})
			continue

		raw_data = json.loads(doc.raw_data)
		try:
			sync_fn(doc.record_key, raw_data)
			frappe.db.commit()
			resolve_failed_sync(doc.endpoint, doc.record_key)
			frappe.db.commit()
			results.append({"name": name, "record_key": doc.record_key, "ok": True, "message": "Berhasil"})
		except Exception as exc:
			frappe.db.rollback()
			log_failed_sync(doc.endpoint, doc.record_key, str(exc), raw_data)
			frappe.db.commit()
			results.append({"name": name, "record_key": doc.record_key, "ok": False, "message": str(exc)})

	return {
		"total": len(results),
		"succeeded": sum(1 for r in results if r["ok"]),
		"failed": sum(1 for r in results if not r["ok"]),
		"results": results,
	}
