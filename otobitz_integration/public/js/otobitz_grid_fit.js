// Items table of the Sales Invoice, Purchase Invoice and Purchase Order: columns as wide as their content, in
// proportion. The same fit as the Sales Order's Order Lines ("Sales Order Column Picker" client script). The two
// invoices shared the row out by fixed flex ratios (their "Full Width" client scripts), which cut the longer item
// names, descriptions and prices short with "...", and more of them once the table text went to the standard
// 13px. The Purchase Order's own fit ("Purchase Order Column Picker") now calls this one.
//
// Each column's natural width is its longest content: the header label or any row's value. It is measured
// from the text itself, because a cell's .static-area is as wide as the cell. With room to spare, the natural
// widths are scaled up together until the table fills the grid. Without, every column keeps its natural
// width, nothing is clipped, and the grid scrolls sideways. Widths are inline with !important, so they win
// over the scripts' flex rules.
(() => {
	if (window.otobitz_grid_fit) return;

	const DOCTYPES = ["Sales Invoice", "Purchase Invoice", "Purchase Order"];
	const CELL_PAD = 18; // 4px cell padding each side + a 10px buffer so text never touches the edge
	const MIN_WIDTH = 48;

	function text_width(area) {
		// from the left of its first piece of text to the right of its last: a number sits in a block-level
		// right-aligned div as wide as the cell, so the area's own box says nothing
		let left = Infinity;
		let right = -Infinity;
		const walker = document.createTreeWalker(area, NodeFilter.SHOW_TEXT);
		const range = document.createRange();
		for (let node = walker.nextNode(); node; node = walker.nextNode()) {
			if (!node.textContent.trim()) continue;
			range.selectNodeContents(node);
			for (const rect of range.getClientRects()) {
				if (!rect.width) continue;
				left = Math.min(left, rect.left);
				right = Math.max(right, rect.right);
			}
		}
		// a pill (Tax) carries its own padding; a mandatory column's red star is drawn by ::after, not text
		let extra = area.querySelector(".po-tax-pill, .indicator-pill") ? 16 : 0;
		for (const el of [area, ...area.querySelectorAll("*")]) {
			const after = getComputedStyle(el, "::after");
			if (after.content && !["none", "normal", '""'].includes(after.content)) {
				extra += Math.ceil(parseFloat(after.width) || 0) + Math.ceil(parseFloat(after.marginLeft) || 0) + 8;
			}
		}
		return right > left ? Math.ceil(right - left) + extra : 0;
	}

	function fit(grid) {
		const wrapper = grid.wrapper && grid.wrapper[0];
		const form_grid = wrapper && wrapper.querySelector(".form-grid");
		const head = wrapper && wrapper.querySelector(".grid-heading-row .data-row");
		if (!form_grid || !head || !form_grid.clientWidth) return;
		const cols = [...head.querySelectorAll(":scope > .grid-static-col[data-fieldname]")];
		if (!cols.length) return;
		const cells = (col) => wrapper.querySelectorAll(`.grid-static-col[data-fieldname="${col.dataset.fieldname}"]`);
		const natural = cols.map((col) => {
			let width = 0;
			for (const cell of cells(col)) {
				const area = cell.querySelector(".static-area");
				if (area) width = Math.max(width, text_width(area));
			}
			return Math.max(width + CELL_PAD, MIN_WIDTH);
		});
		// the chrome columns (checkbox, No., the edit pencil) keep their own width
		const fixed = [...head.children].filter((c) => !cols.includes(c)).reduce((sum, c) => sum + c.getBoundingClientRect().width, 0);
		const room = form_grid.clientWidth - fixed - 2;
		const total = natural.reduce((a, b) => a + b, 0);
		const scale = room > total ? room / total : 1;
		let given = 0;
		cols.forEach((col, i) => {
			// the last column takes the rounding remainder, so a filled table ends exactly at the grid's edge
			const width = scale > 1 && i === cols.length - 1 ? Math.floor(room) - given : Math.floor(natural[i] * scale);
			given += width;
			for (const cell of cells(col)) {
				for (const prop of ["width", "min-width", "max-width"]) cell.style.setProperty(prop, `${width}px`, "important");
				cell.style.setProperty("flex", `0 0 ${width}px`, "important");
			}
		});
		const row_width = `${Math.ceil(fixed + given + 2)}px`;
		for (const el of wrapper.querySelectorAll(".grid-heading-row, .grid-body")) el.style.setProperty("min-width", row_width, "important");
		form_grid.style.setProperty("overflow-x", "auto", "important");
	}

	function setup(frm) {
		const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
		if (!grid || !grid.wrapper) return;
		let pending = null;
		const soon = () => {
			clearTimeout(pending);
			pending = setTimeout(() => {
				try {
					fit(grid);
				} catch (e) {
					console.error(e); // a measure gone wrong leaves the old widths, not a broken form
				}
			}, 80);
		};
		if (!grid.__otobitz_fit) {
			grid.__otobitz_fit = true;
			// rows re-render (add row, edit a value) and the grid's room changes (window, sidebar)
			new MutationObserver(soon).observe(grid.wrapper[0], { childList: true, subtree: true });
			const form_grid = grid.wrapper[0].querySelector(".form-grid");
			if (form_grid && typeof ResizeObserver !== "undefined") new ResizeObserver(soon).observe(form_grid);
		}
		soon();
	}

	for (const doctype of DOCTYPES) {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				setup(frm);
				// the forms' own scripts rebuild the grid in steps after refresh
				[300, 900, 1600].forEach((ms) => setTimeout(() => setup(frm), ms));
			},
		});
	}
	window.otobitz_grid_fit = { fit };
})();
