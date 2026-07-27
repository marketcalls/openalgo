"""Tests for websocket_proxy.mode_utils (issue #1375).

Covers the 8 input variants the issue called out plus invalid-input rejection
and bool/float/None type guards. Imports the lightweight mode_utils module
directly so the tests don't depend on broker adapters or the database layer.
"""

import importlib.util
import pathlib

import pytest

_MODULE_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "websocket_proxy"
    / "mode_utils.py"
)


def _load_mode_utils():
    spec = importlib.util.spec_from_file_location("_mode_utils_under_test", _MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load_mode_utils()
normalize_mode = _mod.normalize_mode
normalize_mode_or_none = _mod.normalize_mode_or_none


@pytest.mark.parametrize(
    "value, expected_int, expected_label",
    [
        # Numeric inputs (3 variants)
        (1, 1, "LTP"),
        (2, 2, "Quote"),
        (3, 3, "Depth"),
        # String inputs - canonical CapCase (3 variants)
        ("LTP", 1, "LTP"),
        ("Quote", 2, "Quote"),
        ("Depth", 3, "Depth"),
        # String inputs - documented uppercase (the original silent-failure case)
        ("QUOTE", 2, "Quote"),
        ("DEPTH", 3, "Depth"),
        # Lowercase
        ("ltp", 1, "LTP"),
        ("quote", 2, "Quote"),
        ("depth", 3, "Depth"),
        # Mixed case
        ("DePtH", 3, "Depth"),
        ("qUoTe", 2, "Quote"),
        # Whitespace tolerance
        ("  LTP  ", 1, "LTP"),
    ],
)
def test_normalize_mode_accepts_valid_inputs(value, expected_int, expected_label):
    numeric, label = normalize_mode(value)
    assert numeric == expected_int
    assert label == expected_label


@pytest.mark.parametrize(
    "value",
    [
        # Out-of-range ints
        0,
        4,
        -1,
        100,
        # Unknown strings
        "Foo",
        "BAR",
        "",
        "   ",
        "ltp1",
        "Quotes",
    ],
)
def test_normalize_mode_rejects_invalid_inputs(value):
    with pytest.raises(ValueError):
        normalize_mode(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        1.5,
        2.0,        # float lookalike — must reject (we only accept int/str)
        True,       # bool subclass of int — must reject explicitly
        False,
        ["LTP"],
        {"mode": 1},
    ],
)
def test_normalize_mode_rejects_wrong_types(value):
    with pytest.raises(TypeError):
        normalize_mode(value)


def test_normalize_mode_or_none_returns_none_on_invalid():
    assert normalize_mode_or_none("Foo") is None
    assert normalize_mode_or_none(99) is None
    assert normalize_mode_or_none(None) is None


def test_normalize_mode_or_none_passes_through_valid():
    assert normalize_mode_or_none("QUOTE") == (2, "Quote")
    assert normalize_mode_or_none(1) == (1, "LTP")


def test_canonical_label_is_idempotent():
    """Round-tripping a canonical label or its numeric form returns the same label."""
    for label in ("LTP", "Quote", "Depth"):
        numeric, canonical = normalize_mode(label)
        assert canonical == label
        _, canonical_from_int = normalize_mode(numeric)
        assert canonical_from_int == label
