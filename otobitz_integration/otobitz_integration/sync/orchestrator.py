# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""Runs every in-scope Phase 1 sync function, in dependency order, logging one
`OtoBitz Sync Log` row per endpoint. A failure in one endpoint is caught and
logged - it never aborts the rest of the batch (28 unrelated data sources have
no business failing together because one of them had a bad day).

`masterdata_customerpage` (sync_customers.py) is deliberately NOT in
SYNC_STEPS: that endpoint has no date filter at all - every call returns the
full 80k+ customer list (confirmed live), so running it hourly means paying
that full-table cost forever, not just once. sync_service_orders.py now
get-or-creates customers directly from otoxpertsoandpart's own embedded
customer fields instead, so only customers who actually show up on a Work
Order in the sync window get created - "current activity", not full history.
sync_customers() is still there if a full one-off catalog sync is ever
genuinely needed; it's just not automatic.
"""

import functools
import time

import frappe
from frappe.utils import getdate, nowdate, now_datetime

from otobitz_integration.otobitz_integration.api.client import OtoBitzAPIError
from otobitz_integration.otobitz_integration.sync.common import acquire_sync_lock, release_sync_lock, renew_sync_lock
from otobitz_integration.otobitz_integration.sync.sync_booking import sync_booking
from otobitz_integration.otobitz_integration.sync.sync_cogsparts import sync_cogsparts
from otobitz_integration.otobitz_integration.sync.sync_orderparts import sync_orderparts
from otobitz_integration.otobitz_integration.sync.sync_orderpekerjaanluar import sync_orderpekerjaanluar
from otobitz_integration.otobitz_integration.sync.sync_oppnt import sync_oppnt
from otobitz_integration.otobitz_integration.sync.sync_payment_modes import sync_payment_modes
from otobitz_integration.otobitz_integration.sync.sync_penerimaan import sync_penerimaan
from otobitz_integration.otobitz_integration.sync.sync_pengeluaran import sync_pengeluaran
from otobitz_integration.otobitz_integration.sync.sync_service_menu import sync_service_menu
from otobitz_integration.otobitz_integration.sync.sync_service_orders import sync_service_orders
from otobitz_integration.otobitz_integration.sync.sync_services import sync_jasaservice, sync_pekerjaanluar
from otobitz_integration.otobitz_integration.sync.sync_spareparts import sync_spareparts
from otobitz_integration.otobitz_integration.sync.sync_suppliers import sync_suppliers, sync_vendors
from otobitz_integration.otobitz_integration.sync.sync_teknisi import sync_teknisi
from otobitz_integration.otobitz_integration.sync.sync_vehicle_masters import (
	sync_vehicle_categories,
	sync_vehicle_colors,
	sync_vehicle_types,
)

# Dependency order matters: vehicle categories before types (Link field), and
# vehicle types/colors before customers (customer rows link to them).
SYNC_STEPS = [
	("masterdata_kategorikendaraan", sync_vehicle_categories),
	("masterdata_tipekendaraan", sync_vehicle_types),
	("masterdata_warna", sync_vehicle_colors),
	("masterdata_supplier", sync_suppliers),
	("masterdata_vendor", sync_vendors),
	("masterdata_sparepart", sync_spareparts),
	("masterdata_jasaservice", sync_jasaservice),
	("masterdata_pekerjaanluar", sync_pekerjaanluar),
	("masterdata_paymentmetode", sync_payment_modes),
	("masterdata_teknisi", sync_teknisi),
	("masterdata_servicemenu", sync_service_menu),
	("otoxpertsoandpart", sync_service_orders),
	("penerimaanuang", sync_penerimaan),
	("pengeluaranuang", sync_pengeluaran),
	("penerimaanuangmukabooking", sync_booking),
	("masterdata_orderparts", sync_orderparts),
	("masterdata_orderpekerjaanluar", sync_orderpekerjaanluar),
	("masterdata_oppnt", sync_oppnt),
	("cogsparts", sync_cogsparts),
]

# The subset of SYNC_STEPS that's actually date-windowed (reads/advances its
# own watermark via get_sync_window() in its module) - everything else above
# (vehicle masters, suppliers, spareparts, ...) has no date filter at all, so
# "re-sync from a date" is meaningless for those. Paired with each step's own
# OtoBitz Settings watermark field, so run_manual_sync_from_date() below can
# rewind just these before re-running them.
DATE_WINDOWED_STEPS = [
	("otoxpertsoandpart", sync_service_orders, "last_so_sync_date"),
	("penerimaanuang", sync_penerimaan, "last_penerimaan_sync_date"),
	("pengeluaranuang", sync_pengeluaran, "last_pengeluaran_sync_date"),
	("penerimaanuangmukabooking", sync_booking, "last_booking_sync_date"),
	("masterdata_orderparts", sync_orderparts, "last_orderparts_sync_date"),
	("masterdata_orderpekerjaanluar", sync_orderpekerjaanluar, "last_orderpekerjaanluar_sync_date"),
	("masterdata_oppnt", sync_oppnt, "last_oppnt_sync_date"),
]


def trigger_scheduled_sync():
	"""Scheduler entrypoint for hooks.py's scheduler_events["cron"] (fires
	every 15 minutes). Only actually triggers a sync once per hour listed in
	OtoBitz Settings' "Jam Sync" - the gap between configured hours is the
	rest period the OtoBitz server needs (confirmed: hitting it nonstop with
	no gap at all is what was causing it to work too hard and throw 504s),
	while still syncing same-day (H+0) instead of the once-a-day/next-day
	pattern the other system on this same API uses.

	Checking every 15 minutes rather than scheduling each hour as its own
	separate cron line keeps the actual run times adjustable from the Desk
	(OtoBitz Settings) with no code change or restart - editing "Jam Sync"
	takes effect on the very next 15-minute check."""
	settings = frappe.get_single("OtoBitz Settings")
	if not settings.enabled:
		return

	configured_hours = {
		int(h.strip()) for h in (settings.sync_hours or "").split(",") if h.strip().isdigit()
	}
	now = now_datetime()
	if now.hour not in configured_hours:
		return

	# one slot per calendar hour - without this, the 15-minute checker would
	# re-trigger up to 4 times during the same configured hour
	hour_key = now.strftime("%Y-%m-%d-%H")
	if settings.last_sync_trigger_hour_key == hour_key:
		return

	frappe.db.set_single_value("OtoBitz Settings", "last_sync_trigger_hour_key", hour_key)
	frappe.db.commit()
	trigger_hourly_sync()


def trigger_hourly_sync():
	"""Enqueues run_hourly_sync with an explicit timeout instead of letting it
	run directly under whatever default timeout Frappe's scheduler assigns
	the "long" queue (1500s) - real OtoBitz endpoints (otoxpertsoandpart in
	particular) can take longer than that when the upstream API is slow, and
	now that _run_all_steps() also sleeps between endpoints for the cooldown
	above, a full run legitimately takes even longer.
	Shares job_id with sync_now()'s manual enqueue so the two can't overlap."""
	frappe.enqueue(
		"otobitz_integration.otobitz_integration.sync.orchestrator.run_hourly_sync",
		queue="long",
		timeout=3600,
		job_id="otobitz_hourly_sync",
		deduplicate=True,
	)


def run_hourly_sync():
	if not acquire_sync_lock():
		frappe.logger("otobitz_integration").info("Hourly sync already in progress, skipping this tick.")
		return

	try:
		_run_all_steps()
	finally:
		release_sync_lock()


def run_manual_sync_from_date(from_date, to_date=None):
	"""Runs the 6 date-windowed steps for an EXACT date range an admin
	picked - from_date..(to_date or today) - bypassing each module's own
	watermark/overlap-days logic entirely via the date_range param every
	sync_X() function now accepts (see each module's own signature).
	Deliberately does NOT touch any watermark: this is a bounded, re-runnable
	probe of a specific date (e.g. "did OtoBitz actually have WO data for
	2026-11-06"), not a way to advance the real incremental position - an
	earlier version rewound watermarks instead, which both pulled in an
	unwanted extra few days from each module's own OVERLAP_DAYS and had a
	bug where an all-time-unset watermark (reads back as the sentinel
	0001-01-01, not None) silently failed to rewind at all, falling through
	to "first day of the current month" instead of the requested date.

	For exactly the scenario this was built for: the live OtoBitz endpoint
	going down for a day or two (confirmed to happen - see
	otoxpertsoandpartnondecrypt's own fallback in OtoBitz Settings) leaves a
	gap; this lets an admin pick the exact date(s) and check/re-pull them
	right now, from the Desk, no code/restart needed."""
	if not acquire_sync_lock():
		frappe.throw(frappe._("A sync is already in progress - try again once it finishes."))

	try:
		date_range = (str(getdate(from_date)), str(getdate(to_date)) if to_date else nowdate())
		steps = [
			(endpoint, functools.partial(sync_fn, date_range=date_range))
			for endpoint, sync_fn, _ in DATE_WINDOWED_STEPS
		]
		_run_all_steps(steps)
	finally:
		release_sync_lock()


def _run_all_steps(steps=None):
	steps = SYNC_STEPS if steps is None else steps
	settings = frappe.get_single("OtoBitz Settings")
	heavy_endpoints = {e.strip() for e in (settings.heavy_endpoints or "").split(",") if e.strip()}
	heavy_cooldown = settings.heavy_endpoint_cooldown_seconds or 150
	light_cooldown = settings.light_endpoint_cooldown_seconds or 20

	overall_status = "Success"
	problem_logs = []

	for step_index, (endpoint, sync_fn) in enumerate(steps):
		renew_sync_lock()
		started_at = now_datetime()
		log = frappe.new_doc("OtoBitz Sync Log")
		log.endpoint = endpoint
		log.started_at = started_at

		try:
			result = sync_fn()
			log.records_fetched = result.get("fetched", 0)
			log.records_created = result.get("created", 0)
			log.records_updated = result.get("updated", 0)
			log.records_failed = result.get("failed", 0)
			if log.records_failed:
				log.status = "Partial"
				overall_status = "Partial"
			else:
				log.status = "Success"
		except OtoBitzAPIError as exc:
			frappe.db.rollback()
			log.status = "Failed"
			log.traceback = str(exc)
			overall_status = "Partial"
		except Exception:
			frappe.db.rollback()
			log.status = "Failed"
			log.traceback = frappe.get_traceback()
			overall_status = "Partial"

		log.ended_at = now_datetime()
		log.insert(ignore_permissions=True)
		frappe.db.commit()

		if log.status != "Success":
			problem_logs.append(log)

		# rest between endpoints instead of hammering OtoBitz back-to-back -
		# longer after a heavy/rate-sensitive endpoint, shorter otherwise.
		# Skipped after the last step - nothing left to protect by then.
		if step_index < len(steps) - 1:
			cooldown = heavy_cooldown if endpoint in heavy_endpoints else light_cooldown
			time.sleep(cooldown)
			renew_sync_lock()

	frappe.db.set_single_value(
		"OtoBitz Settings",
		{"last_sync_status": overall_status, "last_synced_on": now_datetime()},
		update_modified=False,
	)
	frappe.db.commit()

	if problem_logs:
		_notify_failures(problem_logs)


def _notify_failures(problem_logs: list) -> None:
	"""Email System Manager users a summary when a run finishes with any
	Partial/Failed endpoint, instead of that only being visible to whoever
	happens to open OtoBitz Sync Log."""
	recipients = frappe.get_all(
		"Has Role",
		filters={"role": "System Manager", "parenttype": "User"},
		pluck="parent",
	)
	recipients = frappe.get_all(
		"User",
		filters={"name": ["in", recipients], "enabled": 1, "user_type": "System User"},
		pluck="email",
	)
	if not recipients:
		return

	rows = "".join(
		f"<tr><td>{log.endpoint}</td><td>{log.status}</td>"
		f"<td>{log.records_failed}</td><td>{(log.traceback or '')[:200]}</td></tr>"
		for log in problem_logs
	)
	message = f"""
		<p>The hourly OtoBitz sync finished with {len(problem_logs)} endpoint(s)
		not fully successful:</p>
		<table border="1" cellpadding="4" style="border-collapse: collapse;">
			<tr><th>Endpoint</th><th>Status</th><th>Records Failed</th><th>Error</th></tr>
			{rows}
		</table>
		<p>See the OtoBitz Sync Log list in the Desk for full details.</p>
	"""

	try:
		frappe.sendmail(
			recipients=recipients,
			subject=f"OtoBitz sync: {len(problem_logs)} endpoint(s) had issues",
			message=message,
			now=True,
		)
	except Exception:
		frappe.log_error(title="OtoBitz sync: failed to send failure notification email")
