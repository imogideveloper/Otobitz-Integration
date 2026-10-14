# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class OtoBitzSettings(Document):
	def get_base_url(self) -> str:
		return (self.base_url or "").rstrip("/")

	@frappe.whitelist()
	def sync_now(self):
		frappe.only_for("System Manager")

		from otobitz_integration.otobitz_integration.sync.orchestrator import run_hourly_sync

		if frappe.conf.developer_mode:
			run_hourly_sync()
		else:
			frappe.enqueue(
				"otobitz_integration.otobitz_integration.sync.orchestrator.run_hourly_sync",
				queue="long",
				timeout=3600,
				job_id="otobitz_hourly_sync",
				deduplicate=True,
			)
			frappe.msgprint(frappe._("Sync has been queued."))

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
