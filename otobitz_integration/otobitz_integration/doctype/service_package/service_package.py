# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ServicePackage(Document):
	def validate(self):
		if not self.items:
			frappe.throw(_("Isi paket belum ada: tambahkan minimal satu barang atau jasa."))
		if self.is_all_branch:
			self.set("branches", [])
		elif not self.branches:
			frappe.throw(_("Pilih minimal satu cabang, atau centang Semua Cabang."))
		if self.code:
			dup = frappe.db.exists("Service Package", {"code": self.code, "name": ["!=", self.name]})
			if dup:
				frappe.throw(_("Kode {0} sudah dipakai paket {1}.").format(frappe.bold(self.code), dup))
