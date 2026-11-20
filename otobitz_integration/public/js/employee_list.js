// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

// Employee list: shorter Branch and Department text so every column fits on one screen without "..." (widths in
// desk.css). Only the displayed text changes - the full value stays in the tooltip, and clicking still filters by it.
//   Branch:     "OTOXPERT KELAPA GADING JAKARTA BY AUTO2000" -> "KELAPA GADING JAKARTA", "HO OTOXPERT AUTO2000" -> "HEAD OFFICE"
//   Department: "OPERATION DEPARTEMENT KELAPA GADING - AIO" -> "OPERATION KELAPA GADING" (company suffix and the word
//               "Departement" dropped - the column is already called Department)
(function () {
	const short = {
		branch(v) {
			v = (v || "").trim();
			if (/^HO\b/i.test(v)) return "HEAD OFFICE";
			return v.replace(/^OTOXPERT\s+/i, "").replace(/\s+(OPERATED\s+)?BY\s+AUTO2000$/i, "");
		},
		department(v) {
			return (v || "").replace(/\s+-\s+[A-Z0-9]+$/, "").replace(/\bDEPARTE?MENT\s+/i, "");
		},
	};

	function cell(fieldname, value) {
		if (!value) return "";
		const full = frappe.utils.escape_html(value);
		return `<a class="filterable" data-filter="${fieldname},=,${full}" title="${full}">${frappe.utils.escape_html(
			short[fieldname](value)
		)}</a>`;
	}

	const settings = (frappe.listview_settings["Employee"] = frappe.listview_settings["Employee"] || {});
	settings.formatters = Object.assign(settings.formatters || {}, {
		branch: (value) => cell("branch", value),
		department: (value) => cell("department", value),
	});
})();
