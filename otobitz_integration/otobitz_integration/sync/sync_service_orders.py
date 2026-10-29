# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""otoxpertsoandpart -> Sales Order (+ Sales Invoice once statuswo is FAKTUR).

One row here is one line item (Part or Jasa) within a Work Order; every row
sharing the same `nomorwo` repeats the WO's header fields (customer, vehicle,
branch, totals, payment) - same flat-join shape as `masterdata_sparepart`'s
per-branch repetition in Phase 1. Rows are grouped by `nomorwo` before building
each Sales Order's item table.

Customers are get-or-created directly from this endpoint's own embedded
customer fields (nama/alamat/nik/npwp/...) rather than depending on a prior
`masterdata_customerpage` sync - that endpoint has no date filter at all (it
always returns the full 80k+ customer list, confirmed live), so requiring it
to have already run would mean paying that full-table cost just to sync one
recent Work Order. `masterdata_customerpage` is no longer in the hourly
SYNC_STEPS for this reason (see orchestrator.py) - only customers who actually
show up on a Work Order get created, which is exactly the "current activity,
not full history" scope this was built for.

No stock/Warehouse impact by design (`update_stock = 0` on the Sales Invoice) -
OtoBitz manages physical part stock itself; this sync is bookkeeping only.

Payment (`nilaipenerimaan`/`sisapiutang`) is stored as informational fields on
the Sales Invoice only - actual Payment Entry creation is `penerimaanuang`'s
job in a later slice, matched back to these invoices via `custom_otobitz_wo_number`.
"""

from collections import defaultdict

import frappe
from erpnext.controllers.accounts_controller import get_taxes_and_charges
from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
from frappe.utils import add_days, flt, get_first_day, getdate, nowdate

from otobitz_integration.otobitz_integration.api.client import OtoBitzAPIError, call_api
from otobitz_integration.otobitz_integration.sync.common import (
	IMOGIBOT_USER,
	clean,
	clean_or_none,
	get_or_create_customer_address,
	get_or_create_vehicle,
	log_failed_sync,
	log_so_detail_rows,
	renew_sync_lock,
	resolve_failed_sync,
	safe_name,
	set_period_fields,
	sync_so_payment_status,
	upsert,
)

TAXES_AND_CHARGES_TEMPLATE = "Sales Tax - O"
OVERLAP_DAYS = 3
# A 2-day window took ~3 minutes and returned 1109 rows; a full-month window
# (30 days) timed out every retry. Response time scales with the range, not
# just raw slowness, so the window is walked in small chunks - same idea as
# masterdata_customerpage's pagination, just keyed by date instead of page.
#
# 1 day, not 2: confirmed live (2026-10-28) that even some 2-day windows get
# zero bytes back from the upstream server for the full 180s read timeout -
# not slow, just never responds - while the exact same date ranges split
# into 1-day windows succeeded every time. A chunk-level failure here isn't
# cheap: it was silently leaving Work Orders unsynced until someone compared
# totals against the source system by hand (see reconciliation.py, which
# exists precisely because that's what happened for 1-18 Oct). Doubling the
# number of API calls per run is worth it against that.
CHUNK_DAYS = 1


def get_sync_window() -> tuple[str, str]:
	last_sync_date = frappe.db.get_single_value("OtoBitz Settings", "last_so_sync_date")
	# A never-set Date field on a Single doctype can read back as MariaDB's
	# zero-date ("0001-01-01") rather than a real None - treat anything
	# implausibly old the same as unset, rather than only checking truthiness.
	if last_sync_date and getdate(last_sync_date).year > 2000:
		start = add_days(getdate(last_sync_date), -OVERLAP_DAYS)
	else:
		# First run: current month only, not full history - the source system
		# has years of accumulated Work Orders and this sync only cares about
		# current activity.
		start = get_first_day(nowdate())
	return str(start), nowdate()


def _iter_date_chunks(start: str, end: str):
	chunk_start = getdate(start)
	end = getdate(end)
	while chunk_start <= end:
		chunk_end = min(add_days(chunk_start, CHUNK_DAYS - 1), end)
		yield str(chunk_start), str(chunk_end)
		chunk_start = add_days(chunk_end, 1)


def sync_service_orders() -> dict:
	tanggalawal, tanggalakhir = get_sync_window()

	fetched = created = updated = failed = archived = 0
	for chunk_start, chunk_end in _iter_date_chunks(tanggalawal, tanggalakhir):
		renew_sync_lock()
		try:
			response = call_api("otoxpertsoandpart", {"tanggalawal": chunk_start, "tanggalakhir": chunk_end})
		except OtoBitzAPIError:
			frappe.log_error(title=f"OtoBitz sync: giving up on otoxpertsoandpart {chunk_start}..{chunk_end}")
			failed += 1
			continue

		rows = response.get("data-so") or []
		fetched += len(rows)

		# Raw archive, independent of whatever happens below: every line item
		# OtoBitz sent gets a row in OtoBitz SO Detail exactly as received, even
		# one whose Work Order later gets skipped/cancelled/fails to sync as a
		# real Sales Order - see log_so_detail_rows()'s docstring in common.py.
		archived += log_so_detail_rows(rows)
		frappe.db.commit()

		groups = defaultdict(list)
		for row in rows:
			nomorwo = clean(row.get("nomorwo"))
			if nomorwo:
				groups[nomorwo].append(row)

		for i, (nomorwo, wo_rows) in enumerate(groups.items()):
			if i % 20 == 0:
				renew_sync_lock()
			try:
				was_created = _sync_one_wo(nomorwo, wo_rows)
				created += was_created
				updated += not was_created
				# Commit after every single WO, not per-chunk or at the very
				# end: frappe.db.rollback() below rolls back the *entire*
				# open transaction, not just the failed WO - without a commit
				# here, one bad WO later in the same chunk would silently
				# wipe out every good WO already synced since the last
				# commit. This is not hypothetical: it's exactly what caused
				# sync logs to report e.g. "193 created" for a run that left
				# 0 new Sales Orders in the database.
				frappe.db.commit()
				# In case this WO previously failed and is only succeeding
				# now (whether via this normal pass or a manual retry from
				# the OtoBitz Failed Sync queue) - see retry.py.
				resolve_failed_sync("otoxpertsoandpart", nomorwo)
				frappe.db.commit()
			except Exception as exc:
				frappe.db.rollback()
				frappe.log_error(title=f"OtoBitz sync: failed to sync Work Order {nomorwo}")
				log_failed_sync("otoxpertsoandpart", nomorwo, str(exc), wo_rows)
				frappe.db.commit()
				failed += 1

		frappe.logger("otobitz_integration").info(
			f"otoxpertsoandpart {chunk_start}..{chunk_end}: {len(rows)} rows, {len(groups)} Work Orders"
		)

	frappe.db.set_single_value("OtoBitz Settings", "last_so_sync_date", nowdate(), update_modified=False)
	frappe.db.commit()

	return {"fetched": fetched, "created": created, "updated": updated, "failed": failed, "archived": archived}


def _sync_one_wo(nomorwo: str, wo_rows: list) -> bool:
	"""Returns True if a new Sales Order was created for this WO (False if it
	already existed / only the Sales Invoice step ran)."""
	header = wo_rows[0]
	existing_so = frappe.db.get_value("Sales Order", {"custom_otobitz_wo_number": nomorwo})

	if header.get("tglbatal"):
		if existing_so and frappe.db.get_value("Sales Order", existing_so, "docstatus") == 1:
			_cancel_wo_documents(existing_so)
		return False

	if existing_so:
		created = False
	else:
		existing_so = _create_sales_order(nomorwo, header, wo_rows)
		created = True

	if (header.get("statuswo") or "").strip().upper() == "FAKTUR":
		has_invoice = frappe.db.exists("Sales Invoice", {"custom_otobitz_wo_number": nomorwo})
		if not has_invoice:
			_create_sales_invoice(nomorwo, existing_so, header)

	return created


def _cancel_wo_documents(so_name: str) -> None:
	for si_name in frappe.get_all(
		"Sales Invoice", filters={"custom_otobitz_wo_number": frappe.db.get_value("Sales Order", so_name, "custom_otobitz_wo_number")}, pluck="name"
	):
		si = frappe.get_doc("Sales Invoice", si_name)
		if si.docstatus == 1:
			si.cancel()
	so = frappe.get_doc("Sales Order", so_name)
	if so.docstatus == 1:
		so.cancel()


def _resolve_customer(header: dict) -> str | None:
	"""Get-or-create the Customer from this Work Order's own embedded fields -
	see the module docstring for why this doesn't depend on
	masterdata_customerpage having synced this customer already."""
	customerid = clean(header.get("customerid"))
	if not customerid:
		return None

	tax_id = clean_or_none(header.get("npwp"))
	values = {
		"customer_name": safe_name(header.get("nama")) or customerid,
		"customer_type": "Individual",
		"tax_id": tax_id,
		"custom_otobitz_customer_id": customerid,
		"custom_otobitz_nopolisi": clean(header.get("nopolisi")),
		"custom_otobitz_norangka": clean(header.get("norangka")),
		"custom_otobitz_nomesin": clean(header.get("nomesin")),
	}
	values = {k: v for k, v in values.items() if v is not None}

	name, _, _ = upsert("Customer", {"custom_otobitz_customer_id": customerid}, values, ignore_mandatory=True)
	return name


def _create_sales_order(nomorwo: str, header: dict, wo_rows: list):
	customer = _resolve_customer(header)
	if not customer:
		frappe.throw(f"Customer {header.get('customerid')} not found for Work Order {nomorwo}")

	company = frappe.db.get_single_value("OtoBitz Settings", "default_company")
	branch = frappe.db.get_value("Branch", {"custom_otobitz_branch_code": clean(header.get("kode_cabang"))})
	teknisi = frappe.db.get_value("Employee", {"custom_otobitz_teknisi_code": clean(header.get("kodeteknisi"))})
	vehicle_type = _link_if_exists("OtoBitz Vehicle Type", header.get("kodetipe"))
	vehicle_color = _link_if_exists("OtoBitz Vehicle Color", header.get("kodewarna"))
	# OtoBitz Vehicle Type/Color both autoname by their own `kode` (see their
	# doctype JSON), so `vehicle_type`/`vehicle_color` above - needed as-is
	# for the real Link fields below - are themselves that raw code, not
	# anything human-readable. The Sales Order's own display fields
	# (Vehicle Type/Color/Transmission/Manufacture - plain Data/Select
	# fields, not Links) need the actual name/transmisi/brand looked up
	# from those two master doctypes instead, or they show a code like
	# "TYP001" where a vehicle type/colour/brand name is expected.
	vehicle_type_info = (
		frappe.db.get_value("OtoBitz Vehicle Type", vehicle_type, ["nama", "transmisi", "brand"], as_dict=True)
		if vehicle_type
		else None
	)
	vehicle_color_name = frappe.db.get_value("OtoBitz Vehicle Color", vehicle_color, "nama") if vehicle_color else None
	vehicle = get_or_create_vehicle(
		header.get("norangka"),
		nopolisi=header.get("nopolisi"),
		nomesin=header.get("nomesin"),
		customer=customer,
		vehicle_type=vehicle_type,
		vehicle_color=vehicle_color,
		tahunpembuatan=header.get("tahunpembuatan"),
		odometer=header.get("odemeter"),
	)

	so = frappe.new_doc("Sales Order")
	so.customer = customer
	so.company = company
	so.transaction_date = getdate(header.get("tanggal"))
	so.delivery_date = getdate(header.get("tanggal"))
	so.custom_otobitz_wo_number = nomorwo
	# Odoo-side column names the List View is kept matching to - same value
	# as custom_otobitz_wo_number, just the label this was already shown
	# under there.
	so.custom_otobitz_so_number = nomorwo
	# custom_salesperson defaults to "__user" (whoever's logged in) for a
	# Sales Order built by hand in Desk - this sync runs as a service
	# account, not a real salesperson, so it's set explicitly here instead,
	# same role Odoo's OdooBot plays on synced records there.
	so.custom_salesperson = IMOGIBOT_USER
	set_period_fields(so, so.transaction_date)
	# This integration never creates a Delivery Note (OtoBitz owns physical
	# stock), so without this every synced order would sit permanently
	# flagged "Overdue" by ERPNext's delivery-based status logic the moment
	# its delivery date passes, regardless of payment - see
	# sync_so_payment_status() in common.py for the other half of this.
	so.skip_delivery_note = 1
	if branch:
		so.custom_otobitz_branch = branch
	if teknisi:
		so.custom_otobitz_teknisi = teknisi
	if vehicle:
		# Labeled "License Plate" on the form, but this is a Link to OtoBitz
		# Vehicle, which autonames by chassis number (norangka), not by plate
		# - this field was showing a chassis number in a field titled
		# "License Plate" ("License Plate nyaa ga seusai"). The real plate
		# number goes on custom_plat_nomor below, which already had the
		# correct data from sync all along but sat hidden on the form
		# (see the custom_plat_nomor Property Setter removed alongside this).
		so.custom_otobitz_vehicle = vehicle
	# These mirror OtoBitz Vehicle's own fields and are declared as
	# fetch_from=custom_otobitz_vehicle.<field> on the Sales Order doctype,
	# but Frappe's fetch_from only auto-populates when the link field is
	# changed interactively in the browser - it's a no-op on a doc built and
	# inserted from Python, which is how every synced order is created. Set
	# explicitly here from the same source data instead of relying on it.
	so.custom_nomor_rangka = clean(header.get("norangka"))
	so.custom_nomor_mesin = clean(header.get("nomesin"))
	so.custom_tahun_kendaraan = clean(header.get("tahunpembuatan"))
	so.custom_plat_nomor = clean(header.get("nopolisi"))
	# Vehicle Type/Color (plain Data display fields, not Links) need the
	# human-readable name - vehicle_type/vehicle_color above are the master
	# doctypes' own `kode` (their autoname), which is what these two fields
	# were showing before: a code instead of a name ("vehicle type jangan
	# angka, sebutin dia merk apa" / "color jangan nomor").
	if vehicle_type_info and vehicle_type_info.nama:
		so.custom_vehicle_type = vehicle_type_info.nama
	if vehicle_color_name:
		so.custom_warna = vehicle_color_name
	# custom_transmisi is a Select field (AT/MT/CVT/ALL) - only set when
	# OtoBitz Vehicle Type's own free-text transmisi value matches one of
	# those exactly (case-insensitive), rather than risk writing a value
	# Select's own dropdown doesn't recognize.
	if vehicle_type_info and vehicle_type_info.transmisi:
		transmisi = vehicle_type_info.transmisi.strip().upper()
		if transmisi in ("AT", "MT", "CVT", "ALL"):
			so.custom_transmisi = transmisi
	if vehicle_type_info and vehicle_type_info.brand:
		so.custom_vehicle_manufacture = vehicle_type_info.brand
	so.custom_pengguna = clean(header.get("pic"))
	so.custom_keluhan = clean(header.get("keluhan"))
	so.custom_saran = clean(header.get("saran"))
	# Address was never synced before - without one linked to the Customer,
	# these sit empty and ERPNext's display falls back to the bare Customer
	# name instead of a real address ("Invoice/Delivery Address otomatis
	# isinya nama customer itu sendiri").
	address = get_or_create_customer_address(customer, header.get("alamat"))
	if address:
		so.customer_address = address
		so.shipping_address_name = address
	odometer = flt(header.get("odemeter"))
	if odometer:
		so.custom_odometer = odometer

	for row in wo_rows:
		item_code = clean(row.get("kodereferensi"))
		if not item_code or not frappe.db.exists("Item", item_code):
			continue
		stock_uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"
		# `harga` is the gross per-unit price and `discperitem` a per-unit
		# discount - OtoBitz's own `subtotal` = qty * (harga - discperitem),
		# confirmed against a real WO. `price_list_rate` must be set to the
		# gross price for ERPNext to actually apply `discount_amount`
		# (setting `rate` alone and leaving price_list_rate unset means the
		# discount is silently ignored - this is what happened the first
		# time: the ERPNext total came out higher than OtoBitz's).
		price_list_rate = flt(row.get("harga"))
		discount_amount = flt(row.get("discperitem"))
		qty = flt(row.get("qty"))
		# `or 1` alone only catches a literal 0 - some OtoBitz rows carry a
		# genuinely tiny qty (e.g. 0.001) that survives that check but still
		# rounds down to 0 at the Qty field's 2-3 decimal precision once
		# saved, tripping ERPNext's own "cannot be zero" validation on save.
		if qty < 0.01:
			qty = 1
		so.append(
			"items",
			{
				"item_code": item_code,
				"qty": qty,
				"price_list_rate": price_list_rate,
				"discount_amount": discount_amount,
				"rate": price_list_rate - discount_amount,
				"uom": stock_uom,
				"conversion_factor": 1,
			},
		)

	if not so.items:
		frappe.throw(f"No resolvable Items for Work Order {nomorwo}")

	# Same tax template as the Sales Invoice - without this the Sales Order's
	# own grand_total is net-of-tax only, which doesn't match either OtoBitz's
	# own quotation total (already tax-inclusive) or the Sales Invoice made
	# from this SO, even though both describe the same Work Order.
	so.taxes_and_charges = TAXES_AND_CHARGES_TEMPLATE
	so.set("taxes", [])
	so.extend("taxes", get_taxes_and_charges("Sales Taxes and Charges Template", TAXES_AND_CHARGES_TEMPLATE))

	so.insert(ignore_permissions=True, ignore_mandatory=True)
	so.submit()
	return so.name


def _create_sales_invoice(nomorwo: str, so_name: str, header: dict) -> None:
	si = make_sales_invoice(so_name, ignore_permissions=True)
	si.update_stock = 0
	si.custom_otobitz_wo_number = nomorwo
	si.custom_otobitz_branch = frappe.db.get_value("Sales Order", so_name, "custom_otobitz_branch")
	si.custom_otobitz_nofaktur = clean(header.get("nofaktur"))
	si.custom_otobitz_nilaipenerimaan = flt(header.get("nilaipenerimaan"))
	si.custom_otobitz_sisapiutang = flt(header.get("sisapiutang"))
	si.posting_date = getdate(header.get("tglfaktur") or header.get("tanggal"))
	set_period_fields(si, si.posting_date)
	si.taxes_and_charges = TAXES_AND_CHARGES_TEMPLATE
	si.set("taxes", [])
	si.extend("taxes", get_taxes_and_charges("Sales Taxes and Charges Template", TAXES_AND_CHARGES_TEMPLATE))

	si.insert(ignore_permissions=True, ignore_mandatory=True)
	si.submit()
	sync_so_payment_status(si.name)

	# Faktur number only exists once the invoice is made, so it lands on
	# the Sales Order here rather than alongside custom_otobitz_so_number
	# in _create_sales_order - same Odoo-matching List View column as
	# custom_otobitz_nofaktur on the Sales Invoice, just the SO-side copy.
	if si.custom_otobitz_nofaktur:
		frappe.db.set_value("Sales Order", so_name, "custom_otobitz_faktur_number", si.custom_otobitz_nofaktur)
		_add_oto_so_api_reference(so_name, "Sales Order", "custom_oto_so_api")
		_add_oto_so_api_reference(si.name, "Sales Invoice", "custom_oto_so", so_name=so_name)


def _add_oto_so_api_reference(
	docname: str, doctype: str, fieldname: str, so_name: str | None = None
) -> None:
	"""Mirrors Odoo's "Oto SO API"/"OTO SO" tracking field (a one-line-per-
	invoice log reading "SO-xxx - SV-xxx") on the Oto Integration tab -
	present on both Sales Order and Sales Invoice, but was previously never
	populated by this sync on either, despite the Custom Field/child doctype
	existing on both. Only called once a faktur_number exists (a Sales Order
	can be synced from OtoBitz before its invoice is made, so_number alone
	isn't the complete reference yet). so_name defaults to docname itself
	(the Sales Order case); the Sales Invoice case passes it explicitly
	since the invoice's own name isn't the Sales Order's."""
	so_number, faktur_number = frappe.db.get_value(
		"Sales Order",
		so_name or docname,
		["custom_otobitz_so_number", "custom_otobitz_faktur_number"],
	)
	if not (so_number and faktur_number):
		return

	doc = frappe.get_doc(doctype, docname)
	doc.append(fieldname, {"api_reference": f"{so_number} - {faktur_number}"})
	doc.save(ignore_permissions=True)


@frappe.whitelist()
def lookup_and_sync_wo(nomorwo: str) -> dict:
	"""On-demand counterpart to the hourly batch: look up and sync exactly one
	Work Order via `otoxpertsoandpartpernomor` (same response shape as
	`otoxpertsoandpart`, just pre-filtered to one WO server-side), instead of
	waiting for it to fall inside the next hourly date window. Reuses
	`_sync_one_wo` directly - no separate mapping logic to keep in sync."""
	frappe.only_for("System Manager")

	nomorwo = clean(nomorwo)
	if not nomorwo:
		frappe.throw("Enter a Work Order number (nomorwo) to look up.")

	response = call_api("otoxpertsoandpartpernomor", {"nomorso": nomorwo})
	rows = response.get("data-so") or []
	if not rows:
		return {"found": False, "nomorwo": nomorwo}

	was_created = _sync_one_wo(nomorwo, rows)
	frappe.db.commit()

	return {
		"found": True,
		"nomorwo": nomorwo,
		"created": was_created,
		"sales_order": frappe.db.get_value("Sales Order", {"custom_otobitz_wo_number": nomorwo}),
		"sales_invoice": frappe.db.get_value("Sales Invoice", {"custom_otobitz_wo_number": nomorwo}),
	}


def _link_if_exists(doctype: str, value) -> str | None:
	value = clean(value)
	if value and frappe.db.exists(doctype, value):
		return value
	return None


@frappe.whitelist()
def backfill_so_and_faktur_numbers() -> dict:
	"""One-off: custom_otobitz_so_number/custom_otobitz_faktur_number were added
	(see d43bd29) after Work Orders had already been syncing for a while, so any
	Sales Order created before that only has custom_otobitz_wo_number set. Both
	missing fields can be derived from data already on this site - no API call
	needed: so_number is just wo_number's value (see _create_sales_order), and
	faktur_number is the matching Sales Invoice's custom_otobitz_nofaktur (see
	_create_sales_invoice)."""
	frappe.only_for("System Manager")

	frappe.db.sql(
		"""
		update `tabSales Order`
		set custom_otobitz_so_number = custom_otobitz_wo_number
		where ifnull(custom_otobitz_wo_number, '') != ''
		  and ifnull(custom_otobitz_so_number, '') = ''
		"""
	)
	so_rows = frappe.db.sql("select row_count()")[0][0]

	frappe.db.sql(
		"""
		update `tabSales Order` so
		join `tabSales Invoice` si on si.custom_otobitz_wo_number = so.custom_otobitz_wo_number
		set so.custom_otobitz_faktur_number = si.custom_otobitz_nofaktur
		where ifnull(si.custom_otobitz_nofaktur, '') != ''
		  and ifnull(so.custom_otobitz_faktur_number, '') = ''
		"""
	)
	faktur_rows = frappe.db.sql("select row_count()")[0][0]
	frappe.db.commit()

	return {"so_number_rows_matched": so_rows, "faktur_number_rows_matched": faktur_rows}


@frappe.whitelist()
def backfill_so_vehicle_and_contact_fields() -> dict:
	"""One-off: the vehicle-name/transmission/manufacture/complaints/
	suggestion/driver/address fixes in _create_sales_order() only run when a
	Sales Order is first *created* - _sync_one_wo() never calls it again for
	a Work Order whose Sales Order already exists (see its own `created =
	False` branch), so every Sales Order synced before this fix shipped is
	permanently stuck with whatever it had at creation time: Vehicle Type/
	Color showing a raw code instead of a name, Transmission/Manufacture/
	Complaints/Suggestion/User-Driver empty, no real Address.

	Vehicle Type/Color/Transmission/Manufacture are re-derived the same way
	_create_sales_order() does - from the Sales Order's own already-linked
	custom_otobitz_vehicle, no API call needed.

	Complaints/Suggestion/User-Driver/Address need OtoBitz's own per-Work-
	Order `keluhan`/`saran`/`pic`/`alamat` strings, which were never stored
	as their own columns anywhere - they only exist inside the full raw
	JSON `OtoBitz SO Detail.raw_data` (one row per nomorwo is enough; those
	four are WO-header-level fields, identical across every line-item row
	for the same WO). A Work Order whose SO Detail archive doesn't go back
	far enough (archiving started 2026-10-21, same as see log_so_detail_rows()'s
	own docstring) has no raw_data to recover these four from and is
	skipped for just that part - vehicle/transmission fields above don't
	depend on raw_data and still get fixed regardless."""
	frappe.only_for("System Manager")
	import json

	vehicle_fixed = 0
	for so in frappe.get_all(
		"Sales Order",
		filters={"custom_otobitz_vehicle": ["is", "set"]},
		fields=["name", "custom_otobitz_vehicle"],
	):
		vehicle_type, vehicle_color = frappe.db.get_value(
			"OtoBitz Vehicle", so.custom_otobitz_vehicle, ["vehicle_type", "vehicle_color"]
		) or (None, None)
		vehicle_type_info = (
			frappe.db.get_value("OtoBitz Vehicle Type", vehicle_type, ["nama", "transmisi", "brand"], as_dict=True)
			if vehicle_type
			else None
		)
		vehicle_color_name = frappe.db.get_value("OtoBitz Vehicle Color", vehicle_color, "nama") if vehicle_color else None

		values = {}
		if vehicle_type_info and vehicle_type_info.nama:
			values["custom_vehicle_type"] = vehicle_type_info.nama
		if vehicle_color_name:
			values["custom_warna"] = vehicle_color_name
		if vehicle_type_info and vehicle_type_info.transmisi:
			transmisi = vehicle_type_info.transmisi.strip().upper()
			if transmisi in ("AT", "MT", "CVT", "ALL"):
				values["custom_transmisi"] = transmisi
		if vehicle_type_info and vehicle_type_info.brand:
			values["custom_vehicle_manufacture"] = vehicle_type_info.brand

		if values:
			frappe.db.set_value("Sales Order", so.name, values, update_modified=False)
			vehicle_fixed += 1

	frappe.db.commit()

	contact_fixed = 0
	so_rows = frappe.get_all(
		"Sales Order",
		filters={"custom_otobitz_wo_number": ["is", "set"]},
		fields=["name", "customer", "custom_otobitz_wo_number", "custom_pengguna", "custom_keluhan", "custom_saran", "customer_address"],
	)
	for i, so in enumerate(so_rows):
		if i % 200 == 0:
			renew_sync_lock()
		# Already has everything this backfill would set - skip the
		# raw_data lookup entirely for the common case of an SO that was
		# never missing these to begin with.
		if so.custom_pengguna and so.custom_keluhan and so.custom_saran and so.customer_address:
			continue

		raw = frappe.db.get_value(
			"OtoBitz SO Detail", {"nomorwo": so.custom_otobitz_wo_number}, "raw_data"
		)
		if not raw:
			continue
		try:
			header = json.loads(raw)
		except (TypeError, ValueError):
			continue

		values = {}
		if not so.custom_pengguna and clean(header.get("pic")):
			values["custom_pengguna"] = clean(header.get("pic"))
		if not so.custom_keluhan and clean(header.get("keluhan")):
			values["custom_keluhan"] = clean(header.get("keluhan"))
		if not so.custom_saran and clean(header.get("saran")):
			values["custom_saran"] = clean(header.get("saran"))
		if not so.customer_address:
			address = get_or_create_customer_address(so.customer, header.get("alamat"))
			if address:
				values["customer_address"] = address
				values["shipping_address_name"] = address

		if values:
			frappe.db.set_value("Sales Order", so.name, values, update_modified=False)
			contact_fixed += 1
			frappe.db.commit()

	frappe.db.commit()

	return {
		"sales_orders_checked": len(so_rows),
		"vehicle_fields_fixed": vehicle_fixed,
		"contact_fields_fixed": contact_fixed,
	}


@frappe.whitelist()
def backfill_oto_so_api_references() -> dict:
	"""One-off: _add_oto_so_api_reference() (the Oto Integration tab's "OTO SO
	API"/"OTO SO" log, on Sales Order and Sales Invoice respectively) was
	added after this sync had already been creating Sales Orders/Invoices
	for a while - any pair synced before that has so_number/faktur_number
	but no matching child table row on either side."""
	frappe.only_for("System Manager")

	so_names = frappe.get_all(
		"Sales Order",
		filters={
			"custom_otobitz_so_number": ["is", "set"],
			"custom_otobitz_faktur_number": ["is", "set"],
		},
		pluck="name",
	)
	so_added = 0
	for name in so_names:
		existing = frappe.get_all("SO Oto API", filters={"parent": name, "parenttype": "Sales Order"}, limit=1)
		if existing:
			continue
		_add_oto_so_api_reference(name, "Sales Order", "custom_oto_so_api")
		so_added += 1

	si_names = frappe.get_all(
		"Sales Invoice",
		filters={"custom_otobitz_wo_number": ["is", "set"], "custom_otobitz_nofaktur": ["is", "set"]},
		fields=["name", "custom_otobitz_wo_number"],
	)
	si_added = 0
	for row in si_names:
		existing = frappe.get_all("SO Oto API", filters={"parent": row.name, "parenttype": "Sales Invoice"}, limit=1)
		if existing:
			continue
		so_name = frappe.db.get_value("Sales Order", {"custom_otobitz_wo_number": row.custom_otobitz_wo_number})
		if not so_name:
			continue
		_add_oto_so_api_reference(row.name, "Sales Invoice", "custom_oto_so", so_name=so_name)
		si_added += 1

	frappe.db.commit()

	return {
		"so_checked": len(so_names),
		"so_rows_added": so_added,
		"si_checked": len(si_names),
		"si_rows_added": si_added,
	}
