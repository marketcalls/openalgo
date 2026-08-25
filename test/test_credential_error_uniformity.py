"""Every endpoint must give the same answer for the same credential failure.

``database.auth_db.get_auth_token_broker()`` answers ``(None, None)`` for four
different situations: an unrecognised API key, a revoked token, a broker that
was never connected, and a session that belongs to a previous trading session
(issue #1858). Only the first is a problem with the API key.

Before this change each of the ~39 consumers made that call and reported
"Invalid openalgo apikey", so the daily rollover told operators to regenerate a
key that was fine -- and the replacement key failed identically, because the
verdict never came from the key. ``utils.credential_errors.credential_error()``
decides once, and these tests pin that every caller inherits it.

The static test is the one that matters over time: it fails for a service added
next year that copies the old two-case shape.
"""

import glob
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# restx_api must be imported first. services/place_order_service.py:8 imports
# restx_api.schemas, whose package __init__ pulls in options_multiorder, which
# imports place_order_service back: importing place_order_service directly hits
# that cycle half-built. Importing the package first lets it complete.
import restx_api  # noqa: E402,F401
import services.place_order_service as place_order_service  # noqa: E402
import utils.credential_errors as credential_errors  # noqa: E402
from utils.credential_errors import credential_error  # noqa: E402

TEST_USER = "test_trader"
TEST_API_KEY = "test-api-key"

# These four never call a broker, so they must not resolve a credential at all:
# ping returns pong, symbol reads the local SymToken table, intervals reads a
# static per-broker map, and the analyzer endpoints drive the sandbox.
NO_BROKER_SERVICES = {
    "services/ping_service.py",
    "services/symbol_service.py",
    "services/intervals_service.py",
    "services/analyzer_service.py",
}


class TestTheDecisionItself:
    """credential_error() is the single place that tells the two apart."""

    def test_valid_key_means_the_broker_session_is_at_fault(self, monkeypatch):
        monkeypatch.setattr(credential_errors, "verify_api_key", lambda key: TEST_USER)

        payload, status = credential_error(TEST_API_KEY)

        assert status == 401
        assert payload["code"] == "BROKER_SESSION_EXPIRED"
        assert "reconnect your broker" in payload["message"]

    def test_unrecognised_key_keeps_its_403(self, monkeypatch):
        monkeypatch.setattr(credential_errors, "verify_api_key", lambda key: None)

        payload, status = credential_error("not-a-real-key")

        assert status == 403
        assert payload["message"] == "Invalid openalgo apikey"
        assert "code" not in payload

    def test_the_answer_does_not_depend_on_session_rows(self, monkeypatch):
        """The verdict must not evaporate once the expiry sweep clears sessions.

        An earlier revision asked the freshness inference here, which answers
        "unknown" for an empty active_sessions. Once the sweep ran, the honest
        401 silently reverted to the misleading 403 while the docs still told
        the reader to re-issue their API key. Deriving it from the API key alone
        is what makes the answer stable.
        """
        monkeypatch.setattr(credential_errors, "verify_api_key", lambda key: TEST_USER)
        import database.auth_db as auth_db

        monkeypatch.setattr(auth_db, "get_active_sessions", lambda user: [])

        _, status = credential_error(TEST_API_KEY)

        assert status == 401


class TestEveryConsumerInherits:
    """The habit the review asked for, enforced by a test rather than a grep."""

    def test_no_service_hand_rolls_the_credential_answer(self):
        """A service that resolves a credential must route its failure through
        credential_error(), so the next one added inherits the behaviour."""
        offenders = []
        for path in sorted(glob.glob("services/*.py")):
            if path in NO_BROKER_SERVICES:
                continue
            src = open(path, encoding="utf-8").read()
            if "get_auth_token_broker(" not in src:
                continue
            if re.search(r'"message": "Invalid openalgo apikey"', src):
                offenders.append(path)

        assert offenders == [], (
            "these services resolve a broker credential but still report every "
            "failure as a bad API key; route them through credential_error(): "
            f"{offenders}"
        )

    def test_endpoints_that_never_call_a_broker_do_not_resolve_one(self):
        """ping, symbol, intervals and analyzer must not be gated on a live
        broker session. /api/v1/ping is the canonical health check, so gating it
        turns the 03:00 rollover into a monitoring outage."""
        offenders = [
            path
            for path in sorted(NO_BROKER_SERVICES)
            if re.search(r"^\s*\w+.*=\s*get_auth_token_broker\(", open(path, encoding="utf-8").read(), re.M)
        ]

        assert offenders == [], (
            f"these endpoints never call a broker and must resolve identity "
            f"(verify_api_key + get_broker_name) instead: {offenders}"
        )


@pytest.mark.parametrize(
    "module_name,func_name",
    [
        ("services.funds_service", "get_funds"),
        ("services.holdings_service", "get_holdings"),
        ("services.orderbook_service", "get_orderbook"),
        ("services.tradebook_service", "get_tradebook"),
        ("services.positionbook_service", "get_positionbook"),
    ],
)
class TestRepresentativeEndpoints:
    """A sample of the previously-unpatched majority, exercised end to end."""

    def test_stale_session_answers_401(self, module_name, func_name, monkeypatch):
        import importlib

        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, "get_auth_token_broker", lambda *a, **k: (None, None))
        monkeypatch.setattr(credential_errors, "verify_api_key", lambda key: TEST_USER)

        success, response, status = getattr(module, func_name)(api_key=TEST_API_KEY)

        assert success is False
        assert status == 401, f"{module_name} still blames the API key"
        assert response["code"] == "BROKER_SESSION_EXPIRED"

    def test_bad_key_still_answers_403(self, module_name, func_name, monkeypatch):
        import importlib

        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, "get_auth_token_broker", lambda *a, **k: (None, None))
        monkeypatch.setattr(credential_errors, "verify_api_key", lambda key: None)

        success, response, status = getattr(module, func_name)(api_key="not-a-real-key")

        assert success is False
        assert status == 403
        assert "code" not in response


class TestNoBrokerEndpointsKeepWorking:
    """The rollover must not take these down. This is lost functionality, not a
    labelling problem: a 401 would be just as wrong as the 403 was."""

    def test_ping_answers_pong_after_the_rollover(self, monkeypatch):
        """/api/v1/ping is the canonical health check. External monitoring would
        otherwise report an outage every morning after 03:00 IST."""
        import database.auth_db as auth_db
        import services.ping_service as ping_service

        monkeypatch.setattr(ping_service, "verify_api_key", lambda key: TEST_USER)
        monkeypatch.setattr(ping_service, "get_broker_name", lambda key: "zerodha")
        # A confirmed-stale broker session, which must be irrelevant here.
        monkeypatch.setattr(auth_db, "is_broker_session_stale_for_user", lambda u: True)

        success, response, status = ping_service.get_ping(api_key=TEST_API_KEY)

        assert success is True
        assert status == 200
        assert response["data"]["message"] == "pong"

    def test_ping_still_rejects_a_bad_key(self, monkeypatch):
        import services.ping_service as ping_service

        monkeypatch.setattr(ping_service, "verify_api_key", lambda key: None)

        success, response, status = ping_service.get_ping(api_key="not-a-real-key")

        assert success is False
        assert status == 403
        assert response["message"] == "Invalid openalgo apikey"


class TestSandboxIsNotCoupledToTheBroker:
    """CLAUDE.md documents the sandbox engine as fully isolated from live
    trading. Resolving a live credential before the analyze-mode branch coupled
    the two, so the daily rollover rejected sandbox orders that never reach a
    broker."""

    def test_analyze_mode_never_resolves_a_credential(self, monkeypatch):
        """The functional proof: with analyze mode on, the order must reach the
        sandbox without the resolver being consulted at all."""
        monkeypatch.setattr(place_order_service, "get_analyze_mode", lambda: True)

        def fail_if_called(*args, **kwargs):
            raise AssertionError(
                "analyze mode must not resolve a live broker credential; the "
                "sandbox never talks to the broker"
            )

        monkeypatch.setattr(place_order_service, "get_auth_token_broker", fail_if_called)
        reached = {}
        monkeypatch.setattr(
            place_order_service,
            "place_order_with_auth",
            lambda *a, **k: reached.setdefault("yes", True)
            and (True, {"status": "success", "mode": "analyze"}, 200),
        )

        order = {
            "symbol": "SBIN",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": "1",
            "pricetype": "MARKET",
            "product": "MIS",
            "strategy": "test",
            "apikey": TEST_API_KEY,
        }

        success, response, status = place_order_service.place_order(
            order, api_key=TEST_API_KEY, emit_event=False
        )

        assert reached.get("yes") is True, "the sandbox path was never reached"
        assert success is True
        assert status == 200

    def test_analyze_mode_is_checked_before_the_credential(self):
        """Belt and braces: the ordering itself, so a refactor that reintroduces
        the coupling fails even if the functional test is skipped."""
        src = open("services/place_order_service.py", encoding="utf-8").read()
        case_one = src[src.index("    # Case 1: API-based authentication") :]
        case_one = case_one[: case_one.index("    # Case 2:")]

        analyze_at = case_one.find("if get_analyze_mode():")
        resolve_at = case_one.find("get_auth_token_broker(")

        assert analyze_at != -1 and resolve_at != -1
        assert analyze_at < resolve_at, (
            "the sandbox branch must come first; otherwise a rolled-over broker "
            "session blocks a sandbox order that never touches the broker"
        )
