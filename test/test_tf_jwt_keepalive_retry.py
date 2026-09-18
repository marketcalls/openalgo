"""The two ways TF JWT auto-refresh silently died: a poll budget consumed by
browser setup, and a single failed attempt leaving the token dead for 20 min."""

import importlib.util
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_poll_budget_survives_slow_browser_setup():
    """The deadline must start after launch/goto/login, not before. Previously a
    slow cold start ate the full timeout and the poll loop ran zero times."""
    import inspect

    ta = _load("tf_auth_t", os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "strategies", "tf_auth.py"))
    src = inspect.getsource(ta.refresh_tf_jwt)
    deadline_at = src.index("deadline = time.time() + timeout_s")
    assert deadline_at > src.index("launch_persistent_context"), \
        "poll deadline must be set after the browser is launched"
    assert deadline_at > src.index("_attempt_google_login"), \
        "poll deadline must be set after the login-modal flow"
    assert deadline_at < src.index("while time.time() < deadline")


def test_transient_failure_is_not_abandoned():
    """One miss must not leave the token dead until the next tick.

    What answers the miss changed: headless used to be retried three times, and
    is now tried once because a real logout fails it identically every time. The
    escalation is the headed window, so this asserts the budget rather than a
    literal call count -- that is how it went stale the first time.
    """
    import services.tf_jwt_keepalive_service as svc

    calls = []

    class FakeAuth:
        def _read_file_jwt(self):
            return ""          # no token -> needs refresh

        def jwt_expiry_seconds(self, _):
            return 0.0

        def refresh_tf_jwt(self):
            calls.append(1)
            # fails for every headless attempt the budget allows, then works
            return "token" if len(calls) > svc._MAX_REFRESH_ATTEMPTS else None

    svc._tf_auth = FakeAuth()
    svc._refreshing = False
    svc._RETRY_BACKOFF_SECONDS = 0

    svc.trigger_refresh_if_needed(min_seconds=1800)
    for _ in range(100):                    # refresh runs on a daemon thread
        if not svc._refreshing:
            break
        time.sleep(0.05)

    assert len(calls) == svc._MAX_REFRESH_ATTEMPTS, (
        f"expected {svc._MAX_REFRESH_ATTEMPTS} headless attempt(s), got {len(calls)}"
    )
    assert not svc._refreshing, "the in-flight guard must be cleared"


def test_headed_fallback_runs_after_headless_exhausted():
    """When TradeFinder's own session is logged out, every headless attempt fails
    identically — the retry loop must fall back to one headed (visible) attempt
    rather than just giving up."""
    import services.tf_jwt_keepalive_service as svc

    calls = []

    class FakeAuth:
        def _read_file_jwt(self):
            return ""

        def jwt_expiry_seconds(self, _):
            return 0.0

        def refresh_tf_jwt(self, headless=True, timeout_s=60):
            calls.append(headless)
            return "token" if headless is False else None   # headless never works here

    svc._tf_auth = FakeAuth()
    svc._refreshing = False
    svc._RETRY_BACKOFF_SECONDS = 0
    svc._HEADED_LOGIN_TIMEOUT_SECONDS = 0

    svc.trigger_refresh_if_needed(min_seconds=1800)
    for _ in range(100):
        if not svc._refreshing:
            break
        time.sleep(0.05)

    expected = [True] * svc._MAX_REFRESH_ATTEMPTS + [False]
    assert calls == expected, (
        f"expected {svc._MAX_REFRESH_ATTEMPTS} headless miss(es) then a headed "
        f"fallback, got {calls}"
    )
    assert not svc._refreshing


if __name__ == "__main__":
    test_poll_budget_survives_slow_browser_setup()
    test_transient_failure_is_retried_not_abandoned()
    test_headed_fallback_runs_after_headless_exhausted()
    print("ok")
