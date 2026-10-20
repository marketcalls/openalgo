"""What the public strategy webhook refuses, and what it lets through.

``services/strategy_module/webhook.py`` is the whole of the authorization
decision for an endpoint that is unauthenticated, CSRF exempt and able to start
real trading. So the tests worth having are the negative ones: every stage is
exercised in both directions, and the accepting direction is asserted too so a
stage cannot pass by refusing everything.

Three properties get their own tests because breaking them is silent:

* an audit row is written for every outcome, with the label from
  ``store.WEBHOOK_RESULTS`` that matches it;
* the token plaintext reaches neither the audit row nor the response, even when
  the sender puts it in the body;
* an unknown token and a malformed one are indistinguishable in the response,
  so the endpoint is not an oracle for which tokens exist.

Nothing here touches the database or an engine. The store's two entry points
are replaced, the clock is driven by hand so the deduplication and cooling-off
windows can be crossed without sleeping, and the engine is injected.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from database import strategy_module_db as store
from services.strategy_module import webhook, webhook_bridge

TOKEN = store.WEBHOOK_TOKEN_PREFIX + "A" * 43
OTHER_TOKEN = store.WEBHOOK_TOKEN_PREFIX + "B" * 43
MALFORMED_TOKEN = "definitely-not-a-webhook-token"


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class FakeClock:
    """A monotonic clock the test advances itself."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@dataclass
class FakeStrategy:
    """Only the SmStrategy columns the pipeline reads."""

    id: int = 1
    live_enabled: bool = False
    webhook_locked: bool = False
    webhook_ip_allowlist: list[str] | None = None
    strategy_kind: str = "batch"
    status: str = "stopped"


@dataclass
class Registry:
    """Stands in for the hashed token lookup, and counts what it was asked."""

    tokens: dict[str, FakeStrategy] = field(default_factory=dict)
    lookups: list[str] = field(default_factory=list)

    def __call__(self, token: str) -> FakeStrategy | None:
        self.lookups.append(token)
        return self.tokens.get(token)


class Recorder:
    """Stands in for ``store.record_webhook_event``."""

    def __init__(self) -> None:
        self.rows: list[SimpleNamespace] = []

    def __call__(self, **kwargs) -> SimpleNamespace:
        row = SimpleNamespace(id=len(self.rows) + 1, **kwargs)
        self.rows.append(row)
        return row

    @property
    def results(self) -> list[str]:
        return [row.result for row in self.rows]

    @property
    def last(self) -> SimpleNamespace:
        return self.rows[-1]

    def dumped(self) -> str:
        return json.dumps([row.__dict__ for row in self.rows], default=str)


#: Distinguishes "the test said nothing about the return value" from "the test
#: said the engine returns None", which is one of the accepted shapes.
UNSET = object()


class FakeEngine:
    """Records what it was asked to do, and answers however the test says."""

    def __init__(self, result=UNSET, raises: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.result = result
        self.raises = raises

    def start_run(self, strategy, mode, *, trigger_source="webhook", webhook_event_id=None):
        self.calls.append(
            {
                "action": "start",
                "strategy_id": strategy.id,
                "mode": mode,
                "trigger_source": trigger_source,
                "webhook_event_id": webhook_event_id,
            }
        )
        if self.raises is not None:
            raise self.raises
        if self.result is not UNSET:
            return self.result
        return webhook.EngineResult(ok=True, run_id=77)

    def stop_run(
        self, strategy, *, stop_reason="manual", trigger_source="webhook", webhook_event_id=None
    ):
        self.calls.append(
            {
                "action": "stop",
                "strategy_id": strategy.id,
                "stop_reason": stop_reason,
                "trigger_source": trigger_source,
                "webhook_event_id": webhook_event_id,
            }
        )
        if self.raises is not None:
            raise self.raises
        if self.result is not UNSET:
            return self.result
        return webhook.EngineResult(ok=True, run_id=88)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(webhook, "_clock", fake)
    # Rebuilt after the clock is in place: a TTLCache stamps its expiries with
    # whatever timer it was built with, so the windows must be created against
    # the fake rather than inheriting real monotonic timestamps.
    webhook.reset_state()
    yield fake
    webhook.reset_state()


@pytest.fixture
def registry(monkeypatch):
    reg = Registry()
    monkeypatch.setattr(store, "get_strategy_by_webhook_token", reg)
    return reg


@pytest.fixture
def audit(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(store, "record_webhook_event", recorder)
    return recorder


@pytest.fixture
def no_default_engine(monkeypatch):
    """Fail loudly if a test reaches the lazily imported engine by accident."""

    def _boom():
        raise AssertionError("the default engine must not be resolved in these tests")

    monkeypatch.setattr(webhook, "_default_engine", _boom)


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def strategy(registry):
    row = FakeStrategy()
    registry.tokens[TOKEN] = row
    return row


@pytest.fixture(autouse=True)
def wiring(clock, registry, audit, no_default_engine):
    """Every test runs with the store, the clock and the engine replaced."""
    return SimpleNamespace(clock=clock, registry=registry, audit=audit)


def call(token=TOKEN, body=None, *, ip="1.2.3.4", user_agent="TradingView", engine=None):
    """One inbound webhook, with a start in sandbox as the default body."""
    if body is None:
        body = {"action": "start", "mode": "sandbox"}
    return webhook.handle_webhook(
        token, body, ip=ip, user_agent=user_agent, engine=engine or FakeEngine()
    )


def assert_status_matches_label(outcome):
    """Every outcome carries the status its label maps to, and a real label."""
    assert outcome.result in store.WEBHOOK_RESULTS
    assert outcome.status == webhook.RESULT_STATUS[outcome.result]


# ---------------------------------------------------------------------------
# The accepting direction
# ---------------------------------------------------------------------------


def test_a_sandbox_start_reaches_the_engine_and_is_audited_ok(strategy, engine, audit):
    outcome = call(engine=engine)

    assert outcome.ok is True
    assert outcome.result == "ok"
    assert outcome.status == 200
    assert outcome.strategy_id == strategy.id
    assert outcome.run_id == 77
    assert engine.calls[0]["action"] == "start"
    assert engine.calls[0]["mode"] == "sandbox"
    assert engine.calls[0]["trigger_source"] == "webhook"
    assert audit.results == ["ok"]
    assert audit.last.action == "start"
    assert audit.last.mode == "sandbox"


def test_the_accepted_row_id_is_handed_to_the_engine(strategy, engine, audit):
    # The run has to be able to point back at the webhook that caused it, and
    # sm_webhook_event is append-only, so the row is written before dispatch.
    call(engine=engine)

    assert engine.calls[0]["webhook_event_id"] == audit.rows[0].id


def test_a_stop_reaches_the_engine(strategy, engine, audit):
    outcome = call(body={"action": "stop"}, engine=engine)

    assert outcome.ok is True
    assert outcome.result == "ok"
    assert engine.calls[0]["action"] == "stop"
    assert engine.calls[0]["stop_reason"] == "manual"
    assert audit.results == ["ok"]
    assert audit.last.mode is None


def test_a_pending_stop_is_structured_in_webhook_result_and_does_not_arm_cooling_off(strategy):
    strategy.status = "running"
    exits = [{"leg_id": 1, "ok": True}]
    engine = FakeEngine(result={"ok": True, "run_id": 88, "stop_pending": True, "exits": exits})

    outcome = call(body={"action": "stop"}, engine=engine)

    assert outcome.ok is True
    assert outcome.stop_pending is True
    assert outcome.exits == exits
    assert outcome.body["stop_pending"] is True
    assert outcome.body["exits"] == exits
    assert webhook._cooling_off_remaining(strategy.id) == 0


def test_a_refused_pending_stop_keeps_structured_retry_detail_in_webhook_response(strategy):
    strategy.status = "running"
    exits = [{"leg_id": 1, "ok": False, "error": "No API key"}]
    engine = FakeEngine(
        result={
            "ok": False,
            "run_id": 88,
            "stop_pending": True,
            "error": "No API key is configured for this user",
            "exits": exits,
        }
    )

    outcome = call(body={"action": "stop"}, engine=engine)

    assert outcome.ok is False
    assert outcome.stop_pending is True
    assert outcome.exits == exits
    assert outcome.body["stop_pending"] is True
    assert outcome.body["exits"] == exits
    assert webhook._cooling_off_remaining(strategy.id) == 0


def test_webhook_bridge_forwards_pending_and_exit_detail():
    strategy = SimpleNamespace(id=9, user_id="bridge-user", current_run_id=44)
    exits = [{"leg_id": 1, "ok": True}]

    with patch(
        "services.strategy_module.engine.stop_run",
        return_value={"ok": True, "stop_pending": True, "exits": exits},
    ):
        result = webhook_bridge.stop_run(strategy)

    assert result.ok is True
    assert result.run_id == 44
    assert result.stop_pending is True
    assert result.exits == exits


def test_action_and_mode_are_read_case_insensitively(strategy, engine):
    outcome = call(body={"action": " START ", "mode": "Sandbox"}, engine=engine)

    assert outcome.ok is True
    assert engine.calls[0]["mode"] == "sandbox"


def test_raw_json_text_and_bytes_are_both_accepted(strategy):
    text_engine = FakeEngine()
    text = json.dumps({"action": "start", "mode": "sandbox"})
    assert call(body=text, engine=text_engine).ok is True

    webhook.reset_state()
    bytes_engine = FakeEngine()
    assert call(body=text.encode(), engine=bytes_engine).ok is True


def test_the_default_engine_is_used_when_none_is_injected(strategy, monkeypatch):
    injected = FakeEngine()
    monkeypatch.setattr(webhook, "_default_engine", lambda: injected)

    outcome = webhook.handle_webhook(TOKEN, {"action": "start", "mode": "sandbox"}, ip="1.2.3.4")

    assert outcome.ok is True
    assert injected.calls[0]["action"] == "start"


# ---------------------------------------------------------------------------
# 1. Token
# ---------------------------------------------------------------------------


def test_an_unknown_token_is_rejected_and_audited(audit, registry):
    outcome = call(token=OTHER_TOKEN)

    assert outcome.ok is False
    assert outcome.result == "rejected_token"
    assert outcome.status == 404
    assert outcome.strategy_id is None
    assert audit.results == ["rejected_token"]
    assert audit.last.strategy_id is None
    assert registry.lookups == [OTHER_TOKEN]


def test_a_malformed_token_is_indistinguishable_from_an_unknown_one(audit, registry):
    unknown = call(token=OTHER_TOKEN)
    malformed = call(token=MALFORMED_TOKEN)

    assert malformed.as_response() == unknown.as_response()
    assert malformed.body == unknown.body
    assert audit.results == ["rejected_token", "rejected_token"]
    # The malformed one is refused on its shape, so it never costs a lookup:
    # the two cases are not separable by timing either.
    assert registry.lookups == [OTHER_TOKEN]


@pytest.mark.parametrize("token", [None, "", "oaws_", "oaws_short", "nope_" + "A" * 43, 12345])
def test_anything_not_shaped_like_a_token_is_refused_without_a_lookup(token, registry):
    outcome = webhook.handle_webhook(token, {"action": "stop"}, ip="1.2.3.4")

    assert outcome.result == "rejected_token"
    assert registry.lookups == []


def test_unknown_token_outcome_is_the_helper_the_route_returns(audit):
    outcome = webhook.unknown_token_outcome(ip="9.9.9.9", user_agent="curl")

    # Same answer the pipeline gives, so the route can use it for a request
    # that carries no usable token at all without inventing a second shape.
    assert outcome.as_response() == call(token=OTHER_TOKEN).as_response()
    assert outcome.status == 404
    assert audit.rows[0].result == "rejected_token"
    assert audit.rows[0].ip == "9.9.9.9"


def test_unknown_token_outcome_can_skip_the_audit(audit):
    outcome = webhook.unknown_token_outcome(audit=False)

    assert outcome.result == "rejected_token"
    assert audit.rows == []


# ---------------------------------------------------------------------------
# 2. Kill switch
# ---------------------------------------------------------------------------


def test_a_locked_strategy_refuses_every_signal(strategy, engine, audit):
    strategy.webhook_locked = True

    outcome = call(engine=engine)

    assert outcome.ok is False
    assert outcome.result == "rejected_locked"
    assert outcome.status == 403
    assert engine.calls == []
    assert audit.results == ["rejected_locked"]
    assert audit.last.strategy_id == strategy.id


def test_the_kill_switch_outranks_a_malformed_body(strategy, engine, audit):
    # A locked strategy is locked against everything, so the body is never even
    # parsed and the operator sees the lock rather than a payload complaint.
    strategy.webhook_locked = True

    outcome = call(body="}{ not json", engine=engine)

    assert outcome.result == "rejected_locked"
    assert audit.results == ["rejected_locked"]


def test_releasing_the_lock_lets_the_signal_through(strategy, engine):
    strategy.webhook_locked = False

    assert call(engine=engine).ok is True


# ---------------------------------------------------------------------------
# 3. IP allowlist
# ---------------------------------------------------------------------------


def test_an_address_inside_the_allowlist_is_accepted(strategy, engine):
    strategy.webhook_ip_allowlist = ["52.89.214.238/32", "10.0.0.0/8"]

    assert call(ip="10.4.1.9", engine=engine).ok is True


def test_an_address_outside_the_allowlist_is_refused(strategy, engine, audit):
    strategy.webhook_ip_allowlist = ["10.0.0.0/8"]

    outcome = call(ip="203.0.113.7", engine=engine)

    assert outcome.ok is False
    assert outcome.result == "rejected_ip"
    assert outcome.status == 403
    assert engine.calls == []
    assert audit.results == ["rejected_ip"]
    assert audit.last.ip == "203.0.113.7"


def test_an_empty_allowlist_allows_any_address(strategy, engine):
    strategy.webhook_ip_allowlist = []

    assert call(ip="203.0.113.7", engine=engine).ok is True


def test_a_request_with_no_address_fails_a_non_empty_allowlist(strategy, engine):
    strategy.webhook_ip_allowlist = ["10.0.0.0/8"]

    outcome = call(ip=None, engine=engine)

    assert outcome.result == "rejected_ip"
    assert engine.calls == []


def test_the_allowlist_is_checked_before_the_body_is_parsed(strategy, engine, audit):
    strategy.webhook_ip_allowlist = ["10.0.0.0/8"]

    outcome = call(ip="203.0.113.7", body="}{ not json", engine=engine)

    assert outcome.result == "rejected_ip"
    assert audit.results == ["rejected_ip"]


@pytest.mark.parametrize(
    ("ip", "allowlist", "expected"),
    [
        ("192.168.1.20", ["192.168.1.0/24"], True),
        ("192.168.2.20", ["192.168.1.0/24"], False),
        ("52.89.214.238", ["52.89.214.238"], True),
        ("52.89.214.239", ["52.89.214.238"], False),
        ("2001:db8::5", ["2001:db8::/32"], True),
        ("2001:dbf::5", ["2001:db8::/32"], False),
        ("10.1.2.3", ["2001:db8::/32"], False),
        ("::ffff:10.1.2.3", ["10.0.0.0/8"], True),
        ("not-an-address", ["10.0.0.0/8"], False),
        ("10.1.2.3", None, True),
        # A single unusable entry is skipped rather than failing the list
        # closed, so one bad row cannot mute a working webhook.
        ("10.1.2.3", ["garbage", "10.0.0.0/8"], True),
    ],
)
def test_ip_allowed(ip, allowlist, expected):
    assert webhook.ip_allowed(ip, allowlist) is expected


# ---------------------------------------------------------------------------
# 4. Payload
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        None,
        "",
        "   ",
        "not json at all",
        "[1, 2, 3]",
        '"a bare string"',
        "42",
        b"\xff\xfe not utf 8",
        ["action", "start"],
    ],
)
def test_a_body_that_is_not_a_json_object_is_refused(body, strategy, engine, audit):
    outcome = webhook.handle_webhook(TOKEN, body, ip="1.2.3.4", engine=engine)

    assert outcome.ok is False
    assert outcome.result == "rejected_payload"
    assert outcome.status == 400
    assert engine.calls == []
    assert audit.results == ["rejected_payload"]


def test_an_oversized_body_is_refused(strategy, engine, audit):
    body = json.dumps(
        {"action": "start", "mode": "sandbox", "pad": "x" * (webhook.MAX_PAYLOAD_BYTES + 1)}
    )

    outcome = webhook.handle_webhook(TOKEN, body, ip="1.2.3.4", engine=engine)

    assert outcome.result == "rejected_payload"
    assert engine.calls == []
    assert str(webhook.MAX_PAYLOAD_BYTES) in outcome.message


def test_an_oversized_pre_parsed_body_is_refused(strategy, engine):
    body = {"action": "start", "mode": "sandbox", "pad": "x" * (webhook.MAX_PAYLOAD_BYTES + 1)}

    outcome = webhook.handle_webhook(TOKEN, body, ip="1.2.3.4", engine=engine)

    assert outcome.result == "rejected_payload"
    assert engine.calls == []


def test_a_body_at_the_cap_is_accepted(strategy, engine):
    pad = "x" * (webhook.MAX_PAYLOAD_BYTES - 100)
    body = json.dumps({"action": "start", "mode": "sandbox", "pad": pad})
    assert len(body.encode()) <= webhook.MAX_PAYLOAD_BYTES

    assert webhook.handle_webhook(TOKEN, body, ip="1.2.3.4", engine=engine).ok is True


# ---------------------------------------------------------------------------
# 5 and 6. Action and mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"mode": "sandbox"},
        {"action": "pause"},
        {"action": "START_RUN"},
        {"action": ""},
        {"action": None},
        {"action": 1},
        {"action": ["start"]},
    ],
)
def test_an_unrecognised_action_is_refused(body, strategy, engine, audit):
    outcome = call(body=body, engine=engine)

    assert outcome.ok is False
    assert outcome.result == "rejected_invalid_action"
    assert outcome.status == 400
    assert engine.calls == []
    assert audit.results == ["rejected_invalid_action"]


@pytest.mark.parametrize(
    "body",
    [
        {"action": "start"},
        {"action": "start", "mode": None},
        {"action": "start", "mode": ""},
        {"action": "start", "mode": "paper"},
        {"action": "start", "mode": "SANDBOXX"},
        {"action": "start", "mode": 1},
    ],
)
def test_a_start_without_a_valid_mode_is_refused(body, strategy, engine, audit):
    outcome = call(body=body, engine=engine)

    assert outcome.result == "rejected_invalid_action"
    assert outcome.status == 400
    assert engine.calls == []
    assert audit.results == ["rejected_invalid_action"]
    assert audit.last.action == "start"


def test_a_stop_needs_no_mode_and_ignores_a_stray_one(strategy, engine):
    # A sender's extra field is not a reason to leave a position open.
    outcome = call(body={"action": "stop", "mode": "nonsense"}, engine=engine)

    assert outcome.ok is True
    assert engine.calls[0]["action"] == "stop"


# ---------------------------------------------------------------------------
# 7. The live gate
# ---------------------------------------------------------------------------


def test_a_live_start_on_a_sandbox_only_strategy_is_refused(strategy, engine, audit):
    strategy.live_enabled = False

    outcome = call(body={"action": "start", "mode": "live"}, engine=engine)

    assert outcome.ok is False
    assert outcome.result == "rejected_live_disabled"
    assert outcome.status == 403
    assert engine.calls == []
    assert audit.results == ["rejected_live_disabled"]
    assert audit.last.mode == "live"


def test_a_live_start_is_accepted_once_live_is_enabled(strategy, engine):
    strategy.live_enabled = True

    outcome = call(body={"action": "start", "mode": "live"}, engine=engine)

    assert outcome.ok is True
    assert engine.calls[0]["mode"] == "live"


def test_a_sandbox_start_is_unaffected_by_the_live_gate(strategy, engine):
    strategy.live_enabled = False

    assert call(body={"action": "start", "mode": "sandbox"}, engine=engine).ok is True


def test_a_stop_is_unaffected_by_the_live_gate(strategy, engine):
    # A strategy that is not allowed to start live must still be stoppable.
    strategy.live_enabled = False

    assert call(body={"action": "stop"}, engine=engine).ok is True


# ---------------------------------------------------------------------------
# 8. Idempotency
# ---------------------------------------------------------------------------


def test_a_repeated_signal_inside_the_window_is_a_no_op_success(strategy, engine, audit):
    first = call(engine=engine)
    second = call(engine=engine)

    assert first.result == "ok"
    assert second.ok is True
    assert second.result == "rejected_dedupe"
    assert second.status == 200
    assert len(engine.calls) == 1
    assert audit.results == ["ok", "rejected_dedupe"]


def test_deduplication_is_keyed_on_action_and_mode(strategy, engine):
    call(body={"action": "start", "mode": "sandbox"}, engine=engine)
    call(body={"action": "stop"}, engine=engine)

    assert [c["action"] for c in engine.calls] == ["start", "stop"]


def test_a_different_mode_is_a_different_signal(strategy, engine):
    strategy.live_enabled = True

    call(body={"action": "start", "mode": "sandbox"}, engine=engine)
    call(body={"action": "start", "mode": "live"}, engine=engine)

    assert [c["mode"] for c in engine.calls] == ["sandbox", "live"]


def test_the_same_signal_is_accepted_again_once_the_window_expires(strategy, engine, clock):
    call(engine=engine)
    clock.advance(webhook.DEDUPE_WINDOW_SECONDS + 1)
    outcome = call(engine=engine)

    assert outcome.result == "ok"
    assert len(engine.calls) == 2


def test_deduplication_is_per_strategy(registry, engine):
    first = FakeStrategy(id=1)
    second = FakeStrategy(id=2)
    registry.tokens[TOKEN] = first
    registry.tokens[OTHER_TOKEN] = second

    call(token=TOKEN, engine=engine)
    call(token=OTHER_TOKEN, engine=engine)

    assert [c["strategy_id"] for c in engine.calls] == [1, 2]


# ---------------------------------------------------------------------------
# 9. Cooling off
# ---------------------------------------------------------------------------


def test_a_start_right_after_a_stop_is_refused(strategy, audit, clock):
    strategy.status = "running"
    stop_engine = FakeEngine()
    call(body={"action": "stop"}, engine=stop_engine)

    clock.advance(5)
    start_engine = FakeEngine()
    outcome = call(engine=start_engine)

    assert outcome.ok is False
    assert outcome.result == "rejected_cooling_off"
    assert outcome.status == 409
    assert start_engine.calls == []
    assert audit.results == ["ok", "rejected_cooling_off"]


def test_cooling_off_expires(strategy, clock):
    strategy.status = "running"
    call(body={"action": "stop"}, engine=FakeEngine())

    clock.advance(webhook.COOLING_OFF_SECONDS + 1)
    start_engine = FakeEngine()

    assert call(engine=start_engine).ok is True
    assert len(start_engine.calls) == 1


def test_cooling_off_does_not_block_a_stop(strategy, clock):
    # The window exists to stop an alert pair oscillating into the market, not
    # to make a position harder to close.
    webhook.note_run_stopped(strategy.id)
    clock.advance(1)
    engine = FakeEngine()

    outcome = call(body={"action": "stop"}, engine=engine)

    assert outcome.ok is True
    assert engine.calls[0]["action"] == "stop"


def test_an_engine_initiated_stop_arms_the_window(strategy, clock):
    # note_run_stopped is what the engine calls for a square-off or a stop loss
    # it triggered itself, so a stale alert cannot restart one second later.
    webhook.note_run_stopped(strategy.id)
    clock.advance(1)

    outcome = call(engine=FakeEngine())

    assert outcome.result == "rejected_cooling_off"


def test_a_stop_against_an_already_stopped_strategy_does_not_arm_the_window(strategy, clock):
    # A stray stop that stopped nothing must not lock out a legitimate start.
    strategy.status = "stopped"
    call(body={"action": "stop"}, engine=FakeEngine())

    clock.advance(1)
    start_engine = FakeEngine()

    assert call(engine=start_engine).ok is True
    assert len(start_engine.calls) == 1


def test_cooling_off_is_per_strategy(registry, clock):
    first = FakeStrategy(id=1, status="running")
    second = FakeStrategy(id=2)
    registry.tokens[TOKEN] = first
    registry.tokens[OTHER_TOKEN] = second

    call(token=TOKEN, body={"action": "stop"}, engine=FakeEngine())
    clock.advance(1)
    other_engine = FakeEngine()

    assert call(token=OTHER_TOKEN, engine=other_engine).ok is True
    assert len(other_engine.calls) == 1


# ---------------------------------------------------------------------------
# 10. The engine
# ---------------------------------------------------------------------------


def test_an_engine_exception_is_reported_not_raised(strategy, audit):
    engine = FakeEngine(raises=RuntimeError("broker session expired"))

    outcome = call(engine=engine)

    assert outcome.ok is False
    assert outcome.result == "rejected_engine_error"
    assert outcome.status == 500
    assert "broker session expired" in outcome.message
    # The accepted row stays: the webhook was valid, and the failure is a
    # second row because sm_webhook_event is append-only.
    assert audit.results == ["ok", "rejected_engine_error"]


def test_a_failed_dispatch_releases_the_deduplication_claim(strategy):
    failing = FakeEngine(raises=RuntimeError("boom"))
    call(engine=failing)

    retry = FakeEngine()
    outcome = call(engine=retry)

    # A sender retrying a delivery that did nothing must not be told it was a
    # duplicate of it.
    assert outcome.ok is True
    assert len(retry.calls) == 1


def test_an_engine_refusal_is_reported(strategy, audit):
    engine = FakeEngine(result=webhook.EngineResult(ok=False, error="no broker session"))

    outcome = call(engine=engine)

    assert outcome.result == "rejected_engine_error"
    assert outcome.message == "no broker session"
    assert audit.last.error == "no broker session"


@pytest.mark.parametrize(
    ("returned", "run_id"),
    [
        (True, None),
        (None, None),
        ({"ok": True, "run_id": 12}, 12),
        (webhook.EngineResult(ok=True, run_id=5), 5),
        (SimpleNamespace(ok=True, run_id=9, error=None), 9),
    ],
)
def test_the_engine_may_answer_in_any_of_the_accepted_shapes(returned, run_id, strategy):
    outcome = call(engine=FakeEngine(result=returned))

    assert outcome.ok is True
    assert outcome.run_id == run_id


def test_an_engine_that_cannot_be_resolved_is_reported(strategy, monkeypatch, audit):
    def _missing():
        raise ImportError("no engine yet")

    monkeypatch.setattr(webhook, "_default_engine", _missing)

    outcome = webhook.handle_webhook(TOKEN, {"action": "stop"}, ip="1.2.3.4")

    assert outcome.result == "rejected_engine_error"
    assert outcome.status == 500
    assert audit.results == ["ok", "rejected_engine_error"]


# ---------------------------------------------------------------------------
# Cross-cutting: audit coverage, secrecy, and the result vocabulary
# ---------------------------------------------------------------------------


def _scenario_rows():
    """One case per stage, each naming the label it must be audited with."""
    return [
        ("rejected_token", {"token": OTHER_TOKEN}, {}),
        ("rejected_locked", {}, {"webhook_locked": True}),
        ("rejected_ip", {"ip": "203.0.113.7"}, {"webhook_ip_allowlist": ["10.0.0.0/8"]}),
        ("rejected_payload", {"body": "not json"}, {}),
        ("rejected_invalid_action", {"body": {"action": "pause"}}, {}),
        ("rejected_live_disabled", {"body": {"action": "start", "mode": "live"}}, {}),
        ("ok", {}, {}),
    ]


@pytest.mark.parametrize(("expected", "kwargs", "attrs"), _scenario_rows())
def test_every_outcome_is_audited_with_its_own_label(expected, kwargs, attrs, registry, audit):
    row = FakeStrategy(**attrs)
    registry.tokens[TOKEN] = row

    outcome = call(engine=FakeEngine(), **kwargs)

    assert outcome.result == expected
    assert audit.results == [expected]
    assert_status_matches_label(outcome)


def test_the_two_window_stages_are_audited_too(strategy, audit, clock):
    strategy.status = "running"
    call(body={"action": "stop"}, engine=FakeEngine())
    call(body={"action": "stop"}, engine=FakeEngine())
    clock.advance(1)
    call(engine=FakeEngine())

    assert audit.results == ["ok", "rejected_dedupe", "rejected_cooling_off"]


def test_the_token_never_reaches_the_audit_row_or_the_response(strategy, audit):
    body = {
        "action": "start",
        "mode": "sandbox",
        "token": TOKEN,
        "secret": "hunter2",
        "note": f"posted to https://example.com/strategy/webhook/{TOKEN}",
        "nested": {"api_key": "abcd", "url": TOKEN},
        "list": [TOKEN, "harmless"],
    }

    outcome = call(body=body, engine=FakeEngine())

    dumped = audit.dumped()
    assert TOKEN not in dumped
    assert "hunter2" not in dumped
    assert "abcd" not in dumped
    assert TOKEN not in json.dumps(outcome.body)
    # The harmless fields survive, so the audit row is still worth reading.
    assert "harmless" in dumped
    assert audit.last.payload["action"] == "start"
    assert audit.last.payload["token"] == "[redacted]"
    assert audit.last.payload["note"] == "[redacted]"
    assert audit.last.payload["nested"]["url"] == "[redacted]"
    assert audit.last.payload["list"] == ["[redacted]", "harmless"]


def test_a_rejected_payload_is_not_persisted_verbatim(strategy, audit):
    # Nothing parsed, so nothing to store: the row still names the failure.
    call(body="}{" + TOKEN, engine=FakeEngine())

    assert audit.last.result == "rejected_payload"
    assert audit.last.payload is None
    assert TOKEN not in audit.dumped()


def test_the_token_is_never_logged(strategy, caplog):
    with caplog.at_level("DEBUG"):
        call(token=OTHER_TOKEN)
        call(engine=FakeEngine())

    assert TOKEN not in caplog.text
    assert OTHER_TOKEN not in caplog.text


def test_the_log_handle_is_a_digest_prefix_not_the_token():
    # What a log line carries instead of the credential: enough to line two
    # events up against one strategy, useless to anyone who reads it.
    hint = webhook._token_hint(TOKEN)

    assert hint == store.hash_webhook_token(TOKEN)[:12]
    assert TOKEN not in hint
    assert webhook._token_hint(None) == "none"


def test_every_result_label_is_part_of_the_store_vocabulary():
    assert set(webhook.RESULT_STATUS) <= set(store.WEBHOOK_RESULTS)


def test_a_deeply_nested_or_huge_body_cannot_grow_the_audit_row(strategy, audit):
    deep = {"action": "stop"}
    node = deep
    for _ in range(12):
        node["child"] = {}
        node = node["child"]
    node["leaf"] = "bottom"
    deep["many"] = {f"k{i}": i for i in range(500)}
    deep["long"] = "y" * 5000

    outcome = call(body=deep, engine=FakeEngine())
    stored = audit.last.payload

    assert outcome.ok is True
    assert stored["child"]["child"]["child"]["child"]["child"] == "[truncated]"
    assert len(stored["many"]) == 50
    assert len(stored["long"]) == 500


# ---------------------------------------------------------------------------
# Bounded state
# ---------------------------------------------------------------------------


def test_both_windows_are_bounded_ttl_caches():
    assert webhook._dedupe.maxsize == webhook.MAX_TRACKED_KEYS
    assert webhook._cooling_off.maxsize == webhook.MAX_TRACKED_KEYS
    assert webhook._dedupe.ttl == webhook.DEDUPE_WINDOW_SECONDS
    assert webhook._cooling_off.ttl == webhook.COOLING_OFF_SECONDS


def test_the_windows_do_not_grow_without_bound():
    # The worker never restarts, so a scanner hitting many strategies must not
    # be able to turn either window into a leak.
    for strategy_id in range(webhook.MAX_TRACKED_KEYS * 2):
        webhook.note_run_stopped(strategy_id)

    assert len(webhook._cooling_off) <= webhook.MAX_TRACKED_KEYS


def test_reset_state_clears_both_windows(strategy, clock):
    call(engine=FakeEngine())
    webhook.note_run_stopped(strategy.id)

    webhook.reset_state()

    assert len(webhook._dedupe) == 0
    assert len(webhook._cooling_off) == 0
