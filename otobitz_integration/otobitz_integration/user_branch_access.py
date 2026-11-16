# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""Friendlier front-end for Branch-scoped User Permission records, surfaced
directly on the User form's Roles & Permissions tab (otobitz_integration's
"User Branch Access" Client Script) instead of behind the native
"Permissions" dropdown.

No new doctype/schema here - this just wraps plain `User Permission` rows
(allow="Branch") that Frappe's own permission engine already enforces
automatically against every doctype carrying a Link field to Branch
(confirmed live: once one of these exists for a user, their visible Sales
Order/Sales Invoice/Purchase Order/etc rows - and search results - are
filtered to that Branch, with no per-doctype code needed). Reusing that
native mechanism rather than inventing a parallel one means every current
and future Branch-linked doctype is covered automatically.

`apply_to_all_doctypes=1` is what makes one User Permission row restrict
every Branch-linked doctype at once, rather than needing a separate row per
doctype (the `applicable_for` alternative)."""

import frappe


@frappe.whitelist()
def get_user_branches(user: str) -> list[dict]:
	frappe.only_for("System Manager")
	return frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": "Branch"},
		fields=["name", "for_value as branch"],
		order_by="for_value",
	)


@frappe.whitelist()
def add_user_branch(user: str, branch: str) -> None:
	frappe.only_for("System Manager")
	if frappe.db.exists("User Permission", {"user": user, "allow": "Branch", "for_value": branch}):
		return
	frappe.get_doc(
		{
			"doctype": "User Permission",
			"user": user,
			"allow": "Branch",
			"for_value": branch,
			"apply_to_all_doctypes": 1,
		}
	).insert(ignore_permissions=True)


@frappe.whitelist()
def remove_user_branch(user_permission_name: str) -> None:
	frappe.only_for("System Manager")
	frappe.delete_doc("User Permission", user_permission_name, ignore_permissions=True)


@frappe.whitelist()
def get_workspace_access_map() -> dict[str, dict]:
	"""One module (Workspace) -> its own Role gate plus a breakdown of every
	DocType link it holds -> the Roles that can read that DocType. Lets the
	User form's live preview show not just "is this module visible at all"
	but "which specific menu item in it can this user actually open" -
	e.g. Buying's Purchase Order link might read for Purchase User while
	its Approval Setting link doesn't, even though both sit in the same
	module.

	Two separate permission layers feed this, both already enforced
	natively (nothing new to build for the enforcement itself, only for
	showing it clearly in one place): Workspace.roles gates the whole
	module exactly like desktop.py's `is_permitted()` does for the Desk
	sidebar (empty roles = visible to everyone); DocPerm/Custom DocPerm
	(read=1 rows) gates each individual DocType link the same way list
	views/search already respect per-role.

	Only `type == "Link"` entries pointing at a real DocType are counted -
	Card Break separators and Page/Report/URL links aren't DocType-gated
	the same way and would just show as "no roles required" noise.

	Read-only by design - see get_workspace_role_map()'s original docstring
	for why: whether a module/doctype SHOULD be role-gated is a judgment
	call for whoever administers Roles and Workspaces, not something to
	infer or auto-populate here."""
	frappe.only_for("System Manager")

	# Custom DocPerm is an all-or-nothing override per doctype, same as
	# Frappe's own permission_manager.get_permissions(): the instant a
	# doctype has ANY Custom DocPerm row (set_doctype_access() above
	# creates one the first time a toggle touches that doctype), its base
	# DocPerm rows stop applying entirely and only the Custom ones count -
	# reading DocPerm alone here (an earlier version of this function did
	# exactly that) meant toggling a doctype's access never changed what
	# this preview showed, no matter how many times it was flipped, since
	# the toggle was never touching the table being read from.
	custom_rows = frappe.get_all("Custom DocPerm", fields=["parent", "role", "read"])
	base_rows = frappe.get_all("DocPerm", fields=["parent", "role", "read"])

	custom_doctypes = {row.parent for row in custom_rows}
	roles_by_doctype: dict[str, set[str]] = {}
	for row in base_rows:
		if row.read and row.parent not in custom_doctypes:
			roles_by_doctype.setdefault(row.parent, set()).add(row.role)
	for row in custom_rows:
		if row.read:
			roles_by_doctype.setdefault(row.parent, set()).add(row.role)

	workspaces = frappe.get_all(
		"Workspace", filters={"public": 1, "is_hidden": 0}, fields=["name", "title"], order_by="title"
	)
	result = {}
	for ws in workspaces:
		ws_roles = frappe.get_all("Has Role", filters={"parent": ws.name, "parenttype": "Workspace"}, pluck="role")

		link_rows = frappe.get_all(
			"Workspace Link",
			filters={"parent": ws.name, "parenttype": "Workspace", "type": "Link", "link_type": "DocType"},
			fields=["label", "link_to"],
			order_by="idx",
		)
		links = []
		seen_doctypes = set()
		for row in link_rows:
			doctype = row.link_to
			if not doctype or doctype in seen_doctypes:
				continue
			seen_doctypes.add(doctype)
			links.append(
				{
					"label": row.label or doctype,
					"doctype": doctype,
					"roles": sorted(roles_by_doctype.get(doctype, [])),
				}
			)

		result[ws.title or ws.name] = {"roles": ws_roles, "links": links}
	return result


# One auto-managed Role per user, holding only that user's own per-doctype
# overrides - keeps a toggle here from ever touching a shared Role's
# permissions (ticking "Asset Category" on for this user must not also
# grant it to every other user who happens to share a Role with them).
DEDICATED_ROLE_PREFIX = "Akses Individual - "


def _dedicated_role_for(user: str) -> str:
	return f"{DEDICATED_ROLE_PREFIX}{user}"


def _ensure_dedicated_role(user: str) -> str:
	role_name = _dedicated_role_for(user)
	if not frappe.db.exists("Role", role_name):
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 1,
				"is_custom": 1,
			}
		).insert(ignore_permissions=True)

	user_doc = frappe.get_doc("User", user)
	if not any(r.role == role_name for r in user_doc.roles):
		user_doc.append("roles", {"role": role_name})
		user_doc.save(ignore_permissions=True)
	return role_name


def _set_one_doctype_access(role_name: str, doctype: str, enabled: bool) -> None:
	"""Toggle `role_name`'s read permission on `doctype` - the same Custom
	DocPerm mechanism the native Permission Manager page itself uses
	(add_permission()/a row update).

	Checks for an existing Custom DocPerm row directly rather than calling
	add_permission() unconditionally and trusting it to no-op safely:
	add_permission()'s own "already exists" guard matches on
	parent+role+permlevel+if_owner only, NOT on whether `read` is actually
	1 on that row - a stale row left at read=0 (e.g. from an interrupted
	earlier toggle) would make it silently skip turning read back on,
	leaving the toggle looking like it did nothing."""
	from frappe.core.page.permission_manager.permission_manager import remove as remove_doc_permission
	from frappe.permissions import add_permission

	existing = frappe.db.get_value(
		"Custom DocPerm", {"parent": doctype, "role": role_name, "permlevel": 0, "if_owner": 0}
	)
	if enabled:
		if existing:
			frappe.db.set_value("Custom DocPerm", existing, "read", 1)
		else:
			add_permission(doctype, role_name, 0, "read")
	elif existing:
		try:
			remove_doc_permission(doctype, role_name, 0)
		except frappe.ValidationError:
			# "There must be at least one permission rule" - this doctype's
			# only remaining rule was this user's own override. Leaving it
			# in place is safer than the doctype ending up with zero rules
			# for anyone.
			pass
	frappe.clear_cache(doctype=doctype)


@frappe.whitelist()
def set_doctype_access(user: str, doctype: str, enabled) -> dict:
	"""Toggle this user's own dedicated Role's read permission on one
	DocType link, scoped to a Role that only this one user holds.

	This can only ever ADD access, never take it away outright: if another
	Role already checked above also grants read on this doctype, switching
	this toggle off removes only this user's own override - the doctype
	stays visible to them via that other Role, same as it would if an
	admin unticked one of several Permission Manager rules. Flagged to the
	caller in the UI rather than silently implying a hard block this
	mechanism can't actually provide.

	Returns the dedicated Role's name so the caller can patch its own
	in-memory view of the user's roles without a full document reload."""
	frappe.only_for("System Manager")
	role_name = _ensure_dedicated_role(user)
	_set_one_doctype_access(role_name, doctype, bool(frappe.utils.cint(enabled)))
	return {"role": role_name}


@frappe.whitelist()
def set_doctypes_access(user: str, doctypes, enabled) -> dict:
	"""Bulk version of set_doctype_access() for the module-level "turn
	everything in this module on/off" switch - one dedicated-Role lookup
	instead of one per doctype, and all the Custom DocPerm writes in a
	single request instead of a round trip per item (a module can hold
	20-30 links)."""
	frappe.only_for("System Manager")
	if isinstance(doctypes, str):
		doctypes = frappe.parse_json(doctypes)

	role_name = _ensure_dedicated_role(user)
	enabled = bool(frappe.utils.cint(enabled))
	for doctype in doctypes:
		_set_one_doctype_access(role_name, doctype, enabled)
	return {"role": role_name}


# --- Navbar Branch Switcher -------------------------------------------
#
# Separate from everything above: those are admin tools (System Manager
# only) for configuring what ANOTHER user can see. These two are for the
# logged-in user themselves, switching which of their OWN already-assigned
# Branches (the "Cabang yang Ditugaskan" User Permission rows) is their
# current default - so creating a new Sales Order/Purchase Order/etc
# pre-fills its Branch field with whichever one they last switched to,
# without having to pick it by hand every time. No System Manager gate:
# any logged-in user manages their own default, same as Frappe's own
# per-user settings.


@frappe.whitelist()
def get_my_branches() -> list[dict]:
	rows = frappe.get_all(
		"User Permission",
		filters={"user": frappe.session.user, "allow": "Branch"},
		fields=["name", "for_value as branch", "is_default"],
		order_by="for_value",
	)
	# custom_otobitz_branch_code (e.g. "104") for the navbar switcher's own
	# compact label - the full Branch name ("OTOXPERT GALUH MAS KARAWANG BY
	# AUTO2000") is still there for the dropdown's own list, just not
	# forced into the collapsed toggle itself.
	codes = {
		b.name: b.custom_otobitz_branch_code
		for b in frappe.get_all(
			"Branch",
			filters={"name": ["in", [r.branch for r in rows]]},
			fields=["name", "custom_otobitz_branch_code"],
		)
	}
	for row in rows:
		row["code"] = codes.get(row.branch) or row.branch
	return rows


@frappe.whitelist()
def set_my_default_branch(user_permission_name: str) -> None:
	"""Marks one of the current user's own Branch User Permission rows as
	default - the same `is_default` flag Frappe itself uses to decide which
	value pre-fills a Link field when a user is restricted to more than
	one. Scoped to frappe.session.user rather than taking a user param, so
	this can only ever change the caller's own default, never someone
	else's."""
	row = frappe.db.get_value("User Permission", user_permission_name, ["user", "allow"], as_dict=True)
	if not row or row.user != frappe.session.user or row.allow != "Branch":
		frappe.throw(frappe._("Not allowed"))

	frappe.db.set_value(
		"User Permission",
		{"user": frappe.session.user, "allow": "Branch"},
		"is_default",
		0,
	)
	frappe.db.set_value("User Permission", user_permission_name, "is_default", 1)
	frappe.clear_cache(user=frappe.session.user)
