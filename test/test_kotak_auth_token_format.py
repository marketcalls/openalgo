"""Kotak's composite auth token must parse at both lengths.

The stored token was "session_token:::session_sid:::base_url:::access_token".
Streaming needs the account's data centre to know which market-data feed it is
routed to, so a fifth part was appended:

    session_token:::session_sid:::base_url:::access_token:::data_center

Appended, never inserted, so tokens issued before the change still parse and no
existing user is forced to log in again. That only holds if *every* reader takes
the first four positionally. One reader that unpacks the split straight into a
4-tuple raises "too many values to unpack (expected 4)" the moment a freshly
issued token reaches it - which is a broken quotes endpoint for anyone who logs
in after the upgrade, not a test failure.

The regression these guard against was a reader missed by a line-oriented grep:
ruff had wrapped its ``.split(`` and its ``":::"`` onto separate lines, so a
search for the two together on one line did not see it. Hence the AST scan
below rather than another grep.
"""

import ast
from pathlib import Path

import pytest

KOTAK = Path(__file__).resolve().parents[1] / "broker" / "kotak"

FOUR_PART = "tok:::sid:::https://e21.kotaksecurities.com:::access"
FIVE_PART = FOUR_PART + ":::E21"


def _split_call_sites(tree):
    """Yield (node, is_tuple_target, is_sliced) for each `x.split(":::")` assign.

    is_sliced covers the tolerant form, `.split(":::")[:4]`, however the source
    happens to be wrapped across lines.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue

        value = node.value
        is_sliced = False
        if isinstance(value, ast.Subscript):
            is_sliced = True
            value = value.value

        if not isinstance(value, ast.Call):
            continue
        func = value.func
        if not (isinstance(func, ast.Attribute) and func.attr == "split"):
            continue
        if not (
            len(value.args) == 1
            and isinstance(value.args[0], ast.Constant)
            and value.args[0].value == ":::"
        ):
            continue

        is_tuple_target = any(isinstance(t, (ast.Tuple, ast.List)) for t in node.targets)
        yield node, is_tuple_target, is_sliced


def _kotak_sources():
    return sorted(KOTAK.rglob("*.py"))


@pytest.mark.parametrize("path", _kotak_sources(), ids=lambda p: str(p.relative_to(KOTAK)))
def test_no_reader_unpacks_the_token_into_a_fixed_tuple(path):
    """A tuple-unpacking reader must slice the first four parts first.

    Assigning the whole split to a single name is fine - those readers index or
    length-check it themselves. What cannot survive a fifth part is unpacking
    the split directly into exactly four targets.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))

    offenders = [
        node.lineno
        for node, is_tuple_target, is_sliced in _split_call_sites(tree)
        if is_tuple_target and not is_sliced
    ]

    assert not offenders, (
        f"{path.relative_to(KOTAK)} unpacks the auth token into a fixed tuple at "
        f"line(s) {offenders}. A token carrying the data centre has five parts and "
        "will raise 'too many values to unpack'. Slice it: .split(':::')[:4]"
    )


@pytest.mark.parametrize("path", _kotak_sources(), ids=lambda p: str(p.relative_to(KOTAK)))
def test_no_reader_rejects_a_token_for_having_extra_parts(path):
    """`len(parts) != 4` rejects a valid five-part token. It must be `< 4`."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()

    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Compare) and len(node.ops) == 1):
            continue
        if not isinstance(node.ops[0], ast.NotEq):
            continue
        if not (isinstance(node.comparators[0], ast.Constant) and node.comparators[0].value == 4):
            continue
        left = node.left
        if isinstance(left, ast.Call) and getattr(left.func, "id", None) == "len":
            offenders.append((node.lineno, lines[node.lineno - 1].strip()))

    assert not offenders, (
        f"{path.relative_to(KOTAK)} rejects a token whose part count is not exactly 4, "
        f"at {offenders}. Five parts is valid; use '< 4'."
    )


# --- the reader that actually broke ------------------------------------------


@pytest.mark.parametrize("token", [FOUR_PART, FIVE_PART], ids=["four-part", "five-part"])
def test_brokerdata_accepts_both_token_lengths(token):
    """data.py's BrokerData is the one that failed in production.

    It parses in __init__ and reaches no network, so it can be constructed
    directly. Before the fix the five-part case raised
    "too many values to unpack (expected 4)" and every quotes request 500'd.
    """
    from broker.kotak.api.data import BrokerData

    broker = BrokerData(token)

    assert broker.session_token == "tok"
    assert broker.session_sid == "sid"
    assert broker.base_url == "https://e21.kotaksecurities.com"
    assert broker.access_token == "access"


def test_the_data_centre_is_read_from_the_fifth_part():
    """And is empty, not an error, when the token predates it."""
    # websocket_proxy first: its __init__ imports every broker adapter, and
    # kotak_adapter imports back into it. Reaching the adapter directly from a
    # cold interpreter hits that pre-existing cycle. This is the order the app
    # itself loads them in.
    import websocket_proxy  # noqa: F401
    from broker.kotak.streaming.kotak_adapter import _data_center_from

    assert _data_center_from(FIVE_PART.split(":::")) == "E21"
    assert _data_center_from(FOUR_PART.split(":::")) == ""
