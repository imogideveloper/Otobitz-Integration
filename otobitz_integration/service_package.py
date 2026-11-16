import frappe
from frappe import _
from frappe.utils import cint


@frappe.whitelist()
def get_package_items(package):
	"""Lines of a Service Package for the Sales Order form (item, qty, uom, rate)."""
	doc = frappe.get_doc("Service Package", package)
	doc.check_permission("read")
	if not doc.is_active:
		frappe.throw(_("Paket {0} tidak aktif.").format(package))
	return [
		{"item_code": r.item_code, "qty": r.qty, "uom": r.uom, "rate": r.rate or 0}
		for r in doc.items
	]


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def package_query(doctype, txt, searchfield, start, page_len, filters):
	"""Link query for Sales Order's Service Package field: active packages for the
	order's company, branch, vehicle model and transmission. A filter whose value is
	empty on the order is skipped, so a half-filled order still sees every package."""
	filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	cond, vals = [], {"txt": f"%{txt}%", "start": cint(start), "page_len": cint(page_len)}
	if filters.get("company"):
		cond.append("(sp.company = %(company)s or ifnull(sp.company, '') = '')")
		vals["company"] = filters["company"]
	if filters.get("branch"):
		cond.append(
			"(sp.is_all_branch = 1 or exists (select 1 from `tabService Package Branch` b "
			"where b.parent = sp.name and b.branch = %(branch)s))"
		)
		vals["branch"] = filters["branch"]
	if filters.get("vehicle_model"):
		cond.append("(ifnull(sp.vehicle_model, '') = '' or sp.vehicle_model = %(model)s)")
		vals["model"] = filters["vehicle_model"]
	if filters.get("transmission"):
		cond.append("(ifnull(sp.transmission, '') in ('', 'ALL') or sp.transmission = %(trans)s or %(trans)s = 'ALL')")
		vals["trans"] = filters["transmission"]
	where = (" and " + " and ".join(cond)) if cond else ""
	return frappe.db.sql(
		f"""select sp.name, sp.package_name, sp.code from `tabService Package` sp
		where sp.is_active = 1
		and (sp.name like %(txt)s or sp.package_name like %(txt)s or ifnull(sp.code, '') like %(txt)s){where}
		order by sp.package_name
		limit %(start)s, %(page_len)s""",
		vals,
	)
