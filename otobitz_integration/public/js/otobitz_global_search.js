// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

// Global Odoo-style search box for every standard List View (Desk-wide),
// replacing the native per-field "standard filter section" row (one
// dropdown/input per in_standard_filter field - ID, Customer, Company, ...)
// which gets visually noisy on doctypes with many such fields.
//
// Typing shows a dropdown with one suggestion per searchable column ("Cari
// {field} untuk: {term}") - same idea as Odoo's search bar telling you which
// field a term could match (Customer? Company? ...). Picking a suggestion
// doesn't reinvent query plumbing: it just calls the list view's own
// filter_area.add(), the exact same mechanism the native per-field filters
// and the Filter button already use - so the result is an ordinary filter
// pill, with all of filter_area's own refresh/persistence/clear behavior for
// free.
//
// Searchable fields are *derived from the list view's own header columns*
// (listview.columns), same source otobitz_group_by.js's Group By widget
// already uses - the box always offers exactly what's on screen, no
// hardcoded per-doctype field lists.
//
// ponytail: fields searched are Data/Small Text/Read Only/Link/Dynamic
// Link/Select only, always "like" (even for Select/Link) - good enough for
// free-text search; an exact-match mode or Link-by-title-field search would
// need more than this box's scope today.
(function () {
	if (!frappe.views || !frappe.views.ListView) return;

	// Every fieldtype that can actually show up as a list view header column
	// (frappe.model.no_value_type - layout-only types like Section Break -
	// never reach listview.columns in the first place, so excluding them
	// here is just documentation, not a real filter).
	// ponytail: Currency/Int/Float/Date/Check are searched with the same
	// plain "like" as text fields (e.g. "like '%150000%'" on a Currency
	// column) rather than a type-aware operator (</>/exact-date-range/
	// true-false) - good enough for "does this number/date/flag's printed
	// value contain what I typed", a real operator picker would need its own
	// per-type UI beyond this box's scope today.
	const SEARCHABLE_FIELDTYPES = [
		"Data", "Small Text", "Text", "Long Text", "Code", "Read Only",
		"Link", "Dynamic Link", "Select",
		"Int", "Float", "Currency", "Percent", "Duration",
		"Date", "Datetime", "Check",
	];

	if (!document.getElementById("ob-gs-style")) {
		var s = document.createElement("style");
		s.id = "ob-gs-style";
		// Hiding (not just emptying) the native row - it stays in the DOM so
		// other code that references ".standard-filter-section" keeps working,
		// it just never takes visual space again.
		// Another installed app (imogi_finance's "erg-style" client script,
		// for Payment Entry's multi-row standard filter layout) injects its
		// own ".standard-filter-section.flex{display:flex!important}" rule
		// at the exact same specificity as a 2-class selector here - a tie
		// that resolves by DOM/source order, which isn't reliably "us last"
		// (script load order across apps isn't guaranteed). Repeating the
		// class a 3rd time keeps matching the identical elements (repeated
		// class selectors don't change what matches, only the specificity
		// count) while strictly outranking their 2-class rule regardless of
		// which style tag landed in the DOM first.
		s.textContent = ".standard-filter-section, .standard-filter-section.flex.flex{display:none!important}"
			// .filter-section natively shrinks to fit its own children's width
			// (721px of a 1690px row, say) rather than filling the row, so a
			// margin-right:auto spacer on our box - which only pushes into
			// *its own* flex container's free space - had nothing to push
			// into until .filter-section itself is stretched to fill the row.
			// align-items:center - the native Filter/Group/Favorites buttons
			// carry their own top margin (var(--margin-xs), from the native
			// ".filter-selector .btn-group" rule) that our box doesn't have,
			// so without an explicit center-alignment the two sit a few
			// pixels off from each other instead of sharing one visual
			// baseline.
			+ ".page-form .filter-section{flex:1 1 auto;align-items:center}"
			// margin-right:auto (classic flexbox spacer trick) keeps the search
			// box pinned to the left edge while pushing every sibling after it
			// (Filter/Group/Favorites/sort) to the right edge of the row - same
			// right-aligned spot they sit in on a plain, un-patched list view.
			+ "#ob-gs-wrap{position:relative;margin:0 auto 0 0;flex:0 0 220px;order:-1}"
			+ "#ob-gs-input-group{position:relative;display:flex;align-items:center}"
			+ "#ob-gs-input-group .ob-gs-icon{position:absolute;left:8px;display:flex;color:#8d99a6;pointer-events:none}"
			+ "#ob-gs-input{width:100%;height:30px;padding:0 28px 0 30px;border:1px solid var(--border-color,#d1d8dd);border-radius:6px;background:var(--control-bg,#fff);font-size:13px}"
			+ "#ob-gs-clear{position:absolute;right:6px;display:none;color:#8d99a6;cursor:pointer;padding:2px}"
			+ "#ob-gs-wrap.has-value #ob-gs-clear{display:flex}"
			+ "#ob-gs-dd{display:none;position:absolute;top:calc(100% + 4px);left:0;min-width:100%;width:max-content;max-width:360px;background:var(--fg-color,#fff);border:1px solid var(--border-color,#d1d8dd);border-radius:8px;max-height:280px;overflow-y:auto;z-index:9999;padding:6px 0;box-shadow:var(--shadow-lg,0 4px 16px rgba(0,0,0,.12))}"
			+ ".ob-gs-row{padding:7px 12px;cursor:pointer;font-size:13px;color:#36414c;white-space:nowrap}"
			+ ".ob-gs-row:hover,.ob-gs-row.is-active{background:#f5f7fa}"
			+ ".ob-gs-row b{font-weight:600}"
			+ ".ob-gs-empty{padding:7px 12px;font-size:12px;color:#8d99a6}";
		document.head.appendChild(s);
	}

	function esc(t) { return frappe.utils.escape_html(t == null ? "" : String(t)); }

	function statusFieldname(doctype) {
		// The "Status" header column (frappe.has_indicator()) isn't backed by
		// a single fixed fieldname - it's whichever of these the doctype
		// actually uses (frappe/public/js/frappe/model/indicator.js mirrors
		// this same precedence for rendering the indicator itself).
		var workflow_fieldname = frappe.workflow.get_state_fieldname(doctype);
		if (workflow_fieldname) return workflow_fieldname;
		if (frappe.meta.has_field(doctype, "status")) return "status";
		if (frappe.meta.has_field(doctype, "enabled")) return "enabled";
		if (frappe.meta.has_field(doctype, "disabled")) return "disabled";
		return null;
	}

	function deriveSearchFields(listview) {
		var fields = [{ fieldname: "name", label: "ID" }];
		var seen = { name: true };
		(listview.columns || []).forEach(function (col) {
			if (col.type === "Status") {
				var fn = statusFieldname(listview.doctype);
				if (fn && !seen[fn]) { seen[fn] = true; fields.push({ fieldname: fn, label: "Status" }); }
				return;
			}
			var df = col.df;
			if (!df || !df.fieldname || seen[df.fieldname]) return;
			if (SEARCHABLE_FIELDTYPES.indexOf(df.fieldtype) === -1) return;
			seen[df.fieldname] = true;
			fields.push({ fieldname: df.fieldname, label: df.label || df.fieldname });
		});
		return fields;
	}

	function setup(listview) {
		if (listview.__ob_gs_patched) return;
		listview.__ob_gs_patched = true;

		var SEARCH_FIELDS = [];
		var active_idx = -1;
		var $widget = null;
		// Odoo's own behaviour (what this box is modeled on): typing searches
		// every offered field at once (OR'd together) - it doesn't guess a
		// single field and risk coming up empty just because the term
		// happens not to match *that one* column. The per-field suggestion
		// row only narrows it down to one exact field once the user
		// explicitly picks it (click, or arrow + Enter) - not on every
		// keystroke.
		//
		// List View's own get_args()/get_filters_for_args() (base_list.js)
		// only ever emits AND'd filters - there's no "OR across these
		// fields" primitive in filter_area at all. or_filters *is* a real,
		// already-validated backend mechanism (frappe/model/db_query.py,
		// wired through frappe.desk.reportview.execute) - just never
		// plumbed into List View's own request building - so it's injected
		// here by wrapping get_args() instead of going through filter_area.
		var live_term = "";
		var applied_fieldname = null; // set only once a single suggestion is explicitly picked

		var _get_args = listview.get_args.bind(listview);
		listview.get_args = function () {
			var args = _get_args();
			if (!applied_fieldname && live_term && SEARCH_FIELDS.length) {
				args.or_filters = SEARCH_FIELDS.map(function (f) {
					return [listview.doctype, f.fieldname, "like", "%" + live_term + "%"];
				});
			}
			return args;
		};

		function refreshFields() { SEARCH_FIELDS = deriveSearchFields(listview); }

		function clearAppliedFilter() {
			var had_or_filter = !!live_term;
			live_term = "";
			if (applied_fieldname) {
				var fn = applied_fieldname;
				applied_fieldname = null;
				listview.filter_area.remove(fn);
			} else if (had_or_filter) {
				listview.refresh();
			}
		}

		function rows(term) {
			if (!SEARCH_FIELDS.length) return "";
			return SEARCH_FIELDS.map(function (f, i) {
				return '<div class="ob-gs-row' + (i === active_idx ? " is-active" : "") + '" data-idx="' + i + '">'
					+ "Cari <b>" + esc(f.label) + '</b> untuk: &quot;' + esc(term) + "&quot;</div>";
			}).join("");
		}

		function renderDD($w, term) {
			var $dd = $w.find("#ob-gs-dd");
			if (!term) { $dd.hide(); return; }
			var html = rows(term);
			$dd.html(html || '<div class="ob-gs-empty">Tidak ada kolom yang bisa dicari</div>').show();
		}

		// Explicitly picking one suggestion (click, or arrow + Enter) narrows
		// the OR-across-every-field live search down to that single field,
		// as a real filter_area filter pill - same as before.
		function applyField($w, idx) {
			var term = $w.find("#ob-gs-input").val().trim();
			var f = SEARCH_FIELDS[idx];
			if (!term || !f) return;
			live_term = "";
			if (applied_fieldname && applied_fieldname !== f.fieldname) {
				listview.filter_area.remove(applied_fieldname);
			}
			applied_fieldname = f.fieldname;
			listview.filter_area.add([[listview.doctype, f.fieldname, "like", "%" + term + "%"]]);
			$w.find("#ob-gs-input").val("");
			$w.find("#ob-gs-dd").hide();
			active_idx = -1;
			$w.addClass("has-value");
		}

		// Debounced so every keystroke doesn't fire its own list refresh -
		// same 300ms the native standard filters debounce their own
		// onchange refresh at (base_list.js's debounced_refresh_list_view).
		var liveSearch = frappe.utils.debounce(function (term) {
			live_term = term;
			listview.start = 0;
			listview.refresh();
		}, 300);

		function buildUI() {
			return $('<div id="ob-gs-wrap">'
				+ '<div id="ob-gs-input-group">'
				+ '<span class="ob-gs-icon">' + frappe.utils.icon("es-line-search", "sm") + "</span>"
				+ '<input id="ob-gs-input" type="text" placeholder="' + esc(__("Cari...")) + '" autocomplete="off">'
				+ '<span id="ob-gs-clear">' + frappe.utils.icon("es-small-close", "xs") + "</span>"
				+ "</div>"
				+ '<div id="ob-gs-dd"></div>'
				+ "</div>");
		}

		function attachUI($w) {
			var $input = $w.find("#ob-gs-input");
			$input.on("input", function () {
				var term = $input.val().trim();
				// The x button also doubles as "clear the applied search", so
				// it must stay visible whenever a filter from this box is
				// active - not just while there's unsubmitted text in the
				// box, which is all applyField() leaves behind once a
				// suggestion is actually picked (it empties the input).
				$w.toggleClass("has-value", !!term || !!applied_fieldname);
				active_idx = -1;
				if (applied_fieldname) {
					// Typing again after having picked a specific field drops
					// back to the OR-everything live search - the single-field
					// pick was a one-time narrowing, not a sticky mode.
					listview.filter_area.remove(applied_fieldname);
					applied_fieldname = null;
				}
				if (!term) {
					// Emptying the box (typing it back down, or deleting all
					// of it) removes this box's filter immediately, not
					// debounced - there's no "search for nothing" to wait
					// out, the intent is unambiguous the instant it's empty.
					liveSearch.cancel && liveSearch.cancel();
					clearAppliedFilter();
				} else {
					liveSearch(term);
				}
				renderDD($w, term);
			});
			$input.on("keydown", function (e) {
				var $rows = $w.find(".ob-gs-row");
				if (e.key === "ArrowDown") {
					e.preventDefault();
					if (!$rows.length) return;
					active_idx = (active_idx + 1) % $rows.length;
					renderDD($w, $input.val().trim());
				} else if (e.key === "ArrowUp") {
					e.preventDefault();
					if (!$rows.length) return;
					active_idx = (active_idx - 1 + $rows.length) % $rows.length;
					renderDD($w, $input.val().trim());
				} else if (e.key === "Enter") {
					e.preventDefault();
					applyField($w, active_idx > -1 ? active_idx : 0);
				} else if (e.key === "Escape") {
					$w.find("#ob-gs-dd").hide();
				}
			});
			$w.on("click", ".ob-gs-row", function () { applyField($w, parseInt($(this).attr("data-idx"), 10)); });
			$w.on("click", "#ob-gs-clear", function (e) {
				e.stopPropagation();
				liveSearch.cancel && liveSearch.cancel();
				$input.val("").trigger("focus");
				$w.removeClass("has-value");
				$w.find("#ob-gs-dd").hide();
				clearAppliedFilter();
			});
			$w.on("click", "#ob-gs-dd", function (e) { e.stopPropagation(); });
			// Namespaced per doctype - same reasoning as otobitz_group_by.js's
			// identical pattern: a stale hidden List View's own copy of this
			// widget must not react to document clicks meant for the live one.
			$(document).off("click.obgs_" + listview.doctype).on("click.obgs_" + listview.doctype, function () {
				if ($widget) $widget.find("#ob-gs-dd").hide();
			});
		}

		function injectUI() {
			var _r = frappe.get_route();
			if (!_r || _r[0] !== "List" || _r[1] !== listview.doctype) return false;
			// Lives inside .filter-section itself (same row as the native
			// Filter/Group/Favorites/Sort buttons, order:-1'd to the front of
			// it) rather than as a sibling of that row in .page-form - the
			// sibling approach pushed the whole row onto its own line since
			// .page-form's own flex-wrap no longer had room for both.
			var $root = listview.$filter_section;
			if (!$root || !$root.length) return false;
			var $existing = $root.find("#ob-gs-wrap");
			if ($existing.length) { $widget = $existing; return true; }
			var $w = buildUI();
			$root.prepend($w);
			attachUI($w);
			$widget = $w;
			return true;
		}

		refreshFields();
		var oR = listview.render, oRf = listview.refresh;
		listview.render = function () { var r = oR.apply(this, arguments); refreshFields(); injectUI(); return r; };
		listview.refresh = function () { var r = oRf.apply(this, arguments); refreshFields(); injectUI(); return r; };

		frappe.after_ajax(function () {
			if (!injectUI()) { var n = 0; var iv = setInterval(function () { n++; if (injectUI() || n > 20) clearInterval(iv); }, 200); }
		});
	}

	// Same rollout approach as otobitz_group_by.js - subclasses that render
	// something other than a row table override setup_view() without calling
	// super.setup_view(), so this patch never fires for them.
	var _setup_view = frappe.views.ListView.prototype.setup_view;
	frappe.views.ListView.prototype.setup_view = function () {
		var r = _setup_view.apply(this, arguments);
		setup(this);
		return r;
	};
})();
