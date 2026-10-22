# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class OtoBitzVehicle(Document):
	pass


@frappe.whitelist()
def search_vehicle(doctype, txt, searchfield, start, page_len, filters):
	txt = f"%{txt}%"
	conditions = []
	values = [txt, txt, txt, txt]

	if isinstance(filters, dict) and filters.get("customer"):
		conditions.append("customer = %s")
		values.append(filters.get("customer"))

	cond_str = " and " + " and ".join(conditions) if conditions else ""

	values.extend([txt, page_len, start])

	# Frappe awesomplete format:
	# item 0 = value (stored in field, norangka)
	# item 1 = description text
	# item 2 = sub-description / badge
	return frappe.db.sql(
		f"""
		select
			name,
			coalesce(nopolisi, norangka) as value_label,
			concat('Chassis: ', coalesce(norangka, '-'), ' | ', coalesce(customer, 'No Customer')) as description
		from `tabOtoBitz Vehicle`
		where
			(nopolisi like %s
			or norangka like %s
			or nomesin like %s
			or customer like %s)
			{cond_str}
		order by
			case when nopolisi like %s then 0 else 1 end,
			modified desc
		limit %s offset %s
		""",
		tuple(values),
	)
