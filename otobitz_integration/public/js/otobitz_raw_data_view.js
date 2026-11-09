// "Tampilan" select (JSON/Tabel) next to raw_data on OtoBitz SO Detail and
// OtoBitz Failed Sync: depends_on in each doctype's json already shows/hides
// raw_data vs raw_data_table, this just renders raw_data's JSON into an HTML
// table the first time (and again on every toggle, since the field is
// read_only and can't go stale between renders).
frappe.provide("otobitz_integration");

if (!document.getElementById("otobitz-raw-table-style")) {
	const style = document.createElement("style");
	style.id = "otobitz-raw-table-style";
	style.textContent = `
		.otobitz-raw-table-wrap { max-height: 500px; overflow: auto; border: 1px solid var(--border-color); border-radius: var(--border-radius); }
		.otobitz-raw-table-wrap table { margin: 0; }
		.otobitz-raw-table-wrap th, .otobitz-raw-table-wrap td { white-space: nowrap; max-width: 320px; overflow: hidden; text-overflow: ellipsis; }
		.otobitz-raw-table-wrap td:hover { white-space: normal; overflow: visible; }
		.otobitz-raw-cell { margin: 0; white-space: pre-wrap; }
	`;
	document.head.appendChild(style);
}

otobitz_integration.json_to_table_html = function (data) {
	const esc = frappe.utils.escape_html;

	const scalar_cell = (value) => {
		if (value === null || value === undefined || value === "") return '<span class="text-muted">-</span>';
		if (typeof value === "object") return `<pre class="otobitz-raw-cell">${esc(JSON.stringify(value, null, 2))}</pre>`;
		return esc(String(value));
	};

	if (Array.isArray(data)) {
		if (!data.length) return '<div class="text-muted">(array kosong)</div>';
		if (data.some((row) => typeof row !== "object" || row === null)) {
			return `<ul>${data.map((v) => `<li>${scalar_cell(v)}</li>`).join("")}</ul>`;
		}
		const columns = [];
		data.forEach((row) => Object.keys(row).forEach((k) => columns.includes(k) || columns.push(k)));
		const head = columns.map((c) => `<th>${esc(c)}</th>`).join("");
		const body = data
			.map((row) => `<tr>${columns.map((c) => `<td>${scalar_cell(row[c])}</td>`).join("")}</tr>`)
			.join("");
		return `<div class="otobitz-raw-table-wrap"><table class="table table-bordered table-sm">
			<thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
	}

	if (data && typeof data === "object") {
		const rows = Object.keys(data)
			.map((k) => `<tr><th style="width:220px">${esc(k)}</th><td>${scalar_cell(data[k])}</td></tr>`)
			.join("");
		return `<div class="otobitz-raw-table-wrap"><table class="table table-bordered table-sm">
			<tbody>${rows}</tbody></table></div>`;
	}

	return `<div>${scalar_cell(data)}</div>`;
};

otobitz_integration.render_raw_data_view = function (frm) {
	if (!frm.fields_dict.raw_data_table) return;
	const wrapper = frm.fields_dict.raw_data_table.$wrapper;
	wrapper.empty();
	if (frm.doc.raw_data_view !== "Tabel") return;
	if (!frm.doc.raw_data) {
		wrapper.html('<div class="text-muted">(kosong)</div>');
		return;
	}
	let parsed;
	try {
		parsed = JSON.parse(frm.doc.raw_data);
	} catch (e) {
		wrapper.html(`<div class="text-danger">JSON tidak valid: ${frappe.utils.escape_html(e.message)}</div>`);
		return;
	}
	wrapper.html(otobitz_integration.json_to_table_html(parsed));
};

["OtoBitz SO Detail", "OtoBitz Failed Sync", "OtoBitz Receipt Detail", "OtoBitz PO Detail"].forEach((doctype) => {
	frappe.ui.form.on(doctype, {
		refresh: otobitz_integration.render_raw_data_view,
		raw_data_view: otobitz_integration.render_raw_data_view,
	});
});
