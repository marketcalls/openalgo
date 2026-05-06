"""Webhook security primitives — signature verification, replay protection,
IP allowlist matching, and adaptive ban tracking.

Design constraint: TradingView CANNOT set custom HTTP headers. This means
HMAC-in-header signing is unavailable for TV signals. The compromise:

  - URL secret (UUID in path)         — always required
  - BODY_SECRET                       — TV can include in alert JSON body
  - HMAC_SHA256                       — Python / Amibroker / curl
  - BOTH                              — accept either method

Plus optional layers on top:
  - replay window (`ts` field in body)
  - IP allowlist (CIDR match)
  - adaptive ban (5 fails / 60s → 15min lockout)

All exposed functions live in utils/ (not services/) to avoid circular
imports — these primitives are used by the webhook route, the ingestion
service, and tests.

Plan ref: docs/plans/2026-05-06-strategy-v2-implementation-plan.md §8.4–§8.5.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import threading
import time
from collections import defaultdict, deque
from typing import Optional, Tuple

from utils.logging import get_logger

logger = get_logger(__name__)


# -----------------------------------------------------------------------------
# Constant-time signature checks
# -----------------------------------------------------------------------------


def verify_body_secret(body_json: dict, expected_secret: Optional[str]) -> bool:
    """True if body['webhook_secret'] matches expected_secret (constant-time).

    Used for the TradingView-compatible BODY_SECRET signing method. The
    secret travels inside the JSON body — TV alerts can paste a static
    value into the alert template.
    """
    if not expected_secret:
        return False
    received = ""
    if isinstance(body_json, dict):
        v = body_json.get("webhook_secret", "")
        if isinstance(v, str):
            received = v
    return hmac.compare_digest(received, expected_secret)


def verify_hmac(raw_body: bytes, header_value: Optional[str], key: Optional[str]) -> bool:
    """True if the X-OpenAlgo-Signature header is a valid HMAC-SHA256 over
    `raw_body` keyed by `key`. Format: 'hmac-sha256=<hex>'.

    `raw_body` MUST be the request body as bytes BEFORE JSON parsing —
    parsing changes whitespace/key-order and breaks the signature.
    """
    if not header_value or not key:
        return False
    if not header_value.startswith("hmac-sha256="):
        return False
    received_hex = header_value.split("=", 1)[1].strip()
    if not received_hex:
        return False
    expected_hex = hmac.new(key.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(received_hex, expected_hex)


# -----------------------------------------------------------------------------
# Replay-window check
# -----------------------------------------------------------------------------


def verify_replay(
    body_json: dict, window_seconds: int, *, now_func=time.time
) -> Tuple[bool, str]:
    """If window_seconds > 0, body must include a 'ts' field (Unix epoch
    seconds). Returns (ok, reason). Future timestamps are also rejected
    — clock-drift bidirectionally bounded by the window.
    """
    if window_seconds <= 0:
        return True, ""

    if not isinstance(body_json, dict):
        return False, "Body is not a JSON object"

    ts_raw = body_json.get("ts")
    if ts_raw is None:
        return False, "Replay protection enabled but 'ts' field missing"

    try:
        ts_value = float(ts_raw)
    except (TypeError, ValueError):
        return False, f"'ts' must be numeric epoch seconds, got {ts_raw!r}"

    drift = abs(now_func() - ts_value)
    if drift > window_seconds:
        return False, f"Timestamp out of window ({drift:.0f}s > {window_seconds}s)"

    return True, ""


# -----------------------------------------------------------------------------
# IP allowlist
# -----------------------------------------------------------------------------


def _client_ip_from_request(request) -> str:
    """Resolve the client IP gated on ``TRUST_PROXY_HEADERS`` so the
    webhook IP allowlist cannot be bypassed by an attacker that reaches
    gunicorn directly and sends a forged ``X-Forwarded-For`` header.

    Delegates to ``utils.ip_helper.get_real_ip`` which is the project's
    canonical client-IP resolver — same source of truth used by the
    login rate-limiter, the IP ban list, and the audit log. Without this
    gate, a self-hosted operator running OpenAlgo on an unprotected
    public port (no proxy in front) would lose the entire allowlist.
    """
    from utils.ip_helper import get_real_ip

    # get_real_ip needs Flask's request context; webhook_guard always
    # runs inside the webhook view, so this is satisfied. We pass via
    # the function-call import (not module-level) only to keep the unit
    # tests in test_webhook_guard.py independent of Flask app setup.
    try:
        return get_real_ip() or ""
    except Exception:
        # Defensive: never let a header-parsing edge case crash the
        # signing pipeline. Falling through to remote_addr is the same
        # safe-default the rest of the project uses.
        return request.remote_addr or ""


def parse_allowlist(stored: Optional[str]) -> list:
    """Decode the JSON-encoded list of CIDR strings on
    strategies_v2.webhook_ip_allowlist. Empty/None means 'no filter'."""
    if not stored:
        return []
    try:
        decoded = json.loads(stored)
    except (TypeError, ValueError):
        logger.warning("webhook_guard: malformed ip_allowlist JSON, ignoring")
        return []
    if not isinstance(decoded, list):
        return []
    return [str(c).strip() for c in decoded if c]


def ip_allowed(client_ip: str, allowlist_cidrs: list) -> bool:
    """True if `client_ip` is in any of the CIDR ranges. Empty allowlist
    means no IP filter is configured → always True.

    Supports IPv4 and IPv6 in mixed lists."""
    if not allowlist_cidrs:
        return True
    if not client_ip:
        return False

    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        logger.warning("webhook_guard: malformed client IP %r", client_ip)
        return False

    for cidr in allowlist_cidrs:
        try:
            net = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            logger.warning("webhook_guard: malformed CIDR in allowlist %r", cidr)
            continue
        if ip in net:
            return True
    return False


def request_ip_allowed(request, allowlist_stored: Optional[str]) -> bool:
    """Convenience: pull the client IP off the Flask request and check it
    against the strategy's stored allowlist."""
    return ip_allowed(_client_ip_from_request(request), parse_allowlist(allowlist_stored))


# -----------------------------------------------------------------------------
# Adaptive ban tracker
# -----------------------------------------------------------------------------


class AdaptiveBanTracker:
    """Per-webhook_id signature-failure rate limiter with adaptive ban.

    Behaviour: if `failure_threshold` failures occur within `window_seconds`,
    subsequent requests for that webhook_id are rejected for `ban_seconds`.
    A successful verification clears the failure counter (but NOT an active
    ban — bans run their full duration to slow down brute-force attempts).

    State is in-memory only. Single-user platform + single-worker eventlet
    means this is sufficient. A restart loses the counter — that's fine,
    since all secrets and HMAC keys must still match for any successful
    request.

    Defaults match plan §8.5 SC7: 5 fails / 60s → 15min ban.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        window_seconds: int = 60,
        ban_seconds: int = 15 * 60,
        *,
        now_func=time.monotonic,
    ):
        self.failure_threshold = int(failure_threshold)
        self.window_seconds = int(window_seconds)
        self.ban_seconds = int(ban_seconds)
        self._now = now_func
        self._failures: dict[str, deque] = defaultdict(deque)
        self._bans: dict[str, float] = {}
        self._lock = threading.Lock()

    def _trim(self, failures: deque, now: float) -> None:
        cutoff = now - self.window_seconds
        while failures and failures[0] < cutoff:
            failures.popleft()

    def is_banned(self, webhook_id: str) -> Tuple[bool, float]:
        """Return (banned, seconds_until_unban). seconds_until_unban=0 when not banned."""
        if not webhook_id:
            return False, 0.0
        now = self._now()
        with self._lock:
            unban_at = self._bans.get(webhook_id)
            if unban_at is None:
                return False, 0.0
            if unban_at <= now:
                # Ban expired — clean up.
                del self._bans[webhook_id]
                return False, 0.0
            return True, unban_at - now

    def record_failure(self, webhook_id: str) -> Tuple[bool, int]:
        """Increment the failure counter. Returns (newly_banned, total_failures_in_window).

        `newly_banned=True` exactly once per ban period — the caller can use
        this to fire a single WebhookBannedEvent without spamming.
        """
        if not webhook_id:
            return False, 0
        now = self._now()
        with self._lock:
            # Already banned? Don't extend; just count the attempt.
            if webhook_id in self._bans and self._bans[webhook_id] > now:
                return False, len(self._failures[webhook_id])

            failures = self._failures[webhook_id]
            failures.append(now)
            self._trim(failures, now)

            if len(failures) >= self.failure_threshold:
                self._bans[webhook_id] = now + self.ban_seconds
                # Reset counter — the ban itself is the consequence; further
                # failures during the ban window don't keep extending it.
                count = len(failures)
                failures.clear()
                return True, count

            return False, len(failures)

    def record_success(self, webhook_id: str) -> None:
        """Successful verification clears the failure counter (but NOT an
        active ban — bans run their full duration)."""
        if not webhook_id:
            return
        with self._lock:
            self._failures.pop(webhook_id, None)

    def reset(self) -> None:
        """Clear all state — used by tests."""
        with self._lock:
            self._failures.clear()
            self._bans.clear()


# Module-level singleton — the webhook route uses this.
DEFAULT_TRACKER = AdaptiveBanTracker()


# -----------------------------------------------------------------------------
# Helpers used by tests + the webhook route
# -----------------------------------------------------------------------------


def hmac_sign(key: str, body_bytes: bytes) -> str:
    """Compute the X-OpenAlgo-Signature value for a body. Test helper."""
    digest = hmac.new(key.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return f"hmac-sha256={digest}"
