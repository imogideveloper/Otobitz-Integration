// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

// Payroll Entry: picking a Branch fills Cost Center from Branch.cost_center (custom field of this app).
// Done client-side, not with fetch_from: fetch_from would overwrite Cost Center on every save, while HR
// must still be able to pick a different one by hand after choosing the branch.
frappe.ui.form.on("Payroll Entry", {
	branch(frm) {
		otobitzFillCostCenterFromBranch(frm);
	},
	refresh(frm) {
		// A new entry can arrive with Branch already filled (duplicate, defaults).
		if (frm.is_new() && frm.doc.branch && !frm.__otobitz_cc_done) otobitzFillCostCenterFromBranch(frm);
	},
});

function otobitzFillCostCenterFromBranch(frm) {
	if (!frm.doc.branch || frm.doc.docstatus !== 0) return;
	frm.__otobitz_cc_done = true;
	frappe.db.get_value("Branch", frm.doc.branch, "cost_center").then((r) => {
		const cc = r && r.message && r.message.cost_center;
		if (cc && cc !== frm.doc.cost_center) frm.set_value("cost_center", cc);
	});
}
