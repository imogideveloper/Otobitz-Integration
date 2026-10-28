# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class OtoBitzListFavorite(Document):
	def before_save(self):
		if self.is_global:
			self.for_user = ""
		elif not self.for_user:
			self.for_user = frappe.session.user
