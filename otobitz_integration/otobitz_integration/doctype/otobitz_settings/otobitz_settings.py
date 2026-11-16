# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class OtoBitzSettings(Document):
	def get_base_url(self) -> str:
		return (self.base_url or "").rstrip("/")

	@frappe.whitelist()
	def sync_now(self):
		"""Always enqueued, developer_mode or not - this can easily run past
		gunicorn's worker timeout (120s, see Procfile), which would
		otherwise SIGKILL the request mid-sync with zero progress saved and
		no real error surfaced to the browser (confirmed live: the worker
		log showed "Worker was sent SIGKILL! Perhaps out of memory?" - not
		OOM at all, just gunicorn's own timeout, while the frontend saw
		nothing but a silently-reset request). A `bench execute` call is
		unaffected (no gunicorn involved), which is why this only ever
		showed up when triggered from the Desk button."""
		frappe.only_for("System Manager")

		frappe.enqueue(
			"otobitz_integration.otobitz_integration.sync.orchestrator.run_hourly_sync",
			queue="long",
			timeout=3600,
			job_id="otobitz_hourly_sync",
			deduplicate=True,
		)
		frappe.msgprint(frappe._("Sync has been queued."))

	@frappe.whitelist()
	def sync_from_date(self):
		"""Manually re-covers a date range whose data might be incomplete -
		e.g. the live OtoBitz endpoint having been down for a day or two -
		by rewinding just the date-windowed syncs' watermarks back to
		manual_sync_from_date and re-running them right now, instead of
		waiting for the hourly job's own small overlap window to eventually
		close the gap on its own. See orchestrator.run_manual_sync_from_date().

		Always enqueued, developer_mode or not - see sync_now()'s docstring
		for why running this synchronously in a Desk request is unsafe
		(gunicorn's 120s worker timeout kills it mid-sync with nothing
		surfaced to the browser)."""
		frappe.only_for("System Manager")

		if not self.manual_sync_from_date:
			frappe.throw(frappe._("Pick a date first."))

		frappe.enqueue(
			"otobitz_integration.otobitz_integration.sync.orchestrator.run_manual_sync_from_date",
			queue="long",
			timeout=3600,
			job_id="otobitz_manual_sync",
			deduplicate=True,
			from_date=self.manual_sync_from_date,
			to_date=self.manual_sync_to_date,
		)
		frappe.msgprint(frappe._("Manual sync has been queued."))

	@frappe.whitelist()
	def fix_customer_names(self):
		"""Re-resolves OtoBitz Customers' names against datacustomerbynumber
		again and propagates the fix onto already-created Sales Order/Sales
		Invoice documents too - see sync_service_orders.backfill_customer_
		names()'s own docstring for why this is ever needed in the first
		place (not every datacustomerbynumber lookup succeeds even with
		retries, under a sustained rate limit - a Customer created at
		exactly the wrong moment is stuck with its scrambled name until
		this runs again). Safe to run anytime; already-correct names just
		cost a no-op lookup each.

		Only re-checks customers whose name actually looks scrambled
		(contains a digit - see backfill_customer_names()'s only_suspicious
		default) instead of paying for one API call per OtoBitz customer
		regardless of whether anything is wrong with it - a handful of
		calls instead of ~970+.

		Always enqueued, developer_mode or not - same reasoning as
		sync_now()'s docstring."""
		frappe.only_for("System Manager")

		frappe.enqueue(
			"otobitz_integration.otobitz_integration.sync.sync_service_orders.backfill_customer_names",
			queue="long",
			timeout=3600,
			job_id="otobitz_fix_customer_names",
			deduplicate=True,
		)
		frappe.msgprint(frappe._("Fixing customer names has been queued."))

	@frappe.whitelist()
	def fix_customer_names_for_date(self):
		"""Scoped version of fix_customer_names(): only re-checks customers
		who actually appear on a Sales Order/Sales Invoice within Dari
		Tanggal..Sampai Tanggal, instead of sweeping every OtoBitz customer -
		for when an admin already knows which day had the problem (noticed
		in the Desk) and wants it fixed right now. See
		sync_service_orders.backfill_customer_names_for_dates()'s own
		docstring.

		Always enqueued, developer_mode or not - same reasoning as
		sync_now()'s docstring."""
		frappe.only_for("System Manager")

		if not self.fix_customer_names_from_date:
			frappe.throw(frappe._("Pick a date first."))

		frappe.enqueue(
			"otobitz_integration.otobitz_integration.sync.sync_service_orders.backfill_customer_names_for_dates",
			queue="long",
			timeout=3600,
			job_id="otobitz_fix_customer_names_for_date",
			deduplicate=True,
			from_date=self.fix_customer_names_from_date,
			to_date=self.fix_customer_names_to_date,
		)
		frappe.msgprint(frappe._("Fixing customer names for that date range has been queued."))

	@frappe.whitelist()
	def lookup_wo(self):
		"""Looks up and syncs whatever's currently in `lookup_wo_number` via
		`otoxpertsoandpartpernomor`, right now - see
		sync_service_orders.lookup_and_sync_wo() for why this reuses the same
		per-WO sync logic as the hourly batch instead of its own copy."""
		frappe.only_for("System Manager")

		from otobitz_integration.otobitz_integration.sync.sync_service_orders import lookup_and_sync_wo

		return lookup_and_sync_wo(self.lookup_wo_number)

	@frappe.whitelist()
	def get_dashboard_summary(self):
		"""Counts shown on the Settings form's "Ringkasan OtoBitz" section,
		so admins can eyeball sync health without opening each list."""
		frappe.only_for("System Manager")

		from frappe.utils import add_days, now_datetime

		since = add_days(now_datetime(), -7)
		sync_counts = dict(
			frappe.db.sql(
				"""select status, count(*) from `tabOtoBitz Sync Log`
				where creation >= %s group by status""",
				since,
			)
		)
		return {
			"vehicle_category_active": frappe.db.count("OtoBitz Vehicle Category", {"aktif": 1}),
			"vehicle_type_active": frappe.db.count("OtoBitz Vehicle Type", {"aktif": 1}),
			"vehicle_color_active": frappe.db.count("OtoBitz Vehicle Color", {"aktif": 1}),
			"service_menu_active": frappe.db.count("OtoBitz Service Menu", {"aktif": 1}),
			"vehicle_total": frappe.db.count("OtoBitz Vehicle"),
			"sync_success_7d": sync_counts.get("Success", 0),
			"sync_partial_7d": sync_counts.get("Partial", 0),
			"sync_failed_7d": sync_counts.get("Failed", 0),
		}
