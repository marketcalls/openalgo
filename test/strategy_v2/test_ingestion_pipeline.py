"""Ingestion-pipeline tests — validates the security gates and duplicate-
signal guard in services/strategy/ingestion_service.handle_webhook.

Covers the rejection paths (which all must publish StrategySignalRejectedEvent
for audit). Uses an in-process fake StrategyV2 row + a captured event list so
no DB writes happen.

The happy-path (signal → run → entry orders) is covered by Phase 1 E2E tests
that hit a running app — those need the broker + symbol DB. Here we exercise
the gates that turn back hostile/malformed/duplicate requests.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from utils.event_bus import bus
from utils.webhook_guard import DEFAULT_TRACKER, hmac_sign


@pytest.fixture(autouse=True)
def _reset_ban_tracker():
    """Each test gets a clean adaptive-ban state."""
    DEFAULT_TRACKER.reset()
    yield
    DEFAULT_TRACKER.reset()


@pytest.fixture
def captured_events():
    """Snoop on the event bus — capture every event published during a test."""
    captured = []

    def _capture(ev):
        captured.append(ev)

    # Subscribe to the topics we care about for these tests.
    topics = [
        "strategy.signal_received",
        "strategy.signal_rejected",
        "strategy.run_started",
        "strategy.webhook_banned",
    ]
    for t in topics:
        bus.subscribe(t, _capture, f"test:{t}")

    yield captured

    # Cleanup — unsubscribe.
    for t in topics:
        bus.unsubscribe(t, _capture)


def _fake_strategy(**overrides):
    """Build a SimpleNamespace that quacks like a StrategyV2 row for ingestion."""
    base = {
        "id": 42,
        "webhook_id": "test-webhook-uuid",
        "user_id": "tester",
        "is_active": True,
        "mode": "live",
        "underlying": "NIFTY",
        "underlying_exchange": "NSE_INDEX",
        "webhook_signing_method": "NONE",
        "webhook_secret": None,
        "webhook_hmac_key": None,
        "webhook_replay_window_seconds": 0,
        "webhook_ip_allowlist": None,
        "legs": [],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _fake_request(remote_addr="127.0.0.1", headers=None):
    return SimpleNamespace(
        remote_addr=remote_addr,
        headers=headers or {},
    )


def _wait_for_events(captured, count, timeout_sec=1.0):
    """The event bus dispatches via thread pool — give callbacks a moment."""
    import time
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline and len(captured) < count:
        time.sleep(0.005)


def _call_ingestion(strategy, raw_body=b"{}", headers=None, dry_run=False, source_ip="127.0.0.1"):
    """Invoke handle_webhook with a mocked DB lookup and broker session."""
    from services.strategy import ingestion_service

    with patch.object(ingestion_service, "db_session") as mock_session, \
         patch.object(ingestion_service, "get_api_key_for_tradingview", return_value=None), \
         patch.object(ingestion_service, "has_active_run", return_value=False):
        mock_session.query.return_value.filter.return_value.first.return_value = strategy

        return ingestion_service.handle_webhook(
            webhook_id=strategy.webhook_id,
            raw_body=raw_body,
            headers=headers or {},
            request=_fake_request(remote_addr=source_ip, headers=headers),
            dry_run=dry_run,
        )


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def test_unknown_webhook_returns_404():
    from services.strategy import ingestion_service
    with patch.object(ingestion_service, "db_session") as ms:
        ms.query.return_value.filter.return_value.first.return_value = None
        status, body = ingestion_service.handle_webhook(
            webhook_id="nope", raw_body=b"{}", headers={}, request=_fake_request(),
        )
    assert status == 404
    assert body["code"] == "UNKNOWN_WEBHOOK"


def test_disabled_strategy_rejected(captured_events):
    s = _fake_strategy(is_active=False)
    status, body = _call_ingestion(s)
    assert status == 403
    assert body["code"] == "STRATEGY_DISABLED"
    _wait_for_events(captured_events, 1)
    assert any(e.topic == "strategy.signal_rejected" for e in captured_events)


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------


def test_bad_json_rejected(captured_events):
    s = _fake_strategy()
    status, body = _call_ingestion(s, raw_body=b"{not valid json")
    assert status == 400
    assert body["code"] == "BAD_JSON"


def test_non_object_body_rejected(captured_events):
    s = _fake_strategy()
    status, body = _call_ingestion(s, raw_body=b"\"a string\"")
    assert status == 400
    assert body["code"] == "BAD_JSON"


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def test_body_secret_method_accepts_correct_secret(captured_events):
    s = _fake_strategy(
        webhook_signing_method="BODY_SECRET",
        webhook_secret="correct-horse-battery-staple",
    )
    body = json.dumps({"webhook_secret": "correct-horse-battery-staple", "action": "BUY"}).encode()
    status, _ = _call_ingestion(s, raw_body=body, dry_run=True)
    assert status == 200


def test_body_secret_method_rejects_wrong_secret(captured_events):
    s = _fake_strategy(
        webhook_signing_method="BODY_SECRET",
        webhook_secret="real-secret",
    )
    body = json.dumps({"webhook_secret": "WRONG", "action": "BUY"}).encode()
    status, response = _call_ingestion(s, raw_body=body)
    assert status == 403
    assert response["code"] == "INVALID_SIGNATURE"


def test_body_secret_method_rejects_missing_field(captured_events):
    s = _fake_strategy(
        webhook_signing_method="BODY_SECRET",
        webhook_secret="real-secret",
    )
    body = json.dumps({"action": "BUY"}).encode()
    status, response = _call_ingestion(s, raw_body=body)
    assert status == 403


def test_hmac_method_accepts_correct_signature(captured_events):
    key = "shared-hmac-key-32-bytes-of-entropy"
    s = _fake_strategy(
        webhook_signing_method="HMAC_SHA256",
        webhook_hmac_key=key,
    )
    raw = json.dumps({"action": "BUY"}).encode()
    sig_header = hmac_sign(key, raw)
    status, _ = _call_ingestion(
        s, raw_body=raw,
        headers={"X-OpenAlgo-Signature": sig_header},
        dry_run=True,
    )
    assert status == 200


def test_hmac_method_rejects_tampered_body(captured_events):
    key = "shared-hmac-key-32-bytes-of-entropy"
    s = _fake_strategy(
        webhook_signing_method="HMAC_SHA256",
        webhook_hmac_key=key,
    )
    original = json.dumps({"action": "BUY"}).encode()
    sig_header = hmac_sign(key, original)
    tampered = json.dumps({"action": "SELL"}).encode()
    status, response = _call_ingestion(
        s, raw_body=tampered,
        headers={"X-OpenAlgo-Signature": sig_header},
    )
    assert status == 403
    assert response["code"] == "INVALID_SIGNATURE"


def test_hmac_method_rejects_missing_header(captured_events):
    s = _fake_strategy(
        webhook_signing_method="HMAC_SHA256",
        webhook_hmac_key="key",
    )
    status, _ = _call_ingestion(s, raw_body=b'{"action":"BUY"}', headers={})
    assert status == 403


def test_both_method_accepts_either_path(captured_events):
    """BOTH mode: either body-secret OR HMAC succeeds."""
    s = _fake_strategy(
        webhook_signing_method="BOTH",
        webhook_secret="bs",
        webhook_hmac_key="hk",
    )
    # Body-secret succeeds, no HMAC header
    body = json.dumps({"webhook_secret": "bs", "action": "BUY"}).encode()
    status, _ = _call_ingestion(s, raw_body=body, dry_run=True)
    assert status == 200

    # HMAC succeeds, no body secret
    raw = json.dumps({"action": "BUY"}).encode()
    sig = hmac_sign("hk", raw)
    status, _ = _call_ingestion(
        s, raw_body=raw, headers={"X-OpenAlgo-Signature": sig}, dry_run=True,
    )
    assert status == 200


def test_both_method_rejects_when_neither_works(captured_events):
    s = _fake_strategy(
        webhook_signing_method="BOTH",
        webhook_secret="bs",
        webhook_hmac_key="hk",
    )
    status, response = _call_ingestion(
        s, raw_body=b'{"webhook_secret":"WRONG","action":"BUY"}',
    )
    assert status == 403
    assert response["code"] == "INVALID_SIGNATURE"


def test_none_method_accepts_any_payload(captured_events):
    """NONE: URL secret only — no body validation."""
    s = _fake_strategy(webhook_signing_method="NONE")
    status, _ = _call_ingestion(s, raw_body=b'{"random":"junk"}', dry_run=True)
    assert status == 200


# ---------------------------------------------------------------------------
# Replay window
# ---------------------------------------------------------------------------


def test_replay_window_disabled_passes(captured_events):
    s = _fake_strategy(webhook_replay_window_seconds=0)
    status, _ = _call_ingestion(s, raw_body=b'{"action":"BUY"}', dry_run=True)
    assert status == 200


def test_replay_window_missing_ts_rejected(captured_events):
    s = _fake_strategy(webhook_replay_window_seconds=60)
    status, response = _call_ingestion(s, raw_body=b'{"action":"BUY"}')
    assert status == 403
    assert response["code"] == "REPLAY_PROTECTION"


def test_replay_window_old_ts_rejected(captured_events):
    s = _fake_strategy(webhook_replay_window_seconds=60)
    body = json.dumps({"action": "BUY", "ts": 1}).encode()  # year 1970 — way out of window
    status, response = _call_ingestion(s, raw_body=body)
    assert status == 403
    assert response["code"] == "REPLAY_PROTECTION"


# ---------------------------------------------------------------------------
# IP allowlist
# ---------------------------------------------------------------------------


def test_ip_allowlist_match_passes(captured_events):
    s = _fake_strategy(webhook_ip_allowlist=json.dumps(["10.0.0.0/8"]))
    status, _ = _call_ingestion(s, raw_body=b'{"action":"BUY"}', source_ip="10.5.0.1", dry_run=True)
    assert status == 200


def test_ip_allowlist_mismatch_rejected(captured_events):
    s = _fake_strategy(webhook_ip_allowlist=json.dumps(["10.0.0.0/8"]))
    status, response = _call_ingestion(s, raw_body=b'{"action":"BUY"}', source_ip="8.8.8.8")
    assert status == 403
    assert response["code"] == "IP_NOT_ALLOWED"


# ---------------------------------------------------------------------------
# Adaptive ban
# ---------------------------------------------------------------------------


def test_repeated_signature_failures_trigger_ban(captured_events):
    s = _fake_strategy(
        webhook_signing_method="BODY_SECRET",
        webhook_secret="real-secret",
    )
    # 5 wrong attempts (default threshold)
    for _ in range(5):
        status, _ = _call_ingestion(
            s, raw_body=b'{"webhook_secret":"WRONG"}',
        )
        assert status == 403

    # 6th attempt — banned
    status, response = _call_ingestion(
        s, raw_body=b'{"webhook_secret":"WRONG"}',
    )
    assert status == 429
    assert response["code"] == "WEBHOOK_BANNED"
    assert "retry_after_seconds" in response

    # Verify a WebhookBannedEvent was published
    _wait_for_events(captured_events, 1)
    assert any(e.topic == "strategy.webhook_banned" for e in captured_events)


def test_successful_request_clears_failure_counter(captured_events):
    s = _fake_strategy(
        webhook_signing_method="BODY_SECRET",
        webhook_secret="real-secret",
    )
    # 4 fails
    for _ in range(4):
        _call_ingestion(s, raw_body=b'{"webhook_secret":"WRONG"}')
    # 1 success
    body = json.dumps({"webhook_secret": "real-secret"}).encode()
    status, _ = _call_ingestion(s, raw_body=body, dry_run=True)
    assert status == 200
    # Counter cleared — next 4 fails should NOT trigger a ban yet
    for _ in range(4):
        status, _ = _call_ingestion(s, raw_body=b'{"webhook_secret":"WRONG"}')
        assert status == 403
    # 5th fail post-success → ban
    banned, _ = DEFAULT_TRACKER.is_banned(s.webhook_id)
    assert banned is False  # threshold = 5; we only logged 4 since success


# ---------------------------------------------------------------------------
# Dry-run vs live distinction
# ---------------------------------------------------------------------------


def test_dry_run_returns_validation_only(captured_events):
    s = _fake_strategy()
    status, response = _call_ingestion(s, raw_body=b'{"action":"BUY"}', dry_run=True)
    assert status == 200
    assert response["mode"] == "dry_run"
    assert response["status"] == "success"
    # Dry-run does NOT publish signal_received (no run is created).
    _wait_for_events(captured_events, 0)
    received = [e for e in captured_events if e.topic == "strategy.signal_received"]
    assert received == []


def test_signing_secret_stripped_before_signal_received(captured_events):
    """The webhook_secret must NEVER appear in signal_received payloads —
    otherwise audit logs leak the secret."""
    from services.strategy import ingestion_service

    s = _fake_strategy(
        webhook_signing_method="BODY_SECRET",
        webhook_secret="hunter2",
    )

    # Use real has_active_run + db_session but mock api_key resolver
    # to force NO_BROKER_SESSION before run creation. The signal_received
    # event still fires because we got past validation.
    with patch.object(ingestion_service, "db_session") as ms, \
         patch.object(ingestion_service, "get_api_key_for_tradingview", return_value=None), \
         patch.object(ingestion_service, "has_active_run", return_value=False):
        ms.query.return_value.filter.return_value.first.return_value = s

        body = json.dumps({"webhook_secret": "hunter2", "action": "BUY", "ts": 0}).encode()
        ingestion_service.handle_webhook(
            webhook_id=s.webhook_id, raw_body=body, headers={}, request=_fake_request(),
        )

    _wait_for_events(captured_events, 1)
    received = [e for e in captured_events if e.topic == "strategy.signal_received"]
    assert received, "signal_received must fire after signature passes"
    payload = received[0].payload
    assert "webhook_secret" not in payload, (
        f"Secret leaked into signal_received payload: {payload!r}"
    )
