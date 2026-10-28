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
from frappe.utils import add_days, nowdate

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
		f"<tr><td>{r['date']}</td><td>{r['fetched']}</td><td>{r['created']}</td><td>{r['gap']}</td></tr>"
		for r in problem_rows
	)
	message = f"""
		<p>Rekonsiliasi harian otoxpertsoandpart menemukan selisih antara Work Order
		yang di-fetch dari OtoBitz dan Sales Order yang benar-benar terbuat di sini
		(selisih lebih dari {GAP_ALERT_THRESHOLD} per hari):</p>
		<table border="1" cellpadding="4" style="border-collapse: collapse;">
			<tr><th>Tanggal</th><th>WO di-fetch</th><th>SO dibuat</th><th>Selisih</th></tr>
			{table_rows}
		</table>
		<p>Cek report "OtoBitz Sync Reconciliation" dan list "OtoBitz Failed Sync" untuk detail.</p>
	"""
	try:
		frappe.sendmail(
			recipients=recipients,
			subject=f"OtoBitz sync: {len(problem_rows)} hari dengan selisih data signifikan",
			message=message,
			now=True,
		)
	except Exception:
		frappe.log_error(title="OtoBitz reconciliation: failed to send alert email")
