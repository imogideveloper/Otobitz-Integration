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
