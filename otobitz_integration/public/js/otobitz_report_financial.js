// Financial statements (Balance Sheet, Profit and Loss, Cash Flow, Trial Balance...): laid out as the
// auto_trust site's (ported from auto_trust report_filter_layout.js / report_financial.js /
// report_chart_toggle.js; only these reports, every other query report is left as Frappe draws it).
// Filters: a form, label left | the choice right, in reading order (company, the period, then the narrowing
// ones), the switches in a column on the right; the tree's Set Level / Expand in a cell among the filters.
// Table: no row numbers nor filter row; amounts in whole rupiah without "Rp" (the column says it: "2026 (Rp)"),
// negatives in brackets and red, groups and totals bold, a total under a line; the rows scroll under a fixed
// header, filters and cards. The cards in whole rupiah. The chart hidden behind a Show Chart button.
(() => {
	const QueryReport = frappe.views.QueryReport;
	if (!QueryReport || QueryReport.prototype._otobitz_financial) return;
	QueryReport.prototype._otobitz_financial = true;

	const REPORTS = [
		"Balance Sheet",
		"Profit and Loss Statement",
		"Cash Flow",
		"Trial Balance",
		"Consolidated Financial Statement",
		"Profit and Loss per Cost Center",
		"Profitability Analysis",
	];
	const is_financial = (report) => REPORTS.includes(report.report_name);
	// reports with the financial statements' filter form only (the auto_trust site has it on every query report);
	// their table stays Frappe's own
	const FILTER_ONLY = ["Custom Financial Statement", "General Ledger"];
	const has_filter_form = (report) => is_financial(report) || FILTER_ONLY.includes(report.report_name);

	// the filters' order; the others after them, as the report has them
	const ORDER = [
		"company",
		"periodicity",
		"filter_based_on",
		"fiscal_year",
		"from_fiscal_year",
		"period_start_date",
		"from_date",
		"to_fiscal_year",
		"period_end_date",
		"to_date",
		"presentation_currency",
		"cost_center",
		"project",
		"finance_book",
		"selected_view",
		"report_template",
	];
	const LONG_SWITCH_LABEL = 180; // the right-hand column (240px) less its switch

	// reports whose switches under the filters go in so many columns (fewer only where their labels would not fit
	// whole): the General Ledger's eleven in four, as the auto_trust site (user, 2026-11-06)
	const CHECK_COLUMNS = { "General Ledger": 4 };

	// a report's filter labels shortened here (the report's own wording too long to sit in its columns), and the
	// words a Select's options repeat from their filter's label dropped ("Categorize by" · "Voucher (Consolidated)")
	const REPORT_LABELS = {
		"General Ledger": {
			ignore_err: "Ignore Exchange Gain / Loss Journals",
			ignore_cr_dr_notes: "Ignore System Credit / Debit Notes",
			show_amount_in_company_currency: "Credit / Debit in Company Currency",
		},
	};
	const OPTION_PREFIXES = { "General Ledger": { categorize_by: "Categorize by " } };

	function relabel_filters(report) {
		const filters = report.report_settings?.filters;
		if (!Array.isArray(filters) || report.report_settings._oto_relabelled) return;
		report.report_settings._oto_relabelled = true;
		const labels = REPORT_LABELS[report.report_name] || {};
		const prefixes = OPTION_PREFIXES[report.report_name] || {};
		for (const df of filters) {
			if (labels[df.fieldname]) df.label = __(labels[df.fieldname]);
			const prefix = prefixes[df.fieldname];
			if (prefix && Array.isArray(df.options)) {
				df.options = df.options.map((option) =>
					option && typeof option === "object" && String(option.label || "").startsWith(__(prefix.trim()))
						? { ...option, label: String(option.label).slice(__(prefix.trim()).length).trim() }
						: option
				);
			}
		}
	}

	// ---- the filters: fields on the left, the switches in a column on the right --------------------------------
	function split_filters(report, $form) {
		const $checks = $form.children('.frappe-control[data-fieldtype="Check"], .check-filter-area');
		if (!$checks.length) {
			$form.removeClass("oto-filter-split");
			return;
		}
		const $fields = $('<div class="oto-filter-fields"></div>').append($form.children().not($checks));
		const $right = $('<div class="oto-filter-checks"></div>').append($checks);
		$form.addClass("oto-filter-split").append($fields, $right);
	}

	const setup_filters = QueryReport.prototype.setup_filters;
	QueryReport.prototype.setup_filters = function () {
		// Frappe opens collapsed filters with this.check_filter_area.css(...), which throws for a report without a
		// separate check box area: an empty one stands in, dropped before the next set up
		if (this._oto_check_area_placeholder) {
			this.check_filter_area = undefined;
			this._oto_check_area_placeholder = false;
		}
		if (has_filter_form(this)) relabel_filters(this);
		const result = setup_filters.apply(this, arguments);
		const $form = this.page.page_form;
		const financial = has_filter_form(this);
		document.body.classList.toggle("oto-fin-page", financial);
		$form.toggleClass("oto-fin-filters", financial);
		if (!financial) {
			$form.removeClass("oto-filter-split oto-fin-checks-below");
			return result;
		}
		if (!this.check_filter_area) {
			this.check_filter_area = $();
			this._oto_check_area_placeholder = true;
		}
		// a report whose filters Frappe opens collapsed (collapsible_filters: the General Ledger's, all but its first
		// row hidden): opened at once, every filter and switch shown, and no chevron to fold them, as the auto_trust
		// site; the filter it sat in (Voucher No) laid out as the others again
		if (this.report_settings?.collapsible_filters && this.$collapse_button) {
			if (this.filters_hidden === false) this.toggle_filter_visiblity();
			const $holder = this.$collapse_button.parent();
			this.$collapse_button.remove();
			this.$collapse_button = $();
			$holder.css({ display: "", "align-items": "", gap: "" });
		}
		split_filters(this, $form);
		arrange_filters(this, $form);
		// many switches (the Trial Balance's seven): a row of their own under the filters
		const $checks = $form.find(".oto-filter-checks > .frappe-control").not(".hide-control, .hidden");
		const long = $checks.get().some((el) => (el.querySelector(".label-area")?.scrollWidth || 0) > LONG_SWITCH_LABEL);
		const few = $checks.length <= 4;
		const columns = CHECK_COLUMNS[this.report_name];
		const below = $checks.length > 4 || long || !!columns;
		$form.toggleClass("oto-fin-checks-below", below);
		if (below)
			rows_of_switches($form.children(".oto-filter-checks").get(0), columns ? Math.ceil($checks.length / columns) : few ? 1 : 2, !!columns);
		// (the switches' column leaving the filters a single column: under them)
		else
			requestAnimationFrame(() => {
				const fields = $form.children(".oto-filter-fields").get(0);
				if (!fields || window.innerWidth < 992) return;
				if (getComputedStyle(fields).gridTemplateColumns.split(" ").length > 1) return;
				$form.addClass("oto-fin-checks-below");
				rows_of_switches($form.children(".oto-filter-checks").get(0), 1);
			});
		return result;
	};

	// the switches under the filters in rows, filled column by column, each column at least as wide as its longest
	// label and the columns spread over the width (labels never cut)
	const SWITCH_GAP = 20;
	// by_width: the switches ordered longest label first, so the long ones share a column and more columns fit (a
	// report with its own column count, CHECK_COLUMNS)
	function rows_of_switches(box, fewest = 2, by_width = false) {
		if (!box) return;
		const arrange = () => {
			let items = [...box.children].filter((el) => el.offsetParent && el.matches(".frappe-control"));
			if (!items.length) return;
			box.style.gridTemplateRows = "";
			box.style.gridAutoFlow = "";
			let widths = items.map((el) => {
				const before = el.style.width;
				el.style.width = "max-content";
				const width = Math.ceil(el.getBoundingClientRect().width) + 4;
				el.style.width = before;
				return width;
			});
			if (by_width) {
				const order = items.map((el, i) => [el, widths[i]]).sort((a, b) => b[1] - a[1]);
				order.forEach(([el]) => box.appendChild(el));
				items = order.map(([el]) => el);
				widths = order.map(([, width]) => width);
			}
			const form = box.parentElement;
			const pad = parseFloat(getComputedStyle(form).paddingLeft) + parseFloat(getComputedStyle(form).paddingRight);
			const inner = parseFloat(getComputedStyle(box).paddingLeft) + parseFloat(getComputedStyle(box).paddingRight);
			const room = form.clientWidth - pad - inner;
			for (let rows = Math.min(fewest, items.length); rows <= items.length; rows++) {
				const cols = Math.ceil(items.length / rows);
				let total = SWITCH_GAP * (cols - 1);
				for (let c = 0; c < cols; c++) total += Math.max(...widths.slice(c * rows, c * rows + rows));
				if (total <= room || rows === items.length) {
					box.style.gridTemplateRows = `repeat(${rows}, auto)`;
					box.style.gridAutoFlow = "column";
					box.style.gridTemplateColumns = `repeat(${cols}, minmax(max-content, 1fr))`;
					box.style.gridAutoColumns = "";
					return;
				}
			}
		};
		requestAnimationFrame(arrange);
		if (!box._oto_rows_observer) {
			box._oto_rows_observer = new ResizeObserver(frappe.utils.debounce(arrange, 100));
			box._oto_rows_observer.observe(box.parentElement);
		}
	}

	function arrange_filters(report, $form) {
		const $box = $form.children(".oto-filter-fields").length ? $form.children(".oto-filter-fields") : $form;
		const rank = (el) => {
			const i = ORDER.indexOf(el.dataset.fieldname);
			return i < 0 ? ORDER.length : i;
		};
		$box
			.children(".frappe-control")
			.get()
			.map((el, i) => [el, i])
			.sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1])
			.forEach(([el]) => $box.append(el));

		// label | input: the label element Frappe leaves out of a report's filters (only_input)
		for (const filter of report.filters || []) {
			const $wrapper = filter.$wrapper;
			if (!$wrapper?.length || filter.df.fieldtype === "Check" || $wrapper.children(".oto-fin-label").length) continue;
			$wrapper.children().wrapAll('<div class="oto-fin-input"></div>');
			$wrapper.addClass("oto-fin-field").prepend(`<label class="oto-fin-label">${__(filter.df.label, null, filter.df.parent)}</label>`);
		}
		fit_labels($box);
	}

	// the labels' column as wide as the longest label shown (never cut nor wrapped)
	function fit_labels($box) {
		requestAnimationFrame(() => {
			const widths = $box
				.find(".oto-fin-label")
				.filter(":visible")
				.get()
				.map((el) => el.scrollWidth);
			if (widths.length) $box.css("--oto-fin-label", `${Math.ceil(Math.max(...widths)) + 2}px`);
		});
	}

	// the tree's controls (Frappe puts them in the footer, under the table): into a cell among the filters
	const show_footer_message = QueryReport.prototype.show_footer_message;
	QueryReport.prototype.show_footer_message = function () {
		const result = show_footer_message.apply(this, arguments);
		if (!has_filter_form(this)) return result;
		const $box = this.page.page_form.children(".oto-filter-fields");
		$box.children(".oto-fin-tree").remove();
		if (this.$tree_footer?.length && $box.length) {
			if (this.report_settings.initial_depth === 0) this.$tree_footer.find("#tree-level").val(1);
			const $cell = $(`<div class="frappe-control oto-fin-field oto-fin-tree"><label class="oto-fin-label">${__("Level")}</label></div>`);
			$cell.append(this.$tree_footer.removeClass("col-md-12"));
			$box.append($cell);
			fit_labels($box);
		}
		return result;
	};

	// ---- the table ----------------------------------------------------------------------------------------------
	const render_datatable = QueryReport.prototype.render_datatable;
	QueryReport.prototype.render_datatable = function () {
		if (!is_financial(this)) {
			if (!has_filter_form(this)) {
				this.$report?.get(0)?.classList.remove("oto-fin-report");
				return render_datatable.apply(this, arguments);
			}
			// (Custom Financial Statement: its columns as wide as their content, the rows as tall as the screen)
			fit_to_content(this);
			fit_height(this);
			const out = render_datatable.apply(this, arguments);
			keep_widths(this);
			requestAnimationFrame(() => widen_cut(this));
			watch_height(this);
			return out;
		}
		prepare_statement(this);
		const result = render_datatable.apply(this, arguments);
		keep_widths(this);
		watch_height(this);
		return result;
	};

	// imogi_finance's report_fit_width.js (loaded after this app) stretches every query report's columns to the
	// page's edge after each draw, over these widths (the room kept on the right, the amounts' AMOUNT_MAX). It leaves
	// a table alone whose columns' base widths (_imf_base, set only when missing) come to nothing: so, here, 0
	function keep_widths(report) {
		for (const column of report.datatable?.datamanager?.getColumns?.() || []) column._imf_base = 0;
	}

	// the rows the datatable shows, without the report's own total row (the datatable draws it in its footer)
	function rows_shown(report) {
		const data = report.data || [];
		return report.raw_data?.add_total_row && !report.report_settings?.tree ? data.slice(0, -1) : data;
	}

	// measured again once the page has laid out, and whenever what is above it changes height
	function refit(report) {
		if (!report.datatable || !has_filter_form(report)) return;
		let changed = fit_height(report);
		const box = report.$report?.get(0);
		const scroller = box?.closest(".main-section");
		const over = scroller ? scroller.scrollHeight - scroller.clientHeight : 0;
		if (over > 0) {
			const now = parseFloat(box.style.getPropertyValue("--oto-fin-rows")) || 0;
			box.style.setProperty("--oto-fin-rows", `${Math.max(200, Math.floor(now - over - 1))}px`);
			changed = true;
		}
		if (changed) {
			report.datatable.refresh(rows_shown(report), report.columns.filter((c) => !c.hidden));
			keep_widths(report);
		}
	}

	function watch_height(report) {
		requestAnimationFrame(() => requestAnimationFrame(() => refit(report)));
		if (report._oto_height_observer) return;
		const later = frappe.utils.debounce(() => refit(report), 100);
		report._oto_height_observer = new ResizeObserver(later);
		[report.page.page_form, report.$summary, report.$chart, report.$message]
			.map(($el) => $el?.get?.(0))
			.filter(Boolean)
			.forEach((el) => report._oto_height_observer.observe(el));
	}

	// the page's width shared out: each amount column as wide as the longest amount it shows (up to AMOUNT_MAX),
	// the Account column the rest (at least ACCOUNT_MIN); more than fit: the table scrolls
	const ACCOUNT_MIN = 240;
	const AMOUNT_MAX = 220;
	const CELL_PADDING = 24;
	const RIGHT_ROOM = 72; // the rows' scrollbar, borders and a margin
	const INDENT = 20;
	const TOGGLE = 34;

	let canvas = null;
	function amount_width(report, columns) {
		canvas ||= document.createElement("canvas").getContext("2d");
		canvas.font = `600 13px ${getComputedStyle(document.body).fontFamily}`;
		let widest = canvas.measureText("000.000.000").width;
		for (const row of report.data || []) {
			for (const column of columns) {
				const number = flt(row[column.fieldname]);
				if (!number) continue;
				const text = number < 0 ? `(${whole.format(Math.abs(number))})` : whole.format(number);
				widest = Math.max(widest, canvas.measureText(text).width);
			}
		}
		return Math.ceil(widest) + CELL_PADDING;
	}

	function account_width(report, column) {
		canvas ||= document.createElement("canvas").getContext("2d");
		canvas.font = `600 13px ${getComputedStyle(document.body).fontFamily}`;
		let widest = 0;
		for (const row of report.data || []) {
			const name = String(row.account_name || row.section_name || row[column.fieldname] || "").replace(/^'|'$/g, "");
			widest = Math.max(widest, canvas.measureText(name).width + cint(row.indent) * INDENT);
		}
		return Math.ceil(widest) + TOGGLE + CELL_PADDING;
	}

	function fit_columns(report) {
		const columns = (report.columns || []).filter((c) => !c.hidden);
		const [account, ...rest] = columns;
		if (!account) return;
		const box = report.$report?.get(0)?.clientWidth || report.page.main.width();
		const room = box - RIGHT_ROOM;
		const amounts = rest.length;
		const need = amounts ? amount_width(report, rest) : 0;
		const account_need = Math.max(ACCOUNT_MIN, account_width(report, account));
		const spare = room - account_need - need * amounts;
		const each = amounts
			? Math.max(need, Math.min(AMOUNT_MAX, need + Math.floor(Math.max(0, spare) / amounts), Math.floor((room * 0.45) / amounts)))
			: 0;
		rest.forEach((c) => (c.width = each));
		account.width = Math.max(account_need, room - each * amounts);
	}

	// a report with the filter form only (not a statement): each column as wide as its longest content, header
	// included (measured on a canvas, the table's own 14px type, the first SAMPLE rows); narrower than the page,
	// the room left shared out in proportion; wider, the table scrolls sideways (ported from the auto_trust site)
	const SAMPLE = 800;
	const CONTENT_MAX = 1100; // a longer text stays cut, its whole on hover
	const HEADER_EXTRA = 16; // the header's padding (its menu button shows on hover, over the text)
	const ROW_NUMBER = 44; // the row numbers' column the datatable adds
	function fit_to_content(report) {
		const columns = (report.columns || []).filter((c) => !c.hidden);
		if (!columns.length) return;
		canvas ||= document.createElement("canvas").getContext("2d");
		const family = getComputedStyle(document.body).fontFamily;
		const rows = (report.data || []).slice(0, SAMPLE);
		const plain = (html) => {
			if (html === null || html === undefined) return "";
			const text = String(html);
			return text.includes("<") ? $("<div>").html(text).text() : text;
		};
		for (const column of columns) {
			canvas.font = `600 14px ${family}`;
			let widest = canvas.measureText(__(column.label || "")).width + HEADER_EXTRA;
			canvas.font = `420 14px ${family}`;
			for (const row of rows) {
				const value = row[column.fieldname];
				if (value === null || value === undefined || value === "") continue;
				let text;
				try {
					text = plain(frappe.format(value, column, { only_value: true }, row));
				} catch (e) {
					text = String(value);
				}
				const digits = (text.match(/[0-9]/g) || []).length;
				widest = Math.max(
					widest,
					canvas.measureText(text.trim()).width + digits * 0.6 + cint(row.indent) * INDENT + (row.indent !== undefined && column === columns[0] ? TOGGLE : 0)
				);
			}
			column.width = Math.min(CONTENT_MAX, Math.ceil(widest) + CELL_PADDING);
		}
		const box = report.$report?.get(0)?.clientWidth || report.page.main.width();
		const room = box - RIGHT_ROOM - ROW_NUMBER;
		const used = columns.reduce((sum, c) => sum + c.width, 0);
		if (used < room) {
			const extra = room - used;
			let given = 0;
			columns.forEach((c, i) => {
				const share = i === columns.length - 1 ? extra - given : Math.floor((extra * c.width) / used);
				c.width += share;
				given += share;
			});
		}
	}

	// a cell cut all the same (past CONTENT_MAX): its whole text on hover
	$(document).on("mouseover", "body.oto-fin-page #page-query-report .dt-cell__content", function () {
		if (this.scrollWidth > this.clientWidth + 1 && !this.title) this.title = this.innerText.trim();
	});

	// after drawing: any cell still cut (measured as drawn) widens its column, drawn again once
	function widen_cut(report) {
		const datatable = report.datatable;
		if (!datatable || report._oto_widened === report.data) return;
		report._oto_widened = report.data;
		const columns = (report.columns || []).filter((c) => !c.hidden);
		const offset = datatable.options.serialNoColumn === false ? 0 : 1;
		let changed = false;
		columns.forEach((column, i) => {
			const cells = datatable.wrapper.querySelectorAll(`.dt-cell__content--col-${i + offset}, .dt-cell__content--header-${i + offset}`);
			let short = 0;
			for (const cell of cells) short = Math.max(short, cell.scrollWidth - cell.clientWidth);
			if (short > 1 && column.width < CONTENT_MAX) {
				column.width = Math.min(CONTENT_MAX, column.width + short + 4);
				changed = true;
			}
		});
		if (changed) {
			datatable.refresh(rows_shown(report), columns);
			keep_widths(report);
		}
	}

	// the rows' box as tall as the screen left under it (its header, the filters, the cards above stay)
	const BOTTOM_ROOM = 20;
	const HEADER = 36;
	function fit_height(report) {
		const box = report.$report?.get(0);
		if (!box) return false;
		if (!box.offsetParent) report.$report.show();
		const scroller = box.closest(".main-section");
		const top = box.getBoundingClientRect().top + (scroller?.scrollTop || 0) + HEADER;
		const height = `${Math.max(240, Math.floor(window.innerHeight - top - BOTTOM_ROOM))}px`;
		box.classList.add("oto-fin-report");
		if (box.style.getPropertyValue("--oto-fin-rows") === height) return false;
		box.style.setProperty("--oto-fin-rows", height);
		return true;
	}
	$(window).on(
		"resize",
		frappe.utils.debounce(() => {
			const report = frappe.query_report;
			if (report && frappe.get_route()?.[0] === "query-report" && has_filter_form(report)) {
				fit_height(report);
				if (is_financial(report)) fit_columns(report);
				else fit_to_content(report);
				report.datatable?.refresh(report.data, report.columns.filter((c) => !c.hidden));
				keep_widths(report);
			}
		}, 200)
	);

	function prepare_statement(report) {
		const settings = report.report_settings;
		fit_columns(report);
		fit_height(report);
		// opened collapsed: the top groups only, Expand All / Set Level open them
		if (report.tree_report) settings.initial_depth = 0;
		if (!settings._oto_financial) {
			settings._oto_financial = true;
			const options = settings.get_datatable_options;
			settings.get_datatable_options = function (opts) {
				opts = options ? options.call(this, opts) : opts;
				return { ...opts, inlineFilters: false, serialNoColumn: false };
			};
			const formatter = settings.formatter;
			settings.formatter = function (value, row, column, data, default_formatter, filter) {
				return format_cell(formatter, this, [value, row, column, data, default_formatter, filter]);
			};
		}
		// the amount columns say their currency once: "2026 (Rp)"
		const symbol = currency_symbol(report);
		for (const column of report.columns || []) {
			if (column.fieldtype !== "Currency" || column.hidden) continue;
			column._oto_label ??= column.label;
			column.label = `${column._oto_label} (${symbol})`;
		}
	}

	const symbol_of = (currency) =>
		(window.get_currency_symbol && currency && get_currency_symbol(currency)) || (!currency || currency === "IDR" ? "Rp" : currency);

	function currency_symbol(report) {
		return symbol_of(
			report.get_filter_value("presentation_currency", false) ||
				window.erpnext?.get_currency?.(report.get_filter_value("company", false)) ||
				frappe.defaults.get_default("currency")
		);
	}

	const whole = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 });

	// a group (an account with accounts under it, a section) or a total: bold, as ERPNext marks them
	const is_strong = (data) => data && ((!data.parent_account && !data.parent_section) || data.is_group_account || data.is_group);
	const is_total = (data) => data && !data.account && /^'?total/i.test(String(data.account_name || data.section_name || ""));

	function format_cell(formatter, ctx, args) {
		const [value, , column, data] = args;
		const blank = window.erpnext?.financial_statements?.is_blank_row?.(data);
		if (column.fieldtype === "Currency" && data && !blank && !is_special_view()) {
			const amount = data[column.fieldname];
			if (amount === undefined || amount === null || amount === "") return "";
			const number = flt(amount);
			const text = number < 0 ? `(${whole.format(Math.abs(number))})` : whole.format(number);
			const classes = ["oto-fin-num", number < 0 ? "oto-fin-neg" : "", is_strong(data) ? "oto-fin-strong" : "", is_total(data) ? "oto-fin-total" : ""];
			return `<div class="${classes.filter(Boolean).join(" ")}">${text}</div>`;
		}
		let html = formatter ? formatter.apply(ctx, args) : args[4] ? args[4](value, args[1], column, data) : value;
		if (is_total(data) && html) html = `<span class="oto-fin-total">${html}</span>`;
		return html;
	}

	// Growth / Margin views show percentages in the amount columns: left as ERPNext formats them
	const is_special_view = () => ["Growth", "Margin"].includes(frappe.query_report?.get_filter_value?.("selected_view", false));

	// the cards above the table in whole rupiah
	const render_summary = QueryReport.prototype.render_summary;
	QueryReport.prototype.render_summary = function (data) {
		if (is_financial(this) && Array.isArray(data)) {
			data = data.map((card) => {
				if (card.datatype !== "Currency") return card;
				const number = flt(card.value);
				const text = `${symbol_of(card.currency)} ${number < 0 ? "−" : ""}${whole.format(Math.abs(number))}`;
				return { ...card, datatype: "Data", value: text };
			});
		}
		return render_summary.call(this, data);
	};

	// ---- the chart: hidden until asked for, a Show Chart / Hide Chart button; the choice kept per report --------
	const chart_key = (report) => `otobitz:show_chart:${report}`;
	const chart_shown = (report) => {
		try {
			return localStorage.getItem(chart_key(report)) === "1";
		} catch (e) {
			return false;
		}
	};
	const set_chart_shown = (report, shown) => {
		try {
			localStorage.setItem(chart_key(report), shown ? "1" : "0");
		} catch (e) {
			// private window / blocked storage: the choice lasts until the page is left
		}
	};

	function apply_chart(report) {
		report._oto_chart_button?.remove();
		if (!has_filter_form(report) || !report.chart_options) return;
		const shown = report._oto_chart_shown ?? chart_shown(report.report_name);
		report.$chart.toggle(shown);
		report._oto_chart_button = report.page.add_inner_button(shown ? __("Hide Chart") : __("Show Chart"), () => {
			report._oto_chart_shown = !shown;
			set_chart_shown(report.report_name, !shown);
			// drawn while hidden it has no width: draw it again once shown
			if (!shown) render_chart.call(report, report.chart_options);
			apply_chart(report);
		});
	}

	const render_chart = QueryReport.prototype.render_chart;
	QueryReport.prototype.render_chart = function (options) {
		render_chart.call(this, options);
		apply_chart(this);
	};

	const toggle_report = QueryReport.prototype.toggle_report;
	QueryReport.prototype.toggle_report = function (flag) {
		toggle_report.call(this, flag);
		if (flag) apply_chart(this);
	};
})();
