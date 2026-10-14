# Copyright (c) 2026, Otoexpert and contributors
# For license information, please see license.txt

"""Centralized HTTP client for the OtoBitzLite/OtoXpert integration API.

Every one of the 28 `/api/integration/*` endpoints must be called through
`call_api()` below. The upstream bearer token expires 300 seconds after it is
issued (confirmed against the live API), so a batch job that calls many
endpoints - or that runs longer than 5 minutes, e.g. paginating through 80k+
customer rows - will hit a stray 401 partway through if each call site manages
its own token. Centralizing token caching + a single transparent
refresh-and-retry here means every caller gets that behaviour for free.

Note: we build the request with `frappe.utils.get_request_session()` directly
rather than `frappe.integrations.utils.make_post_request()`. The latter calls
`frappe.log_error()` on *any* exception, including the first 401 we expect and
handle here on every token expiry - that would spam the Error Log hourly for
normal, already-handled behaviour.
"""

import time

import requests
import frappe
from frappe.utils import cint, get_request_session

TOKEN_CACHE_KEY = "otobitz_integration:token"
TOKEN_SAFETY_MARGIN_SECONDS = 30
MIN_TOKEN_CACHE_SECONDS = 30
# requests has no default timeout - without one, a stalled connection to the
# upstream API hangs the whole sync forever instead of raising (this is what
# actually happened: the Customer backfill sat frozen for 90+ minutes on one
# stuck request). otoxpertsoandpart specifically has been observed taking
# 70+ seconds to respond even when it's genuinely just slow, not down - a
# 60s read timeout was cutting off responses that were still on their way,
# misreporting "down" for what was really "slow". (connect_timeout, read_timeout).
REQUEST_TIMEOUT = (10, 180)
NETWORK_RETRIES = 3
NETWORK_RETRY_DELAY_SECONDS = 5


class OtoBitzAPIError(Exception):
	pass


def get_settings():
	settings = frappe.get_cached_doc("OtoBitz Settings")
	if not settings.enabled:
		frappe.throw(frappe._("OtoBitz Integration is not enabled. Enable it in OtoBitz Settings."))
	if not settings.base_url or not settings.username:
		frappe.throw(frappe._("OtoBitz Settings is missing Base URL or Username."))
	return settings


def get_token(force_refresh: bool = False) -> str:
	"""Return a cached bearer token, transparently fetching a new one when
	missing/expired or when `force_refresh` is set."""
	if not force_refresh:
		token = frappe.cache().get_value(TOKEN_CACHE_KEY)
		if token:
			return token

	settings = get_settings()
	session = get_request_session()
	response = session.post(
		f"{settings.get_base_url()}/api/token/gettoken",
		json={"username": settings.username, "password": settings.get_password("password")},
		timeout=REQUEST_TIMEOUT,
	)
	response.raise_for_status()
	payload = response.json()

	if payload.get("status_code") != 200 or not payload.get("token"):
		frappe.throw(frappe._("OtoBitz login failed: {0}").format(payload.get("message") or "unknown error"))

	token = payload["token"]
	expires_in = cint(payload.get("expired") or 300) - TOKEN_SAFETY_MARGIN_SECONDS
	frappe.cache().set_value(TOKEN_CACHE_KEY, token, expires_in_sec=max(expires_in, MIN_TOKEN_CACHE_SECONDS))
	return token


def call_api(endpoint: str, payload: dict | None = None) -> dict:
	"""POST to `/api/integration/{endpoint}` with a valid bearer token.

	On a 401 (token expired mid-batch, or invalidated early by the upstream
	server), the token is force-refreshed exactly once and the same request is
	retried exactly once. A second 401 is a real auth failure and is raised.

	On a network-level failure (timeout, connection reset - the upstream API
	has shown itself to be flaky, not just slow), retries a few times with a
	short delay before giving up. This is every caller's only network retry
	layer - individual sync functions (e.g. the Customer paginator) don't need
	their own.
	"""
	last_network_error: Exception | None = None
	for attempt in range(1, NETWORK_RETRIES + 1):
		try:
			return _call_api_once(endpoint, payload)
		except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
			last_network_error = exc
			if attempt < NETWORK_RETRIES:
				time.sleep(NETWORK_RETRY_DELAY_SECONDS)
	raise OtoBitzAPIError(f"Network error calling {endpoint} after {NETWORK_RETRIES} attempts") from last_network_error


def _call_api_once(endpoint: str, payload: dict | None) -> dict:
	settings = get_settings()
	base_url = settings.get_base_url()
	session = get_request_session()
	url = f"{base_url}/api/integration/{endpoint}"
	body = payload or {}

	token = get_token()
	response = session.post(url, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT)

	if response.status_code == 401:
		token = get_token(force_refresh=True)
		response = session.post(
			url, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT
		)

	try:
		response.raise_for_status()
	except requests.exceptions.HTTPError as exc:
		raise OtoBitzAPIError(f"HTTP {response.status_code} calling {endpoint}: {response.text[:500]}") from exc

	data = response.json()
	if data.get("error"):
		raise OtoBitzAPIError(data.get("message") or f"OtoBitz API returned an error calling {endpoint}")

	return data
