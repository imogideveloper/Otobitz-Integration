# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""Gabungkan Employee duplikat teknisi OtoBitz ke satu Employee.

Satu teknisi bisa punya beberapa kode OtoBitz (satu per outlet). Dulu tiap kode menjadi Employee sendiri. Alat ini
memindahkan semua kode milik `dari` ke tabel kode milik `ke`, lalu menggabungkan `dari` ke `ke`
(frappe.rename_doc merge): semua tautan seperti Sales Order, Sales Invoice, dan Attendance pindah ke `ke`, dan sync
berikutnya mengenali kode itu sebagai milik `ke` sehingga tidak membuat Employee baru lagi.

Dipanggil manual per pasangan yang sudah disetujui, sesudah backup:

    bench --site SITE execute otobitz_integration.otobitz_integration.sync.gabung_teknisi.gabung_teknisi \
        --kwargs "{'dari': 'HR-EMP-00083', 'ke': 'HR-EMP-00070'}"

Default `dry_run=True`: hanya melaporkan apa yang akan terjadi. Penggabungan sungguhan butuh `dry_run=False`.
Ditolak bila `dari` punya Salary Structure Assignment atau Salary Slip yang sudah submit (batalkan dulu). Bila ada
Attendance di tanggal yang sama pada kedua Employee, ditolak kecuali `hapus_absensi_bentrok=True` (Attendance milik
`dari` di tanggal itu dibatalkan lalu dihapus).
"""

import frappe

TABEL_KODE = "custom_otobitz_teknisi_codes"


def gabung_teknisi(dari: str, ke: str, dry_run: bool = True, hapus_absensi_bentrok: bool = False) -> dict:
	frappe.only_for("System Manager")
	dry_run = frappe.parse_json(dry_run) if isinstance(dry_run, str) else dry_run
	if dari == ke:
		frappe.throw(f"Employee asal dan tujuan sama: {dari}")
	for emp in (dari, ke):
		if not frappe.db.exists("Employee", emp):
			frappe.throw(f"Employee {emp} tidak ditemukan")

	payroll = {
		dt: frappe.get_all(dt, filters={"employee": dari, "docstatus": 1}, pluck="name")
		for dt in ("Salary Structure Assignment", "Salary Slip")
	}
	if any(payroll.values()):
		frappe.throw(
			f"{dari} masih punya dokumen payroll yang sudah submit: {payroll}. Batalkan dulu, lalu buat ulang di {ke}."
		)

	kode_asal = _kode_milik(dari)
	tanggal_ke = set(
		frappe.get_all("Attendance", filters={"employee": ke, "docstatus": ["<", 2]}, pluck="attendance_date")
	)
	bentrok = frappe.get_all(
		"Attendance",
		filters={"employee": dari, "docstatus": ["<", 2], "attendance_date": ["in", list(tanggal_ke) or [""]]},
		fields=["name", "attendance_date", "docstatus"],
	)

	laporan = {
		"dari": dari,
		"ke": ke,
		"kode_dipindah": kode_asal,
		"attendance_bentrok": [b.name for b in bentrok],
		"tautan": _hitung_tautan(dari),
		"dry_run": bool(dry_run),
	}
	if dry_run:
		return laporan

	if bentrok and not hapus_absensi_bentrok:
		frappe.throw(
			f"{len(bentrok)} Attendance {dari} bentrok tanggal dengan {ke}. "
			"Jalankan dengan hapus_absensi_bentrok=True sesudah backup."
		)
	for b in bentrok:
		att = frappe.get_doc("Attendance", b.name)
		if att.docstatus == 1:
			att.cancel()
		frappe.delete_doc("Attendance", b.name, ignore_permissions=True, force=True)

	# Pindahkan kode: field lama `dari` dikosongkan (unique), baris tabelnya dipindah ke `ke`.
	tujuan = frappe.get_doc("Employee", ke)
	sudah = {r.kode for r in tujuan.get(TABEL_KODE) or []}
	if tujuan.get("custom_otobitz_teknisi_code") and tujuan.custom_otobitz_teknisi_code not in sudah:
		tujuan.append(TABEL_KODE, {"kode": tujuan.custom_otobitz_teknisi_code, "branch": tujuan.branch})
		sudah.add(tujuan.custom_otobitz_teknisi_code)

	frappe.db.delete("OtoBitz Technician Code", {"parenttype": "Employee", "parent": dari})
	frappe.db.set_value("Employee", dari, "custom_otobitz_teknisi_code", None, update_modified=False)
	for k in kode_asal:
		if k["kode"] not in sudah:
			tujuan.append(TABEL_KODE, k)
			sudah.add(k["kode"])
	tujuan.flags.ignore_mandatory = True
	tujuan.save(ignore_permissions=True)

	frappe.rename_doc("Employee", dari, ke, merge=True, force=True)
	frappe.db.commit()
	laporan["selesai"] = True
	return laporan


def _kode_milik(employee: str) -> list[dict]:
	baris = frappe.get_all(
		"OtoBitz Technician Code",
		filters={"parenttype": "Employee", "parent": employee},
		fields=["kode", "branch", "nama_otobitz"],
		order_by="idx",
	)
	kode = [dict(b) for b in baris]
	lama, branch, nama = frappe.db.get_value(
		"Employee", employee, ["custom_otobitz_teknisi_code", "branch", "employee_name"]
	)
	if lama and lama not in {k["kode"] for k in kode}:
		kode.insert(0, {"kode": lama, "branch": branch, "nama_otobitz": nama})
	return kode


def _hitung_tautan(employee: str) -> dict:
	hasil = {}
	for dt, field in (
		("Sales Order", "custom_otobitz_teknisi"),
		("Sales Invoice", "custom_otobitz_teknisi"),
		("Attendance", "employee"),
	):
		if frappe.get_meta(dt).has_field(field):
			hasil[dt] = frappe.db.count(dt, {field: employee})
	return hasil
