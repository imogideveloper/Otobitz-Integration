# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class MasterVehicle(Document):
	pass


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
def get_owner_history(vehicle):
	vehicle_doc = frappe.db.get_value(
		"Master Vehicle", vehicle, ["customer"], as_dict=True
	)
	if not vehicle_doc:
		frappe.throw(frappe._("Vehicle {0} not found").format(vehicle))

	current = None
	if vehicle_doc.customer:
		current = frappe.db.get_value(
			"Customer", vehicle_doc.customer, ["name", "customer_name", "mobile_no"], as_dict=True
		)

	rows = frappe.get_all(
		"Master Vehicle Owner History",
		filters={"vehicle": vehicle},
		fields=["previous_owner", "previous_owner_phone", "owner", "creation"],
		order_by="creation desc",
	)
	for row in rows:
		row["previous_owner_name"] = frappe.db.get_value("Customer", row.previous_owner, "customer_name")
		row["changed_by_name"] = frappe.db.get_value("User", row.owner, "full_name") or row.owner

	return {"current": current, "history": rows}


@frappe.whitelist()
def update_vehicle_owner(vehicle, new_owner):
	if frappe.session.user == "Guest":
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)

	current_owner = frappe.db.get_value("Master Vehicle", vehicle, "customer")
	if not current_owner:
		frappe.throw(frappe._("Vehicle {0} not found").format(vehicle))

	if current_owner == new_owner:
		frappe.throw(frappe._("{0} is already the owner of this vehicle").format(new_owner))

	previous_owner_phone = frappe.db.get_value("Customer", current_owner, "mobile_no")

	frappe.get_doc({
		"doctype": "Master Vehicle Owner History",
		"vehicle": vehicle,
		"previous_owner": current_owner,
		"previous_owner_phone": previous_owner_phone,
	}).insert(ignore_permissions=True)

	frappe.db.set_value("Master Vehicle", vehicle, "customer", new_owner)
	frappe.db.commit()

	return {
		"new_owner": new_owner,
		"new_owner_name": frappe.db.get_value("Customer", new_owner, "customer_name"),
	}


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
