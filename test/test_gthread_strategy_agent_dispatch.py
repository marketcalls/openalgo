"""The agent's order tools reach the service layer through the hub.

The agent runs its tools on a real OS thread. Under the eventlet worker the
service layer is not safe to call from one: a sandbox order takes green locks
(the fund manager's, the execution engine's), and a real thread that waits on
one while a greenlet holds it is left blocked forever, holding its place in the
waiter queue. ``OrdersToolkit._run_mutation`` now runs its preparation and its
dispatch through ``utils.real_threading.run_on_hub``, which runs them on the
hub under eventlet and calls them inline everywhere else, so the gthread
worker and the development server behave exactly as before.
"""

import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("agno", reason="the agent's toolkit needs agno")

from services.agent.tools import orders as orders_mod  # noqa: E402
from utils import real_threading  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class _Guard:
    def __init__(self):
        self.released = 0
        self.committed = 0

    def release(self, verdict):
        self.released += 1
        return True

    def commit(self, verdict):
        self.committed += 1
        return True


def _verdict():
    return SimpleNamespace(
        allowed=True, code="ok", as_dict=lambda: {"code": "ok"}, as_message=lambda: ""
    )


@pytest.fixture
def toolkit(monkeypatch):
    """An OrdersToolkit with the audit, guard and result plumbing stubbed."""
    tk = orders_mod.OrdersToolkit.__new__(orders_mod.OrdersToolkit)
    guard = _Guard()
    audits = []
    monkeypatch.setattr(orders_mod, "_order_services_warmed", True)
    tk.audit_attempt = lambda tool, args: 1
    tk.audit_result = lambda tool, **kwargs: audits.append(kwargs)
    tk._emit = lambda tool, payload, **attrs: dict(payload)
    tk._guard = lambda: guard
    tk.unwrap_service_result = lambda raw, label="": raw
    tk.extract_order_ids = lambda payload: [payload.get("orderid")] if payload else []
    tk.guard = guard
    tk.audits = audits
    return tk


def _plan(dispatch):
    return lambda: orders_mod._Plan(verdict=_verdict(), dispatch=dispatch, label="place_order")


def test_preparation_and_dispatch_both_go_through_run_on_hub(toolkit, monkeypatch):
    calls = []
    real = real_threading.run_on_hub

    def spy(fn, *args, timeout, **kwargs):
        calls.append(timeout)
        return real(fn, *args, timeout=timeout, **kwargs)

    monkeypatch.setattr(orders_mod.real_threading, "run_on_hub", spy)

    result = toolkit._run_mutation("place_order", {}, _plan(lambda: {"orderid": "A1"}))

    assert result["ok"] is True and result["order_ids"] == ["A1"]
    assert calls == [
        orders_mod.AGENT_PREPARE_TIMEOUT_SECONDS,
        orders_mod.AGENT_DISPATCH_TIMEOUT_SECONDS,
    ]
    assert toolkit.guard.committed == 1


def test_a_call_the_hub_could_not_take_was_not_sent_and_gives_the_claim_back(toolkit, monkeypatch):
    real = real_threading.run_on_hub
    dispatched = []

    def refuse_dispatch(fn, *args, timeout, **kwargs):
        if timeout == orders_mod.AGENT_DISPATCH_TIMEOUT_SECONDS:
            raise real_threading.HubQueueFull("busy")
        return real(fn, *args, timeout=timeout, **kwargs)

    monkeypatch.setattr(orders_mod.real_threading, "run_on_hub", refuse_dispatch)

    result = toolkit._run_mutation("place_order", {}, _plan(lambda: dispatched.append(1)))

    assert dispatched == []
    assert result["ok"] is False and result["status"] == "error"
    assert "nothing was sent" in result["message"]
    assert toolkit.guard.released == 1


def test_a_dispatch_that_outlives_its_wait_is_reported_as_unknown(toolkit, monkeypatch):
    real = real_threading.run_on_hub

    def time_out_dispatch(fn, *args, timeout, **kwargs):
        if timeout == orders_mod.AGENT_DISPATCH_TIMEOUT_SECONDS:
            raise TimeoutError("the call did not finish on the hub")
        return real(fn, *args, timeout=timeout, **kwargs)

    monkeypatch.setattr(orders_mod.real_threading, "run_on_hub", time_out_dispatch)

    result = toolkit._run_mutation("place_order", {}, _plan(lambda: {"orderid": "A1"}))

    assert result["status"] == "unknown"
    assert "do NOT send it again" in result["message"]
    # The claim is kept, so the duplicate window refuses an immediate resend.
    assert toolkit.guard.released == 0 and toolkit.guard.committed == 0


# ---------------------------------------------------------------------------
# Under eventlet
# ---------------------------------------------------------------------------

EVENTLET_PREAMBLE = """
import eventlet
eventlet.monkey_patch()

import threading, time
from types import SimpleNamespace

import utils.real_threading as rt
assert rt.start_hub_worker()

from services.agent.tools import orders as orders_mod

orders_mod._order_services_warmed = True

# What FundManager._lock is under eventlet: a green RLock.
green_lock = threading.RLock()


class Guard:
    def release(self, verdict):
        return True

    def commit(self, verdict):
        return True


guard = Guard()
tk = orders_mod.OrdersToolkit.__new__(orders_mod.OrdersToolkit)
tk.audit_attempt = lambda tool, args: 1
tk.audit_result = lambda tool, **kwargs: None
tk._emit = lambda tool, payload, **attrs: dict(payload)
tk._guard = lambda: guard
tk.unwrap_service_result = lambda raw, label="": raw
tk.extract_order_ids = lambda payload: []
verdict = SimpleNamespace(allowed=True, code="ok", as_dict=lambda: {}, as_message=lambda: "")


def dispatch():
    with green_lock:
        return {"status": "success"}


def plan_factory():
    with green_lock:
        return orders_mod._Plan(verdict=verdict, dispatch=dispatch, label="place_order")


def hold_the_lock():
    with green_lock:
        eventlet.sleep(0.3)


ticks = []


def ticker():
    for _ in range(100):
        ticks.append(time.monotonic())
        eventlet.sleep(0.01)


def run_agent_call(wait):
    holder = eventlet.spawn(hold_the_lock)
    eventlet.sleep(0.05)
    result = []
    began = time.monotonic()
    agent = rt.Thread(
        target=lambda: result.append(tk._run_mutation("place_order", {}, plan_factory)),
        daemon=True,
    )
    agent.start()
    rt.join(agent, timeout=wait)
    holder.wait()
    return result, time.monotonic() - began
"""


def _run(body):
    return subprocess.run(
        [sys.executable, "-c", EVENTLET_PREAMBLE + textwrap.dedent(body)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
    )


def test_under_eventlet_an_inline_call_from_the_agent_thread_wedges():
    """The defect itself, so the next test cannot pass vacuously."""
    pytest.importorskip(
        "eventlet",
        reason="eventlet is installed by the production installer, not by pyproject",
    )
    result = _run(
        """
        orders_mod.real_threading.run_on_hub = lambda fn, *a, timeout, **k: fn(*a, **k)
        result, _elapsed = run_agent_call(wait=3.0)
        assert result == [], "an inline call through a green lock completed"
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr[-4000:]


def test_under_eventlet_the_agent_thread_places_through_the_hub():
    pytest.importorskip(
        "eventlet",
        reason="eventlet is installed by the production installer, not by pyproject",
    )
    result = _run(
        """
        t = eventlet.spawn(ticker)
        result, elapsed = run_agent_call(wait=5.0)
        t.wait()
        assert result and result[0]["status"] == "success", result
        assert elapsed < 2.0, f"the agent call took {elapsed:.2f}s"
        gaps = [b - a for a, b in zip(ticks, ticks[1:])]
        assert max(gaps) < 0.25, f"the hub stalled for {max(gaps):.2f}s"
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr[-4000:]
