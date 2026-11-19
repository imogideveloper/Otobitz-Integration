# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""masterdata_teknisi -> Employee.

OtoBitz doesn't send gender (mandatory on ERPNext's Employee doctype) or any
other HR-specific data for technicians - they're synced with
`ignore_mandatory=True` and only the fields OtoBitz actually provides.

Satu teknisi bisa punya beberapa kode OtoBitz (satu per outlet). Kode dicari
lewat tabel `custom_otobitz_teknisi_codes` (find_employee_by_teknisi_code),
jadi kode yang sudah ditempelkan ke sebuah Employee tidak lagi membuat
Employee baru. Employee yang sudah dikelola HR (Employment Type terisi) tidak
ditimpa nama dan cabangnya: data HR yang menang. Yang diperbarui hanya baris
kodenya (outlet dan nama di OtoBitz).
"""

import frappe

from otobitz_integration.otobitz_integration.api.client import call_api
from otobitz_integration.otobitz_integration.sync.common import (
	clean,
	find_employee_by_teknisi_code,
	get_or_create_branch,
	safe_name,
	upsert_safe,
)

TABEL_KODE = "custom_otobitz_teknisi_codes"


def sync_teknisi() -> dict:
	response = call_api("masterdata_teknisi")
	rows = response.get("data-teknisi") or []

	settings = frappe.get_cached_doc("OtoBitz Settings")
	company = settings.default_company
	if not company:
		frappe.throw(frappe._("Set Default Company in OtoBitz Settings before syncing Teknisi."))

	ada_tabel = frappe.get_meta("Employee").has_field(TABEL_KODE)

	created = updated = failed = 0
	for row in rows:
		kode = clean(row.get("kode"))
		if not kode:
			continue

		branch = get_or_create_branch(row.get("kodecabang"), row.get("namacabang"))
		nama = safe_name(row.get("nama")) or kode

		existing = find_employee_by_teknisi_code(kode) if ada_tabel else None
		if existing:
			was_updated, was_failed = _update_existing(existing, kode, nama, branch, company)
			updated += was_updated
			failed += was_failed
			continue

		values = {
			"employee_name": nama,
			"first_name": nama,
			"company": company,
			"branch": branch,
			"custom_otobitz_teknisi_code": kode,
		}
		if ada_tabel:
			values[TABEL_KODE] = [{"kode": kode, "branch": branch, "nama_otobitz": nama}]

		_, was_created, was_updated, was_failed = upsert_safe(
			"Employee", {"custom_otobitz_teknisi_code": kode}, values, ignore_mandatory=True
		)
		created += was_created
		updated += was_updated
		failed += was_failed

	return {"fetched": len(rows), "created": created, "updated": updated, "failed": failed}


def _update_existing(name: str, kode: str, nama: str, branch: str | None, company: str) -> tuple[bool, bool]:
	"""Perbarui Employee pemilik `kode`. Returns `(updated, failed)`.

	- Baris kode di tabel: outlet dan nama OtoBitz diperbarui (ditambahkan bila belum ada).
	- Nama, cabang, perusahaan Employee hanya diperbarui untuk record teknisi murni (Employment Type kosong).
	"""
	try:
		doc = frappe.get_doc("Employee", name)
		changed = False

		if not doc.get("employment_type"):
			for fieldname, value in (
				("employee_name", nama),
				("first_name", nama),
				("company", company),
				("branch", branch),
			):
				if doc.get(fieldname) != value:
					doc.set(fieldname, value)
					changed = True

		baris = next((r for r in doc.get(TABEL_KODE) or [] if r.kode == kode), None)
		if baris is None:
			doc.append(TABEL_KODE, {"kode": kode, "branch": branch, "nama_otobitz": nama})
			changed = True
		else:
			for fieldname, value in (("branch", branch), ("nama_otobitz", nama)):
				if baris.get(fieldname) != value:
					baris.set(fieldname, value)
					changed = True

		if changed:
			doc.flags.ignore_mandatory = True
			doc.save(ignore_permissions=True)
		return changed, False
	except Exception:
		frappe.log_error(title=f"OtoBitz sync: failed to update Employee {name} for teknisi {kode}")
		return False, True
