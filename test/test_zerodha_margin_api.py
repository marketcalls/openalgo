import os
import sys
from pathlib import Path

os.environ.setdefault("API_KEY_PEPPER", "test-pepper-value-at-least-32-chars")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import broker.zerodha.mapping.margin_data as margin_data  # noqa: E402


def test_basket_response_exposes_pre_credit_total_alongside_optimized_total():
    """final.total already nets the option premium collected from the short
    legs; initial_total_margin is the pre-credit figure a caller should use
    to size a position before that premium has actually been received."""
    response = {
        "status": "success",
        "data": {
            "initial": {
                "total": 258139.0,
                "span": 258139.0,
                "exposure": 0.0,
                "option_premium": 0.0,
            },
            "final": {
                "total": 191119.0,
                "span": 191119.0,
                "exposure": 0.0,
                "option_premium": 67020.0,
            },
            "orders": [],
        },
    }

    result = margin_data.parse_margin_response(response)

    assert result["status"] == "success"
    data = result["data"]
    assert data["total_margin_required"] == 191119.0
    assert data["initial_total_margin"] == 258139.0
    assert data["option_premium_credit"] == 67020.0
    # The relationship the fix is built on: initial - final == option_premium
    assert (
        data["initial_total_margin"] - data["total_margin_required"]
        == data["option_premium_credit"]
    )


def test_non_basket_response_uses_total_as_initial_with_zero_credit():
    """Single/aggregated-order responses have no initial/final split, so
    initial_total_margin should just fall back to total_margin_required."""
    response = {
        "status": "success",
        "data": [
            {"total": 50000.0, "span": 40000.0, "exposure": 10000.0},
            {"total": 30000.0, "span": 25000.0, "exposure": 5000.0},
        ],
    }

    result = margin_data.parse_margin_response(response)

    data = result["data"]
    assert data["total_margin_required"] == 80000.0
    assert data["initial_total_margin"] == 80000.0
    assert data["option_premium_credit"] == 0


def test_error_response_passes_through_unchanged():
    response = {"status": "error", "message": "Invalid session"}

    result = margin_data.parse_margin_response(response)

    assert result == {"status": "error", "message": "Invalid session"}
