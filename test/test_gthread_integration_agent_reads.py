"""The agent's read tools reach the service layer through the hub.

The agent runs its tools on a real OS thread. The order tools already hand
their preparation and dispatch to the hub under eventlet; the read tools
(funds, positions, order book, quotes, charts) called the services directly,
and a sandbox read can take the same green locks an order does. A real thread
waiting on a green lock that a greenlet holds is never woken. Every read now
goes through ``OpenAlgoToolkit.service_call``, which uses
``utils.real_threading.run_on_hub``: on the hub under eventlet, inline and
unchanged everywhere else.
"""

import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

pytest.importorskip("agno", reason="the agent's toolkit needs agno")

from agno.exceptions import RetryAgentRun  # noqa: E402

from services.agent.tools import account as account_mod  # noqa: E402
from services.agent.tools import base as base_mod  # noqa: E402
from utils import real_threading  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _toolkit():
    from services.agent.tools import ToolContext

    return account_mod.AccountToolkit(ToolContext(api_key="k"))


def test_off_eventlet_a_read_runs_inline_on_the_callers_thread():
    tk = _toolkit()
    seen = []

    def read(x, *, timeout=None):
        seen.append((threading.get_ident(), x, timeout))
        return True, {"status": "success", "data": x}, 200

    assert tk.service_call(read, 5, timeout=3) == {"status": "success", "data": 5}
    assert seen == [(threading.get_ident(), 5, 3)]


def test_a_read_goes_through_run_on_hub(monkeypatch):
    tk = _toolkit()
    calls = []

    def spy(fn, *args, timeout, **kwargs):
        calls.append(timeout)
        return fn(*args, **kwargs)

    monkeypatch.setattr(real_threading, "run_on_hub", spy)

    payload = tk.service_call(lambda: (True, {"status": "success"}, 200))

    assert payload == {"status": "success"}
    assert calls == [base_mod.AGENT_SERVICE_TIMEOUT_SECONDS]


def test_a_read_the_hub_could_not_take_says_so_plainly(monkeypatch):
    tk = _toolkit()

    def full(fn, *args, timeout, **kwargs):
        raise real_threading.HubQueueFull("busy")

    monkeypatch.setattr(real_threading, "run_on_hub", full)

    with pytest.raises(RetryAgentRun) as caught:
        tk.service_call(lambda: (True, {}, 200))
    assert "too busy" in str(caught.value) and "Nothing was changed" in str(caught.value)


def test_a_service_that_raises_timeout_itself_is_not_reported_as_busy():
    tk = _toolkit()

    def slow_broker():
        raise TimeoutError("broker did not answer")

    with pytest.raises(RetryAgentRun) as caught:
        tk.service_call(slow_broker)
    assert "raised TimeoutError" in str(caught.value)


def test_the_order_status_read_goes_through_the_hub(monkeypatch):
    import services.orderstatus_service as orderstatus

    tk = _toolkit()
    calls = []

    def spy(fn, *args, timeout, **kwargs):
        calls.append(timeout)
        return fn(*args, **kwargs)

    monkeypatch.setattr(real_threading, "run_on_hub", spy)
    monkeypatch.setattr(
        orderstatus,
        "get_order_status",
        lambda data, api_key=None: (False, {"status": "error", "message": "nope"}, 404),
    )

    result = tk.get_order_status("123")

    assert calls == [base_mod.AGENT_SERVICE_TIMEOUT_SECONDS]
    assert "123" in result


# ---------------------------------------------------------------------------
# Under eventlet
# ---------------------------------------------------------------------------

EVENTLET_PREAMBLE = """
import eventlet
eventlet.monkey_patch()

import threading, time

import utils.real_threading as rt
assert rt.start_hub_worker()

from services.agent.tools import account as account_mod

# What the sandbox fund manager's lock is under eventlet: a green RLock.
green_lock = threading.RLock()

from services.agent.tools import ToolContext

tk = account_mod.AccountToolkit(ToolContext(api_key="k"))


def read_funds():
    with green_lock:
        return True, {"status": "success", "data": {"availablecash": "1"}}, 200


def hold_the_lock():
    with green_lock:
        eventlet.sleep(0.3)


ticks = []


def ticker():
    for _ in range(100):
        ticks.append(time.monotonic())
        eventlet.sleep(0.01)


def run_agent_read(wait):
    holder = eventlet.spawn(hold_the_lock)
    eventlet.sleep(0.05)
    result = []
    began = time.monotonic()
    agent = rt.Thread(target=lambda: result.append(tk.service_call(read_funds)), daemon=True)
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


def test_under_eventlet_an_inline_read_from_the_agent_thread_wedges():
    """The defect itself, so the next test cannot pass vacuously."""
    pytest.importorskip(
        "eventlet",
        reason="eventlet is installed by the production installer, not by pyproject",
    )
    result = _run(
        """
        rt.run_on_hub = lambda fn, *a, timeout, **k: fn(*a, **k)
        result, _elapsed = run_agent_read(wait=3.0)
        assert result == [], "an inline read through a green lock completed"
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr[-4000:]


def test_under_eventlet_the_agent_thread_reads_through_the_hub():
    pytest.importorskip(
        "eventlet",
        reason="eventlet is installed by the production installer, not by pyproject",
    )
    result = _run(
        """
        t = eventlet.spawn(ticker)
        result, elapsed = run_agent_read(wait=5.0)
        t.wait()
        assert result and result[0]["status"] == "success", result
        assert elapsed < 2.0, f"the agent read took {elapsed:.2f}s"
        gaps = [b - a for a, b in zip(ticks, ticks[1:])]
        assert max(gaps) < 0.25, f"the hub stalled for {max(gaps):.2f}s"
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr[-4000:]
