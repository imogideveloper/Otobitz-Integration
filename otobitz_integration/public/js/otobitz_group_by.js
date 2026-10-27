// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

// Global "Group By" widget for every standard List View (Desk-wide), not a
// per-doctype client script. Patches frappe.views.ListView.prototype once,
// so it applies to any doctype automatically with no per-doctype setup.
//
// Group options are *derived from the list view's own header columns*
// (listview.columns, i.e. exactly what List View Settings + in_list_view
// produced) rather than hardcoded per doctype - the dropdown always mirrors
// what's already on screen. Subclasses that render something other than a
// row table (Kanban/Report/Calendar/Gantt/Map/Image/File/Dashboard/Inbox)
// all override setup_view() without calling super.setup_view(), so this
// patch never fires for them - it only ever runs for the plain "List" view.
//
// Each date column expands into 3 separate choices (Tahun/Bulan/Hari),
// each independently selectable as its own group level.
//
// ponytail: Link field values are grouped by their raw stored value, not
// their title field - fine for the branch/status-style links this is aimed
// at, would need a title lookup for Links whose name isn't human-readable.
(function () {
	if (!frappe.views || !frappe.views.ListView) return;

	const MN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"];
	const GROUPABLE_FIELDTYPES = ["Link", "Select", "Dynamic Link", "Check"];
	const SKIP_FIELDNAMES = new Set(["name"]);

	if (!document.getElementById("ob-gg-style")) {
		var s = document.createElement("style"); s.id = "ob-gg-style";
		// Widget is built to look exactly like the native Filter button
		// (.filter-selector .btn-group .filter-button) and sits in the same
		// row (list_view.$filter_section), right next to it - not in the
		// standard-filter-section row below where the per-field dropdowns
		// (Status, Vendor, ...) live.
		s.textContent = "#ob-gg-wrap{margin:var(--margin-xs);position:relative}"
			+ "#ob-gg-select{display:flex;align-items:center}"
			+ "#ob-gg-badge{display:inline-block;font-weight:600;color:var(--text-color);background-color:var(--control-bg);min-width:21px;border-radius:22px;margin-left:6px;padding:0 6px;font-size:11px;line-height:17px;text-align:center}"
			+ "#ob-gg-dd{display:none;position:absolute;top:calc(100% + 4px);left:0;background:var(--fg-color,#fff);border:1px solid var(--border-color,#d1d8dd);border-radius:8px;min-width:230px;max-height:320px;overflow-y:auto;z-index:9999;padding:8px 0;box-shadow:var(--shadow-lg,0 4px 16px rgba(0,0,0,.12))}"
			+ ".ob-gg-dd-title{padding:0 12px 8px;font-size:11px;font-weight:600;color:#8d99a6;border-bottom:1px solid #f0f4f7;margin-bottom:4px;line-height:1.4}"
			+ ".ob-gg-opt{display:flex;align-items:center;gap:8px;padding:7px 12px;cursor:pointer;font-size:13px;color:#36414c}"
			+ ".ob-gg-opt:hover{background:#f5f7fa}"
			+ ".ob-gg-opt.is-selected{background:#eaf3fd;color:#1a2e4a;font-weight:600}"
			+ ".ob-gg-opt.is-disabled{cursor:not-allowed;color:#c2c9d1}"
			+ ".ob-gg-opt.is-disabled:hover{background:transparent}"
			+ ".ob-gg-opt-order{flex:0 0 auto;width:18px;height:18px;border-radius:50%;background:#2490ef;color:#fff;font-size:10px;font-weight:700;display:flex;align-items:center;justify-content:center}"
			+ ".ob-gg-opt-order-empty{background:transparent}"
			+ ".ob-gg-opt-label{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
			+ ".ob-gg-group-separator{margin:20px 0 8px;border-top:2px solid #dbe3ea}"
			+ ".ob-gg-group-header{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;margin:0 0 6px;background:#f7f9fb;border:1px solid #e3e8ee;border-radius:8px;cursor:pointer;user-select:none}"
			+ ".ob-gg-group-header:hover{background:#f2f6fa}"
			+ ".ob-gg-group-left{display:flex;align-items:center;gap:10px;min-width:0}"
			+ ".ob-gg-group-toggle{width:18px;text-align:center;color:#8d99a6;font-size:12px;flex:0 0 auto}"
			+ ".ob-gg-group-title{font-size:12px;font-weight:700;color:#36414c;line-height:1.3}"
			+ ".ob-gg-group-sub{font-size:11px;color:#8d99a6;line-height:1.3;margin-top:2px}"
			+ ".ob-gg-group-right{display:flex;align-items:center;gap:8px;flex-shrink:0}"
			+ ".ob-gg-group-total{font-size:12px;font-weight:700;color:#1a2e4a;white-space:nowrap}"
			+ ".ob-gg-group-count{font-size:11px;color:#68717d;background:#edf2f7;border:1px solid #dde5ee;border-radius:999px;padding:2px 8px;white-space:nowrap}"
			+ ".ob-gg-group-badge{flex:0 0 auto;font-size:10px;font-weight:600;color:#68717d;background:#edf2f7;border:1px solid #dde5ee;border-radius:999px;padding:3px 8px}"
			+ ".ob-gg-lvl-1{margin-top:10px}"
			+ ".ob-gg-lvl-2{margin-left:18px;background:#fbfcfd}"
			+ ".ob-gg-lvl-3{margin-left:36px;background:#fcfdfe}"
			+ ".ob-gg-lvl-4{margin-left:54px;background:#fff}"
			+ ".ob-gg-lvl-5{margin-left:72px;background:#fff}"
			+ ".ob-gg-hidden-by-collapse{display:none!important}";
		document.head.appendChild(s);
	}

	function esc(t) { return frappe.utils.escape_html(t == null ? "" : String(t)); }

	// Build the list of grouping choices straight from the columns actually
	// rendered in the header - same labels, same order.
	const DATE_GRANULARITIES = [
		{ suffix: "year", label: "Tahun" },
		{ suffix: "month", label: "Bulan" },
		{ suffix: "day", label: "Hari" },
	];

	function deriveGroups(listview) {
		var groups = [], amountField = null;
		(listview.columns || []).forEach(function (col) {
			if (col.type === "Tag") return;
			if (col.type === "Status") {
				groups.push({ key: "__status__", label: "Status", kind: "status" });
				return;
			}
			var df = col.df;
			if (!df || !df.fieldname || SKIP_FIELDNAMES.has(df.fieldname)) return;
			var ft = df.fieldtype;
			if (ft === "Date" || ft === "Datetime") {
				DATE_GRANULARITIES.forEach(function (gr) {
					groups.push({
						key: df.fieldname + ":" + gr.suffix,
						label: (df.label || df.fieldname) + " (" + gr.label + ")",
						kind: "date",
						granularity: gr.suffix,
						fieldname: df.fieldname,
					});
				});
			} else if (GROUPABLE_FIELDTYPES.indexOf(ft) > -1) {
				groups.push({ key: df.fieldname, label: df.label || df.fieldname, kind: "value", fieldname: df.fieldname });
			} else if (!amountField && ft === "Currency") {
				amountField = df.fieldname;
			}
		});
		return { groups: groups, amountField: amountField };
	}

	function groupValue(doc, g, doctype) {
		if (g.kind === "status") {
			var ind = frappe.get_indicator(doc, doctype);
			var v = ind ? ind[0] : (doc.status || "(Kosong)");
			return { key: String(v), label: String(v) };
		}
		if (g.kind === "date") {
			var raw = doc[g.fieldname];
			if (!raw) return { key: g.key + ":NO_DATE", label: "Tanpa Tanggal" };
			var d = frappe.datetime.str_to_obj(raw);
			if (g.granularity === "year") {
				return { key: g.key + ":" + d.getFullYear(), label: String(d.getFullYear()) };
			}
			if (g.granularity === "day") {
				return {
					key: g.key + ":" + d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"),
					label: d.getDate() + " " + MN[d.getMonth()] + " " + d.getFullYear(),
				};
			}
			return { key: g.key + ":" + d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0"), label: MN[d.getMonth()] + " " + d.getFullYear() };
		}
		var v = doc[g.fieldname];
		if (g.kind === "value" && g.fieldname) {
			var df = frappe.meta.get_docfield(doctype, g.fieldname);
			if (df && df.fieldtype === "Check") v = v ? "Ya" : "Tidak";
		}
		if (v === undefined || v === null || v === "") v = "(Kosong)";
		return { key: g.key + ":" + String(v), label: String(v) };
	}

	function setup(listview) {
		if (listview.__ob_gg_patched) return;
		listview.__ob_gg_patched = true;

		var selected_groups = [], collapsed_groups = {}, apply_timer = null, is_rendering = false;
		var $widget = null;

		function getRows() { return listview.$result ? listview.$result.find(".list-row-container").filter(function () { return !!getDN($(this)); }) : $(); }
		function getDN($r) { return $r.attr("data-name") || $r.find("[data-name]").first().attr("data-name") || null; }
		function getDoc(n) { return Array.isArray(listview.data) ? listview.data.find(function (d) { return d.name === n; }) || null : null; }
		function rmv() { if (!listview.$result) return; listview.$result.find(".ob-gg-group-header,.ob-gg-group-separator").remove(); listview.$result.find(".ob-gg-hidden-by-collapse").removeClass("ob-gg-hidden-by-collapse"); }
		function mkSep() { return $('<div class="ob-gg-group-separator">'); }

		function mkHdr(lv, mode, label, sub, ck, count, sum) {
			var ic = !!collapsed_groups[ck];
			var countLabel = count === 1 ? "1 data" : count + " data";
			var sumLabel = typeof format_currency === "function" ? format_currency(sum || 0) : (sum || 0);
			return $('<div class="ob-gg-group-header ob-gg-lvl-' + lv + '" data-group-level="' + lv + '" data-chain-key="' + esc(ck) + '" data-collapsed="' + (ic ? "1" : "0") + '">'
				+ '<div class="ob-gg-group-left"><div class="ob-gg-group-toggle">' + (ic ? "&#9658;" : "&#9660;") + '</div>'
				+ '<div class="ob-gg-group-text"><div class="ob-gg-group-title">' + esc(label) + '</div><div class="ob-gg-group-sub">' + esc(sub || "") + '</div></div></div>'
				+ '<div class="ob-gg-group-right">'
				+ (SUM_FIELD ? '<div class="ob-gg-group-total">' + esc(sumLabel) + '</div>' : '')
				+ '<div class="ob-gg-group-count">' + esc(countLabel) + '</div>'
				+ '<div class="ob-gg-group-badge">' + esc(mode) + '</div>'
				+ '</div></div>');
		}

		function doCollapse($h) {
			var lv = parseInt($h.attr("data-group-level"), 10);
			collapsed_groups[$h.attr("data-chain-key")] = true;
			$h.attr("data-collapsed", "1").find(".ob-gg-group-toggle").html("&#9658;");
			var $n = $h.next();
			while ($n.length) { if ($n.hasClass("ob-gg-group-header") && parseInt($n.attr("data-group-level"), 10) <= lv) break; $n.addClass("ob-gg-hidden-by-collapse"); $n = $n.next(); }
		}
		function doExpand($h) {
			var lv = parseInt($h.attr("data-group-level"), 10);
			delete collapsed_groups[$h.attr("data-chain-key")];
			$h.attr("data-collapsed", "0").find(".ob-gg-group-toggle").html("&#9660;");
			var $n = $h.next();
			while ($n.length) {
				if ($n.hasClass("ob-gg-group-header")) {
					var nl = parseInt($n.attr("data-group-level"), 10); if (nl <= lv) break;
					$n.removeClass("ob-gg-hidden-by-collapse");
					if ($n.attr("data-collapsed") === "1") { var $sb = $n.next(); while ($sb.length) { if ($sb.hasClass("ob-gg-group-header") && parseInt($sb.attr("data-group-level"), 10) <= nl) break; $sb.addClass("ob-gg-hidden-by-collapse"); $sb = $sb.next(); } }
				} else { $n.removeClass("ob-gg-hidden-by-collapse"); }
				$n = $n.next();
			}
			listview.$result.find(".ob-gg-group-header[data-collapsed='1']").each(function () { doCollapse($(this)); });
		}
		function bindEv() { listview.$result.find(".ob-gg-group-header").off("click.obgg").on("click.obgg", function (e) { e.stopPropagation(); $(this).attr("data-collapsed") === "1" ? doExpand($(this)) : doCollapse($(this)); }); }

		var GROUP_OPTIONS = [], SUM_FIELD = null, DATE_FIELD = null;

		function refreshGroupDefinitions() {
			var derived = deriveGroups(listview);
			GROUP_OPTIONS = derived.groups;
			SUM_FIELD = derived.amountField;
			var first_date = GROUP_OPTIONS.find(function (g) { return g.kind === "date"; });
			DATE_FIELD = first_date ? first_date.fieldname : null;
			// drop selections for groups that no longer exist (columns changed)
			var valid_keys = GROUP_OPTIONS.map(function (g) { return g.key; });
			selected_groups = selected_groups.filter(function (k) { return valid_keys.indexOf(k) > -1; });
		}

		function applyGrouping() {
			var _r = frappe.get_route();
			if (!_r || _r[0] !== "List" || _r[1] !== listview.doctype) return;
			if (is_rendering || !listview.$result) return;
			if (!selected_groups.length) { rmv(); return; }
			is_rendering = true;
			try {
				rmv();
				var rs = [];
				getRows().each(function () {
					var $r = $(this), n = getDN($r);
					if (!n) return;
					var d = getDoc(n), dVal = DATE_FIELD && d ? d[DATE_FIELD] : null, dObj = dVal ? frappe.datetime.str_to_obj(dVal) : null;
					var amt = SUM_FIELD && d ? flt(d[SUM_FIELD]) : 0;
					rs.push({ $r: $r, n: n, doc: d || {}, ts: dObj ? dObj.getTime() : 0, amt: amt });
				});
				if (DATE_FIELD) {
					rs.sort(function (a, b) { return a.ts !== b.ts ? a.ts - b.ts : a.n.localeCompare(b.n); });
					if (rs.length) { var $p = rs[0].$r.parent(); rs.forEach(function (r) { $p.append(r.$r); }); }
				}

				var countMap = {}, sumMap = {};
				var groupsByKey = {}; GROUP_OPTIONS.forEach(function (g) { groupsByKey[g.key] = g; });
				rs.forEach(function (item) {
					var chain = selected_groups.map(function (k) { return groupValue(item.doc, groupsByKey[k], listview.doctype); });
					chain.forEach(function (g, idx) {
						var ck = chain.slice(0, idx + 1).map(function (x) { return x.key; }).join("||");
						countMap[ck] = (countMap[ck] || 0) + 1;
						sumMap[ck] = (sumMap[ck] || 0) + item.amt;
					});
				});

				var pk = [], pt = null;
				rs.forEach(function (item) {
					var chain = selected_groups.map(function (k) { return { mode: groupsByKey[k].label, v: groupValue(item.doc, groupsByKey[k], listview.doctype) }; });
					if (!chain.length) return;
					var tk = chain[0].v.key;
					chain.forEach(function (c, idx) {
						var lv = idx + 1, ck = chain.slice(0, lv).map(function (x) { return x.v.key; }).join("||");
						if (pk[idx] !== ck) {
							if (idx === 0 && pt !== null && tk !== pt) item.$r.before(mkSep());
							var sub = idx === 0 ? "Group by " + c.mode : chain.slice(0, idx).map(function (x) { return x.v.label; }).join(" / ");
							item.$r.before(mkHdr(lv, c.mode, c.v.label, sub, ck, countMap[ck] || 0, sumMap[ck] || 0));
							pk[idx] = ck; for (var j = idx + 1; j < pk.length; j++) pk[j] = null;
						}
					});
					pt = tk;
				});
				bindEv();
				if (!Object.keys(collapsed_groups).length) listview.$result.find(".ob-gg-group-header").each(function () { doCollapse($(this)); });
				else listview.$result.find(".ob-gg-group-header[data-collapsed='1']").each(function () { doCollapse($(this)); });
			} finally { is_rendering = false; }
		}

		var MAX_LEVELS = 3;

		function sched(d) { clearTimeout(apply_timer); apply_timer = setTimeout(function () { refreshGroupDefinitions(); injectUI(); applyGrouping(); }, d || 400); }
		function updDisp() {
			if (!$widget) return;
			var $badge = $widget.find("#ob-gg-badge");
			if (selected_groups.length) {
				$widget.find("#ob-gg-select").addClass("btn-primary-light");
				$badge.text(String(selected_groups.length)).show();
				$widget.find("#ob-gg-clr").show();
			} else {
				$widget.find("#ob-gg-select").removeClass("btn-primary-light");
				$badge.hide();
				$widget.find("#ob-gg-clr").hide();
			}
		}
		function syncChk() {
			if (!$widget) return;
			$widget.find(".ob-gg-opt").each(function () {
				var $o = $(this), k = $o.attr("data-key"), idx = selected_groups.indexOf(k);
				var at_max = idx === -1 && selected_groups.length >= MAX_LEVELS;
				$o.toggleClass("is-selected", idx > -1).toggleClass("is-disabled", at_max);
				$o.find(".ob-gg-opt-order").html(idx > -1 ? String(idx + 1) : "").toggleClass("ob-gg-opt-order-empty", idx === -1);
			});
		}
		function buildUI() {
			var opts = GROUP_OPTIONS.map(function (o) {
				return '<div class="ob-gg-opt" data-key="' + esc(o.key) + '">'
					+ '<span class="ob-gg-opt-order ob-gg-opt-order-empty"></span>'
					+ '<span class="ob-gg-opt-label">' + esc(o.label) + '</span></div>';
			}).join("");
			// Markup mirrors the native Filter button exactly:
			// .filter-selector > .btn-group > button.btn.btn-default.btn-sm
			// (icon + label + badge), so it renders pixel-identical to it.
			return $('<div id="ob-gg-wrap" class="filter-selector">'
				+ '<div class="btn-group">'
				+ '<button id="ob-gg-select" class="btn btn-default btn-sm">'
				+ '<span class="filter-icon button-icon">' + frappe.utils.icon("es-line-filter") + '</span>'
				+ '<span class="button-label hidden-xs">' + __("Group") + '<span id="ob-gg-badge" style="display:none"></span></span>'
				+ '</button>'
				+ '<button id="ob-gg-clr" class="btn btn-default btn-sm" title="' + esc(__("Clear grouping")) + '" style="display:none">'
				+ '<span class="filter-icon button-icon">' + frappe.utils.icon("es-small-close") + '</span>'
				+ '</button>'
				+ '</div>'
				+ '<div id="ob-gg-dd"><div class="ob-gg-dd-title">Klik untuk menambah level (maks. ' + MAX_LEVELS + '), klik lagi untuk melepas.</div>' + opts
				+ '</div></div>');
		}
		function attachUI($w) {
			$w.on("click", "#ob-gg-select", function (e) { e.stopPropagation(); syncChk(); $w.find("#ob-gg-dd").toggle(); });
			$w.on("click", ".ob-gg-opt", function (e) {
				e.stopPropagation();
				var $o = $(this), k = $o.attr("data-key"), idx = selected_groups.indexOf(k);
				if (idx > -1) {
					selected_groups.splice(idx, 1);
				} else {
					if (selected_groups.length >= MAX_LEVELS) return;
					selected_groups.push(k);
				}
				collapsed_groups = {}; syncChk(); updDisp(); sched(300);
			});
			$w.on("click", "#ob-gg-clr", function (e) { e.stopPropagation(); selected_groups = []; collapsed_groups = {}; updDisp(); rmv(); syncChk(); $w.find("#ob-gg-dd").hide(); });
			// Namespaced per doctype so a stale, hidden, previously-visited
			// List View's copy of this widget can't react to clicks meant
			// for the live one after navigating away and back.
			$(document).off("click.obgg_" + listview.doctype).on("click.obgg_" + listview.doctype, function () { if ($widget) $widget.find("#ob-gg-dd").hide(); });
			$w.on("click", "#ob-gg-dd", function (e) { e.stopPropagation(); });
		}
		function injectUI() {
			var _r = frappe.get_route();
			if (!_r || _r[0] !== "List" || _r[1] !== listview.doctype) return false;
			if (!GROUP_OPTIONS.length) { if ($widget) { $widget.remove(); $widget = null; } return false; }
			// Anchor directly next to the native Filter button
			// (.filter-selector, inside page_form > filter-section) rather
			// than trusting a stored $filter_section reference - inserting
			// as its sibling guarantees the exact same flex row/parent the
			// native Filter + sort selector already render in correctly.
			var $root = listview.page ? listview.page.page_form : $();
			var $anchor = $root.find(".filter-selector").first();
			if (!$anchor.length) return false;
			var $existing = $root.find("#ob-gg-wrap");
			if ($existing.length && $existing.prev().is($anchor)) { $widget = $existing; return true; }
			$root.find("#ob-gg-wrap").remove();
			var $w = buildUI();
			$anchor.after($w);
			attachUI($w); $widget = $w; updDisp(); return true;
		}

		var oR = listview.render, oRf = listview.refresh;
		listview.render = function () { var r = oR.apply(this, arguments); sched(500); return r; };
		listview.refresh = function () { var r = oRf.apply(this, arguments); sched(600); return r; };

		refreshGroupDefinitions();
		frappe.after_ajax(function () {
			if (!injectUI()) { var n = 0; var iv = setInterval(function () { n++; if (injectUI() || n > 20) clearInterval(iv); }, 200); }
			sched(700);
		});
	}

	// Rolled out Desk-wide after validating the UX on Purchase Order first -
	// applies to every standard List View automatically now.
	var _setup_view = frappe.views.ListView.prototype.setup_view;
	frappe.views.ListView.prototype.setup_view = function () {
		var r = _setup_view.apply(this, arguments);
		setup(this);
		return r;
	};
})();
