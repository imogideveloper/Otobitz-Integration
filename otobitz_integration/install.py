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
