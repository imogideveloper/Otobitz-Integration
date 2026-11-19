# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""Satu Employee dengan beberapa kode teknisi OtoBitz (plan-teknisi-multi-kode.md).

Setiap test berjalan di dalam transaksi yang di-rollback, jadi tidak meninggalkan data.
"""

import unittest
from unittest.mock import patch

import frappe

from otobitz_integration.otobitz_integration.sync import sync_teknisi as modul
from otobitz_integration.otobitz_integration.sync.common import find_employee_by_teknisi_code
from otobitz_integration.otobitz_integration.sync.gabung_teknisi import gabung_teknisi

KODE_A = "ZZTEST-A1"
KODE_B = "ZZTEST-B2"
KODE_BARU = "ZZTEST-NEW"


class TestSyncTeknisiCodes(unittest.TestCase):
	def setUp(self):
		self.company = frappe.db.get_single_value("OtoBitz Settings", "default_company") or frappe.db.get_value(
			"Company", {}, "name"
		)
		frappe.db.set_single_value("OtoBitz Settings", "default_company", self.company)
		frappe.clear_document_cache("OtoBitz Settings", "OtoBitz Settings")
		self.cabang_hr = self._branch("ZZ HR BRANCH")
		self.hr = self._employee("ZZ Karyawan HR", KODE_A, employment_type="Full-time", branch=self.cabang_hr)
		self.teknisi = self._employee("ZZ Teknisi Murni", KODE_B)

	def tearDown(self):
		frappe.db.rollback()

	def _branch(self, nama):
		if not frappe.db.exists("Branch", nama):
			frappe.get_doc({"doctype": "Branch", "branch": nama}).insert(ignore_permissions=True)
		return nama

	def _employee(self, nama, kode, employment_type=None, branch=None):
		doc = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": nama,
				"employee_name": nama,
				"company": self.company,
				"gender": frappe.db.get_value("Gender", {}, "name"),
				"date_of_birth": "1995-01-01",
				"date_of_joining": "2024-01-01",
				"status": "Active",
				"employment_type": employment_type,
				"branch": branch,
				"custom_otobitz_teknisi_code": kode,
				"custom_otobitz_teknisi_codes": [{"kode": kode, "branch": branch}],
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		return doc.name

	def _sync(self, rows):
		with patch.object(modul, "call_api", return_value={"data-teknisi": rows}):
			return modul.sync_teknisi()

	def test_kode_dicari_lewat_tabel(self):
		frappe.get_doc("Employee", self.hr).append("custom_otobitz_teknisi_codes", {"kode": "ZZTEST-A2"}).db_insert()
		self.assertEqual(find_employee_by_teknisi_code("ZZTEST-A2"), self.hr)
		self.assertEqual(find_employee_by_teknisi_code(f"  {KODE_A} "), self.hr)
		self.assertIsNone(find_employee_by_teknisi_code("ZZTEST-TIDAK-ADA"))

	def test_kode_kedua_tidak_membuat_employee_baru_dan_data_hr_tidak_ditimpa(self):
		frappe.get_doc("Employee", self.hr).append("custom_otobitz_teknisi_codes", {"kode": "ZZTEST-A2"}).db_insert()
		jumlah = frappe.db.count("Employee")
		hasil = self._sync([{"kode": "ZZTEST-A2", "nama": "NAMA DARI OTOBITZ", "kodecabang": "ZZC1", "namacabang": "ZZ OUTLET 1"}])
		self.assertEqual(hasil["created"], 0)
		self.assertEqual(frappe.db.count("Employee"), jumlah)
		emp = frappe.get_doc("Employee", self.hr)
		self.assertEqual(emp.employee_name, "ZZ Karyawan HR")
		self.assertEqual(emp.branch, self.cabang_hr)
		baris = next(r for r in emp.custom_otobitz_teknisi_codes if r.kode == "ZZTEST-A2")
		self.assertEqual(baris.branch, "ZZ OUTLET 1")
		self.assertEqual(baris.nama_otobitz, "NAMA DARI OTOBITZ")

	def test_teknisi_murni_tetap_diperbarui(self):
		self._sync([{"kode": KODE_B, "nama": "Nama Baru", "kodecabang": "ZZC2", "namacabang": "ZZ OUTLET 2"}])
		emp = frappe.get_doc("Employee", self.teknisi)
		self.assertEqual(emp.employee_name, "Nama Baru")
		self.assertEqual(emp.branch, "ZZ OUTLET 2")

	def test_kode_baru_membuat_employee_dengan_baris_kode(self):
		hasil = self._sync([{"kode": KODE_BARU, "nama": "Teknisi Baru", "kodecabang": "ZZC3", "namacabang": "ZZ OUTLET 3"}])
		self.assertEqual(hasil["created"], 1)
		nama = find_employee_by_teknisi_code(KODE_BARU)
		self.assertTrue(nama)
		emp = frappe.get_doc("Employee", nama)
		self.assertEqual(emp.custom_otobitz_teknisi_code, KODE_BARU)
		self.assertEqual([r.kode for r in emp.custom_otobitz_teknisi_codes], [KODE_BARU])

	def test_gabung_dry_run_tidak_mengubah_apa_pun(self):
		laporan = gabung_teknisi(self.teknisi, self.hr)
		self.assertTrue(laporan["dry_run"])
		self.assertEqual([k["kode"] for k in laporan["kode_dipindah"]], [KODE_B])
		self.assertTrue(frappe.db.exists("Employee", self.teknisi))
		self.assertEqual(find_employee_by_teknisi_code(KODE_B), self.teknisi)

	def test_gabung_memindahkan_kode_ke_tujuan(self):
		with patch.object(frappe.db, "commit"):
			gabung_teknisi(self.teknisi, self.hr, dry_run=False)
		self.assertFalse(frappe.db.exists("Employee", self.teknisi))
		self.assertEqual(find_employee_by_teknisi_code(KODE_B), self.hr)
		self.assertEqual(find_employee_by_teknisi_code(KODE_A), self.hr)
		jumlah = frappe.db.count("Employee")
		self._sync([{"kode": KODE_B, "nama": "ZZ Teknisi Murni", "kodecabang": "ZZC2", "namacabang": "ZZ OUTLET 2"}])
		self.assertEqual(frappe.db.count("Employee"), jumlah)
