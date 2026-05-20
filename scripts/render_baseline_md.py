"""Render docs/benchmarks/greeks_baseline_pyvollib.json → human-readable markdown."""
import json
from collections import defaultdict

with open("docs/benchmarks/greeks_baseline_pyvollib.json") as f:
    data = json.load(f)

samples = data["samples"]
SPOT = data["spot"]

# Group by moneyness for summary
by_class = defaultdict(list)
for r in samples:
    by_class[(r["type"], r["moneyness"])].append(r)

ORDER = ["DEEP ITM", "ITM", "ATM", "OTM", "DEEP OTM"]


def fmt_greeks(resp):
    g = resp.get("greeks", {})
    return (
        f"{resp.get('option_price', 0):>9.2f} | "
        f"{resp.get('implied_volatility', 0):>6.2f} | "
        f"{g.get('delta', 0):>+8.4f} | "
        f"{g.get('gamma', 0):>9.6f} | "
        f"{g.get('theta', 0):>+9.4f} | "
        f"{g.get('vega', 0):>+8.4f} | "
        f"{g.get('rho', 0):>+9.6f}"
    )


def section(opt_type: str) -> str:
    lines = [
        f"### {opt_type} samples (20 strikes, NIFTY26MAY26)",
        "",
        "| Strike | Moneyness | Symbol | LTP | IV % | Delta | Gamma | Theta | Vega | Rho | Latency (ms) |",
        "|---:|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in samples:
        if r["type"] != opt_type:
            continue
        resp = r["response"]
        g = resp.get("greeks", {})
        lines.append(
            f"| {r['strike']} | {r['moneyness']} | `{r['symbol']}` | "
            f"{resp.get('option_price', 0):.2f} | {resp.get('implied_volatility', 0):.2f} | "
            f"{g.get('delta', 0):+.4f} | {g.get('gamma', 0):.6f} | "
            f"{g.get('theta', 0):+.4f} | {g.get('vega', 0):+.4f} | "
            f"{g.get('rho', 0):+.6f} | {r['latency_ms']:.1f} |"
        )
    return "\n".join(lines)


def latency_summary() -> str:
    ce_lat = [r["latency_ms"] for r in samples if r["type"] == "CE"]
    pe_lat = [r["latency_ms"] for r in samples if r["type"] == "PE"]
    all_lat = ce_lat + pe_lat

    def stats(xs):
        xs_sorted = sorted(xs)
        n = len(xs_sorted)
        return {
            "min": xs_sorted[0],
            "p50": xs_sorted[n // 2],
            "p95": xs_sorted[int(n * 0.95)],
            "max": xs_sorted[-1],
            "mean": sum(xs_sorted) / n,
        }

    s_ce, s_pe, s_all = stats(ce_lat), stats(pe_lat), stats(all_lat)
    return (
        "### End-to-end latency (HTTP → broker quotes → py_vollib → response)\n\n"
        "| Bucket | n | min | p50 | mean | p95 | max |\n"
        "|:---|---:|---:|---:|---:|---:|---:|\n"
        f"| CE | {len(ce_lat)} | {s_ce['min']:.1f} | {s_ce['p50']:.1f} | {s_ce['mean']:.1f} | {s_ce['p95']:.1f} | {s_ce['max']:.1f} |\n"
        f"| PE | {len(pe_lat)} | {s_pe['min']:.1f} | {s_pe['p50']:.1f} | {s_pe['mean']:.1f} | {s_pe['p95']:.1f} | {s_pe['max']:.1f} |\n"
        f"| All | {len(all_lat)} | {s_all['min']:.1f} | {s_all['p50']:.1f} | {s_all['mean']:.1f} | {s_all['p95']:.1f} | {s_all['max']:.1f} |\n"
        "\n*Latency is wall-clock per HTTP round-trip and dominated by broker quote fetching, not by py_vollib's math (which is microseconds). It serves as the baseline reference for the post-migration comparison.*\n"
    )


def coverage_summary() -> str:
    rows = ["| Type | DEEP ITM | ITM | ATM | OTM | DEEP OTM | Total |", "|:---|---:|---:|---:|---:|---:|---:|"]
    for t in ("CE", "PE"):
        counts = [len(by_class[(t, c)]) for c in ORDER]
        rows.append(f"| {t} | {counts[0]} | {counts[1]} | {counts[2]} | {counts[3]} | {counts[4]} | {sum(counts)} |")
    return "### Moneyness coverage\n\n" + "\n".join(rows) + "\n"


md = f"""# Option Greeks Baseline — py_vollib (Black-76)

Captured before migrating from `py_vollib==1.0.1` to `opengreeks`. This snapshot is the parity oracle for the post-migration check.

- **Engine**: `py_vollib==1.0.1` (Black-76, options on futures/forwards)
- **Service**: `services/option_greeks_service.py` → `POST /api/v1/optiongreeks`
- **Underlying**: NIFTY @ ₹{SPOT:.2f} (NSE_INDEX LTP)
- **Expiry**: 26-MAY-2026 (`NIFTY26MAY26<strike><CE/PE>`)
- **Risk-free rate**: 0 (default for NFO in `DEFAULT_INTEREST_RATES`)
- **Samples**: {len(samples)} ({sum(1 for r in samples if r['type'] == 'CE')} CE + {sum(1 for r in samples if r['type'] == 'PE')} PE)
- **Raw JSON**: [`greeks_baseline_pyvollib.json`](./greeks_baseline_pyvollib.json)

## Moneyness classification

Computed from strike vs spot ({SPOT:.0f}):

| Bucket | CE rule | PE rule |
|:---|:---|:---|
| DEEP ITM | strike ≤ spot − 1000 | strike ≥ spot + 1000 |
| ITM | spot − 1000 < strike < spot − 100 | spot + 100 < strike < spot + 1000 |
| ATM | \\|strike − spot\\| ≤ 100 | \\|strike − spot\\| ≤ 100 |
| OTM | spot + 100 < strike < spot + 1000 | spot − 1000 < strike < spot − 100 |
| DEEP OTM | strike ≥ spot + 1000 | strike ≤ spot − 1000 |

{coverage_summary()}
{latency_summary()}
{section('CE')}

{section('PE')}

## Notes

- All Greeks are returned in trader-friendly units by py_vollib's Black-76:
  - **Theta**: per-day (already scaled by 1/365 inside the library)
  - **Vega**: per 1% absolute vol change (scaled by 0.01)
  - **Rho**: per 1% absolute rate change (scaled by 0.01)
  - **IV** in the table is shown as percentage (the service multiplies the decimal by 100 for display).
- Deep-ITM options with option price ≤ intrinsic value return theoretical Greeks (Δ=±1, others=0, IV=0) — see `option_greeks_service.py` lines 348-378.
- The service auto-resolves the underlying for NIFTY → `NSE_INDEX` and uses spot LTP as the forward `F` in Black-76. For a more accurate parity check against a true forward, pass `forward_price` explicitly.

## Next step: opengreeks migration

The follow-up document `greeks_opengreeks_parity.md` will replay these same 40 samples against `opengreeks.black76` and report:

1. Bit-for-bit / max-abs / max-rel error vs this baseline for every Greek and IV
2. End-to-end latency improvement
3. Pure-math latency (`calculate_greeks()` excluding broker fetch) — the genuine apples-to-apples speedup
"""

out = "docs/benchmarks/greeks_baseline_pyvollib.md"
with open(out, "w") as f:
    f.write(md)
print(f"Wrote {out}")
