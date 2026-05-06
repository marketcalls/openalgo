"""Phase 6 — strategy mode contextvar tests.

Validates the per-call mode override that lets v2 sandbox/live runs route
independently of the global analyze flag (database/settings_db.py).

Covers:
  - get_force_mode default (None)
  - force_strategy_mode context manager set + reset
  - exception-safety (override clears even on exception)
  - nested contexts compose correctly
  - get_analyze_mode() override behavior (sandbox→True, live→False, None→fallback)
  - Adapter wrapping calls _BaseBrokerAdapter methods inside the context
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_order_services(monkeypatch):
    """Inject stub modules for the lazy-imported order services so adapter
    method tests don't have to load the full restx_api chain (which depends
    on broker plugins / app context). Each stub module exposes the function
    name the adapter expects and a `last_call` dict capturing the call args
    + the contextvar value at call time.
    """
    captured: dict = {}

    def _stub(module_path: str, func_name: str, success: bool = True):
        from utils.strategy_mode_context import get_force_mode

        def _impl(*args, **kwargs):
            captured["mode"] = get_force_mode()
            captured["args"] = args
            captured["kwargs"] = kwargs
            if not success:
                raise RuntimeError("simulated broker error")
            return True, {"orderid": "STUB-1"}, 200

        mod = types.ModuleType(module_path)
        setattr(mod, func_name, _impl)
        monkeypatch.setitem(sys.modules, module_path, mod)
        return _impl

    return {"stub": _stub, "captured": captured}


# ===========================================================================
# Pure-function contextvar tests
# ===========================================================================


def test_default_is_none():
    from utils.strategy_mode_context import get_force_mode
    assert get_force_mode() is None


def test_force_strategy_mode_sets_and_resets():
    from utils.strategy_mode_context import force_strategy_mode, get_force_mode

    assert get_force_mode() is None
    with force_strategy_mode("sandbox"):
        assert get_force_mode() == "sandbox"
    assert get_force_mode() is None


def test_force_strategy_mode_live():
    from utils.strategy_mode_context import force_strategy_mode, get_force_mode

    with force_strategy_mode("live"):
        assert get_force_mode() == "live"
    assert get_force_mode() is None


def test_force_strategy_mode_invalid_value_raises():
    from utils.strategy_mode_context import force_strategy_mode

    with pytest.raises(ValueError):
        with force_strategy_mode("paper"):  # type: ignore[arg-type]
            pass


def test_force_strategy_mode_resets_on_exception():
    """Even if the with-block raises, the override must clear."""
    from utils.strategy_mode_context import force_strategy_mode, get_force_mode

    class Boom(RuntimeError):
        pass

    with pytest.raises(Boom):
        with force_strategy_mode("sandbox"):
            assert get_force_mode() == "sandbox"
            raise Boom()
    assert get_force_mode() is None


def test_nested_contexts_compose_correctly():
    """Inner with-block restores outer value, not None."""
    from utils.strategy_mode_context import force_strategy_mode, get_force_mode

    with force_strategy_mode("live"):
        assert get_force_mode() == "live"
        with force_strategy_mode("sandbox"):
            assert get_force_mode() == "sandbox"
        # Inner reset → back to outer's "live", NOT to None
        assert get_force_mode() == "live"
    assert get_force_mode() is None


def test_is_sandbox_forced_helper():
    from utils.strategy_mode_context import force_strategy_mode, is_sandbox_forced

    assert is_sandbox_forced() is False
    with force_strategy_mode("sandbox"):
        assert is_sandbox_forced() is True
    with force_strategy_mode("live"):
        assert is_sandbox_forced() is False


def test_is_live_forced_helper():
    from utils.strategy_mode_context import force_strategy_mode, is_live_forced

    assert is_live_forced() is False
    with force_strategy_mode("live"):
        assert is_live_forced() is True


# ===========================================================================
# get_analyze_mode override behavior
# ===========================================================================


def test_get_analyze_mode_with_sandbox_override(monkeypatch):
    """When force_strategy_mode('sandbox') is set, get_analyze_mode returns
    True regardless of the underlying global flag."""
    from database import settings_db
    from utils.strategy_mode_context import force_strategy_mode

    # Pretend global analyze is OFF so we can observe the override winning.
    settings_db._settings_cache["analyze_mode"] = False

    assert settings_db.get_analyze_mode() is False
    with force_strategy_mode("sandbox"):
        assert settings_db.get_analyze_mode() is True
    # Reset → fall back to global flag again
    assert settings_db.get_analyze_mode() is False

    settings_db._settings_cache.clear()


def test_get_analyze_mode_with_live_override(monkeypatch):
    """When force_strategy_mode('live') is set, get_analyze_mode returns
    False regardless of the underlying global flag."""
    from database import settings_db
    from utils.strategy_mode_context import force_strategy_mode

    settings_db._settings_cache["analyze_mode"] = True  # global is ON

    assert settings_db.get_analyze_mode() is True
    with force_strategy_mode("live"):
        assert settings_db.get_analyze_mode() is False
    assert settings_db.get_analyze_mode() is True

    settings_db._settings_cache.clear()


def test_get_analyze_mode_no_override_falls_through(monkeypatch):
    """No override → global flag wins."""
    from database import settings_db

    settings_db._settings_cache["analyze_mode"] = True
    assert settings_db.get_analyze_mode() is True
    settings_db._settings_cache["analyze_mode"] = False
    assert settings_db.get_analyze_mode() is False

    settings_db._settings_cache.clear()


# ===========================================================================
# Adapter wrapping — verifies the context is set DURING the service call
# ===========================================================================


def test_sandbox_adapter_sets_force_mode_during_place_order(fake_order_services):
    """SandboxBrokerAdapter.place_order sets force_mode=sandbox for the
    duration of the underlying service call, then resets."""
    from utils.strategy_mode_context import get_force_mode

    fake_order_services["stub"]("services.place_order_service", "place_order")
    from services.strategy.broker_adapter_impls import SandboxBrokerAdapter

    adapter = SandboxBrokerAdapter("test-key")
    adapter.place_order({"symbol": "INFY"})

    assert fake_order_services["captured"]["mode"] == "sandbox"
    assert get_force_mode() is None


def test_live_adapter_sets_force_mode_during_call(fake_order_services):
    from utils.strategy_mode_context import get_force_mode

    fake_order_services["stub"]("services.place_order_service", "place_order")
    from services.strategy.broker_adapter_impls import LiveBrokerAdapter

    adapter = LiveBrokerAdapter("test-key")
    adapter.place_order({"symbol": "INFY"})

    assert fake_order_services["captured"]["mode"] == "live"
    assert get_force_mode() is None


def test_adapter_resets_on_exception(fake_order_services):
    """If the underlying service raises, the override still resets."""
    from utils.strategy_mode_context import get_force_mode

    fake_order_services["stub"](
        "services.place_order_service", "place_order", success=False
    )
    from services.strategy.broker_adapter_impls import SandboxBrokerAdapter

    adapter = SandboxBrokerAdapter("test-key")
    with pytest.raises(RuntimeError):
        adapter.place_order({"symbol": "INFY"})

    assert get_force_mode() is None


def test_sandbox_adapter_routes_basket_order_under_override(fake_order_services):
    """Same wrapping for basket_order — verifies the override is set."""
    fake_order_services["stub"]("services.basket_order_service", "place_basket_order")
    from services.strategy.broker_adapter_impls import SandboxBrokerAdapter

    adapter = SandboxBrokerAdapter("test-key")
    adapter.basket_order({"orders": []})

    assert fake_order_services["captured"]["mode"] == "sandbox"


def test_sandbox_adapter_routes_options_multiorder_under_override(fake_order_services):
    fake_order_services["stub"](
        "services.options_multiorder_service", "place_options_multiorder"
    )
    from services.strategy.broker_adapter_impls import SandboxBrokerAdapter

    adapter = SandboxBrokerAdapter("test-key")
    adapter.place_options_multiorder({"legs": []})

    assert fake_order_services["captured"]["mode"] == "sandbox"


def test_get_adapter_factory_picks_correct_class():
    from services.strategy.broker_adapter_impls import (
        LiveBrokerAdapter,
        SandboxBrokerAdapter,
        get_adapter,
    )

    assert isinstance(get_adapter("live", "key"), LiveBrokerAdapter)
    assert isinstance(get_adapter("sandbox", "key"), SandboxBrokerAdapter)
    # Default / unknown mode → live (defensive)
    assert isinstance(get_adapter("", "key"), LiveBrokerAdapter)
    assert isinstance(get_adapter(None, "key"), LiveBrokerAdapter)  # type: ignore[arg-type]
