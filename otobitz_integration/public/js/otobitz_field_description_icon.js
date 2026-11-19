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

	// Frappe's own show_description_on_click() is SUPPOSED to guard against
	// building a second (i) icon, via `this._doc_url_info_card` - but that
	// property is only ever SET by set_doc_url() (the separate
	// documentation_url case), never by show_description_on_click() itself.
	// For a field whose icon comes from a description (not a
	// documentation_url), that guard never actually engages: every call
	// builds a brand new icon+card on top of whatever's already there.
	// Native Frappe rarely notices, because set_label() (the only native
	// caller) only calls this once the label text actually changes - but
	// set_description() below calls it on every refresh_input(), which
	// turned into one more duplicate (i) icon piling up per re-render
	// (confirmed live: 3+ stacked icons on every field, visibly laggy
	// forms). Fixed at the root with a dedicated flag - this also covers
	// set_label()'s own native call to the same method, not just ours.
	const original_show_description_on_click = proto.show_description_on_click;
	proto.show_description_on_click = function () {
		if (this._otobitz_description_icon_added) return;
		if (this.df && this.df.show_description_on_click) {
			this._otobitz_description_icon_added = true;
		}
		return original_show_description_on_click.call(this);
	};

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
		// Now properly deduped by the patch above - safe to call on every
		// refresh; this is what actually builds the icon+card the first
		// time a field with a description renders.
		this.show_description_on_click();
	};
})();
