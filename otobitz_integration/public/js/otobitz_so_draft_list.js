// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

// Reported live: the "SO Draft (Booking)" embedded table in otobitz_navbar.js
// shows a read-only summary dialog before opening the real Sales Order Form
// (see that file), but its "Lihat semua" link just opens the standard Sales
// Order List View - clicking a row THERE always went straight to the raw
// Form, same as every other Sales Order, because nothing special lives on
// that List View for this one subset of rows. Expected the same "Detail"-
// style consistency every other Transaksi entry already has end to end
// (e.g. "Sales Order (WO)"'s own "Lihat semua" opens "OtoBitz SO Detail"'s
// List View, and THAT doctype's Form always renders its own rich summary no
// matter how you arrive at it - see otobitz_so_detail.js).
//
// A new doctype/page isn't needed to get that same consistency here: a draft
// Sales Order is already one real, complete document (unlike OtoBitz SO
// Detail's raw per-item archive rows, which need joining before they mean
// anything). So this just teaches the real "Sales Order" List View itself,
// Desk-wide, to open the SAME dialog for the specific rows that are a
// booking draft (custom_otobitz_booking_number set) - every OTHER Sales
// Order (the vast majority, nothing to do with OtoBitz bookings) keeps
// behaving exactly as before: click a row, go straight to its Form.
//
// Deliberately NOT done by merging into frappe.listview_settings["Sales
// Order"] (add_fields/onload) - confirmed live in erpnext's own
// sales_order_list.js, that file does a bare `frappe.listview_settings["Sales
// Order"] = {...}` (a plain overwrite, not a merge) and is only lazy-loaded
// the first time the Sales Order List View route is actually visited, well
// AFTER this app's own app_include_js scripts already ran at Desk boot - a
// merge attempted here at boot time would just get clobbered the moment
// erpnext's own list.js finally loads. Keeping a small, separately-fetched
// cache of this one field's "yes/no" set instead sidesteps that whole race:
// it owes nothing to whatever erpnext's settings object looks like or when.
//
// Click interception uses the native CAPTURE phase on `document`, not a
// jQuery .on() delegated handler on the List View's own result container -
// Frappe's own ListView.setup_list_click() already binds its own bubble-
// phase handler on this exact same DOM (apps/frappe/frappe/public/js/frappe/
// list/list_view.js), and jQuery delegated handlers fire in bind order, which
// this script has no reliable way to guarantee it wins against. Capture
// always runs before bubble regardless of bind order, so
// preventDefault()/stopPropagation() here reliably wins before Frappe's own
// handler (or the plain <a href> navigation) ever runs.
(function () {
	if (!frappe.views || !frappe.views.ListView) return;

	// Refreshed once per Sales Order List View visit (setup_view fires once
	// per instantiation - same lifecycle hook otobitz_group_by.js already
	// patches for a Desk-wide concern, reused here for one doctype only).
	// A row created/converted since the last refresh just falls through to
	// the normal Form open below (harmless - same staleness any List View
	// already has until its own next reload) rather than needing a live
	// subscription.
	let draftBookingNames = new Set();

	function refreshDraftBookingNames() {
		frappe
			.call({
				method: "frappe.client.get_list",
				args: {
					doctype: "Sales Order",
					fields: ["name"],
					filters: { custom_otobitz_booking_number: ["is", "set"] },
					limit_page_length: 500,
				},
			})
			.then((r) => {
				draftBookingNames = new Set((r.message || []).map((d) => d.name));
			});
	}

	const _setup_view = frappe.views.ListView.prototype.setup_view;
	frappe.views.ListView.prototype.setup_view = function () {
		const r = _setup_view.apply(this, arguments);
		if (this.doctype === "Sales Order") refreshDraftBookingNames();
		return r;
	};

	// getDN mirrors otobitz_group_by.js's own already-proven-live selector:
	// `.list-row-container` doesn't always carry data-name directly (only
	// some of its descendants do - see that file's own comment), so this
	// falls back to the first descendant that does.
	function getDN($row) {
		return $row.attr("data-name") || $row.find("[data-name]").first().attr("data-name") || null;
	}

	document.addEventListener(
		"click",
		function (e) {
			const route = frappe.get_route ? frappe.get_route() : [];
			if (route[0] !== "List" || route[1] !== "Sales Order") return;

			const $row = $(e.target).closest(".list-row-container");
			if (!$row.length) return;
			const name = getDN($row);
			if (!name || !draftBookingNames.has(name)) return;

			e.preventDefault();
			e.stopPropagation();
			if (typeof window.otobitzShowSalesOrderDraftDialog === "function") {
				window.otobitzShowSalesOrderDraftDialog(name);
			} else {
				// otobitz_navbar.js somehow didn't load/expose it - fall back
				// to the normal Form instead of a dead click.
				frappe.set_route("Form", "Sales Order", name);
			}
		},
		true
	);
})();
