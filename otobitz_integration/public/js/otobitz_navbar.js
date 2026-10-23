// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

// Odoo-style horizontal dropdown navbar, shown only on the OtoBitz
// Integration workspace page - this is deliberately scoped to that one
// route (checked on every SPA route change, injected/removed accordingly)
// rather than shown app-wide, since Frappe Desk's own navigation is the
// sidebar/Workspace paradigm everywhere else and this should feel like an
// enhancement to this one module's landing page, not a competing global nav.
//
// "Transaksi" items render an embedded, read-only table right on this same
// page instead of navigating to the doctype's own List View - those are
// core ERPNext doctypes (Sales Order, Payment Entry, ...) whose own List
// View lives under a different module's breadcrumb (Selling, Accounts, ...),
// which reads as "leaving" OtoBitz Integration entirely. Setup/Laporan/
// Pengaturan items navigate normally: Setup is this app's own doctypes
// (already breadcrumbed under OtoBitz Integration), and a Report or a
// Settings Form aren't reasonably embeddable the same way a list of rows is.
//
// Columns are hardcoded per doctype (matching each one's own in_list_view
// set up earlier) rather than discovered via frappe.model.with_doctype() -
// that call fetches the *entire* doctype meta (every field, every linked
// doctype's own meta recursively) before the list query can even start,
// which is genuinely slow for a wide doctype like Sales Order and was the
// actual cause of the embedded list hanging on "Memuat..." - a single
// frappe.call with a fixed, small field list is both faster and has far
// fewer places to silently fail.

(function () {
	// frappe.router rewrites an incoming "/app/otobitz-integration" URL into
	// the internal route ["Workspaces", "<Workspace docname>"] before
	// frappe.get_route() ever sees it - checking route[0] against the raw
	// URL slug ("otobitz-integration") would never match.
	const WORKSPACE_NAME = "OtoBitz Integration";
	const PAGE_LENGTH = 20;

	const MENUS = [
		{
			label: "Transaksi",
			icon: "receipt",
			items: [
				{
					// Arsip mentah otoxpertsoandpart (1 baris = 1 item, apa
					// adanya dari API) - bukan doctype Sales Order bawaan.
					// Sales Order/Sales Invoice tetap dibuat seperti biasa oleh
					// sync_service_orders.py, tapi tabel ini sumbernya langsung
					// dari arsip, bukan dari dokumen bisnis itu.
					label: "Sales Order (WO)",
					icon: "car",
					doctype: "OtoBitz SO Detail",
					filters: {},
					embed: true,
					columns: [
						["nomorwo", "Nomor WO"],
						["namacabang", "Cabang"],
						["tanggal", "Tanggal", "Date"],
						["statuswo", "Status", "Status"],
						["namareferensi", "Item"],
						["grandtotal", "Total WO", "Currency"],
					],
				},
				{
					label: "Sales Invoice",
					icon: "receipt-text",
					doctype: "Sales Invoice",
					filters: { custom_otobitz_wo_number: ["is", "set"] },
					embed: true,
					columns: [
						["custom_otobitz_wo_number", "Nomor WO"],
						["custom_otobitz_nofaktur", "No. Faktur"],
						["posting_date", "Tanggal", "Date"],
						["due_date", "Jatuh Tempo", "Date"],
						["status", "Status", "Status"],
						["grand_total", "Total", "Currency"],
					],
				},
				{
					label: "Payment Entry",
					icon: "credit-card",
					doctype: "Payment Entry",
					filters: { custom_otobitz_receipt_number: ["is", "set"] },
					embed: true,
					columns: [
						["custom_otobitz_receipt_number", "Nomor Kwitansi"],
						["posting_date", "Tanggal", "Date"],
						["mode_of_payment", "Metode"],
						["custom_otobitz_branch", "Cabang"],
						["paid_to", "Akun Tujuan"],
						["paid_amount", "Jumlah", "Currency"],
					],
				},
				{
					label: "Journal Entry (Setoran)",
					icon: "banknote",
					doctype: "Journal Entry",
					filters: { custom_otobitz_receipt_number: ["is", "set"] },
					embed: true,
					columns: [
						["custom_otobitz_receipt_number", "Nomor Setoran"],
						["posting_date", "Tanggal", "Date"],
						["custom_otobitz_branch", "Cabang"],
						["total_debit", "Total", "Currency"],
					],
				},
				{
					label: "Purchase Order",
					icon: "truck",
					doctype: "Purchase Order",
					filters: { custom_otobitz_order_number: ["is", "set"] },
					embed: true,
					columns: [
						["custom_otobitz_order_number", "Nomor Order"],
						["supplier", "Supplier"],
						["custom_otobitz_branch", "Cabang"],
						["transaction_date", "Tanggal", "Date"],
						["status", "Status", "Status"],
						["grand_total", "Total", "Currency"],
					],
				},
			],
		},
		{
			label: "Setup / Master Data",
			icon: "sliders-horizontal",
			items: [
				{ label: "Vehicle Category", icon: "layout-grid", doctype: "OtoBitz Vehicle Category" },
				{ label: "Vehicle Type", icon: "car", doctype: "OtoBitz Vehicle Type" },
				{ label: "Vehicle Color", icon: "palette", doctype: "OtoBitz Vehicle Color" },
				{ label: "Service Menu", icon: "wrench", doctype: "OtoBitz Service Menu" },
			],
		},
		{
			label: "Laporan",
			icon: "chart-column",
			items: [
				{ label: "Sales Order Summary", icon: "file-chart-column", report: "OtoBitz Sales Order Summary" },
				{ label: "Sales Invoice Summary", icon: "file-chart-column", report: "OtoBitz Sales Invoice Summary" },
				{ label: "Payment Entry Summary", icon: "file-chart-column", report: "OtoBitz Payment Entry Summary" },
			],
		},
		{
			label: "Pengaturan",
			icon: "settings",
			items: [
				{ label: "OtoBitz Settings", icon: "settings-2", route: ["otobitz-settings", "OtoBitz Settings"] },
				{ label: "Sync Log", icon: "database", doctype: "OtoBitz Sync Log" },
				{ label: "Job Queue (Gagal Sync)", icon: "refresh-cw", doctype: "OtoBitz Failed Sync" },
			],
		},
	];

	// Keyword -> Frappe indicator-pill color, checked in order against a
	// lowercased status string. Covers the status vocabulary actually seen
	// across Sales Order/Sales Invoice/Purchase Order (OtoBitz's own
	// "FAKTUR", plus ERPNext's native Draft/Submitted/Paid/Overdue/...) -
	// falls back to gray for anything unrecognized rather than guessing.
	const STATUS_COLORS = [
		[/cancel/, "red"],
		[/overdue|unpaid|failed|reject/, "red"],
		[/draft/, "gray"],
		[/to\s*(invoice|bill|receive|deliver)|pending|open|partly/, "orange"],
		[/faktur|paid|closed|completed|submitted|success/, "green"],
	];
	function statusColor(value) {
		const v = String(value || "").toLowerCase();
		for (const [re, color] of STATUS_COLORS) {
			if (re.test(v)) return color;
		}
		return "gray";
	}

	// Frappe's own .icon/.icon-sm/.icon-xs classes set stroke/fill via
	// --icon-stroke/--icon-fill custom properties rather than currentColor
	// (apps/frappe/frappe/public/scss/common/icons.scss), so a plain CSS
	// `color` on a parent element never actually recolors them, and
	// different lucide glyphs end up looking inconsistently sized/heavy at
	// the same class-based size (gak rapih in practice). Rendering the
	// <svg> directly with explicit width/height and stroke="currentColor"
	// sidesteps both problems: size is exact and uniform regardless of
	// which icon, and `color: ...` on a CSS selector around it just works.
	function icon(name, px) {
		const size = px || 14;
		return (
			`<svg class="ob-ic" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" ` +
			`stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" ` +
			`style="flex-shrink:0;display:block;vertical-align:middle" aria-hidden="true"><use href="#icon-${name}"></use></svg>`
		);
	}

	if (!document.getElementById("ob-nav-style")) {
		const s = document.createElement("style");
		s.id = "ob-nav-style";
		s.textContent =
			// Navbar shell
			"#ob-navbar{display:flex;align-items:stretch;background:var(--fg-color);border:1px solid var(--border-color);border-radius:10px;margin:0 0 16px;overflow:visible;box-shadow:var(--shadow-sm)}" +
			".ob-nav-item{position:relative}" +
			".ob-nav-btn{display:flex;align-items:center;gap:7px;padding:12px 18px;font-size:13.5px;font-weight:600;color:var(--text-color);cursor:pointer;user-select:none;border-right:1px solid var(--border-color);white-space:nowrap;transition:background .12s ease,box-shadow .12s ease}" +
			".ob-nav-item:first-child .ob-nav-btn{border-radius:10px 0 0 10px}" +
			".ob-nav-item:last-child .ob-nav-btn{border-right:none;border-radius:0 10px 10px 0}" +
			".ob-nav-btn .ob-ic{color:var(--text-muted);transition:color .12s ease}" +
			".ob-nav-btn:hover,.ob-nav-item.ob-open .ob-nav-btn{background:var(--control-bg)}" +
			".ob-nav-btn:hover .ob-ic,.ob-nav-item.ob-open .ob-nav-btn .ob-ic{color:var(--text-color)}" +
			".ob-nav-item.ob-open .ob-nav-btn{box-shadow:inset 0 -2px 0 var(--blue-500,#2490ef)}" +
			".ob-nav-chevron{display:flex;color:var(--text-muted);transition:transform .15s ease}" +
			".ob-nav-item.ob-open .ob-nav-chevron{transform:rotate(180deg)}" +
			// Dropdown
			".ob-nav-dd{display:none;position:absolute;top:calc(100% + 6px);left:0;min-width:240px;background:var(--fg-color);border:1px solid var(--border-color);border-radius:10px;box-shadow:var(--shadow-lg,0 8px 24px rgba(0,0,0,.14));z-index:999;padding:6px;margin-top:0}" +
			".ob-nav-item.ob-open .ob-nav-dd{display:block;animation:ob-dd-in .12s ease}" +
			"@keyframes ob-dd-in{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:translateY(0)}}" +
			".ob-nav-dd a,.ob-nav-dd .ob-nav-dd-link{display:flex;align-items:center;gap:10px;padding:9px 10px;font-size:13px;font-weight:500;color:var(--text-color);text-decoration:none;cursor:pointer;border-radius:7px;transition:background .1s ease}" +
			".ob-nav-dd a .ob-ic,.ob-nav-dd-link .ob-ic{color:var(--text-muted);flex-shrink:0}" +
			".ob-nav-dd a:hover,.ob-nav-dd .ob-nav-dd-link:hover{background:var(--control-bg);color:var(--text-color)}" +
			".ob-nav-dd-link.ob-active{background:var(--control-bg)}" +
			".ob-nav-dd-link.ob-active .ob-ic{color:var(--blue-500,#2490ef)}" +
			// Content card
			"#ob-content-area{border:1px solid var(--border-color);border-radius:12px;padding:0;margin-bottom:16px;background:var(--fg-color);box-shadow:var(--shadow-sm);overflow:hidden}" +
			"#ob-content-area .ob-list-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 16px;border-bottom:1px solid var(--border-color);flex-wrap:wrap}" +
			"#ob-content-area .ob-list-title-wrap{display:flex;align-items:center;gap:9px;min-width:0}" +
			"#ob-content-area .ob-list-title-wrap>.ob-ic{color:var(--blue-500,#2490ef);flex-shrink:0}" +
			"#ob-content-area .ob-list-title{font-weight:700;font-size:14.5px;color:var(--text-color);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}" +
			"#ob-content-area .ob-count-badge{font-size:11.5px;font-weight:600;color:var(--text-muted);background:var(--control-bg);border-radius:999px;padding:2px 9px;flex-shrink:0}" +
			"#ob-content-area .ob-list-actions{display:flex;align-items:center;gap:6px;flex-shrink:0}" +
			"#ob-content-area .ob-icon-btn{display:flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:7px;color:var(--text-muted);cursor:pointer;transition:background .1s ease,color .1s ease}" +
			"#ob-content-area .ob-icon-btn:hover{background:var(--control-bg);color:var(--text-color)}" +
			"#ob-content-area .ob-icon-btn.ob-spin .ob-ic{animation:ob-spin .6s linear infinite}" +
			"@keyframes ob-spin{to{transform:rotate(360deg)}}" +
			"#ob-content-area .ob-view-all{display:flex;align-items:center;gap:5px;font-size:12.5px;font-weight:600;color:var(--blue-500,#2490ef);text-decoration:none;white-space:nowrap}" +
			"#ob-content-area .ob-view-all:hover{text-decoration:underline}" +
			// Table
			"#ob-content-area .ob-table-wrap{overflow-x:auto}" +
			"#ob-content-area table{width:100%;border-collapse:collapse}" +
			"#ob-content-area th{position:sticky;top:0;padding:9px 16px;font-size:10.5px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--text-muted);text-align:left;background:var(--fg-color);border-bottom:1px solid var(--border-color);white-space:nowrap}" +
			"#ob-content-area td{padding:10px 16px;font-size:13px;color:var(--text-color);border-top:1px solid var(--border-color);white-space:nowrap}" +
			"#ob-content-area th.ob-col-currency,#ob-content-area td.ob-col-currency{text-align:right;font-variant-numeric:tabular-nums}" +
			"#ob-content-area tbody tr{cursor:pointer;transition:background .1s ease}" +
			"#ob-content-area tbody tr:hover{background:var(--control-bg)}" +
			"#ob-content-area tbody tr td:first-child{box-shadow:inset 3px 0 0 transparent}" +
			"#ob-content-area tbody tr:hover td:first-child{box-shadow:inset 3px 0 0 var(--blue-500,#2490ef)}" +
			"#ob-content-area .ob-id-link{color:var(--text-muted);font-size:12px}" +
			// Status pill (reuses Frappe's own indicator-pill color tokens
			// so it matches the rest of Desk and stays theme-aware)
			"#ob-content-area .ob-status-pill{display:inline-flex;align-items:center;gap:5px;padding:3px 10px 3px 8px;border-radius:999px;font-size:11.5px;font-weight:600;white-space:nowrap}" +
			"#ob-content-area .ob-status-pill::before{content:'';width:6px;height:6px;border-radius:50%;background:currentColor;flex-shrink:0}" +
			// Empty / loading / error states
			"#ob-content-area .ob-state{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;padding:48px 20px;color:var(--text-muted);text-align:center}" +
			"#ob-content-area .ob-state .ob-ic{color:var(--text-muted);opacity:.5}" +
			"#ob-content-area .ob-state-text{font-size:13px}" +
			"#ob-content-area .ob-state.ob-loading .ob-ic{animation:ob-spin .8s linear infinite;opacity:.8;color:var(--blue-500,#2490ef)}" +
			"#ob-content-area .ob-error{color:var(--red-600);padding:10px 0}" +
			"#ob-content-area .ob-error a{color:var(--blue-500,#2490ef);text-decoration:underline}" +
			// Frappe's own Workspace content (the "OtoBitz Integration"/
			// "Laporan" shortcut cards) renders into .editor-js-container
			// (workspace.js: `this.$page = $('<div class="editor-js-
			// container">').appendTo(this.body)`, a sibling of what we
			// prepend into .layout-main-section) - hidden here, scoped to
			// this one Workspace route, since the embedded Transaksi table
			// now replaces it as the page's default content.
			"body.ob-workspace-active .editor-js-container{display:none !important;}";
		document.head.appendChild(s);
	}

	// Workspace pages get centered with a max-width by Frappe itself
	// (desktop.scss: `[data-page-route="Workspaces"] .layout-main` gets
	// `max-width: var(--page-max-width)` unless <body> has "full-width") -
	// that's what was actually eating the side margins, not
	// .layout-main-section-wrapper's own 80% rule from page.scss (fixing
	// that alone left this stronger, more specific rule still in charge).
	// Frappe already ships a real "Toggle Full Width" feature for exactly
	// this (ui/toolbar/toolbar.js, persisted in
	// localStorage.container_fullwidth) - reusing that native class instead
	// of fighting it with a custom width override.
	//
	// On the way out, restored to the user's *actual* saved preference
	// (the same localStorage key toolbar.js itself reads on every page
	// load) rather than tracking "did this script add it" in a plain JS
	// variable - that variable resets to false on every fresh page load,
	// but the body class it was tracking doesn't reset until something
	// explicitly changes it. Visit the workspace once, then reload or open
	// a new page without passing back through this route in the same
	// script execution, and a variable-based guard leaves full-width stuck
	// on for every other page from then on (observed: stuck true on the
	// Sales Invoice List View). Re-reading the real preference every time
	// is correct regardless of how many page loads happened in between.
	function syncFullWidth(on_workspace) {
		if (on_workspace) {
			document.body.classList.add("full-width");
			return;
		}
		let preferred = false;
		try {
			preferred = JSON.parse(localStorage.getItem("container_fullwidth") || "false");
		} catch (e) {
			preferred = false;
		}
		document.body.classList.toggle("full-width", preferred);
	}

	function buildHref(item) {
		if (item.report) return "/app/query-report/" + encodeURIComponent(item.report);
		if (item.route) return "/app/" + item.route.join("/");
		if (item.doctype) {
			let url = "/app/" + frappe.router.slug(item.doctype);
			if (item.filters) url += "?" + Object.entries(item.filters).map(([k, v]) => `${k}=${encodeURIComponent(JSON.stringify(v))}`).join("&");
			return url;
		}
		return "#";
	}

	function formatCell(fieldtype, value, row) {
		if (fieldtype === "Status") {
			if (value == null || value === "") return "";
			const color = statusColor(value);
			return `<span class="ob-status-pill indicator-pill ${color} no-indicator-dot">${frappe.utils.escape_html(String(value))}</span>`;
		}
		if (value == null || value === "") return "";
		if (fieldtype === "Currency") return frappe.utils.escape_html(format_currency(value));
		if (fieldtype === "Date") return frappe.utils.escape_html(frappe.datetime.str_to_user(value));
		return frappe.utils.escape_html(String(value));
	}

	// Tracks the currently-shown Transaksi item so the refresh button and
	// the dropdown's "active item" highlight both have something to read.
	let currentItem = null;

	function loadingState() {
		return `<div class="ob-state ob-loading">${icon("loader-circle", 26)}<div class="ob-state-text">Memuat data...</div></div>`;
	}
	function emptyState() {
		return `<div class="ob-state">${icon("inbox", 26)}<div class="ob-state-text">Tidak ada data.</div></div>`;
	}

	function renderEmbeddedList(item) {
		currentItem = item;
		const $area = $("#ob-content-area");
		$area.show().html(loadingState());

		const fields = ["name"].concat(item.columns.map((c) => c[0]));

		frappe
			.call({
				method: "frappe.client.get_list",
				args: {
					doctype: item.doctype,
					fields: fields,
					filters: item.filters || {},
					limit_page_length: PAGE_LENGTH,
					order_by: "modified desc",
				},
			})
			.then((r) => {
				renderTable(item, r.message || []);
			})
			.catch((err) => {
				$area.html(
					`<div class="ob-error" style="padding:20px 16px;">Gagal memuat data ${frappe.utils.escape_html(item.doctype)}. ` +
						`<a href="${buildHref(item)}">Coba buka List View biasa &rarr;</a></div>`
				);
				console.error("OtoBitz embedded list failed:", err);
			});
	}

	function renderTable(item, rows) {
		const list_href = buildHref(item);

		let body = "";
		if (!rows.length) {
			body = emptyState();
		} else {
			let html = '<div class="ob-table-wrap"><table><thead><tr>';
			html += "<th>" + __("ID") + "</th>";
			item.columns.forEach(([, label, fieldtype]) => {
				const cls = fieldtype === "Currency" ? ' class="ob-col-currency"' : "";
				html += `<th${cls}>${frappe.utils.escape_html(label)}</th>`;
			});
			html += "</tr></thead><tbody>";
			rows.forEach((row) => {
				html += `<tr data-name="${frappe.utils.escape_html(row.name)}" data-doctype="${frappe.utils.escape_html(item.doctype)}">`;
				html += `<td class="ob-id-link">${frappe.utils.escape_html(row.name)}</td>`;
				item.columns.forEach(([fieldname, , fieldtype]) => {
					const cls = fieldtype === "Currency" ? ' class="ob-col-currency"' : "";
					html += `<td${cls}>${formatCell(fieldtype, row[fieldname], row)}</td>`;
				});
				html += "</tr>";
			});
			html += "</tbody></table></div>";
			body = html;
		}

		const $area = $("#ob-content-area");
		$area.html(
			`<div class="ob-list-head">` +
				`<div class="ob-list-title-wrap">${icon(item.icon || "list", 17)}` +
				`<div class="ob-list-title">${frappe.utils.escape_html(item.label)}</div>` +
				`<div class="ob-count-badge">${rows.length}</div></div>` +
				`<div class="ob-list-actions">` +
				`<div class="ob-icon-btn" title="${__("Muat ulang")}" id="ob-refresh-btn">${icon("refresh-cw", 14)}</div>` +
				`<a class="ob-view-all" href="${list_href}">${__("Lihat semua")}${icon("arrow-right", 13)}</a>` +
				`</div>` +
				`</div>` +
				body
		);
		$area.find("tbody tr[data-name]").on("click", function () {
			frappe.set_route("Form", $(this).data("doctype"), $(this).data("name"));
		});
		$area.find("#ob-refresh-btn").on("click", function () {
			const $btn = $(this).addClass("ob-spin");
			renderEmbeddedList(item);
			setTimeout(() => $btn.removeClass("ob-spin"), 500);
		});
	}

	function buildNavbar() {
		const $bar = $('<div id="ob-navbar"></div>');
		MENUS.forEach((menu) => {
			const $item = $('<div class="ob-nav-item"></div>');
			const $btn = $(
				`<div class="ob-nav-btn">${icon(menu.icon || "folder", 15)}` +
					`<span>${frappe.utils.escape_html(menu.label)}</span>` +
					`<span class="ob-nav-chevron">${icon("chevron-down", 11)}</span></div>`
			);
			const $dd = $('<div class="ob-nav-dd"></div>');
			menu.items.forEach((entry) => {
				if (entry.embed) {
					const $link = $(
						`<div class="ob-nav-dd-link">${icon(entry.icon || "file", 15)}<span>${frappe.utils.escape_html(entry.label)}</span></div>`
					);
					$link.on("click", (e) => {
						e.stopPropagation();
						$(".ob-nav-item").removeClass("ob-open");
						$(".ob-nav-dd-link").removeClass("ob-active");
						$link.addClass("ob-active");
						renderEmbeddedList(entry);
					});
					$dd.append($link);
				} else {
					$dd.append(
						`<a href="${buildHref(entry)}">${icon(entry.icon || "file", 15)}<span>${frappe.utils.escape_html(entry.label)}</span></a>`
					);
				}
			});
			$item.append($btn).append($dd);
			$item.on("click", (e) => {
				e.stopPropagation();
				const was_open = $item.hasClass("ob-open");
				$(".ob-nav-item").removeClass("ob-open");
				if (!was_open) $item.addClass("ob-open");
			});
			$bar.append($item);
		});
		$(document).off("click.obnav").on("click.obnav", () => $(".ob-nav-item").removeClass("ob-open"));
		// Mark the default Transaksi item (auto-loaded below) as active
		// right away, so the dropdown reflects reality the first time it's
		// opened instead of showing nothing selected.
		$bar.find(".ob-nav-dd-link").first().addClass("ob-active");
		return $bar;
	}

	function isWorkspaceRoute() {
		const route = frappe.get_route();
		if (!route || route[0] !== "Workspaces") return false;
		// Private workspace routes end up as ["Workspaces", "private", "<name>"];
		// public ones as ["Workspaces", "<name>"] - match either shape.
		return route[1] === WORKSPACE_NAME || route[2] === WORKSPACE_NAME;
	}

	function injectOrRemove() {
		const on_workspace = isWorkspaceRoute();
		document.body.classList.toggle("ob-workspace-active", on_workspace);
		syncFullWidth(on_workspace);

		// Frappe keeps every page visited this session in the DOM, toggling
		// plain display:none on old ones instead of removing them (see
		// container.js) - so a #ob-navbar/#ob-content-area injected on an
		// earlier visit to this Workspace doesn't disappear when the user
		// navigates away, it just goes invisible along with its now-hidden
		// parent. Sweep those out on every call so there's never more than
		// one live copy in the DOM: without this, both the "already
		// injected?" check below and the #ob-content-area lookups in
		// renderEmbeddedList()/renderTable() could silently resolve to a
		// stale hidden copy instead of the one actually on screen (jQuery's
		// #id selectors return the first DOM match, not necessarily the
		// visible one, when duplicate ids exist).
		//
		// Checked via the *.layout-main-section ancestor's* visibility, not
		// the element's own - #ob-content-area is deliberately
		// display:none until a Transaksi item is clicked, so checking its
		// own visibility treated every legitimate, correctly-placed copy as
		// "stale" a moment after injecting it and deleted it right back out
		// (renderEmbeddedList's $("#ob-content-area") then silently matched
		// nothing, so clicking a Transaksi item did nothing at all).
		$("#ob-navbar, #ob-content-area").each(function () {
			const $section = $(this).closest(".layout-main-section");
			if (!$section.length || !$section.is(":visible")) $(this).remove();
		});

		if (!on_workspace) {
			$("#ob-navbar, #ob-content-area").remove();
			currentItem = null;
			return;
		}
		if ($("#ob-navbar").length) return;
		// .first() in DOM order would pick whichever page loaded first this
		// session, which is only the *current* page by coincidence (a hard
		// reload, where this is the only page that's ever existed) -
		// :visible filters down to the one actually on screen regardless of
		// how many hidden ones have piled up from earlier navigation.
		const $target = $(".layout-main-section").filter(":visible").first();
		if (!$target.length) return;
		$target.prepend('<div id="ob-content-area" style="display:none;"></div>');
		$target.prepend(buildNavbar());
		// Load straight into the default Transaksi view (Sales Order (WO))
		// instead of landing on the now-hidden native Workspace cards and
		// requiring a click just to see anything.
		renderEmbeddedList(MENUS[0].items[0]);
	}

	frappe.router.on("change", () => setTimeout(injectOrRemove, 300));
	$(document).on("page-change", () => setTimeout(injectOrRemove, 300));
	setTimeout(injectOrRemove, 800);

	// Fixed-delay setTimeout calls above are a best-effort nudge, not a
	// guarantee: the Workspace page fetches and renders its own content
	// asynchronously, and on a slow/cold load (or a hard refresh landing
	// directly on this route) that can finish well after 800ms - or it can
	// re-render .layout-main-section's contents *after* we've already
	// injected, wiping the navbar back out with no further "change"/
	// "page-change" event to catch it. A MutationObserver on the whole page
	// body sidesteps guessing at timing entirely: injectOrRemove() is a cheap
	// no-op when the navbar is already present (see the early return above),
	// so calling it on every DOM mutation is safe and makes the navbar
	// self-healing regardless of how/when the Workspace page finishes
	// rendering.
	const observer = new MutationObserver(() => {
		if (isWorkspaceRoute()) injectOrRemove();
	});
	observer.observe(document.body, { childList: true, subtree: true });

	// Belt-and-suspenders on top of the observer: navigating straight from
	// one Workspace to another (sidebar link, not a hard reload) sometimes
	// lands in a brief window where frappe.get_route() hasn't updated yet at
	// the exact moment the Workspace page's own async content swap fires its
	// DOM mutations - the observer's callback checks isWorkspaceRoute() at
	// that stale instant, sees "not yet this route", and skips injecting,
	// and if nothing else mutates the DOM afterwards there's no second
	// chance. A standing 1s poll closes that gap unconditionally: it costs
	// nothing when idle (injectOrRemove() no-ops the moment the navbar is
	// already correctly present/absent for the current route) and removes
	// the dependency on any particular Frappe event firing in a particular
	// order.
	setInterval(injectOrRemove, 1000);
})();
