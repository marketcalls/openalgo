"""Live accounting for long-lived streams (gthread gate A6-04 / B1).

Under gthread every open SSE stream pins one Gunicorn worker thread for its
whole lifetime, which makes streams the dominant term in the thread budget --
and the term nobody could measure. The plan's sizing formula asks for "active
Python Strategy SSE streams" and "active MCP SSE streams" as inputs; before
this, the first was knowable only by reading a private list and the second was
not knowable at all.
"""

import inspect
import threading
from pathlib import Path

from utils.stream_registry import reset_peaks, stream_counts, track_stream

REPO = Path(__file__).resolve().parent.parent


def _reset():
    # Drain any counts left by other tests, then clear peaks.
    counts = stream_counts()["active"]
    for kind, n in counts.items():
        for _ in range(n):
            with track_stream(kind):
                pass
    reset_peaks()


def test_a_stream_is_counted_for_its_lifetime():
    _reset()
    before = stream_counts()["total_active"]
    with track_stream("probe"):
        assert stream_counts()["active"]["probe"] == 1
        assert stream_counts()["total_active"] == before + 1
    assert stream_counts()["active"]["probe"] == 0


def test_the_count_is_released_when_the_client_disconnects():
    """A disconnecting client raises out of the generator -- that is the common
    exit, not the exceptional one. Miss it and the count only ever rises, which
    is worse than not counting at all."""
    _reset()

    def stream():
        with track_stream("probe"):
            yield "chunk"
            yield "chunk"

    gen = stream()
    next(gen)
    assert stream_counts()["active"]["probe"] == 1

    gen.close()  # what a disconnect does
    assert stream_counts()["active"]["probe"] == 0, "a disconnect leaked a count"


def test_an_exception_inside_the_stream_still_releases():
    _reset()
    try:
        with track_stream("probe"):
            raise RuntimeError("stream blew up")
    except RuntimeError:
        pass
    assert stream_counts()["active"]["probe"] == 0


def test_counts_are_accurate_under_concurrency():
    _reset()
    hold = threading.Event()
    ready = threading.Barrier(13)  # 12 workers + this thread

    def stream(_b=ready):
        with track_stream("probe"):
            _b.wait()
            hold.wait(timeout=3)

    threads = [threading.Thread(target=stream) for _ in range(12)]
    for t in threads:
        t.start()
    ready.wait(timeout=3)

    assert stream_counts()["active"]["probe"] == 12
    hold.set()
    for t in threads:
        t.join()
    assert stream_counts()["active"]["probe"] == 0


def test_peak_is_retained_after_streams_close():
    """Peak is what sizing needs: the budget must cover the worst moment, not
    whatever happens to be open when someone looks."""
    _reset()
    with track_stream("probe"), track_stream("probe"), track_stream("probe"):
        pass
    assert stream_counts()["active"]["probe"] == 0
    assert stream_counts()["peak"]["probe"] == 3


def test_both_sse_endpoints_are_instrumented():
    strategy = (REPO / "blueprints" / "python_strategy.py").read_text(encoding="utf-8")
    mcp = (REPO / "blueprints" / "mcp_http.py").read_text(encoding="utf-8")
    assert 'track_stream("python_strategy_sse")' in strategy
    assert 'track_stream("mcp_sse")' in mcp


def test_instrumentation_wraps_the_generator_not_the_route():
    """The thread is held for as long as the generator lives. Counting at the
    route would record a stream that has already ended, or miss one that has
    not started."""
    strategy = (REPO / "blueprints" / "python_strategy.py").read_text(encoding="utf-8")
    gen_start = strategy.index("def event_stream():")
    gen_body = strategy[gen_start : strategy.index("return Response(", gen_start)]
    assert "track_stream" in gen_body, "counting happens outside the generator"


def test_counts_reach_the_runtime_diagnostics():
    """So an operator can compare live streams against configured_threads
    rather than inferring headroom."""
    from blueprints.admin import _runtime_info

    info = _runtime_info()
    assert "streams" in info
    assert set(info["streams"]) >= {"active", "peak", "total_active", "total_peak"}


def test_diagnostics_never_break_on_a_stream_registry_failure():
    src = inspect.getsource(_runtime_info_source())
    idx = src.index('info["streams"]')
    assert "except Exception" in src[idx - 400 : idx + 400], (
        "a stream-registry failure would break the whole diagnostics endpoint"
    )


def _runtime_info_source():
    from blueprints.admin import _runtime_info

    return _runtime_info
