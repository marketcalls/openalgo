# scripts/generate_indicator_reference.py
"""Generate the Flow indicator reference from the installed openalgo build.

Hand-maintained indicator docs drift from the library: the QA audit found 43 of
the catalog's indicators had no discoverable call example, leaving a user or a
generating model to guess parameter names. This derives every entry by
introspecting the callable and then executing it, so an indicator that cannot
produce a value never reaches the reference.

Run: uv run python scripts/generate_indicator_reference.py
"""

import inspect
import json
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from openalgo import ta  # noqa: E402

from services.indicator_service import (  # noqa: E402
    _REQUIRED_PARAM_DEFAULTS,
    _SERIES_PARAM_TO_COLUMN,
    compute_indicator,
    list_supported_indicators,
)

OUTPUT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "docs/prompt/indicators/flow indicator reference.md"
)
BARS = 400


def sample_records() -> list[dict]:
    """Deterministic OHLCV long enough for any warm-up in the catalog."""
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0, 1, BARS))
    return [
        {
            "timestamp": 1_700_000_000 + i * 300,
            "open": float(close[i] - 0.2),
            "high": float(close[i] + 1),
            "low": float(close[i] - 1),
            "close": float(close[i]),
            "volume": int(rng.integers(100, 1000)),
        }
        for i in range(BARS)
    ]


def describe(name: str, records: list[dict]) -> dict | None:
    fn = getattr(ta, name, None)
    if fn is None:
        return None
    sig = inspect.signature(fn)
    inputs, params = [], []
    for param in sig.parameters.values():
        if param.name in _SERIES_PARAM_TO_COLUMN and not params:
            inputs.append(_SERIES_PARAM_TO_COLUMN[param.name])
        elif param.default is not inspect.Parameter.empty:
            params.append((param.name, param.default))
        else:
            # Required, no default. Omitting these produced call examples like
            # `ta.sma(close)` that raise TypeError when run directly, and implied
            # no configuration was needed. The service supplies a value from
            # _REQUIRED_PARAM_DEFAULTS; show what it actually uses.
            supplied = _REQUIRED_PARAM_DEFAULTS.get(name, {}).get(param.name)
            params.append((param.name, supplied if supplied is not None else "required"))

    try:
        result = compute_indicator(records, name, {})
    except Exception:
        # One indicator with an unexpected required parameter must not take the
        # whole reference down with it.
        return None
    if result.get("status") != "success":
        return None
    return {
        "name": name,
        "inputs": inputs,
        "params": params,
        "outputs": list((result.get("latest") or {}).keys()),
    }


def main() -> int:
    records = sample_records()
    entries, unusable = [], []
    for name in sorted(list_supported_indicators()):
        entry = describe(name, records)
        (entries if entry else unusable).append(entry or name)

    lines = [
        "# Flow Indicator Reference",
        "",
        "Generated from the installed `openalgo` build: every entry was produced by",
        f"introspecting the callable and then executing it over {BARS} deterministic",
        "OHLCV bars. Each one returned a non-null value in that run, so each is",
        "usable from the Flow `indicator` node.",
        "",
        "**Do not hand-edit.** Regenerate with:",
        "",
        "```bash",
        "uv run python scripts/generate_indicator_reference.py",
        "```",
        "",
        "- **Inputs** are the OHLCV columns the node feeds in for you.",
        "- **Parameters** go in the node's `params` object.",
        "- **Outputs** are the keys under `latest` / `previous` / `at_offset`. A single",
        "  output is always `value`; multiple outputs are `out0`, `out1`, ...",
        "",
        "| Indicator | Python call | Inputs | Parameters | Outputs | `params` example |",
        "|---|---|---|---|---|---|",
    ]
    for e in entries:
        inputs = ", ".join(f"`{i}`" for i in e["inputs"]) or "-"
        params = ", ".join(f"`{p}`={d!r}" for p, d in e["params"]) or "-"
        outputs = ", ".join(f"`{o}`" for o in e["outputs"]) or "-"
        if e["params"]:
            pairs = ", ".join(f'"{p}": {d!r}' for p, d in e["params"][:2])
            example = "{" + pairs + "}"
        else:
            example = "{}"
        call_args = ", ".join(e["inputs"]) or "data"
        if e["params"]:
            call_args += ", " + ", ".join(f"{p}={d!r}" for p, d in e["params"][:2])
        lines.append(
            f"| `{e['name']}` | `ta.{e['name']}({call_args})` | {inputs} | {params} | "
            f"{outputs} | `{example.replace(chr(39), chr(34))}` |"
        )

    lines += [
        "",
        f"**{len(entries)} indicators**, all verified to compute.",
        "",
        "## Not available from the `indicator` node",
        "",
        "| Function | Why |",
        "|---|---|",
        "| `crossover`, `crossunder`, `cross` | Need two independent series. Use two "
        "`indicator` nodes plus an `andGate`. |",
        "| `correlation`, `beta` | Compare two symbols. |",
        "| `exrem`, `flip`, `valuewhen` | Need a second boolean series and carry state "
        "across bars. |",
        "| `median_bands`, `ulcerindex`, `vi` | The installed build returns no usable "
        "value for these. |",
        "",
        "## Using an indicator in Flow",
        "",
        "```json",
        "{",
        '  "id": "node_2",',
        '  "type": "indicator",',
        '  "position": { "x": 100, "y": 100 },',
        '  "data": {',
        '    "symbol": "RELIANCE",',
        '    "exchange": "NSE",',
        '    "interval": "5m",',
        '    "indicatorName": "rsi",',
        '    "params": { "period": 14 },',
        '    "outputVariable": "r"',
        "  }",
        "}",
        "```",
        "",
        "Read the latest value as `{{r.latest.value}}`, the prior bar as",
        "`{{r.previous.value}}`, and a specific bar back as `{{r.at_offset.value}}`",
        "with `offsetBars` set. For a multi-output indicator use `{{r.latest.out0}}`,",
        "`{{r.latest.out1}}`, and so on.",
        "",
    ]

    OUTPUT.write_text("\n".join(lines))
    print(f"Wrote {OUTPUT} with {len(entries)} indicators")
    if unusable:
        print(f"Skipped (no usable value): {unusable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
