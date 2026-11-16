# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""Compares what otoxpertsoandpart actually fetched from OtoBitz - every
line item lands in "OtoBitz SO Detail" via log_so_detail_rows() regardless
of whether its Work Order later became a real Sales Order - against how
many of those Work Orders actually turned into a Sales Order here. Exists
because of a real incident: a chunk-level API failure (the upstream server
timing out with zero bytes back, not a handled error) silently left ~1350
Work Orders from 1-18 Oct never created, and nobody noticed until someone
happened to compare totals against the source Odoo system by hand. This is
the automated version of that same comparison, so a future gap like that
one surfaces within a day instead of whenever someone next checks by hand.

get_reconciliation_rows() backs both "OtoBitz Sync Reconciliation" (the
report a human can run anytime) and daily_reconciliation_check() (the
scheduled watchdog that emails System Managers) - one query, two
consumers, so they can't drift out of sync with each other."""

import frappe
from frappe.utils import add_days, cint, flt, nowdate

from otobitz_integration.otobitz_integration.sync.notifications import (
	TONE_INFO,
	TONE_WARNING,
	email_wrapper,
	failed_sync_breakdown_html,
	get_failed_sync_grouped,
	section_heading,
	stat_strip,
)

GAP_ALERT_THRESHOLD = 5
LOOKBACK_DAYS = 7


def get_reconciliation_rows(from_date, to_date):
	fetched_rows = frappe.db.sql(
		"""
		SELECT DATE(tanggal) AS d, COUNT(DISTINCT nomorwo) AS cnt
		FROM `tabOtoBitz SO Detail`
		WHERE tanggal BETWEEN %s AND %s
		GROUP BY DATE(tanggal)
		""",
		(from_date, to_date),
		as_dict=True,
	)
	fetched_map = {r.d: r.cnt for r in fetched_rows}

	created_rows = frappe.db.sql(
		"""
		SELECT DATE(transaction_date) AS d, COUNT(DISTINCT custom_otobitz_wo_number) AS cnt
		FROM `tabSales Order`
		WHERE transaction_date BETWEEN %s AND %s
			AND custom_otobitz_wo_number IS NOT NULL AND custom_otobitz_wo_number != ''
		GROUP BY DATE(transaction_date)
		""",
		(from_date, to_date),
		as_dict=True,
	)
	created_map = {r.d: r.cnt for r in created_rows}

	rows = []
	for d in sorted(set(fetched_map) | set(created_map)):
		fetched = fetched_map.get(d, 0)
		created = created_map.get(d, 0)
		rows.append({"date": d, "fetched": fetched, "created": created, "gap": fetched - created})
	return rows


def daily_reconciliation_check():
	"""scheduler_events["daily"] entrypoint. Checks the last LOOKBACK_DAYS
	days ending yesterday (today's own data is still incomplete, so it's
	excluded to avoid a false-positive "gap" every single day)."""
	to_date = add_days(nowdate(), -1)
	from_date = add_days(to_date, -LOOKBACK_DAYS)
	rows = get_reconciliation_rows(from_date, to_date)
	problem_rows = [r for r in rows if r["gap"] > GAP_ALERT_THRESHOLD]
	if not problem_rows:
		return

	recipients = frappe.get_all("Has Role", filters={"role": "System Manager", "parenttype": "User"}, pluck="parent")
	recipients = frappe.get_all(
		"User", filters={"name": ["in", recipients], "enabled": 1, "user_type": "System User"}, pluck="email"
	)
	if not recipients:
		return

	table_rows = "".join(
		f"""<tr>
			<td style="padding:8px 10px 8px 0;border-bottom:1px solid #edf2f7;color:#1e293b;font-weight:600;">{r['date']}</td>
			<td style="padding:8px 10px;border-bottom:1px solid #edf2f7;text-align:right;color:#64748b;">{r['fetched']}</td>
			<td style="padding:8px 10px;border-bottom:1px solid #edf2f7;text-align:right;color:#64748b;">{r['created']}</td>
			<td style="padding:8px 0 8px 10px;border-bottom:1px solid #edf2f7;text-align:right;font-weight:700;color:#b45309;">{r['gap']}</td>
		</tr>"""
		for r in problem_rows
	)
	total_gap = sum(flt(r["gap"]) for r in problem_rows)
	stats_html = stat_strip(
		[
			(str(len(problem_rows)), "Hari Bermasalah", TONE_WARNING),
			(str(int(total_gap)), "Total Selisih WO", TONE_WARNING),
		]
	)
	body = f"""
		<p style="margin:0 0 16px;">Rekonsiliasi harian <b>otoxpertsoandpart</b> menemukan selisih antara
		Work Order yang di-fetch dari OtoBitz dan Sales Order yang benar-benar terbuat di sini
		(selisih lebih dari {GAP_ALERT_THRESHOLD} per hari).</p>
		{stats_html}
		{section_heading("Rincian per Hari")}
		<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="font-size:12.5px;">
			<tr style="color:#94a3b8;text-align:left;">
				<th style="padding:0 10px 8px 0;font-weight:600;">Tanggal</th>
				<th style="padding:0 10px 8px;text-align:right;font-weight:600;">WO di-fetch</th>
				<th style="padding:0 10px 8px;text-align:right;font-weight:600;">SO dibuat</th>
				<th style="padding:0 0 8px 10px;text-align:right;font-weight:600;">Selisih</th>
			</tr>
			{table_rows}
		</table>
		<p style="color:#94a3b8;font-size:11.5px;margin-top:20px;">
			Cek report &ldquo;OtoBitz Sync Reconciliation&rdquo; dan list &ldquo;OtoBitz Failed Sync&rdquo; untuk detail.
		</p>
	"""
	message = email_wrapper(
		title="OtoBitz Sync - Selisih Data Harian",
		subtitle=f"{len(problem_rows)} hari dalam {LOOKBACK_DAYS} hari terakhir",
		tone=TONE_WARNING,
		body_html=body,
	)
	try:
		frappe.sendmail(
			recipients=recipients,
			subject=f"OtoBitz sync: {len(problem_rows)} hari dengan selisih data signifikan",
			message=message,
			now=True,
		)
	except Exception:
		frappe.log_error(title="OtoBitz reconciliation: failed to send alert email")


def daily_failed_sync_digest():
	"""scheduler_events["daily"] entrypoint - a once-a-day rollup of whatever
	landed in "OtoBitz Failed Sync" in the last 24h, grouped by category.

	Deliberately separate from daily_reconciliation_check() above even
	though both run daily and both email System Managers: that one flags a
	WO-vs-Sales-Order COUNT gap (missing documents), this one flags
	per-record data/validation errors that log_failed_sync() already caught
	and retried from - documents that exist, just didn't sync cleanly. A
	bad run on one doesn't imply anything about the other. Silently skips
	the email entirely on a clean day (nothing in the queue) rather than
	sending an empty "0 errors" email every single day.

	Gated by the same "Aktifkan Alert API Down" toggle as the orchestrator's
	down-streak alert - one on/off switch for every OtoBitz error email,
	rather than a second setting nobody remembers to also flip."""
	if not cint(frappe.db.get_single_value("OtoBitz Settings", "enable_down_alert")):
		return

	since = add_days(frappe.utils.now_datetime(), -1)
	grouped = get_failed_sync_grouped(since)
	if not grouped:
		return

	recipients = frappe.get_all("Has Role", filters={"role": "System Manager", "parenttype": "User"}, pluck="parent")
	recipients = frappe.get_all(
		"User", filters={"name": ["in", recipients], "enabled": 1, "user_type": "System User"}, pluck="email"
	)
	if not recipients:
		return

	total = int(sum(r["cnt"] for r in grouped))
	stats_html = stat_strip(
		[
			(str(total), "Total Record", TONE_INFO),
			(str(len(grouped)), "Kategori", TONE_INFO),
		]
	)
	body = f"""
		<p style="margin:0 0 16px;">Rekap 24 jam terakhir: record yang gagal sync dan masuk
		ke antrian retry &ldquo;OtoBitz Failed Sync&rdquo;, dikelompokkan per jenis error di bawah.</p>
		{stats_html}
		{failed_sync_breakdown_html(grouped)}
		<p style="color:#94a3b8;font-size:11.5px;margin-top:20px;">
			Semua record ini sudah otomatis dicoba retry di sync berikutnya - email ini cuma buat
			kelihatan polanya, gak perlu tindakan manual kecuali jumlahnya terus menumpuk.
		</p>
	"""
	message = email_wrapper(
		title="OtoBitz Sync - Rekap Error Harian",
		subtitle=f"{total} record &middot; {len(grouped)} kategori",
		tone=TONE_INFO,
		body_html=body,
	)
	try:
		frappe.sendmail(
			recipients=recipients,
			subject=f"OtoBitz sync: rekap {total} error harian ({len(grouped)} kategori)",
			message=message,
			now=True,
		)
	except Exception:
		frappe.log_error(title="OtoBitz: failed to send daily failed-sync digest email")
