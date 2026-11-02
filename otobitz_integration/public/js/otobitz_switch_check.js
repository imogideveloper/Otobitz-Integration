// Every Check field (in every doctype, core and custom alike) renders as a
// sliding toggle instead of a checkbox - matching production's look there
// (e.g. Sales Order's "Sub-Contract"/"CRM / Non CRM").
//
// Frappe already ships this exact visual as fieldtype "Switch"
// (ControlSwitch, see frappe/public/js/frappe/form/controls/switch.js) -
// same value semantics (0/1), same validate/read-only behavior, only the
// wrapper markup differs so CSS can skin it (frappe/public/scss/common/
// controls.scss, class `switch-control`). Reusing that markup here (instead
// of writing new CSS) means the toggle and its label-left/control-right
// layout are both already correct and theme-aware (incl. dark mode) for
// free - and nothing about field *data* changes: these stay fieldtype
// Check in the database/doctype schema, only make_wrapper()'s output does.
(() => {
	const ControlCheck = frappe.ui.form.ControlCheck;
	if (!ControlCheck || ControlCheck.prototype.__ob_switch_skin) return;

	ControlCheck.prototype.__ob_switch_skin = true;
	ControlCheck.prototype.make_wrapper = function () {
		this.$wrapper = $(`<div class="form-group frappe-control">
			<label class="switch-control">
				<span class="switch-text">
					<span class="label-area"></span>
					<span class="disp-area"></span>
					<div class="help-box small text-extra-muted hide"></div>
				</span>
				<span class="input-area"></span>
				<span class="switch-visual" aria-hidden="true">
					<span class="switch-thumb"></span>
				</span>
				<span class="ml-1 help"></span>
			</label>
		</div>`).appendTo(this.parent);
	};

	const make_input = ControlCheck.prototype.make_input;
	ControlCheck.prototype.make_input = function () {
		make_input.apply(this, arguments);
		this.$input && this.$input.attr("role", "switch");
	};

	// On a read-only field, base_input.js's refresh() hides .input-area and
	// fills .disp-area via set_disp_area() instead - normally a plain text
	// readout, but here .disp-area sits inside the switch-skinned markup too,
	// so formatters.Check's raw "<input disabled>" would render a second,
	// undesired checkbox next to the switch. The switch-visual track already
	// reflects checked state on its own, via CSS `:has(input:checked)` on
	// .input-area's real (hidden-but-present, not removed) input - so
	// .disp-area never needs its own content here.
	ControlCheck.prototype.set_disp_area = function () {};

	// Align the toggle with every other field's input column, CSS-only, one
	// rule for the whole Desk (not duplicated per-doctype anymore - this used
	// to also be copy-pasted into this app's tuned forms (Sales Order Full
	// Width, Purchase Order Form, Purchase/Sales Invoice Full Width, Payment
	// Entry Full Width), each with a flex-basis that drifted independently
	// (clamp(...) in some, auto in others) and fought each other / this rule
	// for who wins by CSS specificity - that's why the toggle visibly sat at
	// a different spot form to form despite looking like "the same switch".
	// Removed from all of them; this is now the only place it's set.
	//
	// A still-earlier version measured a sibling field's .clearfix width at
	// runtime via getBoundingClientRect() and applied it as an explicit
	// inline width on .switch-text, re-running on every refresh() (which
	// fires on every value change, including the click that flips the
	// switch itself) - that measurement could read a slightly different
	// width each time it re-ran mid-layout-settle, compounding into the
	// column visibly growing wider with every click on some pages.
	//
	// clamp(110px,32%,190px) is the exact flex-basis this app's forms use
	// for an ordinary field's own label column (the `.clearfix` element
	// built by Frappe's ControlInput.make_wrapper(), frappe/public/js/
	// frappe/form/controls/base_input.js) - giving switch-text the identical
	// formula, not just a visually-similar one, is what makes a toggle's
	// label column match a text field's label column in the same form by
	// construction, in any viewport, not by coincidence.
	// Targets both [data-fieldtype="Check"] (skinned as a switch by this file,
	// above) and [data-fieldtype="Switch"] (ControlSwitch, native Frappe -
	// already renders this exact switch-control/switch-text markup on its
	// own, never touched by make_wrapper() above, but needing the identical
	// alignment rule). A field declared fieldtype "Switch" directly in its
	// DocType (e.g. Purchase Order's "Ask confirmation") would otherwise
	// never get this rule at all and keep whatever width the browser's
	// default flex sizing happens to give switch-text.
	// Frappe's own label.switch-control ships `gap: 2rem` (32px) between
	// .switch-text and .switch-visual (frappe/public/scss/common/
	// controls.scss) - an ordinary field's label/.clearfix sits only 8px
	// from its input (the gap set on `sel` in every tuned form's own CSS
	// above). That extra 24px was invisible when switch-text had slack to
	// spare, but on a label right at the edge of its clamp()'d column width
	// (e.g. Purchase Order's "Ask confirmation", 17 characters) it was
	// enough to force a second line - the label itself was never
	// misaligned, it just had less real width to render in than a same-
	// column text field's label did. `gap:8px` here matches that 8px
	// exactly, so switch-text gets the same usable width a text field's
	// label gets from the same clamp().
	if (!document.getElementById("ob-switch-align-style")) {
		const style = document.createElement("style");
		style.id = "ob-switch-align-style";
		style.textContent = `
.frappe-control[data-fieldtype="Check"] .switch-control,.frappe-control[data-fieldtype="Switch"] .switch-control{justify-content:flex-start !important;gap:8px !important}
.frappe-control[data-fieldtype="Check"] .switch-text,.frappe-control[data-fieldtype="Switch"] .switch-text{flex:0 0 clamp(110px,32%,190px);max-width:none;box-sizing:border-box}
.frappe-control[data-fieldtype="Check"] .label-area,.frappe-control[data-fieldtype="Switch"] .label-area{white-space:nowrap}
`;
		document.head.appendChild(style);
	}
})();
