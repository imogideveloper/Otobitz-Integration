// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

// Maps each OtoBitz endpoint to where its rows land in ERPNext, so a Sync
// Log entry can jump straight to those records instead of searching by hand.
const OTOBITZ_ENDPOINT_TARGETS = {
	masterdata_kategorikendaraan: { doctype: "OtoBitz Vehicle Category" },
	masterdata_tipekendaraan: { doctype: "OtoBitz Vehicle Type" },
	masterdata_warna: { doctype: "OtoBitz Vehicle Color" },
	masterdata_servicemenu: { doctype: "OtoBitz Service Menu" },
	masterdata_supplier: { doctype: "Supplier", filter_field: "custom_otobitz_supplier_no" },
	masterdata_vendor: { doctype: "Supplier", filter_field: "custom_otobitz_vendor_code" },
	masterdata_sparepart: { doctype: "Item", filter_field: "custom_otobitz_part_code" },
	masterdata_jasaservice: { doctype: "Item", filter_field: "custom_otobitz_service_code" },
	masterdata_pekerjaanluar: { doctype: "Item", filter_field: "custom_otobitz_service_code" },
	masterdata_paymentmetode: { doctype: "Mode of Payment", filter_field: "custom_otobitz_payment_code" },
	masterdata_teknisi: { doctype: "Employee", filter_field: "custom_otobitz_teknisi_code" },
	masterdata_customerpage: { doctype: "Customer", filter_field: "custom_otobitz_customer_id" },
};

frappe.ui.form.on("OtoBitz Sync Log", {
	refresh(frm) {
		const target = OTOBITZ_ENDPOINT_TARGETS[frm.doc.endpoint];
		if (!target) return;

		frm.add_custom_button(__("View Records"), () => {
			const filters = target.filter_field ? { [target.filter_field]: ["is", "set"] } : {};
			frappe.set_route("List", target.doctype, filters);
		});
	},
});
