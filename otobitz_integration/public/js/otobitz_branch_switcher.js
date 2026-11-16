// Copyright (c) 2026, Otoexpert and contributors
// For license information, please see license.txt

// A "Cabang: <kode>" dropdown in the real Desk navbar (not the
// OtoBitz-Integration-workspace-only horizontal nav otobitz_navbar.js
// builds) - visible app-wide so it's useful while browsing Sales Order
// lists, reports, dashboards, anywhere, not just this one workspace's own
// landing page. Lets the current user switch which of their own assigned
// Branches (the "Cabang yang Ditugaskan" User Permission rows managed from
// the User form) is their default - see
// otobitz_integration.user_branch_access.set_my_default_branch()'s
// docstring for exactly what "default" changes (pre-fills new documents'
// Branch field; does not retroactively filter already-open list views).
//
// Hidden entirely for a user with 0 or 1 assigned Branch - nothing to
// switch between.
//
// This Desk build's navbar is NOT the classic Bootstrap <ul class="navbar-
// right"><li>...</li></ul> structure frappe/public/js/frappe/ui/toolbar/
// toolbar.js's own add_icon_link() targets (confirmed dead/stale code path
// for this UI - that class doesn't exist anywhere in the rendered DOM
// here). The actual structure, confirmed live via DevTools inspection:
//
//   <header class="desktop-navbar ...">
//     <div class="navbar-home">...</div>
//     <div class="desktop-search-wrapper ...">...</div>
//     <div class="flex" style="gap:16px;...">          <- no class/id of its own
//       <button class="... desktop-cloud-settings ...">...</button>
//       <div class="desktop-notifications">             <- stable anchor
//         <div class="dropdown dropdown-notifications">...</div>
//       </div>
//       <div class="desktop-avatar">...</div>
//     </div>
//   </header>
//
// ".desktop-notifications" is the one stable, specific class in that run of
// icons - anchoring to it (insert immediately before it, inside its own
// flex parent) is what actually lands this between the search bar and the
// bell, instead of relying on a class that was never there.
//
// Also confirmed live: this Desk build re-renders <header>'s contents on
// every SPA route change (frappe.router "change"), same as
// otobitz_navbar.js's own workspace-page nav has to defend against -
// anything manually inserted here gets wiped the instant the user clicks
// into any doctype, and only comes back on a full page reload unless this
// re-checks and re-inserts itself on every route change too.
(function () {
	if (!frappe.session || frappe.session.user === "Guest") return;

	let cached_branches = null;

	function ensure_present() {
		if (document.getElementById("otobitz-branch-switcher")) return;
		const anchor = document.querySelector(".desktop-notifications");
		if (!anchor || !anchor.parentElement) return;

		if (cached_branches) {
			if (cached_branches.length >= 2) render(cached_branches);
			return;
		}
		frappe.call({
			method: "otobitz_integration.otobitz_integration.user_branch_access.get_my_branches",
			callback(r) {
				cached_branches = r.message || [];
				if (cached_branches.length < 2) return; // nothing to switch between
				render(cached_branches);
			},
		});
	}

	function render(branches) {
		if (document.getElementById("otobitz-branch-switcher")) return;
		const anchor = document.querySelector(".desktop-notifications");
		if (!anchor || !anchor.parentElement) return;

		if (!document.getElementById("otobitz-branch-switcher-style")) {
			const style = document.createElement("style");
			style.id = "otobitz-branch-switcher-style";
			style.textContent = `
#otobitz-branch-switcher{position:relative;display:flex;align-items:center}
#otobitz-branch-switcher .branch-switcher-toggle{display:flex;align-items:center;gap:4px;cursor:pointer;white-space:nowrap;font-size:13px;padding:6px 8px;border-radius:6px}
#otobitz-branch-switcher .branch-switcher-toggle:hover{background:var(--control-bg)}
#otobitz-branch-switcher .branch-switcher-toggle svg{width:14px;height:14px}
#otobitz-branch-switcher .dropdown-menu{min-width:240px}
#otobitz-branch-switcher .dropdown-item.active-branch{font-weight:600;color:var(--text-on-light-blue, #1a73e8)}
`;
			document.head.appendChild(style);
		}

		const current = branches.find((b) => b.is_default) || branches[0];

		// Same class list the real notification-bell button right next to
		// this uses (btn-reset nav-link text-muted ...) so this blends
		// into the native navbar styling instead of looking foreign -
		// just one icon for the dropdown caret, not two, and the compact
		// branch code (e.g. "104") instead of the full Branch name, which
		// only fits comfortably inside the open dropdown's own list.
		const $el = $(`
			<div class="dropdown" id="otobitz-branch-switcher" title="${__("Cabang")}: ${frappe.utils.escape_html(current.branch)}">
				<button class="btn-reset nav-link text-muted branch-switcher-toggle dropdown-toggle" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">
					${frappe.utils.icon("branch", "xs")}
					<span>${frappe.utils.escape_html(current.code)}</span>
				</button>
				<div class="dropdown-menu dropdown-menu-right" role="menu">
					${branches
						.map(
							(b) => `
						<a class="dropdown-item ${b.name === current.name ? "active-branch" : ""}" href="#" data-up-name="${frappe.utils.escape_html(b.name)}">
							${frappe.utils.escape_html(b.branch)}
						</a>`
						)
						.join("")}
				</div>
			</div>`);

		anchor.parentElement.insertBefore($el.get(0), anchor);
		// Bootstrap's dropdown plugin only ever gets wired up once, at the
		// toolbar's own load time, for whatever ".dropdown-toggle"
		// elements already exist then - this one doesn't exist yet when
		// that runs, so it needs calling again for just this element.
		$el.find(".dropdown-toggle").dropdown();

		$el.find(".dropdown-item").on("click", function (e) {
			e.preventDefault();
			const up_name = $(this).data("up-name");
			if (up_name === current.name) return;
			frappe.call({
				method: "otobitz_integration.otobitz_integration.user_branch_access.set_my_default_branch",
				args: { user_permission_name: up_name },
				callback() {
					window.location.reload();
				},
			});
		});
	}

	let attempts = 0;
	const first_try = setInterval(() => {
		attempts++;
		const anchor = document.querySelector(".desktop-notifications");
		if (anchor || attempts > 40) {
			clearInterval(first_try);
			if (anchor) ensure_present();
		}
	}, 250);

	frappe.router.on("change", () => setTimeout(ensure_present, 300));
})();
