app_name = "otobitz_integration"
app_title = "OtoBitz Integration"
app_publisher = "Otoexpert"
app_description = "Realtime sync from OtoBitzLite/OtoXpert into ERPNext"
app_email = "imogierpnext@gmail.com"
app_license = "mit"

# Apps
# ------------------

required_apps = ["frappe/erpnext"]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "otobitz_integration",
# 		"logo": "/assets/otobitz_integration/logo.png",
# 		"title": "OtoBitz Integration",
# 		"route": "/otobitz_integration",
# 		"has_permission": "otobitz_integration.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/otobitz_integration/css/otobitz_integration.css"
# app_include_js = "/assets/otobitz_integration/js/otobitz_integration.js"

# include js, css files in header of web template
# web_include_css = "/assets/otobitz_integration/css/otobitz_integration.css"
# web_include_js = "/assets/otobitz_integration/js/otobitz_integration.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "otobitz_integration/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "otobitz_integration/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "otobitz_integration.utils.jinja_methods",
# 	"filters": "otobitz_integration.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "otobitz_integration.install.before_install"
# after_install = "otobitz_integration.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "otobitz_integration.uninstall.before_uninstall"
# after_uninstall = "otobitz_integration.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

after_app_install = "otobitz_integration.install.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "otobitz_integration.utils.before_app_uninstall"
# after_app_uninstall = "otobitz_integration.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "otobitz_integration.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "otobitz_integration.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["otobitz_integration.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Sales Order": {
		"before_insert": "otobitz_integration.sales_order.set_next_service_date"
	},
	"Purchase Order": {
		"validate": "otobitz_integration.purchase_order.track",
		"before_update_after_submit": "otobitz_integration.purchase_order.track"
	},
	"Payment Entry": {
		"on_submit": "otobitz_integration.purchase_order.on_payment_entry",
		"on_cancel": "otobitz_integration.purchase_order.on_payment_entry"
	},
	"Purchase Invoice": {
		"on_submit": "otobitz_integration.purchase_order.on_purchase_invoice",
		"on_cancel": "otobitz_integration.purchase_order.on_purchase_invoice"
	}
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"hourly_long": [
		"otobitz_integration.otobitz_integration.sync.orchestrator.trigger_hourly_sync",
	],
}

after_migrate = ["otobitz_integration.install.reapply_fixtures"]

# Fixtures
# --------

fixtures = [
	{"dt": "Custom Field", "filters": [["module", "=", "OtoBitz Integration"]]},
	{"dt": "Property Setter", "filters": [["module", "=", "OtoBitz Integration"]]},
	{"dt": "Client Script", "filters": [["module", "=", "OtoBitz Integration"]]},
	{"dt": "List View Settings", "filters": [["name", "in", ["Sales Order", "Sales Invoice", "Payment Entry"]]]},
]

# Testing
# -------

# before_tests = "otobitz_integration.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "otobitz_integration.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "otobitz_integration.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "otobitz_integration.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["otobitz_integration.utils.before_request"]
# after_request = ["otobitz_integration.utils.after_request"]

# Job Events
# ----------
# before_job = ["otobitz_integration.utils.before_job"]
# after_job = ["otobitz_integration.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"otobitz_integration.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

