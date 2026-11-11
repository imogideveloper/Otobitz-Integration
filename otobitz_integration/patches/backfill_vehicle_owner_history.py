import frappe


def execute():
	"""One row of owner history (the current owner) for every vehicle that has a
	customer but no history yet. Straight child-row inserts: the vehicles are not
	re-saved, so `modified` and the sync's change detection stay untouched."""
	frappe.reload_doc("OtoBitz Integration", "doctype", "master_vehicle_owner")
	frappe.reload_doc("OtoBitz Integration", "doctype", "master_vehicle")
	have = set(frappe.get_all("Master Vehicle Owner", filters={"parenttype": "Master Vehicle"}, pluck="parent"))
	for v in frappe.get_all("Master Vehicle", filters={"customer": ["is", "set"]}, fields=["name", "customer", "creation"]):
		if v.name in have:
			continue
		frappe.get_doc(
			{
				"doctype": "Master Vehicle Owner",
				"parent": v.name,
				"parenttype": "Master Vehicle",
				"parentfield": "owner_history",
				"customer": v.customer,
				"from_date": v.creation.date(),
				"source": "Sinkronisasi",
			}
		).insert(ignore_permissions=True)
