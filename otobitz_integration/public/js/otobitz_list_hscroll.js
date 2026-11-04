// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

// Desk-wide: Shift+wheel anywhere over a List View's rows scrolls the list
// horizontally. The horizontal scrollbar belongs to .result-container
// (frappe/public/scss/desk/list.scss), whose own height is the full row
// count, not the viewport - the scrollbar itself only becomes reachable
// after scrolling all the way down past every row, with no way to reach it
// (or pan sideways) from anywhere else on the page. Shift+wheel is the
// browser/spreadsheet-standard horizontal-scroll convention (Excel, Google
// Sheets, GitHub's own wide tables), so this doesn't introduce a new
// gesture, just wires it up where Frappe's own list view never did.
(function () {
	document.addEventListener(
		"wheel",
		function (e) {
			if (!e.shiftKey) return;
			var container = e.target.closest(".result-container");
			if (!container) return;
			// Shift+wheel already reports its delta on deltaX in some
			// browsers/input devices (trackpads) and on deltaY in others
			// (a plain mouse wheel) - whichever carries the larger
			// magnitude is the one the user actually scrolled.
			var delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
			container.scrollLeft += delta;
			e.preventDefault();
		},
		{ passive: false }
	);
})();
