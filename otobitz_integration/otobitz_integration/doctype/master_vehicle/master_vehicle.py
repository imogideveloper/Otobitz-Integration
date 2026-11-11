# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate, nowdate


class MasterVehicle(Document):
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

	Used by the "Ganti Pemilik" button on the vehicle form and by the "Update
	Data Pemilik" prompt on a Sales Order. The history row itself is written by
	MasterVehicle.track_owner when the document saves."""
	if source not in ("Manual", "Sales Order"):
		source = "Manual"
	if not customer or not frappe.db.exists("Customer", customer):
		frappe.throw(frappe._("Customer {0} not found").format(customer))
	doc = frappe.get_doc("Master Vehicle", vehicle)
	doc.check_permission("write")
	if doc.customer == customer:
		frappe.throw(frappe._("{0} is already the owner of this vehicle").format(customer))
	doc.flags.owner_source = source
	doc.flags.owner_date = date
	doc.flags.owner_note = note
	doc.customer = customer
	doc.save()
	return {"new_owner": doc.customer, "new_owner_name": frappe.db.get_value("Customer", doc.customer, "customer_name")}


@frappe.whitelist()
def search_vehicle(doctype, txt, searchfield, start: int, page_len: int, filters):
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
		from `tabMaster Vehicle`
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


@frappe.whitelist()
def create_vehicle(
	norangka,
	customer,
	nopolisi=None,
	nomesin=None,
	vehicle_type=None,
	vehicle_color=None,
	tahunpembuatan=None,
	last_odometer=None,
):
	if frappe.session.user == "Guest":
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)

	if frappe.db.exists("Master Vehicle", norangka):
		frappe.throw(frappe._("A vehicle with chassis number {0} already exists").format(norangka))

	doc = frappe.get_doc({
		"doctype": "Master Vehicle",
		"norangka": norangka,
		"nopolisi": nopolisi,
		"nomesin": nomesin,
		"customer": customer,
		"vehicle_type": vehicle_type,
		"vehicle_color": vehicle_color,
		"tahunpembuatan": tahunpembuatan,
		"last_odometer": last_odometer,
	})
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"name": doc.name, "nopolisi": doc.nopolisi}
