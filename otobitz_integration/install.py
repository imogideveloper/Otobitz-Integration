# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""Lets a fresh install pick up OtoBitz API credentials from this site's own
site_config.json instead of requiring them to be typed into the Settings
form again - and, unlike hardcoding them into this app's source, keeps them
out of git entirely (site_config.json is never committed).

On a new server, before (or right after) `bench install-app otobitz_integration`:

	bench --site <site> set-config otobitz_base_url "https://..."
	bench --site <site> set-config otobitz_username "..."
	bench --site <site> set-config otobitz_password "..."
"""

import frappe

CONFIG_KEYS = {
	"base_url": "otobitz_base_url",
	"username": "otobitz_username",
	"password": "otobitz_password",
}


def after_app_install(app_name):
	if app_name != "otobitz_integration":
		return

	from otobitz_integration.otobitz_integration.sync.common import ensure_imogibot_user

	ensure_imogibot_user()

	settings = frappe.get_single("OtoBitz Settings")
	changed = False
	for fieldname, conf_key in CONFIG_KEYS.items():
		value = frappe.conf.get(conf_key)
		if value and not settings.get(fieldname):
			settings.set(fieldname, value)
			changed = True

	if changed:
		settings.save(ignore_permissions=True)
		frappe.db.commit()


def reapply_fixtures():
	"""Re-import this app's fixtures after every migrate.

	imogi_finance is installed after this app and ships fixtures with the same
	names (e.g. 'Sales Order-main-field_order'); its sync would otherwise win.
	"""
	from frappe.utils.fixtures import import_fixtures

	frappe.flags.in_fixtures = True
	try:
		import_fixtures("otobitz_integration")
	finally:
		frappe.flags.in_fixtures = False
	frappe.clear_cache()

	# Runs on every migrate (not just after_app_install) so a site that
	# already had this app installed before IMOGIBOT_USER existed - e.g.
	# production - picks it up on its next `bench migrate` too.
	from otobitz_integration.otobitz_integration.sync.common import ensure_imogibot_user

	ensure_imogibot_user()
	frappe.db.commit()


# Desktop (/desk) modules an auto workshop (bengkel) has no use for (user, 2026-11-05): hidden on every migrate,
# since migrate syncs the standard icons back from the apps' files. Still reachable by search / URL.
HIDDEN_DESKTOP_ICONS = ("Framework", "Frappe Framework", "Manufacturing", "Subcontracting", "Projects")
APP_ICON = "OtoBitz Integration"
APP_LOGO = "/assets/otobitz_integration/images/otobitz-logo.svg"


def hide_desktop_icons():
	changed = False
	# (an app icon's children too: with Framework hidden the desk lifts its Users / System / Build... onto the page)
	children = frappe.get_all("Desktop Icon", filters={"parent_icon": ["in", HIDDEN_DESKTOP_ICONS]}, pluck="name")
	for name in (*HIDDEN_DESKTOP_ICONS, *children):
		if frappe.db.exists("Desktop Icon", name) and not frappe.db.get_value("Desktop Icon", name, "hidden"):
			frappe.db.set_value("Desktop Icon", name, "hidden", 1, update_modified=False)
			changed = True
	# the app's own icon: green like Imogi Payroll's, not the grey letter the desk draws for an icon with no image
	# (the icon is the site's own record, made with the workspace, so it is set here and not shipped)
	if frappe.db.exists("Desktop Icon", APP_ICON) and frappe.db.get_value("Desktop Icon", APP_ICON, "logo_url") != APP_LOGO:
		frappe.db.set_value("Desktop Icon", APP_ICON, "logo_url", APP_LOGO, update_modified=False)
		changed = True
	if changed:
		frappe.db.commit()
	# (the desk caches each user's icons)
	frappe.cache.delete_key("desktop_icons")


def add_service_package_to_selling_workspace():
	"""Adds a link to this app's own "Service Package" DocType into the core
	erpnext "Selling" workspace, right alongside Customer/Customer Group/etc
	under its "Settings" card - reported live: "service package itu jangan
	disimpan di doctype Otobitz Integration, tapi disimpen di bagian module
	selling... bagian setup".

	Deliberately NOT tracked as this app's own fixture for the whole
	"Workspace Selling" document - erpnext owns that document outright, and
	exporting it wholesale as an otobitz_integration fixture risks either
	app's own fixture-sync silently reverting the other's version of it on
	a later migrate (confirmed live elsewhere in this app: reapply_fixtures()
	above exists for exactly this class of problem, imogi_finance's own
	fixtures winning a naming collision). A small, idempotent append here
	instead, re-checked on every migrate (same as this module's other
	after_migrate hooks) so it's self-healing if erpnext's own workspace
	sync ever resets Selling back to its shipped state.

	Also strips the old link from this app's own "OtoBitz Integration"
	workspace - confirmed live, removing that entry from this app's
	workspace JSON fixture didn't retroactively delete it from the
	already-existing Workspace row on the next `bench migrate` (fixture
	import upserts, it doesn't prune), leaving Service Package listed in
	BOTH workspaces at once. Done here (in code, re-checked every migrate)
	rather than a one-off manual delete, so it's gone for good regardless
	of whatever fixture-sync does or doesn't do to that row."""
	if not frappe.db.exists("Workspace", "Selling"):
		return
	doc = frappe.get_doc("Workspace", "Selling")
	already_in_selling = any(l.link_to == "Service Package" for l in doc.links)

	if not already_in_selling:
		new_row = doc.append(
			"links",
			{"type": "Link", "label": "Service Package", "link_to": "Service Package", "link_type": "DocType"},
		)
		# Right after "Campaign", the last entry of the "Settings" card group -
		# the same group Customer Group/Contact/Address/Territory already sit
		# in. Falls back to leaving it appended at the end (still a valid,
		# just less tidily-grouped, link) if that label's ever renamed/removed
		# upstream.
		insert_at = next((i for i, l in enumerate(doc.links) if l.label == "Campaign"), None)
		if insert_at is not None:
			doc.links.remove(new_row)
			doc.links.insert(insert_at + 1, new_row)
			for idx, l in enumerate(doc.links, start=1):
				l.idx = idx
		doc.save(ignore_permissions=True)
		frappe.db.commit()

	if frappe.db.exists("Workspace", "OtoBitz Integration"):
		otobitz_ws = frappe.get_doc("Workspace", "OtoBitz Integration")
		stale_links = [l for l in otobitz_ws.links if l.link_to == "Service Package"]
		if stale_links:
			for l in stale_links:
				otobitz_ws.links.remove(l)
			for idx, l in enumerate(otobitz_ws.links, start=1):
				l.idx = idx
			otobitz_ws.save(ignore_permissions=True)
			frappe.db.commit()

	# The Desk's own left sidebar tree does NOT read from "Workspace.links"
	# above at all - confirmed live, editing that field left the sidebar
	# showing the exact same list as before. It reads from a separate
	# "Workspace Sidebar" document (one per workspace, its own "items" child
	# table) that's only ever auto-(re)built for a workspace that doesn't
	# have one yet - an already-existing one (every core workspace, Selling
	# included) never gets refreshed from its Workspace's own links again.
	# Both documents have to be kept in step by hand.
	_add_service_package_to_workspace_sidebar("Selling", after_label="Campaign")
	_remove_service_package_from_workspace_sidebar("OtoBitz Integration")


def _add_service_package_to_workspace_sidebar(sidebar_title: str, after_label: str) -> None:
	if not frappe.db.exists("Workspace Sidebar", sidebar_title):
		return
	doc = frappe.get_doc("Workspace Sidebar", sidebar_title)
	if any(i.link_to == "Service Package" for i in doc.items):
		return

	new_row = doc.append(
		"items",
		{"type": "Link", "label": "Service Package", "link_to": "Service Package", "link_type": "DocType", "child": 1},
	)
	insert_at = next((i for i, it in enumerate(doc.items) if it.label == after_label), None)
	if insert_at is not None:
		doc.items.remove(new_row)
		doc.items.insert(insert_at + 1, new_row)
		for idx, it in enumerate(doc.items, start=1):
			it.idx = idx
	# Not this function's job to fix some unrelated pre-existing bad row in
	# this same sidebar (confirmed live, Selling's own had one: "Import
	# Data" pointing at a Page that no longer resolves) - Document.save()
	# validates every link on the whole document, not just the one just
	# appended here, so a single already-broken row would otherwise block
	# this save entirely.
	doc.flags.ignore_links = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()


def _remove_service_package_from_workspace_sidebar(sidebar_title: str) -> None:
	if not frappe.db.exists("Workspace Sidebar", sidebar_title):
		return
	doc = frappe.get_doc("Workspace Sidebar", sidebar_title)
	stale = [i for i in doc.items if i.link_to == "Service Package"]
	if not stale:
		return
	for i in stale:
		doc.items.remove(i)
	for idx, it in enumerate(doc.items, start=1):
		it.idx = idx
	doc.flags.ignore_links = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()


def ensure_salesperson_default():
	"""One-off (idempotent): Sales Order-custom_salesperson defaults to the
	logged-in user ("__user") for anyone building a Sales Order by hand in
	Desk - synced orders override this explicitly to IMOGIBOT_USER (see
	_create_sales_order in sync_service_orders.py)."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	exists = frappe.db.exists(
		"Property Setter",
		{"doc_type": "Sales Order", "field_name": "custom_salesperson", "property": "default"},
	)
	if exists:
		return "already exists: " + exists

	ps = make_property_setter(
		"Sales Order",
		"custom_salesperson",
		"default",
		"__user",
		"Text",
		is_system_generated=False,
	)
	ps.module = "OtoBitz Integration"
	ps.save(ignore_permissions=True)
	frappe.db.commit()
	return "created: " + ps.name
