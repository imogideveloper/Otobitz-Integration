// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

// Makes the TAM / Non TAM split jump out in the List View instead of
// reading as plain Select text - same badge language as the Ringkasan
// dashboard's own "Sumber" box (otobitz_po_detail.js's pod_sumber_badge()),
// just the List View's own formatter hook instead of the Desk form.
frappe.listview_settings["OtoBitz PO Detail"] = {
	formatters: {
		sumber(value) {
			if (!value) return "";
			const cls = value === "TAM" ? "wo-badge-tam" : "wo-badge-nontam";
			return `<span class="wo-badge ${cls}">${frappe.utils.escape_html(value)}</span>`;
		},
	},
};

(function () {
	if (document.getElementById("pod-sumber-badge-style")) return;
	const s = document.createElement("style");
	s.id = "pod-sumber-badge-style";
	s.textContent = `
.wo-badge{font-size:11px;font-weight:500;padding:1px 8px;border-radius:10px;display:inline-block}
.wo-badge-tam{background:var(--bg-green, #e6f4ea);color:var(--text-on-light-green, #137333)}
.wo-badge-nontam{background:var(--bg-orange, #fef3e2);color:var(--text-on-light-orange, #b35900)}
`;
	document.head.appendChild(s);
})();
