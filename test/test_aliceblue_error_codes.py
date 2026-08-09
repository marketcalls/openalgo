"""AliceBlue EC* error codes are expanded into readable text.

AliceBlue answers failures with a bare code and no prose, so a rejected order
surfaced to the user as the literal string "EC912". 15-error-code.md publishes
133 of them.
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ec = pytest.importorskip("broker.aliceblue.api.error_codes")
order_api = pytest.importorskip("broker.aliceblue.api.order_api")


def test_the_published_table_is_loaded():
    assert len(ec.ERROR_CODES) == 133
    assert ec.ERROR_CODES["EC912"] == "Failed to place the order."


@pytest.mark.parametrize(
    "code,fragment",
    [
        ("EC912", "Failed to place the order"),
        ("EC904", "positive number"),
        ("EC922", "No holdings found"),
        ("EC930", "LIMIT"),
    ],
)
def test_a_bare_code_is_expanded(code, fragment):
    out = ec.describe(code)
    assert out.startswith(f"{code}: ")
    assert fragment in out


def test_a_code_embedded_in_a_sentence_is_expanded_in_place():
    assert "positive number" in ec.describe("Order rejected: EC904")
    assert "Order rejected:" in ec.describe("Order rejected: EC904")


def test_an_unknown_code_passes_through_untouched():
    """Inventing a description would be worse than showing the raw code."""
    assert ec.describe("EC100") == "EC100"


def test_a_message_with_no_code_is_unchanged():
    assert ec.describe("Session expired") == "Session expired"


@pytest.mark.parametrize("value", ["", None])
def test_empty_input_is_returned_as_is(value):
    assert ec.describe(value) == value


def test_the_api_error_path_expands_codes():
    """_extract_result is the funnel every read error passes through."""
    with patch.object(order_api, "logger") as log:
        result = order_api._extract_result({"status": "Not_Ok", "message": "EC922"})

    assert result is None
    logged = " ".join(str(c) for c in log.error.call_args_list)
    assert "No holdings found" in logged, f"code was not expanded in the log: {logged}"
