// "Lihat Data API (JSON)" icon button on every OtoBitz-synced Sales Order/
// Sales Invoice/Payment Entry/Journal Entry/Purchase Order - opens the raw
// archive row(s) this document was built from (OtoBitz SO Detail/Receipt
// Detail/PO Detail) right in a modal, no page navigation. Only shown when
// the document's own OtoBitz reference number (wo/receipt/order number) is
// set - i.e. it actually came from a sync, not entered by hand.
frappe.provide("otobitz_integration");

if (!document.getElementById("otobitz-raw-json-btn-style")) {
	const style = document.createElement("style");
	style.id = "otobitz-raw-json-btn-style";
	style.textContent = `
		.oto-raw-json-btn, .oto-raw-json-btn:hover, .oto-raw-json-btn:focus { color: #e8740c !important; }
		.oto-raw-json-dialog .oto-raw-card { border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; margin-bottom: 12px; }
		.oto-raw-json-dialog .oto-raw-card:last-child { margin-bottom: 0; }
		.oto-raw-json-dialog .oto-raw-summary { width: 100%; margin-bottom: 10px; }
		.oto-raw-json-dialog .oto-raw-summary th { width: 170px; color: var(--text-muted); font-weight: 600; font-size: 12px; vertical-align: top; padding: 3px 10px 3px 0; }
		.oto-raw-json-dialog .oto-raw-summary td { font-size: 12.5px; padding: 3px 0; }
		.oto-raw-json-dialog .oto-raw-section-label { font-size: 11px; text-transform: uppercase; font-weight: 700; letter-spacing: .03em; color: var(--text-muted); margin-bottom: 6px; }
	`;
	document.head.appendChild(style);
}

// Fields that are internal bookkeeping, not real data from OtoBitz - not
// worth showing in the summary table.
const SKIP_FIELDS = new Set([
	"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx", "doctype",
	"raw_data", "raw_data_view", "raw_data_table", "dedup_key",
	"_user_tags", "_comments", "_assign", "_liked_by",
]);

function renderArchiveCard(doc) {
	const summary_rows = Object.keys(doc)
		.filter((k) => !SKIP_FIELDS.has(k) && doc[k] !== null && doc[k] !== "" && doc[k] !== undefined)
		.map(
			(k) =>
				`<tr><th>${frappe.utils.escape_html(frappe.unscrub(k))}</th><td>${frappe.utils.escape_html(String(doc[k]))}</td></tr>`
		)
		.join("");

	let raw_html = '<div class="text-muted">(kosong)</div>';
	if (doc.raw_data) {
		try {
			raw_html = otobitz_integration.json_to_table_html(JSON.parse(doc.raw_data));
		} catch (e) {
			raw_html = `<pre>${frappe.utils.escape_html(doc.raw_data)}</pre>`;
		}
	}

	return (
		`<div class="oto-raw-card">` +
		`<table class="oto-raw-summary">${summary_rows}</table>` +
		`<div class="oto-raw-section-label">${__("Data Mentah")}</div>` +
		raw_html +
		`</div>`
	);
}

otobitz_integration.open_raw_json_dialog = function (archive_doctype, filter_field, value) {
	const dialog = new frappe.ui.Dialog({
		title: __("Data API (JSON) - {0}", [archive_doctype]),
		size: "large",
	});
	dialog.$body.addClass("oto-raw-json-dialog").html(
		`<div class="text-muted" style="padding:30px;text-align:center;">${__("Memuat...")}</div>`
	);
	dialog.show();

	frappe
		.call({
			method: "frappe.client.get_list",
			args: {
				doctype: archive_doctype,
				filters: { [filter_field]: value },
				fields: ["name"],
				limit_page_length: 20,
				order_by: "creation asc",
			},
		})
		.then((r) => {
			const names = (r.message || []).map((row) => row.name);
			if (!names.length) {
				dialog.$body.html(`<div class="text-muted" style="padding:30px;text-align:center;">${__("Tidak ada data arsip.")}</div>`);
				return;
			}
			return Promise.all(names.map((name) => frappe.db.get_doc(archive_doctype, name))).then((docs) => {
				dialog.$body.html(docs.map(renderArchiveCard).join(""));
			});
		})
		.catch((err) => {
			dialog.$body.html(
				`<div class="text-danger" style="padding:20px;">${__("Gagal memuat data.")}</div>`
			);
			console.error("OtoBitz raw json dialog failed:", err);
		});
};

otobitz_integration.add_view_raw_json_button = function (frm, archive_doctype, filter_field, value_fieldname) {
	frm.page.wrapper.find(".oto-raw-json-btn").remove();
	// value_fieldname (custom_otobitz_wo_number/custom_otobitz_receipt_number/
	// custom_otobitz_order_number) is itself the "this document came from a
	// sync" signal - no separate custom_otobitz_endpoint field needed now
	// that this modal is the one place to see which endpoint it came from.
	const value = frm.doc[value_fieldname];
	if (!value) return;

	frm.page.add_action_icon(
		"es-line-code",
		() => otobitz_integration.open_raw_json_dialog(archive_doctype, filter_field, value),
		"oto-raw-json-btn",
		__("Lihat Data API (JSON)")
	);
};

frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		otobitz_integration.add_view_raw_json_button(frm, "OtoBitz SO Detail", "nomorwo", "custom_otobitz_wo_number");
	},
});

frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		otobitz_integration.add_view_raw_json_button(frm, "OtoBitz SO Detail", "nomorwo", "custom_otobitz_wo_number");
	},
});

frappe.ui.form.on("Payment Entry", {
	refresh(frm) {
		otobitz_integration.add_view_raw_json_button(frm, "OtoBitz Receipt Detail", "nomor", "custom_otobitz_receipt_number");
	},
});

frappe.ui.form.on("Journal Entry", {
	refresh(frm) {
		otobitz_integration.add_view_raw_json_button(frm, "OtoBitz Receipt Detail", "nomor", "custom_otobitz_receipt_number");
	},
});

frappe.ui.form.on("Purchase Order", {
	refresh(frm) {
		otobitz_integration.add_view_raw_json_button(frm, "OtoBitz PO Detail", "nomor", "custom_otobitz_order_number");
	},
});
