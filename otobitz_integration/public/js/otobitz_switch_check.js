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
})();
