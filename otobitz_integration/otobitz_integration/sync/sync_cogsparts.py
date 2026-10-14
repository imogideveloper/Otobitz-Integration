# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""cogsparts -> Item.custom_otobitz_last_cogs.

Not date-windowed like the rest of this integration - this endpoint takes a
single `periode` (YYYYMM), not tanggalawal/tanggalakhir, and returns one COGS
figure per part per branch for that whole month. Always fetched for the
*current* month (recomputed fresh each run, same "current activity" spirit
as everything else here) - last-branch-seen wins per part, the same
simplification sync_spareparts.py already makes for cross-branch pricing.

A part the response mentions that doesn't exist in our Item catalog yet is
skipped, not created - this is a pure valuation refresh, not a source of
truth for which parts exist (masterdata_sparepart already owns that).
"""

import frappe
from frappe.utils import flt, nowdate

from otobitz_integration.otobitz_integration.api.client import call_api
from otobitz_integration.otobitz_integration.sync.common import clean


def _current_periode() -> str:
	return nowdate()[:7].replace("-", "")


def sync_cogsparts() -> dict:
	periode = _current_periode()
	response = call_api("cogsparts", {"periode": periode})
	rows = response.get("data-cogsparts") or []

	created = updated = failed = 0
	seen = {}
	for row in rows:
		item_code = clean(row.get("kodepart"))
		if not item_code:
			continue
		seen[item_code] = flt(row.get("cogsstd"))

	for item_code, cogs in seen.items():
		if not frappe.db.exists("Item", item_code):
			continue
		try:
			current = frappe.db.get_value("Item", item_code, "custom_otobitz_last_cogs")
			if flt(current) != cogs:
				frappe.db.set_value("Item", item_code, "custom_otobitz_last_cogs", cogs, update_modified=False)
				updated += 1
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"OtoBitz sync: failed to update COGS for {item_code}")
			failed += 1

	return {"fetched": len(rows), "created": created, "updated": updated, "failed": failed}
