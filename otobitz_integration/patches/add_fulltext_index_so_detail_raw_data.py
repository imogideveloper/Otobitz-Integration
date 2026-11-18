import frappe


def execute():
	"""`OtoBitz SO Detail.raw_data` gets searched with a plain `LIKE
	'%needle%'` (see sync_penerimaan.py's _resolve_sales_invoice() fallback,
	used on every nofaktur that doesn't directly match a Sales Invoice -
	exactly the rows already stuck in OtoBitz Failed Sync) - a leading-
	wildcard LIKE can never use a normal BTREE index, so this was a full
	table scan every single call. Confirmed live on production: 6.7s per
	scan against ~45k rows, paid on every retry of every such failure (the
	regular hourly sync's own retries, not just a one-off maintenance
	script), which is real, recurring, unnecessary load.

	A FULLTEXT index lets _resolve_sales_invoice() narrow to a handful of
	candidates with MATCH ... AGAINST first (near-instant), still followed
	by the same exact LIKE check on just those few rows to confirm a real
	substring match (MySQL's default parser tokenizes on non-alphanumeric
	characters, so "SV-101-260400098" splits into separate word tokens -
	MATCH alone would be a looser match than the exact substring this needs).

	Guarded to skip if the index already exists, so a repeat `bench migrate`
	(this patch re-running, or a fresh site import that already has it) is a
	safe no-op rather than an error on the duplicate ALTER TABLE."""
	exists = frappe.db.sql(
		"""
		select 1 from information_schema.statistics
		where table_schema = database()
			and table_name = 'tabOtoBitz SO Detail'
			and index_name = 'raw_data_fulltext'
		limit 1
		"""
	)
	if exists:
		return
	frappe.db.sql("alter table `tabOtoBitz SO Detail` add fulltext index raw_data_fulltext (raw_data)")
