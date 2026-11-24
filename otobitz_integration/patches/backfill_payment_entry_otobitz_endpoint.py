import frappe


def execute():
	"""custom_otobitz_endpoint already existed as a Select field on Payment
	Entry (options: penerimaanuang / penerimaanuangmukabooking /
	pengeluaranuang) but nothing ever actually set it - see each sync
	module's own _create_payment_entry()/_create_advance_payment_entry()
	fix alongside this patch. Reported live: no way to tell a regular
	invoice payment apart from a booking advance without reading the
	References table or guessing from the receipt number's own prefix.

	Backfills every already-synced Payment Entry from before that fix,
	classified the same way a human would have to by hand: party_type
	Supplier is always a pengeluaranuang (sync_pengeluaran.py's only
	Payment Entry path); among Customer-party ones, a receipt number
	starting "BKS-" is sync_booking.py's own allocation_ref format
	(confirmed live - see that module's own docstring), everything else
	with a receipt number set is a regular sync_penerimaan.py invoice
	payment. Only touches rows where the field is still empty, so this is
	safe to re-run."""
	frappe.db.sql(
		"""
		update `tabPayment Entry`
		set custom_otobitz_endpoint = 'pengeluaranuang'
		where party_type = 'Supplier'
			and ifnull(custom_otobitz_receipt_number, '') != ''
			and ifnull(custom_otobitz_endpoint, '') = ''
		"""
	)
	frappe.db.sql(
		"""
		update `tabPayment Entry`
		set custom_otobitz_endpoint = 'penerimaanuangmukabooking'
		where party_type = 'Customer'
			and custom_otobitz_receipt_number like 'BKS-%'
			and ifnull(custom_otobitz_endpoint, '') = ''
		"""
	)
	frappe.db.sql(
		"""
		update `tabPayment Entry`
		set custom_otobitz_endpoint = 'penerimaanuang'
		where party_type = 'Customer'
			and ifnull(custom_otobitz_receipt_number, '') != ''
			and custom_otobitz_receipt_number not like 'BKS-%'
			and ifnull(custom_otobitz_endpoint, '') = ''
		"""
	)
	frappe.db.commit()
