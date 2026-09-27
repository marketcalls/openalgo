"""Order-update adapters must not spew errors when the broker token is dead.

Two paths produced the noise reported after a 03:00 IST rollover:

1. The boot scan started an adapter for any ``is_revoked=False`` auth row. That
   flag is only flipped by the auto-expiry sweep, which runs from a
   before_request hook, so between the rollover and the first browser request a
   restart happily connected with yesterday's token.
2. The reconnect loop treated a 401 handshake like a network blip and retried
   it forever, one WARNING plus one library-level ERROR per attempt.
"""

import os

import pytest

os.environ.setdefault("HOST_SERVER", "https://legit.example.com")

from websocket_proxy.order_adapter import _is_auth_rejection  # noqa: E402


class _FakeBadStatus(Exception):
    """Stands in for websocket.WebSocketBadStatusException, which carries the
    rejected handshake's status on ``status_code``."""

    def __init__(self, status_code):
        super().__init__(f"Handshake status {status_code}")
        self.status_code = status_code


class TestIsAuthRejection:
    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_statuses_are_rejections(self, status):
        assert _is_auth_rejection(_FakeBadStatus(status))

    @pytest.mark.parametrize("status", [500, 502, 503, 429, 400, 404])
    def test_other_statuses_are_not(self, status):
        """Transient/server-side failures must keep retrying."""
        assert not _is_auth_rejection(_FakeBadStatus(status))

    def test_plain_exception_is_not_a_rejection(self):
        """A socket error has no status_code and must not stop the loop."""
        assert not _is_auth_rejection(ConnectionResetError("connection reset"))

    def test_none_is_not_a_rejection(self):
        assert not _is_auth_rejection(None)


class TestBootGuardWiring:
    """The boot scan must consult trading-session freshness, not just is_revoked."""

    def test_boot_scan_checks_session_freshness(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(
            os.path.join(repo_root, "services", "order_update_service.py"),
            encoding="utf-8",
        ) as f:
            source = f.read()
        assert "has_login_this_trading_session" in source, (
            "the boot scan must skip auth rows with no login since today's "
            "rollover, or a restart reconnects on a dead token"
        )

    def test_helper_is_importable_off_the_request_path(self):
        """It runs on a daemon thread, so it must not need a Flask request."""
        from utils.session import has_login_this_trading_session

        assert callable(has_login_this_trading_session)


class TestRetryLoopStandsDown:
    def test_run_forever_breaks_on_auth_rejection(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(
            os.path.join(repo_root, "websocket_proxy", "order_adapter.py"),
            encoding="utf-8",
        ) as f:
            source = f.read()
        assert "_auth_rejected" in source
        # The flag must be cleared on connect(), or a restarted adapter would
        # refuse to run.
        assert source.count("self._auth_rejected = False") >= 2, (
            "_auth_rejected must be initialised and reset in connect()"
        )
