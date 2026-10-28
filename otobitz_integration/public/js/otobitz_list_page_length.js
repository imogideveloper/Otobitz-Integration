// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

// Desk-wide: default every List View's page size to 100 instead of Frappe's
// own `frappe.is_large_screen() ? 100 : 20`. That check is
// `window.innerHeight > 1180` - a height almost no real desktop browser
// window reaches even maximized on a 1080p screen - so in practice every
// list was defaulting to 20 regardless of actual screen size. Only touches
// the initial value base_list.js's setup_defaults() sets before first
// render; the user's own later page-size picks (20/100/500/2500) are
// untouched, same as frappe.is_large_screen() itself only ever applied once
// at that same point.
(function () {
	if (!frappe.views || !frappe.views.ListView) return;

	var _setup_view = frappe.views.ListView.prototype.setup_view;
	frappe.views.ListView.prototype.setup_view = function () {
		this.page_length = 100;
		this.selected_page_count = 100;
		return _setup_view.apply(this, arguments);
	};
})();
