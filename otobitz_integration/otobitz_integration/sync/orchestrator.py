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

import frappe
from frappe.utils import now_datetime

from otobitz_integration.otobitz_integration.api.client import OtoBitzAPIError
from otobitz_integration.otobitz_integration.sync.common import acquire_sync_lock, release_sync_lock, renew_sync_lock
from otobitz_integration.otobitz_integration.sync.sync_booking import sync_booking
from otobitz_integration.otobitz_integration.sync.sync_cogsparts import sync_cogsparts
from otobitz_integration.otobitz_integration.sync.sync_orderparts import sync_orderparts
from otobitz_integration.otobitz_integration.sync.sync_orderpekerjaanluar import sync_orderpekerjaanluar
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
	("cogsparts", sync_cogsparts),
]


def trigger_hourly_sync():
	"""Scheduler entrypoint for hooks.py's scheduler_events["hourly_long"].

	Enqueues run_hourly_sync with an explicit timeout instead of letting it
	run directly under whatever default timeout Frappe's scheduler assigns
	the "long" queue (1500s) - real OtoBitz endpoints (otoxpertsoandpart in
	particular) can take longer than that when the upstream API is slow.
	Shares job_id with sync_now()'s manual enqueue so the two can't overlap.
	"""
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


def _run_all_steps():
	overall_status = "Success"
	problem_logs = []

	for endpoint, sync_fn in SYNC_STEPS:
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
