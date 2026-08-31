"""Executable contracts for the public strategy and WebSocket documentation.

The strategy module persists safety-critical state that callers must interpret
correctly.  These checks keep the machine-readable vocabularies, serialized
field lists and lifecycle examples aligned with the implementation.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from database import strategy_module_db as store

ROOT = Path(__file__).resolve().parents[1]
STRATEGY_API = ROOT / "docs" / "api" / "strategy-services"


def _read(relative: str | Path) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """Return one Markdown section, excluding the next heading at that level."""

    start = text.index(heading) + len(heading)
    level = len(heading) - len(heading.lstrip("#"))
    next_heading = re.search(rf"(?m)^#{{1,{level}}}\s", text[start:])
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end]


def _backtick_values(line: str) -> list[str]:
    return re.findall(r"`([^`]+)`", line)


def _category_vocabulary(text: str) -> tuple[str, ...]:
    categories = (
        "Lifecycle:",
        "Entry and exit:",
        "Per-leg risk:",
        "Strategy risk:",
        "Tick source:",
        "Operational:",
    )
    found: list[str] = []
    for category in categories:
        line = next(line for line in text.splitlines() if line.startswith(category))
        found.extend(_backtick_values(line))
    return tuple(found)


def _first_vocabulary_paragraph(text: str, heading: str) -> tuple[str, ...]:
    for line in _section(text, heading).splitlines():
        if line.strip():
            return tuple(_backtick_values(line))
    raise AssertionError(f"No vocabulary paragraph found below {heading}")


def _table_fields_after(text: str, marker: str) -> set[str]:
    lines = text[text.index(marker) + len(marker) :].splitlines()
    fields: set[str] = set()
    in_table = False
    for line in lines:
        if line.startswith("| Field |"):
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith("|"):
            if fields:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and cells[0] and set(cells[0]) != {"-"}:
            fields.add(cells[0].strip("`"))
    return fields


def _run_serializer_fields() -> set[str]:
    row = SimpleNamespace(
        id=1,
        strategy_id=2,
        mode="sandbox",
        broker="sandbox",
        started_at=None,
        stopped_at=None,
        stop_reason=None,
        stop_requested_at=None,
        stop_requested_reason=None,
        pnl_realized=0,
        pnl_peak=0,
        pnl_trough=0,
        trigger_source="manual",
        webhook_event_id=None,
        resolved_expiries=None,
    )
    return set(store.run_to_dict(row))


def _order_serializer_fields() -> set[str]:
    row = SimpleNamespace(
        id=1,
        run_id=2,
        leg_id=3,
        kind="entry",
        position_ref="owner-1",
        broker_order_id=None,
        symbol="RELIANCE",
        exchange="NSE",
        action="BUY",
        qty=1,
        product="MIS",
        pricetype="MARKET",
        price=0,
        trigger_price=0,
        status="pending",
        placed_at=None,
        filled_at=None,
        avg_fill_price=None,
        filled_qty=None,
        reject_reason=None,
    )
    return set(store.order_to_dict(row))


def test_strategy_api_documents_the_canonical_event_vocabulary() -> None:
    expected = tuple(store.EVENT_KINDS)
    assert _category_vocabulary(_read(STRATEGY_API / "README.md")) == expected
    assert _category_vocabulary(_read(STRATEGY_API / "events.md")) == expected


def test_strategy_api_documents_the_canonical_order_kind_vocabulary() -> None:
    expected = tuple(store.ORDER_KINDS)
    assert _first_vocabulary_paragraph(
        _read(STRATEGY_API / "README.md"), "### Order kinds"
    ) == expected
    assert _first_vocabulary_paragraph(
        _read(STRATEGY_API / "orders.md"), "### Order kinds"
    ) == expected


def test_run_and_order_field_tables_match_the_serializers() -> None:
    expected_run = _run_serializer_fields()
    assert _table_fields_after(
        _read(STRATEGY_API / "runs.md"), "Each object in `data`:"
    ) == expected_run
    assert _table_fields_after(_read(STRATEGY_API / "status.md"), "`run`:") == expected_run
    assert _table_fields_after(
        _read(STRATEGY_API / "orders.md"), "Each object in `data`:"
    ) == _order_serializer_fields()


def test_pending_stop_and_acknowledgement_examples_preserve_lifecycle_truth() -> None:
    start_sample = _section(_read(STRATEGY_API / "start.md"), "## Sample API Response")
    stop_sample = _section(_read(STRATEGY_API / "stop.md"), "## Sample API Response")
    close_all_sample = _section(
        _read(STRATEGY_API / "close_all.md"), "## Sample API Response"
    )
    webhook_stop_sample = _section(
        _read(STRATEGY_API / "webhook.md"), "### Sample API Response (Stop)"
    )

    assert '"acknowledged": true' in start_sample
    start = _read(STRATEGY_API / "start.md")
    assert '"acknowledged": false' in start
    assert "manual reconciliation" in start
    assert '"stop_pending": true' in stop_sample
    assert '"stop_pending": true' in close_all_sample
    assert '"stop_pending": true' in webhook_stop_sample

    for relative in ("README.md", "runs.md", "status.md", "stop.md", "close_all.md"):
        text = _read(STRATEGY_API / relative).casefold()
        assert "closes the run without waiting" not in text
        assert "run was finalised" not in text

    close_leg = _read(STRATEGY_API / "close_leg.md")
    assert "stop_pending" not in close_leg


def test_every_strategy_bdd_source_anchor_resolves_to_a_symbol() -> None:
    feature = _read("docs/bdd/strategy_module_rms.feature")
    source_re = re.compile(r"^\s*# Source:\s*(.+)$")
    reference_re = re.compile(r"^(.+):(\d+)$")
    references: list[str] = []

    for line in feature.splitlines():
        match = source_re.match(line)
        if match:
            references.extend(
                reference.strip()
                for reference in re.split(r"\s*[;,]\s*", match.group(1))
                if reference.strip()
            )

    assert references
    for reference in references:
        match = reference_re.match(reference)
        assert match, f"Source reference must be path:line: {reference}"
        relative, raw_line = match.groups()
        source = ROOT / relative
        assert source.is_file(), f"Source file does not exist: {reference}"
        lines = source.read_text(encoding="utf-8").splitlines()
        line_number = int(raw_line)
        assert 1 <= line_number <= len(lines), f"Source line is out of range: {reference}"
        excerpt = lines[line_number - 1].strip()
        assert re.match(
            r"(?:async\s+)?def\s+|class\s+|(?:it|test)\(", excerpt
        ), (
            f"Source anchor must resolve to a function or class declaration: "
            f"{reference} -> {excerpt!r}"
        )


def test_market_data_websocket_docs_use_the_server_wire_contract() -> None:
    prompt = _read("docs/prompt/websockets-format.md")
    assert '"symbols": [' in prompt
    assert '"depth": 5' in prompt
    assert '"type": "market_data"' in prompt
    assert '"broker": "' in prompt
    assert '"topic":' not in prompt
    assert '"depth_level":' not in prompt

    for name in ("ltp.md", "quote.md", "depth.md"):
        page = _read(Path("docs/api/websocket-streaming") / name)
        raw_request = _section(page, "## WebSocket Request")
        sample_response = _section(page, "## Sample Response")
        assert '"symbols": [' in raw_request
        assert '"instruments": [' not in raw_request
        assert '"type": "market_data"' in sample_response
