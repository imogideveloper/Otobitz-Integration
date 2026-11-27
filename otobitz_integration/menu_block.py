"""Per-user menu blocks (requested by User 2026-11-27).

Frappe access is the union of a user's Roles, so a single menu (DocType) can't be
taken away from one user without unticking a whole Role - e.g. closing Timesheet
for one employee meant unticking "Employee" and losing ~50 other menus. This adds
the missing "minus" step:

    what a user can open = (menus from their Roles) - (menus blocked for that user)

The blocked DocTypes live on the User itself (Custom Field `custom_blocked_menus`,
a JSON list, permlevel 1 so only System Manager can write it) and are set from the
User form's "Module Access" card. They apply after Save, like Role changes.

Enforcement goes through Frappe's own wildcard hooks, so it covers every DocType:
  * has_permission["*"]               - opening/creating/editing a document is denied
  * permission_query_conditions["*"]  - list views, link search and reports via get_list
                                        return nothing
  * extend_bootinfo                   - the menu disappears from the sidebar, search bar
                                        and "New" shortcuts
Administrator is never blocked, and the DocTypes in PROTECTED can't be blocked so a
user can't be locked out of their own profile, check-in or overtime approval.

The opposite direction (open one menu for one user without a whole Role) is the
`custom_granted_menus` list further down, synced on Save to the user's
"Akses Individual - <user>" Role. Together they back the Module Access toggles:
    open = (menus from Roles - custom_blocked_menus) + custom_granted_menus
"""

import json

import frappe
from frappe import _

FIELD = "custom_blocked_menus"
CACHE_KEY = "otobitz_blocked_menus"

# Needed for the desk/mobile app to work at all for an employee or supervisor.
PROTECTED = frozenset(
	{
		"User",
		"Employee",
		"Employee Checkin",
		"Overtime",
	}
)

# frappe.utils.user.UserPermissions lists that feed the desk UI (sidebar, search, new).
_BOOT_LISTS = (
	"can_create",
	"can_select",
	"can_read",
	"can_write",
	"can_submit",
	"can_cancel",
	"can_delete",
	"can_search",
	"can_get_report",
	"can_import",
	"can_export",
	"can_print",
	"can_email",
	"all_read",
)


def parse(value) -> list[str]:
	"""JSON list stored on the User -> clean, sorted list of DocType names."""
	if not value:
		return []
	try:
		items = json.loads(value) if isinstance(value, str) else value
	except ValueError:
		return []
	if not isinstance(items, list):
		return []
	return sorted({str(d).strip() for d in items if d and str(d).strip()})


def get_blocked_menus(user: str | None = None) -> frozenset[str]:
	user = user or frappe.session.user
	if not user or user in ("Administrator", "Guest"):
		return frozenset()

	local_cache = getattr(frappe.local, "otobitz_blocked_menus", None)
	if local_cache is None:
		local_cache = frappe.local.otobitz_blocked_menus = {}
	if user in local_cache:
		return local_cache[user]

	def load():
		# The Custom Field may not exist yet (e.g. fixtures not synced after a deploy): no blocks then,
		# instead of an "Unknown column" error on every permission check.
		if not frappe.get_meta("User").has_field(FIELD):
			return []
		return parse(frappe.db.get_value("User", user, FIELD))

	blocked = frozenset(frappe.cache.hget(CACHE_KEY, user, load) or [])
	local_cache[user] = blocked
	return blocked


def is_blocked(doctype: str, user: str | None = None) -> bool:
	return bool(doctype) and doctype not in PROTECTED and doctype in get_blocked_menus(user)


def has_permission(doc, ptype=None, user=None, debug=False):
	"""has_permission["*"]: must return True when there's no objection - Frappe treats
	any falsy return (None included) as a denial."""
	try:
		if is_blocked(doc.doctype, user):
			return False
	except Exception:
		# Never let a fault here lock every user out of every document.
		frappe.log_error(title="otobitz menu_block.has_permission")
	return True


def permission_query_conditions(user=None, doctype=None):
	"""permission_query_conditions["*"]: empty result for a blocked DocType."""
	try:
		if doctype and is_blocked(doctype, user):
			return "1=0"
	except Exception:
		frappe.log_error(title="otobitz menu_block.permission_query_conditions")
	return ""


def extend_bootinfo(bootinfo):
	"""Hide blocked DocTypes from the desk: permission lists and the module sidebar.
	Runs on every desk load (after the cached part of the boot), so a block shows up
	on the user's next page load."""
	try:
		_hide_blocked(bootinfo)
	except Exception:
		# A fault here must never stop the desk from loading.
		frappe.log_error(title="otobitz menu_block.extend_bootinfo")


def _hide_blocked(bootinfo):
	blocked = get_blocked_menus() - PROTECTED
	if not blocked:
		return

	user_info = bootinfo.get("user")
	if user_info:
		for key in _BOOT_LISTS:
			values = user_info.get(key)
			if isinstance(values, list):
				user_info[key] = [d for d in values if d not in blocked]

	sidebars = bootinfo.get("workspace_sidebar_item")
	if isinstance(sidebars, dict):
		for sidebar in sidebars.values():
			items = sidebar.get("items") if isinstance(sidebar, dict) else None
			if isinstance(items, list):
				sidebar["items"] = [
					i for i in items if not (i.get("link_type") == "DocType" and i.get("link_to") in blocked)
				]


def validate_user(doc, method=None):
	"""Keep the stored list clean and make sure only a System Manager changes it."""
	if not doc.meta.has_field(FIELD):
		return
	new = parse(doc.get(FIELD))
	old = parse(doc.get_db_value(FIELD)) if not doc.is_new() else []
	if new != old and frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only a System Manager can change blocked menus."), frappe.PermissionError)

	protected = [d for d in new if d in PROTECTED]
	if protected:
		frappe.msgprint(_("These menus can't be blocked and were kept open: {0}").format(", ".join(protected)))
	cleaned = [d for d in new if d not in PROTECTED and frappe.db.exists("DocType", d)]

	granted = _validate_granted(doc)
	if granted:
		# A menu is either opened for this user or turned off, never both.
		cleaned = [d for d in cleaned if d not in granted]
	doc.set(FIELD, json.dumps(cleaned) if cleaned else None)


# --- Individual access (menus opened for one user only) -----------------------
#
# Same mechanism the Module Access toggles always used (user_branch_access:
# a Role "Akses Individual - <user>" held only by this user, with Custom DocPerm
# read rows), but now driven by a list saved with the User form instead of
# applying instantly on every click. `custom_granted_menus` = None means "not
# managed from the list yet" (users set up with the old instant toggles), so
# nothing is synced for them until an admin changes a toggle and saves.

GRANT_FIELD = "custom_granted_menus"


def _validate_granted(doc) -> list[str] | None:
	if not doc.meta.has_field(GRANT_FIELD) or doc.get(GRANT_FIELD) in (None, ""):
		return None
	new = parse(doc.get(GRANT_FIELD))
	old = parse(doc.get_db_value(GRANT_FIELD)) if not doc.is_new() else []
	if new != old and frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only a System Manager can change menu access."), frappe.PermissionError)

	granted = [d for d in new if frappe.db.exists("DocType", d)]
	doc.set(GRANT_FIELD, json.dumps(granted))  # "[]" still means "managed"
	if granted:
		from otobitz_integration.otobitz_integration.user_branch_access import _dedicated_role_for

		role_name = _dedicated_role_for(doc.name)
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": 1, "is_custom": 1}).insert(
				ignore_permissions=True
			)
		if not any(r.role == role_name for r in doc.get("roles") or []):
			doc.append("roles", {"role": role_name})
	return granted


def sync_granted_menus(doc, method=None):
	"""After Save: make the user's dedicated Role read exactly the saved list."""
	if not doc.meta.has_field(GRANT_FIELD) or doc.get(GRANT_FIELD) in (None, ""):
		return
	from otobitz_integration.otobitz_integration.user_branch_access import (
		_dedicated_role_for,
		_set_one_doctype_access,
	)

	role_name = _dedicated_role_for(doc.name)
	if not frappe.db.exists("Role", role_name):
		return
	wanted = set(parse(doc.get(GRANT_FIELD)))
	current = set(
		frappe.get_all(
			"Custom DocPerm", filters={"role": role_name, "permlevel": 0, "read": 1}, pluck="parent"
		)
	)
	for doctype in sorted(wanted - current):
		_set_one_doctype_access(role_name, doctype, True)
	for doctype in sorted(current - wanted):
		_set_one_doctype_access(role_name, doctype, False)


def clear_user_cache(doc, method=None):
	frappe.cache.hdel(CACHE_KEY, doc.name)
	getattr(frappe.local, "otobitz_blocked_menus", {}).pop(doc.name, None)


@frappe.whitelist()
def get_role_profiles() -> list[dict]:
	"""Role Profiles with their Roles, for the quick-pick chips on the User form."""
	frappe.only_for("System Manager")
	return [
		{
			"name": name,
			"roles": frappe.get_all(
				"Has Role", filters={"parent": name, "parenttype": "Role Profile"}, pluck="role", order_by="idx"
			),
		}
		for name in frappe.get_all("Role Profile", pluck="name", order_by="name")
	]


@frappe.whitelist()
def get_protected_menus() -> list[str]:
	return sorted(PROTECTED)
