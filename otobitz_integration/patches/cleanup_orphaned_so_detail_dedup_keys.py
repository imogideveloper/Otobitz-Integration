import frappe


def execute():
	"""log_so_detail_rows()'s dedup key for an item row changed from
	`nomorwo + kodereferensi` to `nomorwo + nofaktur + kodereferensi` (see
	that function's own docstring in sync/common.py) - an item code is only
	distinct per invoice ATTEMPT, not per Work Order, confirmed live on
	SO-302-261100180's cancelled-then-reissued invoice pair sharing 4 item
	codes between them.

	That key change left every already-archived row keyed under the OLD
	2-part format orphaned: nothing re-matches it by the new key, so the
	next sync just inserts a fresh 3-part-keyed row alongside it instead of
	replacing it in place. Confirmed live: get_wo_summary() (which joins
	every row sharing a nomorwo, old and new keys alike, into one Work
	Order view) started showing each shared item code 2-3x over the moment
	production re-synced - the exact "why is this doubled" report that
	caught this.

	Deletes an old-format row only where a new-format sibling for the same
	(nomorwo, kodereferensi) already exists to replace it - never the only
	copy of an item a WO still has (that one's still correct, just not yet
	re-synced under the new key, and will update in place next time it is).
	Safe to re-run: a second pass finds nothing left to match and deletes
	nothing."""
	frappe.db.sql(
		"""
		delete old from `tabOtoBitz SO Detail` old
		where old.kodereferensi is not null and old.kodereferensi != ''
			and old.dedup_key = concat(old.nomorwo, '|', old.kodereferensi)
			and exists (
				select 1 from `tabOtoBitz SO Detail` newrow
				where newrow.nomorwo = old.nomorwo
					and newrow.kodereferensi = old.kodereferensi
					and newrow.dedup_key != old.dedup_key
			)
		"""
	)
	removed = frappe.db.sql("select row_count()")[0][0]
	frappe.db.commit()
	frappe.logger("otobitz_integration").info(f"cleanup_orphaned_so_detail_dedup_keys: removed {removed} orphaned rows")
