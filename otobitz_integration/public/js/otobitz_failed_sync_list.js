// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

// Adds a bulk "Sync Ulang" action to the OtoBitz Failed Sync List View -
// select one or more queued failures (standard Frappe checkbox multi-select,
// nothing custom needed for that part) and retry them against the raw_data
// stored at failure time, without re-fetching from the OtoBitz API. See
// retry.py for the actual dispatch logic this just calls into.
frappe.listview_settings["OtoBitz Failed Sync"] = {
	onload(listview) {
		listview.page.add_actions_menu_item(
			__("Sync Ulang"),
			() => {
				const names = listview.get_checked_items(true);
				if (!names.length) {
					frappe.msgprint(__("Pilih dulu minimal 1 record yang mau di-sync ulang."));
					return;
				}
				frappe.confirm(__("Sync ulang {0} record yang dipilih?", [names.length]), () => {
					frappe.call({
						method: "otobitz_integration.otobitz_integration.sync.retry.retry_failed_syncs",
						args: { names },
						freeze: true,
						freeze_message: __("Sedang sync ulang..."),
					}).then((r) => {
						const res = r.message || {};
						const failed_lines = (res.results || [])
							.filter((row) => !row.ok)
							.map((row) => `<li><b>${frappe.utils.escape_html(row.record_key)}</b>: ${frappe.utils.escape_html(row.message)}</li>`)
							.join("");
						frappe.msgprint({
							title: __("Hasil Sync Ulang"),
							indicator: res.failed ? "orange" : "green",
							message:
								`${res.succeeded || 0} dari ${res.total || 0} record berhasil di-sync ulang.` +
								(failed_lines ? `<p>${__("Masih gagal")}:</p><ul>${failed_lines}</ul>` : ""),
						});
						listview.refresh();
					});
				});
			},
			true
		);
	},
};
