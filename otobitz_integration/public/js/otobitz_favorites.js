// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

// Odoo-style "Favorites" widget for List Views: saves the current Filter +
// Group (from otobitz_group_by.js) + Sort as a single named bundle, and
// re-applies all three together with one click. This is deliberately
// separate from Frappe's native "Saved Filters" (List Filter doctype) -
// that one only stores filters, not the grouping or sort a user had active,
// so a saved "by day" view would silently lose its grouping on reapply.
// Rather than extend that native feature (shared with core Desk, used by
// every other doctype's List View too), this ships its own doctype
// (OtoBitz List Favorite) and button so the native one stays untouched.
//
// Rolled out Desk-wide after validating the UX on Purchase Order first -
// same rollout pattern otobitz_group_by.js used.
(function () {
	if (!frappe.views || !frappe.views.ListView) return;
	var DOCTYPE = "OtoBitz List Favorite";

	if (!document.getElementById("ob-fav-style")) {
		var s = document.createElement("style"); s.id = "ob-fav-style";
		// No margin on #ob-fav-wrap itself for the same reason as
		// #ob-gg-wrap in otobitz_group_by.js: it carries the
		// "filter-selector" class, so frappe's own CSS already applies
		// var(--margin-xs) to the inner .btn-group.
		s.textContent = "#ob-fav-wrap{position:relative}"
			+ "#ob-fav-select{display:flex;align-items:center}"
			+ "#ob-fav-select .filter-icon{margin-right:6px}"
			+ "#ob-fav-dd{display:none;position:absolute;top:calc(100% + 4px);right:0;background:var(--fg-color,#fff);border:1px solid var(--border-color,#d1d8dd);border-radius:8px;min-width:260px;max-height:360px;overflow-y:auto;z-index:9999;padding:8px 0;box-shadow:var(--shadow-lg,0 4px 16px rgba(0,0,0,.12))}"
			+ ".ob-fav-section-title{padding:6px 12px;font-size:11px;font-weight:600;color:#8d99a6;text-transform:uppercase}"
			+ ".ob-fav-item{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:7px 12px;cursor:pointer;font-size:13px;color:#36414c}"
			+ ".ob-fav-item:hover{background:#f5f7fa}"
			+ ".ob-fav-item-label{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
			+ ".ob-fav-item-badge{flex:0 0 auto;font-size:10px;font-weight:600;color:#68717d;background:#edf2f7;border:1px solid #dde5ee;border-radius:999px;padding:2px 6px}"
			+ ".ob-fav-item-del{flex:0 0 auto;color:#8d99a6;cursor:pointer;padding:2px 4px;border-radius:4px}"
			+ ".ob-fav-item-del:hover{background:#fde8e8;color:#c0392b}"
			+ ".ob-fav-empty{padding:10px 12px;font-size:12px;color:#8d99a6}"
			+ ".ob-fav-divider{margin:6px 0;border-top:1px solid #f0f4f7}"
			+ ".ob-fav-save-item{display:flex;align-items:center;gap:8px;padding:8px 12px;cursor:pointer;font-size:13px;color:#2490ef;font-weight:600}"
			+ ".ob-fav-save-item:hover{background:#f5f7fa}"
			+ ".ob-fav-new-form{padding:8px 12px;display:none}"
			+ ".ob-fav-new-form input[type=text]{width:100%;padding:6px 8px;border:1px solid #d1d8dd;border-radius:6px;font-size:13px;margin-bottom:6px;box-sizing:border-box}"
			+ ".ob-fav-new-form label{display:flex;align-items:center;gap:6px;font-size:12px;color:#36414c;margin-bottom:8px;cursor:pointer}"
			+ ".ob-fav-new-actions{display:flex;gap:8px}"
			+ ".ob-fav-new-actions button{flex:1;border:1px solid #d1d8dd;background:#fff;color:#36414c;font-size:12px;border-radius:6px;padding:6px 8px;cursor:pointer}"
			+ ".ob-fav-new-actions button.primary{background:#2490ef;color:#fff;border-color:#2490ef}";
		document.head.appendChild(s);
	}

	function esc(t) { return frappe.utils.escape_html(t == null ? "" : String(t)); }

	function setup(listview) {
		if (listview.__ob_fav_patched) return;
		listview.__ob_fav_patched = true;

		var favorites = [];
		var $widget = null;

		function fetchFavorites() {
			return frappe.db.get_list(DOCTYPE, {
				fields: ["name", "favorite_name", "for_user", "is_global", "filters", "group_fields", "sort_by", "sort_order"],
				filters: { reference_doctype: listview.doctype },
				or_filters: [
					["for_user", "=", frappe.session.user],
					["is_global", "=", 1],
				],
				order_by: "favorite_name asc",
				limit_page_length: 0,
			}).then(function (rows) {
				favorites = rows || [];
			});
		}

		function currentGroupApi() {
			return listview.__ob_gg_api || null;
		}

		function applyFavorite(fav) {
			var filters = [];
			try { filters = JSON.parse(fav.filters || "[]"); } catch (e) { filters = []; }
			var groups = [];
			try { groups = JSON.parse(fav.group_fields || "[]"); } catch (e) { groups = []; }

			listview.filter_area.clear().then(function () {
				return listview.filter_area.set(filters);
			}).then(function () {
				var api = currentGroupApi();
				if (api) api.setGroups(groups);
				if (fav.sort_by) {
					if (listview.sort_selector) listview.sort_selector.set_value(fav.sort_by, fav.sort_order || "desc");
					listview.on_sort_change(fav.sort_by, fav.sort_order || "desc");
				}
			});
			closeDropdown();
		}

		function deleteFavorite(fav) {
			frappe.confirm(
				__("Hapus favorite \"{0}\"?", [fav.favorite_name]),
				function () {
					frappe.db.delete_doc(DOCTYPE, fav.name).then(function () {
						fetchFavorites().then(renderList);
					});
				}
			);
		}

		function renderList() {
			if (!$widget) return;
			var $list = $widget.find("#ob-fav-list");
			$list.empty();
			if (!favorites.length) {
				$list.append('<div class="ob-fav-empty">' + esc(__("Belum ada favorite tersimpan")) + '</div>');
				return;
			}
			favorites.forEach(function (fav) {
				var $item = $('<div class="ob-fav-item" data-name="' + esc(fav.name) + '">'
					+ '<span class="ob-fav-item-label">' + esc(fav.favorite_name) + '</span>'
					+ (fav.is_global ? '<span class="ob-fav-item-badge">' + esc(__("Global")) + '</span>' : '')
					+ '<span class="ob-fav-item-del" title="' + esc(__("Hapus")) + '">&times;</span>'
					+ '</div>');
				$item.on("click", function (e) {
					if ($(e.target).hasClass("ob-fav-item-del")) return;
					applyFavorite(fav);
				});
				$item.find(".ob-fav-item-del").on("click", function (e) {
					e.stopPropagation();
					deleteFavorite(fav);
				});
				$list.append($item);
			});
		}

		function collectCurrentState() {
			var api = currentGroupApi();
			return {
				filters: listview.filter_area ? listview.filter_area.get() : [],
				group_fields: api ? api.getGroups() : [],
				sort_by: listview.sort_selector ? listview.sort_selector.sort_by : (listview.sort_by || null),
				sort_order: listview.sort_selector ? listview.sort_selector.sort_order : (listview.sort_order || "desc"),
			};
		}

		function saveCurrentAsFavorite(name, isGlobal) {
			var state = collectCurrentState();
			return frappe.db.insert({
				doctype: DOCTYPE,
				favorite_name: name,
				reference_doctype: listview.doctype,
				is_global: isGlobal ? 1 : 0,
				filters: JSON.stringify(state.filters || []),
				group_fields: JSON.stringify(state.group_fields || []),
				sort_by: state.sort_by || "",
				sort_order: state.sort_order || "desc",
			});
		}

		function closeDropdown() {
			if ($widget) $widget.find("#ob-fav-dd").hide();
			if ($widget) $widget.find("#ob-fav-new-form").hide();
		}

		function buildUI() {
			return $('<div id="ob-fav-wrap" class="filter-selector">'
				+ '<div class="btn-group">'
				+ '<button id="ob-fav-select" class="btn btn-default btn-sm">'
				+ '<span class="filter-icon button-icon" style="margin-right:6px;display:inline-flex">' + frappe.utils.icon("es-line-star") + '</span>'
				+ '<span class="button-label hidden-xs">' + __("Favorites") + '</span>'
				+ '</button>'
				+ '</div>'
				+ '<div id="ob-fav-dd">'
				+ '<div class="ob-fav-section-title">' + esc(__("Favorites")) + '</div>'
				+ '<div id="ob-fav-list"></div>'
				+ '<div class="ob-fav-divider"></div>'
				+ '<div class="ob-fav-save-item" id="ob-fav-save-toggle">' + esc(__("+ Simpan tampilan saat ini")) + '</div>'
				+ '<div class="ob-fav-new-form" id="ob-fav-new-form">'
				+ '<input type="text" id="ob-fav-new-name" placeholder="' + esc(__("Nama favorite")) + '">'
				+ '<label><input type="checkbox" id="ob-fav-new-global"> ' + esc(__("Bagikan ke semua user")) + '</label>'
				+ '<div class="ob-fav-new-actions">'
				+ '<button id="ob-fav-new-cancel">' + esc(__("Batal")) + '</button>'
				+ '<button class="primary" id="ob-fav-new-save">' + esc(__("Simpan")) + '</button>'
				+ '</div>'
				+ '</div>'
				+ '</div>'
				+ '</div>');
		}

		function attachUI($w) {
			$w.on("click", "#ob-fav-select", function (e) {
				e.stopPropagation();
				var open = $w.find("#ob-fav-dd").is(":visible");
				if (open) { closeDropdown(); return; }
				fetchFavorites().then(renderList);
				$w.find("#ob-fav-dd").show();
			});
			$w.on("click", "#ob-fav-save-toggle", function (e) {
				e.stopPropagation();
				$w.find("#ob-fav-new-form").show();
				$w.find("#ob-fav-new-name").val("").focus();
			});
			$w.on("click", "#ob-fav-new-cancel", function (e) {
				e.stopPropagation();
				$w.find("#ob-fav-new-form").hide();
			});
			$w.on("click", "#ob-fav-new-save", function (e) {
				e.stopPropagation();
				var name = $w.find("#ob-fav-new-name").val().trim();
				if (!name) { $w.find("#ob-fav-new-name").focus(); return; }
				var isGlobal = $w.find("#ob-fav-new-global").is(":checked");
				saveCurrentAsFavorite(name, isGlobal).then(function () {
					$w.find("#ob-fav-new-form").hide();
					return fetchFavorites();
				}).then(renderList).catch(function (err) {
					frappe.msgprint(__("Gagal menyimpan favorite") + (err && err.message ? ": " + err.message : ""));
				});
			});
			$w.on("click", "#ob-fav-dd", function (e) { e.stopPropagation(); });
			$(document).off("click.obfav_" + listview.doctype).on("click.obfav_" + listview.doctype, closeDropdown);
		}

		function injectUI() {
			var _r = frappe.get_route();
			if (!_r || _r[0] !== "List" || _r[1] !== listview.doctype) return false;
			var $root = listview.page ? listview.page.page_form : $();
			// Anchor after the Group widget if present, otherwise after
			// Filter - keeps Favorites as the rightmost of the three
			// (Filter, Group, Favorites), matching the Odoo reference
			// layout (Filters, Group By, Favorites left to right).
			var $anchor = $root.find("#ob-gg-wrap").first();
			if (!$anchor.length) $anchor = $root.find(".filter-selector").first();
			if (!$anchor.length) return false;
			var $existing = $root.find("#ob-fav-wrap");
			if ($existing.length && $existing.prev().is($anchor)) { $widget = $existing; return true; }
			$root.find("#ob-fav-wrap").remove();
			var $w = buildUI();
			$anchor.after($w);
			attachUI($w); $widget = $w; return true;
		}

		frappe.after_ajax(function () {
			if (!injectUI()) { var n = 0; var iv = setInterval(function () { n++; if (injectUI() || n > 20) clearInterval(iv); }, 200); }
		});
		// Re-anchor on every render/refresh too, same reasoning as
		// otobitz_group_by.js: the Group widget it anchors next to can be
		// removed/recreated when columns change.
		var oR = listview.render, oRf = listview.refresh;
		listview.render = function () { var r = oR.apply(this, arguments); setTimeout(injectUI, 500); return r; };
		listview.refresh = function () { var r = oRf.apply(this, arguments); setTimeout(injectUI, 600); return r; };
	}

	var _setup_view = frappe.views.ListView.prototype.setup_view;
	frappe.views.ListView.prototype.setup_view = function () {
		var r = _setup_view.apply(this, arguments);
		setup(this);
		return r;
	};
})();
