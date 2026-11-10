# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate, nowdate


class OtoBitzVehicle(Document):
	def validate(self):
		self.track_owner()

	def track_owner(self):
		"""Keep `owner_history` in step with `customer`, whatever changed it: the
		"Ganti Pemilik" button, a Sales Order, the OtoBitz sync (sync/common.py
		get_or_create_vehicle) or a plain edit. The row for the previous owner is
		closed with today's date and a row for the new one is opened. Flags
		`owner_source` / `owner_date` / `owner_note` are set by those callers;
		without them the change counts as a manual one made today.
		"""
		before = self.get_doc_before_save()
		old = before.customer if before else None
		new = self.customer
		if old == new and (self.owner_history or not new):
			return

		when = getdate(self.flags.get("owner_date") or nowdate())
		open_rows = [r for r in self.owner_history if not r.to_date]
		if old and old != new and not any(r.customer == old for r in self.owner_history):
			# vehicle that predates the history: keep its previous owner on record
			self.append("owner_history", {"customer": old, "source": "Sinkronisasi", "to_date": when})
		for row in open_rows:
			row.to_date = when
		if new:
			self.append(
				"owner_history",
				{
					"customer": new,
					"from_date": when,
					"source": self.flags.get("owner_source") or frappe.flags.get("owner_source") or "Manual",
					"changed_by": frappe.session.user,
					"notes": self.flags.get("owner_note"),
				},
			)


@frappe.whitelist()
def change_owner(vehicle, customer, date=None, note=None, source="Manual"):
	"""Change a vehicle's owner and record it in the owner history.

	Used by the "Ganti Pemilik" button on the vehicle form and by the prompt on a
	hand-made Sales Order. The history row itself is written by
	OtoBitzVehicle.track_owner when the document saves.
	"""
	if source not in ("Manual", "Sales Order"):
		source = "Manual"
	if not customer or not frappe.db.exists("Customer", customer):
		frappe.throw(frappe._("Customer {0} not found").format(customer))
	doc = frappe.get_doc("OtoBitz Vehicle", vehicle)
	doc.check_permission("write")
	if doc.customer == customer:
		frappe.throw(frappe._("{0} is already the owner of this vehicle").format(customer))
	doc.flags.owner_source = source
	doc.flags.owner_date = date
	doc.flags.owner_note = note
	doc.customer = customer
	doc.save()
	return doc.customer


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
