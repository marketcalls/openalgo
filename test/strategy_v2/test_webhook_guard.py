"""Unit tests for utils/webhook_guard.py — signature, replay, IP, ban."""

import json
import time

import pytest

from utils.webhook_guard import (
    AdaptiveBanTracker,
    hmac_sign,
    ip_allowed,
    parse_allowlist,
    verify_body_secret,
    verify_hmac,
    verify_replay,
)


# --- BODY_SECRET -------------------------------------------------------------


def test_body_secret_matches():
    body = {"webhook_secret": "abc123", "action": "BUY"}
    assert verify_body_secret(body, "abc123") is True


def test_body_secret_mismatch():
    body = {"webhook_secret": "WRONG", "action": "BUY"}
    assert verify_body_secret(body, "abc123") is False


def test_body_secret_missing_field():
    assert verify_body_secret({"action": "BUY"}, "abc123") is False


def test_body_secret_no_expected():
    assert verify_body_secret({"webhook_secret": "abc"}, None) is False
    assert verify_body_secret({"webhook_secret": "abc"}, "") is False


def test_body_secret_non_dict():
    assert verify_body_secret("not a dict", "abc") is False


# --- HMAC --------------------------------------------------------------------


def test_hmac_round_trip():
    body = b'{"action":"BUY","ts":12345}'
    key = "shared-key-32-bytes-of-entropy"
    header = hmac_sign(key, body)
    assert verify_hmac(body, header, key) is True


def test_hmac_tampered_body_rejected():
    body = b'{"action":"BUY"}'
    key = "k"
    header = hmac_sign(key, body)
    tampered = b'{"action":"SELL"}'
    assert verify_hmac(tampered, header, key) is False


def test_hmac_wrong_key_rejected():
    body = b'{"action":"BUY"}'
    header = hmac_sign("real-key", body)
    assert verify_hmac(body, header, "fake-key") is False


def test_hmac_missing_header():
    assert verify_hmac(b"body", None, "k") is False
    assert verify_hmac(b"body", "", "k") is False


def test_hmac_wrong_algorithm_label():
    body = b"body"
    key = "k"
    header = hmac_sign(key, body).replace("hmac-sha256", "hmac-md5")
    assert verify_hmac(body, header, key) is False


def test_hmac_no_key():
    body = b"body"
    header = hmac_sign("k", body)
    assert verify_hmac(body, header, None) is False


def test_hmac_signature_over_raw_bytes_not_parsed_json():
    """Critical: HMAC computed over raw bytes; reformatted JSON breaks the sig."""
    canonical = b'{"action":"BUY","ts":1}'
    reformatted = b'{ "action" : "BUY" , "ts" : 1 }'
    key = "k"
    header = hmac_sign(key, canonical)
    assert verify_hmac(canonical, header, key) is True
    assert verify_hmac(reformatted, header, key) is False


# --- Replay window ----------------------------------------------------------


def test_replay_disabled_when_window_zero():
    ok, _ = verify_replay({"action": "BUY"}, 0)
    assert ok is True


def test_replay_within_window():
    now = 1_750_000_000.0
    ok, _ = verify_replay({"ts": now - 30}, 60, now_func=lambda: now)
    assert ok is True


def test_replay_outside_window():
    now = 1_750_000_000.0
    ok, msg = verify_replay({"ts": now - 600}, 60, now_func=lambda: now)
    assert ok is False
    assert "out of window" in msg.lower()


def test_replay_future_timestamp_rejected():
    now = 1_750_000_000.0
    ok, msg = verify_replay({"ts": now + 600}, 60, now_func=lambda: now)
    assert ok is False
    assert "out of window" in msg.lower()


def test_replay_missing_ts_rejected_when_required():
    ok, msg = verify_replay({"action": "BUY"}, 60)
    assert ok is False
    assert "ts" in msg


def test_replay_non_numeric_ts_rejected():
    ok, msg = verify_replay({"ts": "tomorrow"}, 60)
    assert ok is False
    assert "numeric" in msg.lower() or "ts" in msg


def test_replay_body_not_dict_rejected():
    ok, _ = verify_replay("not a dict", 60)
    assert ok is False


# --- IP allowlist -----------------------------------------------------------


def test_parse_allowlist_empty():
    assert parse_allowlist(None) == []
    assert parse_allowlist("") == []


def test_parse_allowlist_json_list():
    out = parse_allowlist(json.dumps(["10.0.0.0/8", "192.168.1.0/24"]))
    assert out == ["10.0.0.0/8", "192.168.1.0/24"]


def test_parse_allowlist_malformed_returns_empty():
    assert parse_allowlist("{not-json") == []


def test_ip_allowed_no_filter():
    assert ip_allowed("8.8.8.8", []) is True


def test_ip_allowed_match_ipv4():
    assert ip_allowed("10.0.0.5", ["10.0.0.0/8"]) is True
    assert ip_allowed("11.0.0.5", ["10.0.0.0/8"]) is False


def test_ip_allowed_match_ipv6():
    assert ip_allowed("2001:db8::1", ["2001:db8::/32"]) is True
    assert ip_allowed("2001:beef::1", ["2001:db8::/32"]) is False


def test_ip_allowed_mixed_v4_v6():
    cidrs = ["10.0.0.0/8", "2001:db8::/32"]
    assert ip_allowed("10.5.0.1", cidrs) is True
    assert ip_allowed("2001:db8::cafe", cidrs) is True
    assert ip_allowed("8.8.8.8", cidrs) is False


def test_ip_allowed_malformed_client_ip():
    assert ip_allowed("not-an-ip", ["10.0.0.0/8"]) is False


def test_ip_allowed_malformed_cidr_skipped():
    # One bad CIDR shouldn't poison the rest.
    assert ip_allowed("10.0.0.5", ["bogus", "10.0.0.0/8"]) is True


# --- Adaptive ban tracker ---------------------------------------------------


def test_ban_below_threshold():
    t = AdaptiveBanTracker(failure_threshold=5, window_seconds=60)
    for _ in range(4):
        newly, count = t.record_failure("wh1")
        assert newly is False
    assert count == 4
    banned, _ = t.is_banned("wh1")
    assert banned is False


def test_ban_triggers_at_threshold():
    t = AdaptiveBanTracker(failure_threshold=3, window_seconds=60)
    for _ in range(2):
        t.record_failure("wh1")
    newly, _ = t.record_failure("wh1")
    assert newly is True
    banned, secs = t.is_banned("wh1")
    assert banned is True
    assert secs > 0


def test_ban_clears_after_duration():
    fake_now = [1000.0]
    t = AdaptiveBanTracker(
        failure_threshold=2, window_seconds=60, ban_seconds=100,
        now_func=lambda: fake_now[0],
    )
    t.record_failure("wh1")
    t.record_failure("wh1")
    assert t.is_banned("wh1")[0] is True
    fake_now[0] += 200
    assert t.is_banned("wh1")[0] is False


def test_ban_per_webhook_id():
    t = AdaptiveBanTracker(failure_threshold=2, window_seconds=60)
    t.record_failure("wh1")
    t.record_failure("wh1")
    assert t.is_banned("wh1")[0] is True
    assert t.is_banned("wh2")[0] is False


def test_success_clears_failure_counter_not_ban():
    fake_now = [1000.0]
    t = AdaptiveBanTracker(
        failure_threshold=3, window_seconds=60,
        now_func=lambda: fake_now[0],
    )
    t.record_failure("wh1")
    t.record_failure("wh1")
    t.record_success("wh1")
    # Counter cleared — next failure should be #1, not #3
    newly, count = t.record_failure("wh1")
    assert newly is False
    assert count == 1


def test_failures_outside_window_ignored():
    fake_now = [1000.0]
    t = AdaptiveBanTracker(
        failure_threshold=3, window_seconds=60,
        now_func=lambda: fake_now[0],
    )
    t.record_failure("wh1")
    fake_now[0] += 120  # outside window
    newly, count = t.record_failure("wh1")
    # Old failure is trimmed; this is failure #1
    assert count == 1
    assert newly is False


def test_already_banned_records_dont_extend_ban():
    fake_now = [1000.0]
    t = AdaptiveBanTracker(
        failure_threshold=2, window_seconds=60, ban_seconds=100,
        now_func=lambda: fake_now[0],
    )
    t.record_failure("wh1")
    t.record_failure("wh1")  # triggers ban
    _, secs1 = t.is_banned("wh1")
    fake_now[0] += 30
    t.record_failure("wh1")  # during ban
    _, secs2 = t.is_banned("wh1")
    # Remaining ban time should have decreased by ~30s, not been extended.
    assert secs2 < secs1
