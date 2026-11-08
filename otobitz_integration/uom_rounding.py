import math

import frappe
from frappe.utils import flt


def round_stock_qty(doc, method=None):
	"""Odoo's UoM rounding, applied where Odoo applies it: only when a line's
	quantity is *converted* to another unit (uom.uom._compute_quantity), rounded
	UP to the target unit's rounding (UOM.rounding_precision, 0.01 as in Odoo).

	When the line's UOM already is the stock UOM nothing is rounded - Odoo keeps
	the quantity as entered too (e.g. 0.1176471 on invoice lines). Runs on
	validate, after ERPNext has computed stock_qty = qty * conversion_factor.
	Only stock_qty (the converted quantity) changes; qty, rate and amount don't.
	"""
	rounding_cache = {}
	for row in doc.get("items") or []:
		stock_uom = row.get("stock_uom")
		if not stock_uom or not row.get("uom") or row.uom == stock_uom:
			continue
		if stock_uom not in rounding_cache:
			rounding_cache[stock_uom] = flt(frappe.db.get_value("UOM", stock_uom, "rounding_precision"))
		rounding = rounding_cache[stock_uom]
		if rounding <= 0:
			continue
		raw = flt(row.qty) * flt(row.conversion_factor)
		# round(.., 6) first so float noise (1.4000000000000001) doesn't tip UP by a step
		row.stock_qty = flt(math.ceil(round(raw / rounding, 6)) * rounding, 7)
