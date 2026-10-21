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
			items: [
				{
					// Arsip mentah otoxpertsoandpart (1 baris = 1 item, apa
					// adanya dari API) - bukan doctype Sales Order bawaan.
					// Sales Order/Sales Invoice tetap dibuat seperti biasa oleh
					// sync_service_orders.py, tapi tabel ini sumbernya langsung
					// dari arsip, bukan dari dokumen bisnis itu.
					label: "Sales Order (WO)",
					doctype: "OtoBitz SO Detail",
					filters: {},
					embed: true,
					columns: [
						["nomorwo", "Nomor WO"],
						["namacabang", "Cabang"],
						["tanggal", "Tanggal", "Date"],
						["statuswo", "Status"],
						["namareferensi", "Item"],
						["grandtotal", "Total WO", "Currency"],
					],
				},
				{
					label: "Sales Invoice",
					doctype: "Sales Invoice",
					filters: { custom_otobitz_wo_number: ["is", "set"] },
					embed: true,
					columns: [
						["custom_otobitz_wo_number", "Nomor WO"],
						["custom_otobitz_nofaktur", "No. Faktur"],
						["posting_date", "Tanggal", "Date"],
						["due_date", "Jatuh Tempo", "Date"],
						["status", "Status"],
						["grand_total", "Total", "Currency"],
					],
				},
				{
					label: "Payment Entry",
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
					doctype: "Purchase Order",
					filters: { custom_otobitz_order_number: ["is", "set"] },
					embed: true,
					columns: [
						["custom_otobitz_order_number", "Nomor Order"],
						["supplier", "Supplier"],
						["custom_otobitz_branch", "Cabang"],
						["transaction_date", "Tanggal", "Date"],
						["status", "Status"],
						["grand_total", "Total", "Currency"],
					],
				},
			],
		},
		{
			label: "Setup / Master Data",
			items: [
				{ label: "Vehicle Category", doctype: "OtoBitz Vehicle Category" },
				{ label: "Vehicle Type", doctype: "OtoBitz Vehicle Type" },
				{ label: "Vehicle Color", doctype: "OtoBitz Vehicle Color" },
				{ label: "Service Menu", doctype: "OtoBitz Service Menu" },
			],
		},
		{
			label: "Laporan",
			items: [
				{ label: "Sales Order Summary", report: "OtoBitz Sales Order Summary" },
				{ label: "Sales Invoice Summary", report: "OtoBitz Sales Invoice Summary" },
				{ label: "Payment Entry Summary", report: "OtoBitz Payment Entry Summary" },
			],
		},
		{
			label: "Pengaturan",
			items: [
				{ label: "OtoBitz Settings", route: ["otobitz-settings", "OtoBitz Settings"] },
				{ label: "Sync Log", doctype: "OtoBitz Sync Log" },
			],
		},
	];

	if (!document.getElementById("ob-nav-style")) {
		const s = document.createElement("style");
		s.id = "ob-nav-style";
		s.textContent =
			"#ob-navbar{display:flex;align-items:stretch;background:var(--fg-color);border:1px solid var(--border-color);border-radius:var(--border-radius);margin:0 0 14px;overflow:visible;box-shadow:var(--shadow-sm)}" +
			".ob-nav-item{position:relative}" +
			".ob-nav-btn{display:flex;align-items:center;gap:6px;padding:10px 16px;font-size:13px;font-weight:600;color:var(--text-color);cursor:pointer;user-select:none;border-right:1px solid var(--border-color);white-space:nowrap}" +
			".ob-nav-item:last-child .ob-nav-btn{border-right:none}" +
			".ob-nav-btn:hover,.ob-nav-item.ob-open .ob-nav-btn{background:var(--control-bg)}" +
			".ob-nav-chevron{font-size:10px;color:var(--text-muted)}" +
			".ob-nav-dd{display:none;position:absolute;top:100%;left:0;min-width:220px;background:var(--fg-color);border:1px solid var(--border-color);border-radius:var(--border-radius);box-shadow:var(--shadow-md);z-index:999;padding:6px 0;margin-top:4px}" +
			".ob-nav-item.ob-open .ob-nav-dd{display:block}" +
			".ob-nav-dd a,.ob-nav-dd .ob-nav-dd-link{display:block;padding:8px 14px;font-size:13px;color:var(--text-color);text-decoration:none;cursor:pointer}" +
			".ob-nav-dd a:hover,.ob-nav-dd .ob-nav-dd-link:hover{background:var(--control-bg);color:var(--text-color)}" +
			"#ob-content-area{border:1px solid var(--border-color);border-radius:var(--border-radius);padding:14px;margin-bottom:16px}" +
			"#ob-content-area table{width:100%;border-collapse:collapse}" +
			"#ob-content-area th{padding:8px 12px;font-size:12px;color:var(--text-muted);text-align:left;border-bottom:1px solid var(--border-color);white-space:nowrap}" +
			"#ob-content-area td{padding:8px 12px;font-size:13px;border-top:1px solid var(--border-color);white-space:nowrap}" +
			"#ob-content-area tbody tr{cursor:pointer}" +
			"#ob-content-area tbody tr:hover{background:var(--control-bg)}" +
			"#ob-content-area .ob-table-wrap{overflow-x:auto}" +
			"#ob-content-area .ob-list-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}" +
			"#ob-content-area .ob-list-title{font-weight:600;font-size:14px}" +
			"#ob-content-area .ob-error{color:var(--red-600);padding:10px 0;}";
		document.head.appendChild(s);
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

	function formatCell(fieldtype, value) {
		if (value == null || value === "") return "";
		if (fieldtype === "Currency") return frappe.utils.escape_html(format_currency(value));
		if (fieldtype === "Date") return frappe.utils.escape_html(frappe.datetime.str_to_user(value));
		return frappe.utils.escape_html(String(value));
	}

	function renderEmbeddedList(item) {
		const $area = $("#ob-content-area");
		$area.show().html('<div class="text-muted">Memuat...</div>');

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
					`<div class="ob-error">Gagal memuat data ${frappe.utils.escape_html(item.doctype)}. ` +
						`<a href="${buildHref(item)}">Coba buka List View biasa &rarr;</a></div>`
				);
				console.error("OtoBitz embedded list failed:", err);
			});
	}

	function renderTable(item, rows) {
		const list_href = buildHref(item);

		let body = "";
		if (!rows.length) {
			body = '<div class="text-muted">Tidak ada data.</div>';
		} else {
			let html = '<div class="ob-table-wrap"><table><thead><tr>';
			html += "<th>" + __("ID") + "</th>";
			item.columns.forEach(([, label]) => {
				html += `<th>${frappe.utils.escape_html(label)}</th>`;
			});
			html += "</tr></thead><tbody>";
			rows.forEach((row) => {
				html += `<tr data-name="${frappe.utils.escape_html(row.name)}" data-doctype="${frappe.utils.escape_html(item.doctype)}">`;
				html += `<td>${frappe.utils.escape_html(row.name)}</td>`;
				item.columns.forEach(([fieldname, , fieldtype]) => {
					html += `<td>${formatCell(fieldtype, row[fieldname])}</td>`;
				});
				html += "</tr>";
			});
			html += "</tbody></table></div>";
			body = html;
		}

		const $area = $("#ob-content-area");
		$area.html(
			`<div class="ob-list-head">` +
				`<div class="ob-list-title">${frappe.utils.escape_html(item.label)} <span class="text-muted" style="font-weight:400;">(${rows.length})</span></div>` +
				`<a href="${list_href}">${__("Lihat semua di List View")} &rarr;</a>` +
				`</div>` +
				body
		);
		$area.find("tbody tr[data-name]").on("click", function () {
			frappe.set_route("Form", $(this).data("doctype"), $(this).data("name"));
		});
	}

	function buildNavbar() {
		const $bar = $('<div id="ob-navbar"></div>');
		MENUS.forEach((menu) => {
			const $item = $('<div class="ob-nav-item"></div>');
			const $btn = $(`<div class="ob-nav-btn">${frappe.utils.escape_html(menu.label)}<span class="ob-nav-chevron">&#9662;</span></div>`);
			const $dd = $('<div class="ob-nav-dd"></div>');
			menu.items.forEach((entry) => {
				if (entry.embed) {
					const $link = $(`<div class="ob-nav-dd-link">${frappe.utils.escape_html(entry.label)}</div>`);
					$link.on("click", (e) => {
						e.stopPropagation();
						$(".ob-nav-item").removeClass("ob-open");
						renderEmbeddedList(entry);
					});
					$dd.append($link);
				} else {
					$dd.append(`<a href="${buildHref(entry)}">${frappe.utils.escape_html(entry.label)}</a>`);
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
		const $existing = $("#ob-navbar");
		if (!isWorkspaceRoute()) {
			$existing.remove();
			$("#ob-content-area").remove();
			return;
		}
		if ($existing.length) return;
		const $target = $(".layout-main-section").first();
		if (!$target.length) return;
		$target.prepend('<div id="ob-content-area" style="display:none;"></div>');
		$target.prepend(buildNavbar());
	}

	frappe.router.on("change", () => setTimeout(injectOrRemove, 300));
	$(document).on("page-change", () => setTimeout(injectOrRemove, 300));
	setTimeout(injectOrRemove, 800);
})();
