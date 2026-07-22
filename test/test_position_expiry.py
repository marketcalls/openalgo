"""Regression tests for sandbox contract settlement boundaries."""

import sys
from datetime import datetime
from pathlib import Path

import pytz

# ``test/sandbox`` is a legacy test package and can shadow the production
# ``sandbox`` package during pytest collection.  Make this regression import
# the application module explicitly without changing the test harness globally.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
shadowed_sandbox = sys.modules.get("sandbox")
if shadowed_sandbox is not None and not str(
    getattr(shadowed_sandbox, "__file__", "")
).startswith(str(PROJECT_ROOT / "sandbox")):
    for module_name in tuple(sys.modules):
        if module_name == "sandbox" or module_name.startswith("sandbox."):
            sys.modules.pop(module_name, None)

from sandbox.position_manager import is_contract_expired

IST = pytz.timezone("Asia/Kolkata")


def _ist(*, hour: int, minute: int, second: int = 0) -> datetime:
    return IST.localize(datetime(2026, 7, 22, hour, minute, second))


def test_delta_contract_is_not_expired_before_its_1730_ist_settlement():
    assert not is_contract_expired(
        "ETH22JUL261920CE", "CRYPTO", now=_ist(hour=17, minute=29, second=59)
    )


def test_delta_contract_expires_at_its_1730_ist_settlement():
    assert is_contract_expired(
        "ETH22JUL261920CE", "CRYPTO", now=_ist(hour=17, minute=30)
    )


def test_delta_contract_remains_expired_after_settlement_day():
    next_day = IST.localize(datetime(2026, 7, 23, 0, 0))
    assert is_contract_expired("ETH22JUL261920CE", "CRYPTO", now=next_day)


def test_non_crypto_contract_keeps_existing_next_day_boundary():
    expiry_day = IST.localize(datetime(2026, 7, 22, 23, 59, 59))
    next_day = IST.localize(datetime(2026, 7, 23, 0, 0))

    assert not is_contract_expired(
        "NIFTY22JUL2624000CE", "NFO", now=expiry_day
    )
    assert is_contract_expired("NIFTY22JUL2624000CE", "NFO", now=next_day)
