// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

// Global: every field's description text (the gray helper line Frappe
// shows below a field, e.g. "If not set, the currency precision will
// depend on number format.") is hidden by default and only appears when a
// small (i) icon next to the field's own label is clicked - site-wide, for
// every doctype, not configured per field.
//
// Frappe already has this exact behavior built in, gated per-field behind
// df.show_description_on_click (see ControlInput.set_description/
// show_description_on_click in base_input.js, and InfoCard in
// info_card.js - the (i) icon + click-to-toggle popover card come from
// there unmodified). Rather than setting that flag on every single
// DocField across the whole site (every doctype, every field, forever
// needing upkeep as new fields get added), set_description() is patched
// here to force it on for every ControlInput-based field the first time
// its description is rendered - same code path Frappe itself runs for a
// field that sets the flag explicitly, just applied everywhere instead of
// one field at a time.
(function () {
	if (!frappe.ui || !frappe.ui.form || !frappe.ui.form.ControlInput) return;

	const proto = frappe.ui.form.ControlInput.prototype;
	if (proto._otobitz_description_icon_patched) return;
	proto._otobitz_description_icon_patched = true;

	const original_set_description = proto.set_description;

	proto.set_description = function (description) {
		if (this.only_input || !this.df) {
			return original_set_description.call(this, description);
		}
		if (!this.df.show_description_on_click) {
			this.df.show_description_on_click = 1;
		}
		// With the flag now on, the original method's own first line
		// ("if (this.df.show_description_on_click) return;") makes it a
		// no-op - the always-visible help-box text is never populated -
		// while still updating this.df.description/this._description for
		// anything else that reads them.
		original_set_description.call(this, description);
		// show_description_on_click() guards against building a second
		// (i) icon itself (via this._doc_url_info_card), so calling it
		// again on every refresh is harmless - this is what actually
		// builds the icon+card the very first time a field with a
		// description renders.
		this.show_description_on_click();
	};
})();
