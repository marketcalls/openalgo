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
from pathlib import PurePosixPath

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

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
#
# Held as forward-slash keys and compared through service_key(), because glob()
# yields "services\\ping_service.py" on Windows: a raw membership test never matches
# there and reports three of them as offenders, which CI cannot see on ubuntu.
NO_BROKER_SERVICES = {
    "services/ping_service.py",
    "services/symbol_service.py",
    "services/intervals_service.py",
    "services/analyzer_service.py",
}


def service_key(path):
    """The forward-slash key NO_BROKER_SERVICES is written in.

    glob() yields "services\\ping_service.py" on Windows, so a raw membership
    test never matches there. Separators are normalised before the split rather
    than left to PurePath, which resolves to PurePosixPath on Linux and would
    keep the backslashes -- that makes the rule the same on every platform, and
    testable on the ubuntu runner where the bug is otherwise invisible.
    """
    return "services/" + PurePosixPath(path.replace("\\", "/")).name


# Every entry point with a sandbox branch inside its *_with_auth function. The
# review asked for this decided explicitly rather than left as an undeclared
# partial: placeorder was fixed first, and these are the rest.
SANDBOX_SERVICE_FILES = [
    "services/place_order_service.py",
    "services/place_smart_order_service.py",
    "services/basket_order_service.py",
    "services/split_order_service.py",
    "services/modify_order_service.py",
    "services/cancel_order_service.py",
    "services/cancel_all_order_service.py",
    "services/close_position_service.py",
    "services/orderbook_service.py",
    "services/positionbook_service.py",
    "services/tradebook_service.py",
    "services/holdings_service.py",
    "services/funds_service.py",
]

_ORDER = {
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": "1",
    "pricetype": "MARKET",
    "product": "MIS",
    "strategy": "test",
}

# (module, entry function, the *_with_auth it must reach, positional args)
SANDBOX_CALLS = [
    (
        "services.place_smart_order_service",
        "place_smart_order",
        "place_smart_order_with_auth",
        (dict(_ORDER, position_size="0"),),
    ),
    (
        "services.basket_order_service",
        "place_basket_order",
        "process_basket_order_with_auth",
        ({"strategy": "test", "orders": [dict(_ORDER)]},),
    ),
    (
        "services.split_order_service",
        "split_order",
        "split_order_with_auth",
        (dict(_ORDER, quantity="10", splitsize="5"),),
    ),
    (
        "services.modify_order_service",
        "modify_order",
        "modify_order_with_auth",
        (dict(_ORDER, orderid="1", price="100", trigger_price="0", disclosed_quantity="0"),),
    ),
    ("services.cancel_order_service", "cancel_order", "cancel_order_with_auth", ("1",)),
    (
        "services.cancel_all_order_service",
        "cancel_all_orders",
        "cancel_all_orders_with_auth",
        ({"strategy": "test"},),
    ),
    (
        "services.close_position_service",
        "close_position",
        "close_position_with_auth",
        ({"strategy": "test"},),
    ),
    ("services.orderbook_service", "get_orderbook", "get_orderbook_with_auth", ()),
    ("services.positionbook_service", "get_positionbook", "get_positionbook_with_auth", ()),
    ("services.tradebook_service", "get_tradebook", "get_tradebook_with_auth", ()),
    ("services.holdings_service", "get_holdings", "get_holdings_with_auth", ()),
    ("services.funds_service", "get_funds", "get_funds_with_auth", ()),
]


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
        service_files = sorted(glob.glob(os.path.join(REPO_ROOT, "services", "*.py")))
        assert service_files, "no service modules found; this test would pass vacuously"

        offenders = []
        for full_path in service_files:
            path = service_key(full_path)
            if path in NO_BROKER_SERVICES:
                continue
            src = open(full_path, encoding="utf-8").read()
            if "get_auth_token_broker(" not in src:
                continue
            if re.search(r'"message": "Invalid openalgo apikey"', src):
                offenders.append(path)

        assert offenders == [], (
            "these services resolve a broker credential but still report every "
            "failure as a bad API key; route them through credential_error(): "
            f"{offenders}"
        )

    def test_the_skip_set_matches_windows_paths(self):
        """The skip above is a set membership test, and glob() uses the native
        separator. With a raw comparison the set never matched on Windows, so
        ping, symbol and intervals were all reported as offenders -- they name
        get_auth_token_broker() in a comment and carry the 403 string. CI is
        ubuntu-only, so the failure was invisible there."""
        assert service_key(r"C:\repo\services\ping_service.py") in NO_BROKER_SERVICES
        assert service_key("/repo/services/ping_service.py") in NO_BROKER_SERVICES
        assert service_key(r"C:\repo\services\funds_service.py") not in NO_BROKER_SERVICES

    def test_restx_resources_answer_the_same_way(self):
        """services/ is not the whole API surface.

        restx_api/portfolio.py and sip.py resolve through the same guarded
        function but answer their own message, which never misdiagnosed the key
        -- so the earlier rounds left them alone. The *status* still disagreed:
        403 with no machine-readable code, where every other consumer answers
        401 BROKER_SESSION_EXPIRED. A client cannot tell "reconnect your broker"
        from "your key is bad" by looking at 403, which is the whole point of
        the change. Each resolve-failure branch must carry one of the two
        markers.
        """
        offenders = []
        for full_path in sorted(glob.glob(os.path.join(REPO_ROOT, "restx_api", "*.py"))):
            lines = open(full_path, encoding="utf-8").read().splitlines()
            if not any("get_auth_token_broker(" in line for line in lines):
                continue
            for i, line in enumerate(lines):
                if not re.match(r"\s*if (auth_token|AUTH_TOKEN) is None:\s*$", line):
                    continue
                window = "\n".join(lines[i : i + 15])
                if "credential_error" in window or "BROKER_SESSION_EXPIRED" in window:
                    continue
                offenders.append(f"{PurePosixPath(full_path).name}:{i + 1}")

        assert offenders == [], (
            "these resolve-failure branches answer differently from every other "
            "consumer; they must return 401 with code BROKER_SESSION_EXPIRED, "
            f"via credential_error() or explicitly: {offenders}"
        )

    def test_endpoints_that_never_call_a_broker_do_not_resolve_one(self):
        """ping, symbol, intervals and analyzer must not be gated on a live
        broker session. /api/v1/ping is the canonical health check, so gating it
        turns the 03:00 rollover into a monitoring outage."""
        offenders = [
            path
            for path in sorted(NO_BROKER_SERVICES)
            if re.search(
                r"^\s*\w+.*=\s*get_auth_token_broker\(",
                open(os.path.join(REPO_ROOT, path), encoding="utf-8").read(),
                re.M,
            )
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

        import database.settings_db as settings_db

        module = importlib.import_module(module_name)
        # Live mode: these entry points now check the sandbox branch first.
        monkeypatch.setattr(settings_db, "get_analyze_mode", lambda: False)
        monkeypatch.setattr(module, "get_auth_token_broker", lambda *a, **k: (None, None))
        monkeypatch.setattr(credential_errors, "verify_api_key", lambda key: TEST_USER)

        success, response, status = getattr(module, func_name)(api_key=TEST_API_KEY)

        assert success is False
        assert status == 401, f"{module_name} still blames the API key"
        assert response["code"] == "BROKER_SESSION_EXPIRED"

    def test_bad_key_still_answers_403(self, module_name, func_name, monkeypatch):
        import importlib

        import database.settings_db as settings_db

        module = importlib.import_module(module_name)
        monkeypatch.setattr(settings_db, "get_analyze_mode", lambda: False)
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


    def test_intervals_answers_401_when_the_broker_name_is_gone(self, monkeypatch):
        """Exempting intervals from the credential resolve replaced the token
        with get_broker_name(), which answers None for a revoked or absent Auth
        row. This endpoint dispatches on that name, so None reached
        import_broker_module() and the endpoint answered 404 "Broker-specific
        module not found" plus an ERROR log line per call, where main answered
        403. The key is valid, so the honest answer is 401."""
        import services.intervals_service as intervals_service

        monkeypatch.setattr(intervals_service, "verify_api_key", lambda key: TEST_USER)
        monkeypatch.setattr(intervals_service, "get_broker_name", lambda key: None)
        monkeypatch.setattr(credential_errors, "verify_api_key", lambda key: TEST_USER)

        success, response, status = intervals_service.get_intervals(api_key=TEST_API_KEY)

        assert success is False
        assert status == 401, "a missing broker name is not a missing module"
        assert response["code"] == "BROKER_SESSION_EXPIRED"

    def test_intervals_still_answers_for_a_connected_broker(self, monkeypatch):
        import services.intervals_service as intervals_service

        monkeypatch.setattr(intervals_service, "verify_api_key", lambda key: TEST_USER)
        monkeypatch.setattr(intervals_service, "get_broker_name", lambda key: "zerodha")
        seen = {}
        monkeypatch.setattr(
            intervals_service,
            "get_intervals_with_auth",
            lambda token, broker: seen.setdefault("broker", broker)
            and (True, {"status": "success"}, 200),
        )

        success, _, status = intervals_service.get_intervals(api_key=TEST_API_KEY)

        assert success is True
        assert status == 200
        assert seen["broker"] == "zerodha"

    def test_intervals_still_rejects_a_bad_key(self, monkeypatch):
        import services.intervals_service as intervals_service

        monkeypatch.setattr(intervals_service, "verify_api_key", lambda key: None)

        success, response, status = intervals_service.get_intervals(api_key="not-a-real-key")

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

    @pytest.mark.parametrize("service_file", SANDBOX_SERVICE_FILES)
    def test_analyze_mode_is_checked_before_the_credential(self, service_file):
        """Belt and braces, across the whole sandbox surface: the ordering
        itself, so a refactor that reintroduces the coupling fails even if the
        functional test is skipped."""
        src = open(os.path.join(REPO_ROOT, service_file), encoding="utf-8").read()
        case_one = src[src.index("    # Case 1: API-based authentication") :]
        case_one = case_one[: case_one.index("    # Case 2:")]

        analyze_at = case_one.find("if get_analyze_mode():")
        resolve_at = case_one.find("get_auth_token_broker(")

        assert analyze_at != -1 and resolve_at != -1, service_file
        assert analyze_at < resolve_at, (
            f"{service_file}: the sandbox branch must come first; otherwise a "
            "rolled-over broker session blocks a sandbox operation that never "
            "touches the broker"
        )

    @pytest.mark.parametrize("module_name,entry,with_auth,args", SANDBOX_CALLS)
    def test_no_sandbox_entry_point_resolves_a_credential(
        self, module_name, entry, with_auth, args, monkeypatch
    ):
        """The functional proof for the rest of the surface. With analyze mode
        on, every sandbox-capable entry point must reach its *_with_auth branch
        without the resolver being consulted."""
        import importlib

        import database.settings_db as settings_db
        import services.order_router_service as order_router_service

        module = importlib.import_module(module_name)

        # Patched in both places: most of these modules bind get_analyze_mode at
        # import, while cancel_order and modify_order re-import it inside the
        # function, which rebinds the name for that scope.
        monkeypatch.setattr(settings_db, "get_analyze_mode", lambda: True)
        if hasattr(module, "get_analyze_mode"):
            monkeypatch.setattr(module, "get_analyze_mode", lambda: True)
        # Semi-auto routing is a separate decision and would hit the real DB.
        monkeypatch.setattr(
            order_router_service, "should_route_to_pending", lambda *a, **k: False
        )

        def fail_if_called(*a, **k):
            raise AssertionError(
                f"{module_name}.{entry} resolved a live broker credential in "
                "analyze mode; the sandbox never talks to the broker"
            )

        monkeypatch.setattr(module, "get_auth_token_broker", fail_if_called)

        seen = {}

        def record(*a, **k):
            seen["args"] = a
            return True, {"status": "success", "mode": "analyze"}, 200

        monkeypatch.setattr(module, with_auth, record)

        success, _, status = getattr(module, entry)(*args, api_key=TEST_API_KEY)

        assert seen, f"{module_name}: the sandbox path was never reached"
        assert success is True
        assert status == 200
        assert "" in seen["args"], (
            f"{module_name}: the sandbox branch must pass an empty credential, "
            "not a resolved one"
        )
