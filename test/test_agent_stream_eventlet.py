"""The agent stream must not stop the eventlet hub while a model is thinking.

`services/agent/stream.py` exists for one reason: agno's `agent.run(stream=True)`
returns an iterator whose next event blocks on the provider's socket, inside
LiteLLM's C-served TLS reads, and on every tool it calls. Production is
`gunicorn --worker-class eventlet -w 1`, so a greenlet that blocks there stops
every other request on the box for as long as the model thinks -- typically tens
of seconds for a reasoning model, and the whole run for a tool-heavy one.

The fix is the crossing: the run is driven on a real OS thread from
`utils.real_threading` and the frames come back over a real queue, which the
greenlet drains with `get_nowait()` and never with a blocking `get()`.

None of that can be checked on the dev server. `uv run app.py` patches nothing,
so a blocking `get()` on a green queue and a `get_nowait()` on a real one behave
identically there and every assertion about return values passes either way.
So these cases run under a real eventlet hub and assert on **elapsed time and
hub liveness**, not on what came back.

`eventlet.monkey_patch()` is global and cannot be undone, so each case runs in a
subprocess: importing it into the pytest process would change the meaning of
every test that ran after it. That is the same shape as
`test/test_eventlet_cross_thread_locks.py`, and the first case here asserts the
defect itself so the rest cannot pass vacuously.

**No provider is called.** The model is a stand-in whose iterator blocks with
the *unpatched* `time.sleep`, which is what a socket read inside C looks like to
the hub. See `docs/design/55-agent/README.md`: a test never calls a real one.
"""

import subprocess
import sys
import textwrap

import pytest

pytest.importorskip(
    "eventlet",
    reason="eventlet is installed by the production installer, not by pyproject",
)

PREAMBLE = '''
import eventlet
eventlet.monkey_patch()

import queue
import threading
import time

import eventlet.patcher

# The unpatched originals. `_real_sleep` is how a blocking C-served read looks
# to the hub: it does not yield, it does not fire timers, it just stops.
_orig_time = eventlet.patcher.original("time")
_orig_threading = eventlet.patcher.original("threading")
_real_sleep = _orig_time.sleep

MODEL_THINKS_FOR = 0.6
TICK = 0.02


class Event:
    """A stand-in agno run event. Read by attribute, exactly as agno's are."""

    def __init__(self, event, **fields):
        self.event = event
        self.run_id = fields.pop("run_id", "run-1")
        self.session_id = fields.pop("session_id", "sess-1")
        for name, value in fields.items():
            setattr(self, name, value)

    def __getattr__(self, name):
        return None


class Metrics:
    def __init__(self, **fields):
        self.__dict__.update(fields)

    def __getattr__(self, name):
        return None


class BlockingAgent:
    """An agent whose run blocks the way a real provider call does.

    The first event costs `MODEL_THINKS_FOR` seconds of *real*, non-yielding
    sleep, which is the wait the crossing has to survive. Tokens follow, then a
    completion carrying metrics.
    """

    def __init__(self, thinks_for=MODEL_THINKS_FOR, tokens=("he", "llo", " there")):
        self.thinks_for = thinks_for
        self.tokens = tokens
        self.cancelled = []
        self.db = None
        self.iterator_closed = False
        self.thread_names = []

    def run(self, message, **kwargs):
        agent = self

        def gen():
            agent.thread_names.append(threading.current_thread().name)
            try:
                # The model thinking. Real sleep: a greenlet doing this stops
                # the hub, a real OS thread doing it does not.
                _real_sleep(agent.thinks_for)
                yield Event("RunStarted")
                for chunk in agent.tokens:
                    _real_sleep(0.02)
                    yield Event("RunContent", content=chunk)
                yield Event(
                    "RunCompleted",
                    metrics=Metrics(input_tokens=11, output_tokens=3, total_tokens=14),
                )
            except GeneratorExit:
                agent.iterator_closed = True
                raise

        return gen()

    def cancel_run(self, run_id):
        self.cancelled.append(run_id)


class HangingAgent(BlockingAgent):
    """Never finishes on its own. Only a cancel or the stop flag ends it."""

    def run(self, message, **kwargs):
        agent = self

        def gen():
            yield Event("RunStarted")
            yield Event("RunContent", content="working")
            while True:
                _real_sleep(0.05)
                yield Event("RunContent", content=".")

        return gen()


def hub_ticker():
    """Spawn a greenlet that counts how often the hub gets to run it."""
    ticks = []

    def loop():
        while True:
            ticks.append(1)
            eventlet.sleep(TICK)

    return eventlet.spawn(loop), ticks
'''


def run(body: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", PREAMBLE + textwrap.dedent(body)],
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_driving_the_run_on_the_greenlet_freezes_the_hub():
    """The defect itself, so nothing below can pass vacuously.

    Consuming agno's iterator inline is the obvious implementation and it is
    the one that stops the worker. Measured here rather than argued: while the
    stand-in model thinks, the hub gets to run nothing at all.
    """
    result = run(
        """
        g, ticks = hub_ticker()
        eventlet.sleep(0.1)

        agent = BlockingAgent()
        before, t0 = len(ticks), time.monotonic()
        events = list(agent.run("hi"))          # the naive version
        took, during = time.monotonic() - t0, len(ticks) - before
        g.kill()

        assert len(events) == 5, events
        assert took >= MODEL_THINKS_FOR, took
        # The hub had MODEL_THINKS_FOR/TICK == 30 chances to run and took none.
        assert during <= 1, (
            f"expected the hub to be frozen by an inline drive, got {during} ticks "
            f"in {took:.2f}s; eventlet may no longer patch time.sleep, which "
            f"would make this whole file moot"
        )
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr + result.stdout


def test_stream_run_keeps_the_hub_alive_while_the_model_is_in_flight():
    """The property the module exists for.

    Same stand-in model, same blocking iterator, driven through `stream_run`.
    The hub must keep running throughout, and the stream must still deliver
    every frame in order and finish in about the time the model took rather
    than in that time plus a poll interval per frame.
    """
    result = run(
        """
        import json
        from services.agent import stream as agent_stream
        from services.agent import catalog

        # Warm the price table before the clock starts. The first estimate_cost
        # of a process imports litellm and walks its 3517-entry cost table, and
        # that costs about two seconds once; timing it here would measure the
        # import rather than the crossing. It happens on the producer thread in
        # this path, so it never reaches the hub -- unlike the /catalog and
        # /models/<id>/test routes, which build it from a greenlet.
        catalog.estimate_cost("openai/gpt-4o-mini", input_tokens=1, output_tokens=1)

        g, ticks = hub_ticker()
        eventlet.sleep(0.1)

        agent = BlockingAgent()
        before, t0 = len(ticks), time.monotonic()

        chunks = []
        for chunk in agent_stream.stream_run(
            agent, "hi", conversation_id=1, session_id="sess-1", model="openai/gpt-4o-mini"
        ):
            chunks.append(chunk)
            # Measured at the moment the first frame lands, which is while the
            # producer is still running: a check taken only at the end could be
            # satisfied by a hub that woke up after the run finished.
            if len(chunks) == 2:
                mid_ticks = len(ticks) - before

        took, during = time.monotonic() - t0, len(ticks) - before
        g.kill()

        frames = [json.loads(c[6:-2]) for c in chunks if c.startswith("data: ")]
        order = [f["type"] for f in frames]
        assert order == ["start", "token", "token", "token", "usage", "done"], order
        assert frames[-1]["reason"] == "stop", frames[-1]
        assert "".join(f["delta"] for f in frames if f["type"] == "token") == "hello there"

        # The run really did happen on a real OS thread, not on a greenlet.
        assert agent.thread_names and agent.thread_names[0].startswith("agent-"), (
            f"the run did not happen on the agent thread: {agent.thread_names}"
        )

        # Liveness. MODEL_THINKS_FOR/TICK == 30 opportunities; anything above a
        # handful proves the hub was scheduling other work throughout.
        assert during > 15, f"the hub only ran {during} times in {took:.2f}s"
        assert mid_ticks > 15, (
            f"the hub only ran {mid_ticks} times before the first frame landed, so it "
            f"was frozen while the model was actually in flight"
        )
        # And the crossing did not cost the answer its latency: the whole
        # stream is the model's own wait plus a poll interval or two, not that
        # wait plus DRAIN_POLL_SECONDS per frame.
        model_took = MODEL_THINKS_FOR + 0.02 * 3
        assert took < model_took + 0.5, f"stream took {took:.2f}s for a {model_took:.2f}s model"
        print(f"OK ticks={during} mid={mid_ticks} took={took:.2f}s model={model_took:.2f}s")
        """
    )
    assert "OK" in result.stdout, result.stderr + result.stdout


def test_the_queue_and_thread_are_the_unpatched_originals():
    """Guards the specific types, so an edit back to a green queue or a green
    thread fails here rather than in production, where the symptom is a worker
    that stops answering for the length of every model call."""
    result = run(
        """
        from utils import real_threading as rt

        green_queue = type(queue.Queue())
        green_thread = threading.Thread

        assert rt.Queue is not green_queue, (
            "real_threading.Queue is the green one; a real thread's put() would "
            "never wake the greenlet waiting on it"
        )
        assert rt.Thread is not green_thread, (
            "real_threading.Thread is green, so the run would be a greenlet and "
            "would block the hub exactly as the inline version does"
        )
        # `Empty` is the one thing eventlet leaves alone: it is a plain
        # exception class with no waiting in it, and the green queue raises the
        # very same object, so the green side's except clause catches both.
        assert rt.Empty is queue.Empty

        # And stream.py takes them from there rather than from the stdlib.
        from services.agent import stream as agent_stream
        assert agent_stream.real_threading is rt
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr + result.stdout


def test_a_client_disconnect_cancels_the_run_and_reaps_the_thread():
    """A dropped connection must not leave a thread billing tokens.

    The worker never restarts, so a thread leaked per abandoned request
    accumulates for the life of the process. Closing the generator is what
    Flask does when the client hangs up.
    """
    result = run(
        """
        from services.agent import stream as agent_stream

        agent = HangingAgent()
        before = set(_orig_threading.enumerate())

        gen = agent_stream.stream_run(agent, "hi", conversation_id=1, session_id="s")
        next(gen)                       # the head flush
        next(gen)                       # the start frame: the run is live now

        live = [t for t in _orig_threading.enumerate()
                if t.name.startswith("agent-") and t not in before]
        assert live, "no real agent thread was started"

        t0 = time.monotonic()
        gen.close()                     # what Flask does on GeneratorExit
        took = time.monotonic() - t0

        assert agent.cancelled == ["run-1"], (
            f"the run was not cancelled on disconnect: {agent.cancelled}"
        )
        assert took < agent_stream.JOIN_TIMEOUT_SECONDS, (
            f"close() took {took:.2f}s, so the join did not reap the thread"
        )
        for _ in range(100):
            leftover = [t for t in _orig_threading.enumerate()
                        if t.name.startswith("agent-") and t.is_alive()]
            if not leftover:
                break
            eventlet.sleep(0.02)
        assert not leftover, f"agent threads outlived the stream: {leftover}"
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr + result.stdout


def test_cancelling_never_takes_agnos_green_lock_from_the_hub():
    """`agent.cancel_run` writes a dict agno guards with a lock built after
    monkey-patching, so that lock is green and the real run thread takes it on
    every cancellation check. A greenlet contending on it is the
    `greenlet.error: Cannot switch to a different thread` crossing CLAUDE.md
    documents. `request_cancel` hands the write to a throwaway real thread, so
    this asserts which world made the call rather than that it happened."""
    result = run(
        """
        from services.agent import stream as agent_stream

        seen = {}

        class Recorder:
            def cancel_run(self, run_id):
                seen["thread"] = threading.current_thread()
                seen["is_main"] = seen["thread"] is threading.main_thread()

        agent_stream.request_cancel(Recorder(), "run-9")

        assert "thread" in seen, "cancel_run was never called"
        assert not seen["is_main"], (
            "cancel_run ran on the greenlet's own thread, so the hub touched "
            "agno's green cancellation lock"
        )
        assert seen["thread"].name.startswith("agent-cancel-"), seen["thread"].name
        # And an empty run id is a no-op rather than a thread.
        agent_stream.request_cancel(Recorder(), "")
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr + result.stdout
