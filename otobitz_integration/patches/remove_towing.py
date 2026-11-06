"""Remove the towing feature: otoexpert is a workshop site, not a towing one (user, 2026-11-06).

Everything towing on the site was made in the desk, not by an app: the Delivery Order Towing doctype and its
DO Towing Kondisi Item table, the DO Towing Workflow, the Admin Towing / Towing Driver roles, a form script,
and custom fields on Item, Purchase Order, Purchase Invoice and Payment Entry (with property setters hiding
some). Each is removed if present, so the patch is a no-op on a site that never had it. The doctypes go only
while they hold no document: a site with towing data keeps them and says so in the log.
"""

import frappe

DOCTYPES = ("Delivery Order Towing", "DO Towing Kondisi Item")
WORKFLOW = "DO Towing Workflow"
ROLES = ("Admin Towing", "Towing Driver")
CLIENT_SCRIPTS = ("Delivery Order Towing-Form-SPK",)
CUSTOM_FIELDS = (
	"Item-custom_lokasi_pickup",
	"Item-custom_lokasi_tujuan",
	"Payment Entry-custom_detail_kendaraan_towing_section",
	"Payment Entry-delivery_order_towing",
	"Purchase Invoice-custom_delivery_order",
	"Purchase Invoice-custom_detail_kendaraan_towing_section",
	"Purchase Order-custom_delivery_order",
	"Purchase Order-custom_detail_kendaraan_towing_section",
	"Delivery Order Towing-purchase_order_uang_jalan",
)
# the fields a property setter may name (the custom fields above, and custom_towing_kendaraan, gone already)
TOWING_FIELDS = (
	"custom_lokasi_pickup",
	"custom_lokasi_tujuan",
	"custom_detail_kendaraan_towing_section",
	"delivery_order_towing",
	"custom_delivery_order",
	"custom_towing_kendaraan",
)


def execute():
	log = []

	for name in CLIENT_SCRIPTS:
		if frappe.db.exists("Client Script", name):
			frappe.delete_doc("Client Script", name, ignore_permissions=True, force=True)
			log.append(f"Client Script {name}")

	if frappe.db.exists("Workflow", WORKFLOW):
		states = set(frappe.get_all("Workflow Document State", {"parent": WORKFLOW}, pluck="state"))
		frappe.delete_doc("Workflow", WORKFLOW, ignore_permissions=True, force=True)
		log.append(f"Workflow {WORKFLOW}")
		# its states, those no other workflow uses (Draft, Cancelled ... stay)
		for state in states:
			if frappe.db.exists("Workflow Document State", {"state": state}):
				continue
			if frappe.db.exists("Workflow State", state):
				frappe.delete_doc("Workflow State", state, ignore_permissions=True, force=True)
				log.append(f"Workflow State {state}")

	for name in CUSTOM_FIELDS:
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
			log.append(f"Custom Field {name}")

	for name in frappe.get_all(
		"Property Setter",
		or_filters=[["field_name", "in", TOWING_FIELDS], ["doc_type", "in", DOCTYPES]],
		pluck="name",
	):
		frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)
		log.append(f"Property Setter {name}")

	for doctype in DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		if frappe.db.table_exists(doctype) and frappe.db.count(doctype):
			log.append(f"KEPT DocType {doctype}: it holds documents")
			continue
		frappe.db.delete("Custom DocPerm", {"parent": doctype})
		frappe.delete_doc("DocType", doctype, ignore_permissions=True, force=True)
		log.append(f"DocType {doctype}")

	for role in ROLES:
		if not frappe.db.exists("Role", role):
			continue
		frappe.db.delete("Has Role", {"role": role})
		frappe.db.delete("Custom DocPerm", {"role": role})
		frappe.delete_doc("Role", role, ignore_permissions=True, force=True)
		log.append(f"Role {role}")

	for doctype in ("Item", "Payment Entry", "Purchase Invoice", "Purchase Order", "Sales Order"):
		frappe.clear_cache(doctype=doctype)

	if log:
		print("remove_towing:\n  " + "\n  ".join(log))
