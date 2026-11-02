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

	// Align the toggle with every other field's input column, CSS-only.
	//
	// A prior version of this measured a sibling field's .clearfix width at
	// runtime via getBoundingClientRect() and applied it as an explicit
	// inline width on .switch-text, re-running on every refresh() (which
	// fires on every value change, including the click that flips the
	// switch itself). That measurement could read a slightly different
	// width each time it re-ran mid-layout-settle, and each run wrote a new
	// inline width that itself shifted the layout before the next run - on
	// some pages this compounded into the switch-text column visibly
	// growing wider with every click instead of converging. CSS only
	// has no re-run and nothing to compound: it's recomputed by the browser
	// on layout change, not by re-invoking JS on every value change.
	//
	// clamp(110px,32%,190px) is the same flex-basis already used for
	// ordinary fields' label column across this app's tuned forms (see
	// Sales Order Full Width / Purchase Order Form's `.clearfix` rule) -
	// reusing it here keeps switches visually consistent with those forms'
	// own labels without depending on being inside one of them. A form with
	// its own more specific per-doctype CSS for `.switch-text` (e.g.
	// `.so-hz`, `.po-hz`) still wins via normal CSS specificity, so this is
	// purely the sane default for every other (untuned) form - Account's
	// "Disable" toggle included.
	if (!document.getElementById("ob-switch-align-style")) {
		const style = document.createElement("style");
		style.id = "ob-switch-align-style";
		style.textContent = `
.frappe-control[data-fieldtype="Check"] .switch-control{justify-content:flex-start !important;gap:8px}
.frappe-control[data-fieldtype="Check"] .switch-text{flex:0 0 clamp(110px,32%,190px);max-width:320px;box-sizing:border-box}
`;
		document.head.appendChild(style);
	}
})();
