# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""Shared HTML email styling + the OtoBitz Failed Sync category breakdown,
used by every OtoBitz alert email (orchestrator.py's API-down alert,
reconciliation.py's gap check and daily failed-sync digest) so they all look
and read the same way instead of each hand-rolling its own <table border="1">
markup.

Table-based layout throughout (not flex/div-positioning) and inline styles
only, no <style> block - the combination every major email client (Gmail,
Outlook, Apple Mail) renders most predictably. Colored banners/badges use a
SOFT tint background with a matching dark text color rather than a saturated
background with white text - the latter is the exact pattern Gmail's dark
mode most often mangles (it inverts light-on-dark text that was already
hand-picked for contrast, sometimes landing on white-on-white)."""

import frappe
from frappe.utils import flt

_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_MONO = "'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"

# (soft background, dark text) pairs - used for both the top banner and
# every badge/card accent so "danger" always reads as the same red
# everywhere, etc.
TONE_DANGER = ("#fef2f2", "#b91c1c")
TONE_WARNING = ("#fffbeb", "#b45309")
TONE_INFO = ("#f8fafc", "#475569")
TONE_PURPLE = ("#faf5ff", "#7e22ce")
TONE_TEAL = ("#f0fdfa", "#0f766e")

# One fixed tone per error_category - keeps the same category visually
# identical across every email instead of an arbitrary table row color.
_CATEGORY_TONES = {
	"Qty desimal ditolak oleh UOM": TONE_DANGER,
	"Mode of Payment belum ada akun Cash/Bank": TONE_WARNING,
	"Sales Invoice belum ada saat sync payment": TONE_PURPLE,
	"Belum ada Approval Setting untuk Cost Center": TONE_TEAL,
	"Race condition penomoran Series": TONE_INFO,
	"Item tidak bisa di-resolve dari WO": TONE_DANGER,
	"Customer tidak ditemukan berdasarkan nama": TONE_PURPLE,
	"Account tidak ditemukan/salah konfigurasi": TONE_WARNING,
	"Lainnya": TONE_INFO,
}


def _category_tone(category: str) -> tuple[str, str]:
	return _CATEGORY_TONES.get(category, TONE_INFO)


def email_wrapper(title: str, subtitle: str, tone: tuple[str, str], body_html: str, footer_note: str | None = None) -> str:
	"""Wraps `body_html` in the shared card layout every OtoBitz alert email
	uses: a soft-tinted banner (title + one-line subtitle), a white content
	card, and a muted footer - centered, max 600px, table-based."""
	bg, text = tone
	footer = footer_note or "Email otomatis dari OtoBitz Integration &middot; jangan dibalas."
	return f"""
	<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
	       style="background:#eef1f5;font-family:{_FONT};">
	  <tr>
	    <td align="center" style="padding:28px 12px;">
	      <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
	             style="width:600px;max-width:100%;background:#ffffff;border:1px solid #e2e8f0;
	                    border-radius:12px;overflow:hidden;">
	        <tr>
	          <td style="background:{bg};border-bottom:1px solid #e2e8f0;padding:20px 26px;">
	            <div style="color:{text};font-size:17px;font-weight:700;letter-spacing:-.01em;">{title}</div>
	            <div style="color:{text};font-size:13px;margin-top:4px;opacity:.85;">{subtitle}</div>
	          </td>
	        </tr>
	        <tr>
	          <td style="padding:24px 26px;color:#1e293b;font-size:13.5px;line-height:1.6;">
	            {body_html}
	          </td>
	        </tr>
	        <tr>
	          <td style="padding:14px 26px;background:#f8fafc;border-top:1px solid #edf2f7;
	                     color:#94a3b8;font-size:11px;">
	            {footer}
	          </td>
	        </tr>
	      </table>
	    </td>
	  </tr>
	</table>
	"""


def stat_strip(stats: list[tuple[str, str, tuple[str, str] | None]]) -> str:
	"""A row of big-number "at a glance" stat chips, e.g. [("3x", "Berturut-turut", TONE_DANGER), ...].
	`tone` may be None for a plain neutral chip."""
	cells = "".join(
		f"""<td width="{100 // len(stats)}%" style="padding:4px;">
			<div style="background:{(tone or TONE_INFO)[0]};border-radius:8px;padding:12px 8px;text-align:center;">
				<div style="color:{(tone or TONE_INFO)[1]};font-size:20px;font-weight:700;line-height:1.1;">{value}</div>
				<div style="color:{(tone or TONE_INFO)[1]};font-size:10.5px;margin-top:3px;opacity:.8;
				            text-transform:uppercase;letter-spacing:.03em;">{label}</div>
			</div>
		</td>"""
		for value, label, tone in stats
	)
	return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>{cells}</tr></table>'


def badge(text: str, tone: tuple[str, str]) -> str:
	bg, color = tone
	return (
		f'<span style="display:inline-block;padding:2px 9px;border-radius:999px;'
		f'font-size:11px;font-weight:700;color:{color};background:{bg};white-space:nowrap;">{text}</span>'
	)


def section_heading(text: str) -> str:
	return (
		f'<div style="font-size:11.5px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;'
		f'color:#94a3b8;margin:22px 0 10px;">{text}</div>'
	)


def get_failed_sync_grouped(since) -> list[dict]:
	"""OtoBitz Failed Sync rows with `last_attempt_at >= since`, grouped by
	error_category, newest activity first. One row per category with a
	count and one representative example message - the breakdown this
	powers is meant to answer "what KINDS of things are failing", not list
	every single record (that's what the Desk list view/Group By is for)."""
	rows = frappe.db.sql(
		"""
		select error_category, count(*) as cnt, max(last_attempt_at) as last_seen,
		       (select error_message from `tabOtoBitz Failed Sync` f2
		        where f2.error_category = f1.error_category and f2.last_attempt_at >= %(since)s
		        order by f2.last_attempt_at desc limit 1) as example_message
		from `tabOtoBitz Failed Sync` f1
		where last_attempt_at >= %(since)s
		group by error_category
		order by last_seen desc
		""",
		{"since": since},
		as_dict=True,
	)
	return rows


def failed_sync_breakdown_html(grouped_rows: list[dict]) -> str:
	"""Renders get_failed_sync_grouped()'s output as one card per category -
	a colored left accent, the category name, a count badge, and one
	example message in a monospace snippet box."""
	if not grouped_rows:
		return ""
	total = int(sum(flt(r["cnt"]) for r in grouped_rows))
	cards = "".join(
		f"""
		<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:10px;">
		  <tr>
		    <td style="border-left:3px solid {_category_tone(r['error_category'])[1]};
		               background:#f8fafc;border-radius:0 8px 8px 0;padding:10px 14px;">
		      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
		        <tr>
		          <td style="font-weight:700;color:#1e293b;font-size:13px;">
		            {frappe.utils.escape_html(r['error_category'])}
		          </td>
		          <td width="40" align="right">{badge(str(int(r['cnt'])), _category_tone(r['error_category']))}</td>
		        </tr>
		      </table>
		      <div style="margin-top:6px;background:#ffffff;border:1px solid #edf2f7;border-radius:6px;
		                  padding:7px 10px;color:#64748b;font-size:11.5px;font-family:{_MONO};
		                  word-break:break-word;">
		        {frappe.utils.escape_html((r.get('example_message') or '')[:160])}
		      </div>
		    </td>
		  </tr>
		</table>"""
		for r in grouped_rows
	)
	return f"""
	{section_heading(f"Rincian per Kategori &middot; {total} record")}
	{cards}
	<div style="margin-top:4px;">
	  <a href="{frappe.utils.get_url()}/app/otobitz-failed-sync" style="color:#2563eb;font-size:12px;text-decoration:none;">
	    Lihat semua di list &ldquo;OtoBitz Failed Sync&rdquo; &rarr;
	  </a>
	</div>
	"""
