# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""Small shared helpers used by every sync_*.py module.

None of the 28 OtoBitz endpoints has a dedicated "list of branches" call -
`kodecabang`/`namacabang` just show up as extra fields on several master-data
records (teknisi, supplier, sparepart, pekerjaanluar). So instead of a
standalone `sync_branches.py`, branches are upserted lazily via
`get_or_create_branch()` the first time a given branch code is seen, from
whichever sync function encounters it.
"""

import re

import frappe
from erpnext.controllers.accounts_controller import get_taxes_and_charges
from frappe.utils import flt, getdate

_MONTH_NAMES = [
	"", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
	"Juli", "Agustus", "September", "Oktober", "November", "Desember",
]

# Frappe's document-name validator rejects these (frappe/model/naming.py).
_NAME_UNSAFE_RE = re.compile(r"[<>]+")
# frappe.utils.validate_phone_number only allows these characters; OtoBitz
# source data uses an en-dash ("021 – 743 0983") which isn't one of them.
_PHONE_UNSAFE_RE = re.compile(r"[^0-9 \+_\-,.*#()]+")

# Guards against the scheduler's hourly tick starting a second run_hourly_sync
# on top of one that's still going (a full run can take well over an hour
# when the upstream API is slow/flaky). The lock is renewed periodically by
# whoever holds it (see renew_sync_lock() calls in orchestrator.py and the
# customer pagination loop) rather than set once with a long fixed TTL - a
# static "assume the worst case" TTL either expires too early and lets a
# second run start anyway (what happened before this was added: two
# processes wrote to the same records concurrently and corrupted several
# hundred of them), or is too long to promptly notice a genuinely dead
# process. A short, renewed TTL gets both right.
SYNC_LOCK_KEY = "otobitz_integration:hourly_sync_running"
SYNC_LOCK_TIMEOUT_SECONDS = 600


def acquire_sync_lock() -> bool:
	if frappe.cache().get_value(SYNC_LOCK_KEY):
		return False
	frappe.cache().set_value(SYNC_LOCK_KEY, "1", expires_in_sec=SYNC_LOCK_TIMEOUT_SECONDS)
	return True


def renew_sync_lock() -> None:
	frappe.cache().set_value(SYNC_LOCK_KEY, "1", expires_in_sec=SYNC_LOCK_TIMEOUT_SECONDS)


def release_sync_lock() -> None:
	frappe.cache().delete_value(SYNC_LOCK_KEY)


def as_bool(value) -> int:
	"""OtoBitz sends booleans as the strings "t"/"f" (raw Postgres booleans)."""
	return 1 if str(value).strip().lower() in ("t", "true", "1") else 0


def clean(value) -> str | None:
	if value is None:
		return None
	value = str(value).strip()
	return value or None


# OtoBitz uses these as a "no value" placeholder across several fields
# (npwp, email, ...) instead of leaving the field empty.
_PLACEHOLDER_VALUES = {"-", "."}


def clean_or_none(value) -> str | None:
	"""Like clean(), but also treats OtoBitz's "-"/"." placeholder strings as
	no value."""
	value = clean(value)
	return None if value in _PLACEHOLDER_VALUES else value


def clean_email(value) -> str | None:
	"""clean_or_none(), and additionally drops anything that isn't even
	shaped like an email - frappe.utils.validate_email_address rejects it
	outright and would otherwise abort the whole row."""
	value = clean_or_none(value)
	if value is None or "@" not in value:
		return None
	return value


def safe_name(value) -> str | None:
	"""Strip characters Frappe's document-name validator rejects ('<', '>')."""
	value = clean(value)
	if value is None:
		return None
	return _NAME_UNSAFE_RE.sub("", value).strip() or None


def clean_phone(value) -> str | None:
	"""Normalize a raw OtoBitz phone/fax string to something
	frappe.utils.validate_phone_number will accept, instead of letting a
	messily-formatted number (en-dashes, stray text) abort a whole batch."""
	value = clean(value)
	if value is None:
		return None
	value = _PHONE_UNSAFE_RE.sub("-", value).strip(" -")
	return value or None


# Checked top to bottom, first match wins. Keep these aligned with reality,
# not aspiration: each pattern here was lifted from an actual recurring
# error_message seen in "OtoBitz Failed Sync", not guessed up front - add a
# new one only once the same raw message has actually shown up grouped under
# "Lainnya" a meaningful number of times.
_ERROR_CATEGORY_PATTERNS = [
	("Qty desimal ditolak oleh UOM", "cannot be a fraction"),
	("Mode of Payment belum ada akun Cash/Bank", "Please set default Cash or Bank account in Mode of Payment"),
	("Sales Invoice belum ada saat sync payment", "No Sales Invoice found for nofaktur"),
	("Belum ada Approval Setting untuk Cost Center", "No active Approval Setting with a purchase"),
	("Tidak ada DO Towing yang bisa ditagih", "Tidak ada DO Towing yang bisa ditagih"),
	("Race condition penomoran Series", "Record has changed since last read"),
	("Item tidak bisa di-resolve dari WO", "No resolvable Items for Work Order"),
	("Customer tidak ditemukan berdasarkan nama", "No Customer found matching name"),
]
_ACCOUNT_ROW_RE = re.compile(r"Could not find Row #\d+: Account:")


def categorize_error(error_message: str | None) -> str:
	"""Collapse a raw error_message into one of a fixed set of human-readable
	categories, so "OtoBitz Failed Sync" rows that are really the same root
	cause - just with a different row number/quantity/account name baked into
	the text - group together under Group By instead of each counting as its
	own one-off problem."""
	if not error_message:
		return "Lainnya"
	for category, needle in _ERROR_CATEGORY_PATTERNS:
		if needle in error_message:
			return category
	if _ACCOUNT_ROW_RE.search(error_message):
		return "Account tidak ditemukan/salah konfigurasi"
	return "Lainnya"


def log_failed_sync(endpoint: str, record_key: str, error_message: str, raw_data) -> None:
	"""Record (or update) one row in the "OtoBitz Failed Sync" retry queue for
	a record a sync function couldn't process this run.

	`raw_data` is whatever was being synced (the single row dict most
	endpoints pass around, or the list of line-item rows sync_service_orders
	groups per WO) - stored as JSON so a later manual retry can re-run the
	exact same per-record sync function directly against it, without
	re-fetching from the OtoBitz API (which may not even return this record
	again once it's rolled out of the sync's rolling date window). Upserted
	by endpoint+record_key so repeat hourly failures for the same record
	update one row (bumping attempt_count) instead of piling up duplicates -
	this function is the only place that creates OtoBitz Failed Sync rows,
	and resolve_failed_sync() is the only place that removes them, so the
	queue always reflects exactly what's still actually broken."""
	import json

	dedup_key = f"{endpoint}|{record_key}"
	existing = frappe.db.get_value("OtoBitz Failed Sync", {"dedup_key": dedup_key})
	now = frappe.utils.now_datetime()
	category = categorize_error(error_message)
	if existing:
		doc = frappe.get_doc("OtoBitz Failed Sync", existing)
		doc.attempt_count = (doc.attempt_count or 0) + 1
		doc.last_attempt_at = now
		doc.error_message = error_message
		doc.error_category = category
		doc.raw_data = json.dumps(raw_data, default=str, ensure_ascii=False)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.new_doc("OtoBitz Failed Sync")
		doc.dedup_key = dedup_key
		doc.endpoint = endpoint
		doc.record_key = record_key
		doc.attempt_count = 1
		doc.first_failed_at = now
		doc.last_attempt_at = now
		doc.error_message = error_message
		doc.error_category = category
		doc.raw_data = json.dumps(raw_data, default=str, ensure_ascii=False)
		doc.insert(ignore_permissions=True)


def resolve_failed_sync(endpoint: str, record_key: str) -> None:
	"""Remove a record from the retry queue once it's synced successfully -
	called on the success path of every sync function that also calls
	log_failed_sync() on failure, so a record that failed once but goes
	through fine on a later hourly pass (or a manual retry) doesn't linger
	in the queue forever. A no-op (not an error) if it was never queued."""
	dedup_key = f"{endpoint}|{record_key}"
	existing = frappe.db.get_value("OtoBitz Failed Sync", {"dedup_key": dedup_key})
	if existing:
		frappe.delete_doc("OtoBitz Failed Sync", existing, ignore_permissions=True, force=True)


def get_or_create_branch(kode: str | None, nama: str | None) -> str | None:
	kode = clean(kode)
	nama = clean(nama)
	if not kode or not nama:
		return None

	existing = frappe.db.get_value("Branch", {"custom_otobitz_branch_code": kode})
	if existing:
		if frappe.db.get_value("Branch", existing, "branch") != nama:
			frappe.db.set_value("Branch", existing, "branch", nama, update_modified=False)
		return existing

	branch = frappe.new_doc("Branch")
	branch.branch = nama
	branch.custom_otobitz_branch_code = kode
	branch.insert(ignore_permissions=True, ignore_mandatory=True)
	return branch.name


def get_or_create_vehicle(
	norangka: str | None,
	*,
	nopolisi: str | None = None,
	nomesin: str | None = None,
	customer: str | None = None,
	vehicle_type: str | None = None,
	vehicle_color: str | None = None,
	tahunpembuatan: str | None = None,
	odometer=None,
) -> str | None:
	"""Get-or-create an OtoBitz Vehicle, refreshing the fields that change
	over a vehicle's life (owner, odometer) on every call - unlike most
	get_or_create_* helpers here this one is expected to be updated
	repeatedly as the same vehicle comes back on later Work Orders."""
	norangka = clean(norangka)
	if not norangka:
		return None

	values = {
		"nopolisi": clean(nopolisi),
		"nomesin": clean(nomesin),
		"customer": customer,
		"vehicle_type": vehicle_type,
		"vehicle_color": vehicle_color,
		"tahunpembuatan": clean(tahunpembuatan),
		"last_odometer": odometer,
	}
	values = {k: v for k, v in values.items() if v is not None}

	name, _, _ = upsert("OtoBitz Vehicle", {"norangka": norangka}, values, ignore_mandatory=True)
	return name


def set_period_fields(doc, date_value) -> None:
	"""Stamp `custom_tahun`/`custom_bulan` (Int year, Indonesian month name) on
	a doc from a date value - these exist purely so Report View's native Group
	By control can group by year/month. It only supports exact-date buckets
	for an actual Date field (one group per calendar day), not year/month
	aggregation, so grouping by a real month or year needs its own plain
	Int/Select field instead."""
	if not date_value:
		return
	d = getdate(date_value)
	doc.custom_tahun = d.year
	doc.custom_bulan = _MONTH_NAMES[d.month]


def sync_so_payment_status(si_name: str) -> None:
	"""Mirror a fully-paid Sales Invoice onto its linked Sales Order(s) as a
	"Paid" status.

	Every Sales Order synced from OtoBitz has `skip_delivery_note` set, since
	this integration never creates a Delivery Note (OtoBitz owns physical
	stock itself) - without that, ERPNext's own per_delivered-based status
	logic leaves every one of these orders permanently flagged "Overdue" the
	moment their delivery date passes, regardless of payment. That alone
	stops the false "Overdue", but it doesn't surface payment status, which
	ERPNext only tracks at the Invoice level, not the Order level. "Paid" is
	a custom status option (see the Sales Order-status-options Property
	Setter) that this function sets directly once the linked Invoice's
	outstanding_amount hits zero, as the closest match to what the order
	actually is at that point - not a native ERPNext document state."""
	outstanding, docstatus = frappe.db.get_value(
		"Sales Invoice", si_name, ["outstanding_amount", "docstatus"]
	)
	if docstatus != 1 or flt(outstanding) > 0:
		return

	so_names = frappe.get_all(
		"Sales Invoice Item",
		filters={"parent": si_name, "sales_order": ["is", "set"]},
		pluck="sales_order",
		distinct=True,
	)
	for so_name in so_names:
		status, so_docstatus = frappe.db.get_value("Sales Order", so_name, ["status", "docstatus"])
		if so_docstatus == 1 and status not in ("Paid", "Cancelled", "Closed"):
			frappe.db.set_value("Sales Order", so_name, "status", "Paid", update_modified=False)


def create_purchase_order(
	*,
	order_number: str,
	company: str,
	supplier: str,
	transaction_date,
	items: list[dict],
	branch: str | None = None,
	sales_order: str | None = None,
	taxes_and_charges_template: str | None = None,
):
	"""Shared builder for both masterdata_orderparts and
	masterdata_orderpekerjaanluar - both are a Purchase Order to a Supplier,
	just with a slightly different `detail` row shape upstream (see each
	sync module's own row-to-item mapping). No stock impact either way
	(submitting a Purchase Order alone never touches Item quantities -
	that only happens on a Purchase Receipt, which this integration never
	creates, consistent with OtoBitz owning physical stock)."""
	po = frappe.new_doc("Purchase Order")
	po.company = company
	po.supplier = supplier
	po.transaction_date = transaction_date
	po.schedule_date = transaction_date
	po.custom_otobitz_order_number = order_number
	if branch:
		po.custom_otobitz_branch = branch
	if sales_order:
		po.custom_otobitz_sales_order = sales_order
	set_period_fields(po, transaction_date)

	for item in items:
		po.append("items", item)

	if not po.items:
		frappe.throw(f"No resolvable Items for order {order_number}")

	if taxes_and_charges_template:
		po.taxes_and_charges = taxes_and_charges_template
		po.set("taxes", [])
		po.extend("taxes", get_taxes_and_charges("Purchase Taxes and Charges Template", taxes_and_charges_template))

	po.insert(ignore_permissions=True, ignore_mandatory=True)
	po.submit()
	# This integration never creates a Purchase Receipt or Purchase Invoice
	# for these (OtoBitz owns that process) - left alone, ERPNext's own
	# per_received/per_billed status logic would leave every single one of
	# these permanently stuck showing "To Receive and Bill", as if still
	# awaiting action on our side. "Closed" is PO's own native terminal
	# status (a plain self.status == "Closed" check, independent of
	# received/billed %) - the correct native fit here, not a custom
	# status like Sales Order's "Paid" needed.
	frappe.db.set_value("Purchase Order", po.name, "status", "Closed", update_modified=False)
	return po.name


def log_so_detail_rows(rows: list[dict]) -> int:
	"""Archive every raw `otoxpertsoandpart` line item into `OtoBitz SO Detail`,
	one row in, one row out - no grouping by `nomorwo`, no dependency on
	whether the matching Sales Order/Invoice was actually created.

	This is a pure log, decoupled from the business documents built from the
	same rows in sync_service_orders.py: a WO that gets skipped there (no
	resolvable customer, no resolvable items, cancelled, whatever) still shows
	up here exactly as OtoBitz sent it, because the archive's whole purpose is
	to answer "what did OtoBitz actually say" independent of how the
	downstream documents turned out. Dedup/upsert key is `nomorwo + kodereferensi`
	(one Work Order's rows are always distinct per item code - see the
	masterdata_sparepart-style flat-join notes in sync_service_orders.py) so a
	re-fetch of the same window (the sync's own overlap days, or a manual
	re-run) updates the existing row in place instead of duplicating it."""
	import json

	logged = 0
	for row in rows:
		nomorwo = clean(row.get("nomorwo"))
		kodereferensi = clean(row.get("kodereferensi"))
		if not nomorwo or not kodereferensi:
			continue
		dedup_key = f"{nomorwo}|{kodereferensi}"
		values = {
			"nomorwo": nomorwo,
			"nofaktur": clean(row.get("nofaktur")),
			"tanggal": getdate(row.get("tanggal")) if row.get("tanggal") else None,
			"statuswo": clean(row.get("statuswo")),
			"kode_cabang": clean(row.get("kode_cabang")),
			"namacabang": clean(row.get("namacabang")),
			"teknisi": clean(row.get("teknisi")),
			"customer_name": clean(row.get("nama")),
			"nopolisi": clean(row.get("nopolisi")),
			"kodereferensi": kodereferensi,
			"namareferensi": clean(row.get("namareferensi")),
			"jenisdoc": clean(row.get("jenisdoc")),
			"qty": flt(row.get("qty")),
			"harga": flt(row.get("harga")),
			"discperitem": flt(row.get("discperitem")),
			"subtotal": flt(row.get("subtotal")),
			"grandtotal": flt(row.get("grandtotal")),
			"nilaipenerimaan": flt(row.get("nilaipenerimaan")),
			"sisapiutang": flt(row.get("sisapiutang")),
			"raw_data": json.dumps(row, default=str, ensure_ascii=False),
		}
		values = {k: v for k, v in values.items() if v is not None}
		try:
			upsert("OtoBitz SO Detail", {"dedup_key": dedup_key}, values, ignore_mandatory=True)
			logged += 1
		except Exception:
			frappe.log_error(title=f"OtoBitz sync: failed to archive SO Detail row {dedup_key}")
	return logged


def get_or_create_uom(uom_name: str | None) -> str:
	uom_name = clean(uom_name) or "Nos"
	if not frappe.db.exists("UOM", uom_name):
		uom = frappe.new_doc("UOM")
		uom.uom_name = uom_name
		uom.insert(ignore_permissions=True, ignore_mandatory=True)
	return uom_name


def get_or_create_item_group(item_group: str) -> str:
	if not frappe.db.exists("Item Group", item_group):
		group = frappe.new_doc("Item Group")
		group.item_group_name = item_group
		group.parent_item_group = "All Item Groups"
		group.is_group = 0
		group.insert(ignore_permissions=True, ignore_mandatory=True)
	return item_group


def upsert(
	doctype: str,
	filters: dict,
	values: dict,
	*,
	ignore_mandatory: bool = False,
	create_only_fields: set[str] | None = None,
) -> tuple[str, bool, bool]:
	"""Idempotent get-or-create/update, mirroring the `frappe.db.exists(...)`
	guard used by erpnext's `frappe_crm_api.create_customer`.

	Skips the write entirely when nothing actually changed, so an hourly
	re-sync of unchanged upstream data doesn't bump `modified` on every
	record. Returns `(docname, created, updated)`.

	`create_only_fields` are set on insert but never re-compared/re-set on an
	update, even if the caller's `values` disagrees with what's stored. Item's
	`stock_uom` is the reason this exists: re-setting it to a value Python
	considers equal but that doesn't survive a round pythontrip->DB->Python
	identically (observed with mixed-case "Pcs"/"PCS" across OtoBitz branches
	for the same part) still flips `has_value_changed("stock_uom")`, which
	makes ERPNext's Item.validate() wipe and re-append the UOM conversion
	table - on enough repeat hourly runs that turns into N duplicate rows and
	a hard validation error. A field that practically never needs to change
	post-creation is safer left untouched on updates entirely.
	"""
	create_only_fields = create_only_fields or set()
	name = frappe.db.get_value(doctype, filters)
	if name:
		doc = frappe.get_doc(doctype, name)
		changed = False
		for fieldname, value in values.items():
			if fieldname in create_only_fields:
				continue
			if doc.get(fieldname) != value:
				doc.set(fieldname, value)
				changed = True
		if changed:
			doc.save(ignore_permissions=True)
		return name, False, changed

	doc = frappe.new_doc(doctype)
	doc.update(filters)
	doc.update(values)
	try:
		doc.insert(ignore_permissions=True, ignore_mandatory=ignore_mandatory)
	except frappe.DuplicateEntryError:
		# Two source rows produced the same free-text name (e.g. two vendors
		# both literally called "HENRI FITRIADI"). Disambiguate with the
		# lookup key rather than losing one of the two records.
		disambiguator = next(iter(filters.values()))
		doc.name = f"{doc.name} - {disambiguator}"
		doc.flags.name_set = True
		doc.insert(ignore_permissions=True, ignore_mandatory=ignore_mandatory)
	return doc.name, True, False


def upsert_safe(
	doctype: str,
	filters: dict,
	values: dict,
	*,
	ignore_mandatory: bool = False,
	create_only_fields: set[str] | None = None,
) -> tuple[str | None, bool, bool, bool]:
	"""`upsert()`, but catches any exception (bad data ERPNext's own
	validation rejects, an unexpected name collision, ...) and logs it
	instead of raising, so one malformed row never aborts the rest of a
	large batch. Returns `(docname, created, updated, failed)`."""
	try:
		name, created, updated = upsert(
			doctype, filters, values, ignore_mandatory=ignore_mandatory, create_only_fields=create_only_fields
		)
		return name, created, updated, False
	except Exception:
		frappe.log_error(title=f"OtoBitz sync: failed to upsert {doctype} {filters}")
		return None, False, False, True
