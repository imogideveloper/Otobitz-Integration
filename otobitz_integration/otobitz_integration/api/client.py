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
# "Too Many Requests" comes back as a 200 with data["error"] truthy, not an
# HTTP 429 - confirmed live against masterdata_orderparts - so it's a
# business-level OtoBitzAPIError, not a requests.exceptions network error,
# and needs its own retry path (previously: zero retries, straight to
# "give up" - the actual cause of most datacustomerbynumber lookups in
# sync_service_orders.py silently failing and leaving Customer names
# scrambled forever, since that lookup only ever runs once per customer).
RATE_LIMIT_RETRIES = 6
RATE_LIMIT_RETRY_DELAY_SECONDS = 20


class OtoBitzAPIError(Exception):
	def __init__(self, message, retry_after=None, status_code=None):
		super().__init__(message)
		# OtoBitz's "Too Many Requests" body includes its own
		# retry_after (seconds) - confirmed live: 56, not the
		# RATE_LIMIT_RETRY_DELAY_SECONDS guess below. Using a fixed 20s
		# delay regardless of what the server actually asked for was
		# exactly why 4 retries in a row still wasn't enough - every
		# retry fired back into the same still-active rate limit window.
		self.retry_after = retry_after
		# HTTP status, when this came from an actual HTTP error response
		# (not the "200 with data['error']" business-error shape rate
		# limiting uses) - lets call_api() retry transient gateway
		# failures (502/503/504 - confirmed live: even /api/token/gettoken
		# itself returned a 504 HTML page, not just the data endpoints)
		# without having to string-match arbitrary HTML error pages.
		self.status_code = status_code


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
	try:
		response.raise_for_status()
		payload = response.json()
	except (requests.exceptions.HTTPError, requests.exceptions.JSONDecodeError) as exc:
		# Unwrapped, this escapes call_api()'s per-chunk OtoBitzAPIError handling
		# entirely - a single flaky token request (confirmed: intermittent
		# 404/502 from the upstream token endpoint) was aborting a whole
		# sync_service_orders() run instead of just costing it one retry.
		raise OtoBitzAPIError(
			f"HTTP {response.status_code} fetching OtoBitz token: {response.text[:500]}",
			status_code=response.status_code,
		) from exc

	if payload.get("status_code") != 200 or not payload.get("token"):
		frappe.throw(frappe._("OtoBitz login failed: {0}").format(payload.get("message") or "unknown error"))

	token = payload["token"]
	expires_in = cint(payload.get("expired") or 300) - TOKEN_SAFETY_MARGIN_SECONDS
	frappe.cache().set_value(TOKEN_CACHE_KEY, token, expires_in_sec=max(expires_in, MIN_TOKEN_CACHE_SECONDS))
	return token


def _is_rate_limited(message: str) -> bool:
	return "too many request" in (message or "").lower()


# Classic transient gateway failures - confirmed live that even
# /api/token/gettoken itself can 504 (the whole upstream being briefly
# unreachable, not specific to any one endpoint/payload). 500 is
# deliberately excluded: that's as likely to be a genuine application bug
# on OtoBitz's side as a transient blip, and retrying it blindly risks
# masking a real error instead of a real recovery.
RETRYABLE_STATUS_CODES = {502, 503, 504}


def _is_retryable_server_error(exc: Exception) -> bool:
	return getattr(exc, "status_code", None) in RETRYABLE_STATUS_CODES


def call_api(endpoint: str, payload: dict | None = None) -> dict:
	"""POST to `/api/integration/{endpoint}` with a valid bearer token.

	On a 401 (token expired mid-batch, or invalidated early by the upstream
	server), the token is force-refreshed exactly once and the same request is
	retried exactly once. A second 401 is a real auth failure and is raised.

	On a network-level failure (timeout, connection reset - the upstream API
	has shown itself to be flaky, not just slow), retries a few times with a
	short delay before giving up. On a "Too Many Requests" response (a 200
	with data["error"] set, not an HTTP 429) or a transient gateway failure
	(502/503/504 - confirmed live: even /api/token/gettoken itself can 504,
	not just the data endpoints), retries with a longer delay instead - this
	is every caller's only retry layer for all three cases, individual sync
	functions (e.g. the Customer paginator, _resolve_customer_info()) don't
	need their own. Any other OtoBitzAPIError (a genuine business error -
	bad params, real auth failure, a plain 500, ...) is not retryable and
	raises immediately.
	"""
	last_error: Exception | None = None
	network_attempt = 0
	rate_limit_attempt = 0
	while True:
		try:
			return _call_api_once(endpoint, payload)
		except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
			last_error = exc
			network_attempt += 1
			if network_attempt >= NETWORK_RETRIES:
				raise OtoBitzAPIError(f"Network error calling {endpoint} after {NETWORK_RETRIES} attempts") from last_error
			time.sleep(NETWORK_RETRY_DELAY_SECONDS)
		except OtoBitzAPIError as exc:
			if not (_is_rate_limited(str(exc)) or _is_retryable_server_error(exc)):
				raise
			last_error = exc
			rate_limit_attempt += 1
			if rate_limit_attempt >= RATE_LIMIT_RETRIES:
				raise
			delay = cint(getattr(exc, "retry_after", None)) or RATE_LIMIT_RETRY_DELAY_SECONDS
			time.sleep(delay)


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
		data = response.json()
	except requests.exceptions.HTTPError as exc:
		raise OtoBitzAPIError(
			f"HTTP {response.status_code} calling {endpoint}: {response.text[:500]}",
			status_code=response.status_code,
		) from exc
	except requests.exceptions.JSONDecodeError as exc:
		# A 200 with a non-JSON body (seen in practice - an upstream error
		# page) used to escape here uncaught, same failure mode as the
		# get_token() fix above: one bad response killed the whole sync run
		# instead of costing just this chunk a retry.
		raise OtoBitzAPIError(f"Non-JSON response calling {endpoint}: {response.text[:500]}") from exc

	if data.get("error"):
		raise OtoBitzAPIError(
			data.get("message") or f"OtoBitz API returned an error calling {endpoint}",
			retry_after=data.get("retry_after"),
		)

	return data
