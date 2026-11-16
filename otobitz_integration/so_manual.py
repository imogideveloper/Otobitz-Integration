import frappe


@frappe.whitelist()
def get_vehicle_details(vehicle):
	"""Fields a manually created Sales Order copies from an OtoBitz Vehicle.

	Synced orders get these from the API in sync_service_orders.py; Frappe's
	fetch_from only covers plate, year, chassis and engine, so a hand-made order
	would be left with empty type, color, transmission and manufacture. Same
	source/mapping as the backfill in sync_service_orders.py. Read-only.
	"""
	frappe.has_permission("OtoBitz Vehicle", "read", vehicle, throw=True)
	v = frappe.db.get_value(
		"OtoBitz Vehicle", vehicle, ["customer", "vehicle_type", "vehicle_color", "last_odometer"], as_dict=True
	)
	if not v:
		return {}
	out = {"customer": v.customer, "odometer": v.last_odometer}
	if v.vehicle_type:
		t = frappe.db.get_value(
			"OtoBitz Vehicle Type", v.vehicle_type, ["nama", "transmisi", "brand"], as_dict=True
		)
		if t:
			out["vehicle_type"] = t.nama
			out["manufacture"] = t.brand
			tr = (t.transmisi or "").strip().upper()
			out["transmisi"] = tr if tr in ("AT", "MT", "CVT", "ALL") else None
	if v.vehicle_color:
		out["color"] = frappe.db.get_value("OtoBitz Vehicle Color", v.vehicle_color, "nama")
	return out


@frappe.whitelist()
def get_customer_address(customer):
	"""Address of a Customer for a hand-made Sales Order's Invoice/Delivery Address.

	The sync keeps one Address per Customer (sync/common.py get_or_create_customer_address),
	marked primary and shipping. ERPNext only auto-fills it when the Customer's
	primary-address link is set, which Addresses made from Python don't always do,
	so look up the Address through its Dynamic Link instead. Read-only.
	"""
	frappe.has_permission("Customer", "read", customer, throw=True)
	rows = frappe.db.sql(
		"""select a.name from `tabAddress` a
		join `tabDynamic Link` dl on dl.parent = a.name and dl.parenttype = 'Address'
		where dl.link_doctype = 'Customer' and dl.link_name = %s and a.disabled = 0
		order by a.is_primary_address desc, a.modified desc limit 1""",
		customer,
	)
	return rows[0][0] if rows else None
