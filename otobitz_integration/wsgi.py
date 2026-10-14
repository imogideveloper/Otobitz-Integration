# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""WSGI entrypoint for gunicorn.

`frappe.app:application` (the entrypoint bench's own official supervisor
template points gunicorn at) is the bare WSGI callable with no static-asset
serving - in a real production deployment, nginx serves `/assets/*` and
`/files/*` directly from disk and gunicorn only ever sees dynamic requests.
This bench has no nginx in front of gunicorn, so without this shim
`/assets/*` 404s (icons, CSS, JS - broke exactly that when `web:` in the
Procfile was switched from the dev-only `bench serve` to gunicorn).

`frappe.app.application_with_statics()` is the same `SharedDataMiddleware` +
`StaticDataMiddleware` wrapping `bench serve` applies for you - calling it
once here gives `frappe.app.application` (and this module's `application`,
which gunicorn binds to) the "serve /assets and /files from disk" behaviour
without needing nginx at all.
"""

import frappe.app

application = frappe.app.application_with_statics()
