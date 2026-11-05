// Camera button on every desk page (forms, lists, reports, workspaces) that saves the whole screen as a PNG:
// the left sidebar included, and the page below the fold, instead of stitching manual screenshots. Ported from
// the auto_trust site's screenshot.js. html-to-image (vendor/html-to-image.js, MIT) is loaded before this file
// as a plain script and sets window.htmlToImage.
(() => {
	if (window.otobitz_screenshot) return;

	const BLANK_PIXEL = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";
	// the camera button, the "Getting Started" panel, date pickers, toasts, dialogs
	const NOT_CAPTURED = ".oto-screenshot-btn, .onb-panel, .datepicker, #alert-container, .modal, .modal-backdrop";

	async function capture() {
		if (!frappe.container?.page) return;
		if (!window.htmlToImage) {
			frappe.msgprint(__("Screenshot gagal dibuat: {0}", [__("library gambar belum termuat, coba muat ulang halaman")]));
			return;
		}

		frappe.show_alert({ message: __("Mengambil screenshot..."), indicator: "blue" }, 3);
		const target = document.body;
		const restore_layout = unroll_scroll_area();
		const restore_icons = inline_icons(target);
		document.body.classList.add("oto-capturing"); // hides scrollbars (desk.css)
		try {
			const png = await window.htmlToImage.toPng(target, {
				// screen width: with the scroll area unrolled, wide inner bits (a long tab bar) overflow
				width: target.clientWidth,
				height: target.scrollHeight,
				pixelRatio: Math.min(window.devicePixelRatio || 1, 2),
				backgroundColor: getComputedStyle(document.body).backgroundColor,
				cacheBust: true,
				imagePlaceholder: BLANK_PIXEL,
				filter: keep_node,
			});
			const link = document.createElement("a");
			link.download = `${file_name()}.png`;
			link.href = png;
			link.click();
		} catch (e) {
			console.error(e);
			// a failed image load rejects with a bare Event, which has no message of its own
			frappe.msgprint(__("Screenshot gagal dibuat: {0}", [e?.message || __("ada gambar di halaman yang gagal dimuat")]));
		} finally {
			document.body.classList.remove("oto-capturing");
			restore_icons();
			restore_layout();
		}
	}

	// The desk body is one screen tall and the page scrolls inside .main-section, so only the visible part would be
	// drawn. Stretch the body, the scroll area and the left sidebar to the page's full height; returns an undo.
	function unroll_scroll_area() {
		const main = document.querySelector(".main-section");
		if (!main) return () => {};
		const scroll = main.scrollTop;
		const height = `${Math.max(main.scrollHeight, document.body.clientHeight)}px`;
		const els = [document.body, main, ...document.querySelectorAll(".body-sidebar-container, .body-sidebar")];
		const saved = els.map((el) => el.style.cssText);
		for (const el of els) {
			// the sidebar animates its size (0.3s): without this it is still screen-tall when the capture reads it
			el.style.setProperty("transition", "none", "important");
			el.style.setProperty("height", height, "important");
			el.style.setProperty("max-height", "none", "important");
		}
		// hidden, not visible: the content fits now, and "visible" let wide bits stretch the layout
		main.style.setProperty("overflow", "hidden", "important");
		void main.offsetHeight; // apply the new sizes now
		return () => {
			els.forEach((el, i) => (el.style.cssText = saved[i]));
			main.scrollTop = scroll;
		};
	}

	// Frappe icons are <svg><use href="#icon-x"> pointing at a sprite outside the captured element, so they would
	// draw blank. Copy each symbol's shapes in for the capture; returns an undo.
	function inline_icons(root) {
		const undo = [];
		for (const use of root.querySelectorAll("svg use")) {
			const id = (use.getAttribute("href") || use.getAttribute("xlink:href") || "").replace(/^#/, "");
			const symbol = id && document.getElementById(id);
			const svg = use.closest("svg");
			if (!symbol || !svg) continue;
			if (!svg.getAttribute("viewBox") && symbol.getAttribute("viewBox")) {
				svg.setAttribute("viewBox", symbol.getAttribute("viewBox"));
				undo.push(() => svg.removeAttribute("viewBox"));
			}
			const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
			group.innerHTML = symbol.innerHTML;
			use.replaceWith(group);
			undo.push(() => group.replaceWith(use));
		}
		return () => undo.reverse().forEach((fn) => fn());
	}

	function keep_node(node) {
		if (node.nodeType !== Node.ELEMENT_NODE) return true;
		if (node.matches(NOT_CAPTURED)) return false;
		// an <img> that never loaded (an empty src resolves to the page itself) aborts the whole capture
		if (node.tagName === "IMG" && (!node.getAttribute("src") || !node.complete || !node.naturalWidth)) return false;
		// a report row outside its table's scroll box is not in the picture: a long General Ledger drawn whole
		// (every row, every cell's style copied) crashed the tab
		if (node.classList.contains("dt-row") && !node.classList.contains("dt-row-header")) {
			const box = node.closest(".dt-scrollable");
			if (box) {
				const row = node.getBoundingClientRect();
				const view = box.getBoundingClientRect();
				if (row.bottom < view.top || row.top > view.bottom) return false;
			}
		}
		// subtrees not drawn (other tabs, hidden fields): nothing to draw, and cloning them is slow
		return node.getClientRects().length > 0 || getComputedStyle(node).display === "contents";
	}

	function file_name() {
		const title = (document.title || "screenshot").replace(/[\\/:*?"<>|]+/g, "-").trim();
		return `${title} ${frappe.datetime.now_datetime().replace(/:/g, "-")}`;
	}

	function add_button() {
		const page = frappe.container?.page?.page;
		if (!page || page._otobitz_screenshot || !page.add_action_icon) return;
		page._otobitz_screenshot = true;
		page.add_action_icon("es-line-camera", () => capture(), "oto-screenshot-btn", __("Screenshot"));
	}

	window.otobitz_screenshot = { capture };
	$(document).on("app_ready", () => {
		add_button();
		// pages are built lazily: give the new one a moment before adding the button
		frappe.router.on("change", () => setTimeout(add_button, 300));
	});
})();
