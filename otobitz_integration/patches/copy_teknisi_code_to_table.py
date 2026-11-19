"""Salin `Employee.custom_otobitz_teknisi_code` ke tabel `custom_otobitz_teknisi_codes` (OtoBitz Technician Code).

Sync OtoBitz kini mencari teknisi lewat tabel itu, supaya satu Employee bisa punya beberapa kode (satu per outlet).
Field lama tetap ada dan tidak diubah; patch ini hanya menambah baris. Idempoten: kode yang sudah ada di tabel dilewati.
"""

import frappe


def execute():
	if not frappe.db.table_exists("OtoBitz Technician Code"):
		frappe.reload_doc("otobitz_integration", "doctype", "otobitz_technician_code")

	sudah = set(frappe.get_all("OtoBitz Technician Code", pluck="kode"))
	karyawan = frappe.get_all(
		"Employee",
		filters={"custom_otobitz_teknisi_code": ["is", "set"]},
		fields=["name", "custom_otobitz_teknisi_code", "branch", "employee_name"],
	)
	for emp in karyawan:
		kode = (emp.custom_otobitz_teknisi_code or "").strip()
		if not kode or kode in sudah:
			continue
		idx = (
			frappe.db.sql(
				"""select max(idx) from `tabOtoBitz Technician Code`
				where parenttype = 'Employee' and parent = %s""",
				emp.name,
			)[0][0]
			or 0
		)
		row = frappe.get_doc(
			{
				"doctype": "OtoBitz Technician Code",
				"parenttype": "Employee",
				"parentfield": "custom_otobitz_teknisi_codes",
				"parent": emp.name,
				"idx": idx + 1,
				"kode": kode,
				"branch": emp.branch,
				"nama_otobitz": emp.employee_name,
			}
		)
		row.db_insert()
		sudah.add(kode)
