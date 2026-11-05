// Every Link field (forms, dialogs, report filters): clicked while it holds a value, it lists all its choices,
// not only the one already chosen. Frappe searches with the text in the box, so a filled field (Report Template:
// "Financial Ratios Analysis") offered just that one, and changing it meant clearing the box first. Now a click
// searches as for an empty box (the field's own filters still apply), and the text is selected, so typing
// replaces it and narrows the list as before.
(() => {
	const ControlLink = frappe.ui.form.ControlLink;
	if (!ControlLink || ControlLink.prototype._otobitz_all_options) return;
	ControlLink.prototype._otobitz_all_options = true;

	const make_input = ControlLink.prototype.make_input;
	ControlLink.prototype.make_input = function () {
		const result = make_input.apply(this, arguments);
		const me = this;
		const show_all = () => {
			// an empty box: Frappe's own focus handler lists everything already; a list open: the user is in it
			if (!me.$input?.val() || me.autocomplete_open || me.df?.read_only) return;
			me.$input.get(0).select();
			me.on_input({ target: { value: "" } });
		};
		this.$input?.on("focus.otobitz_all click.otobitz_all", show_all);
		return result;
	};
})();
