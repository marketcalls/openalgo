"""
Pure-math parity + speedup benchmark: py_vollib vs opengreeks.

Replays the exact inputs recorded in the baseline JSON (no broker fetch, no HTTP)
so we get apples-to-apples library timing and bit-level error metrics.
"""
import json
import time
from typing import Callable

import py_vollib.black.greeks.analytical as pyvg
from py_vollib.black.implied_volatility import implied_volatility as pyv_iv

import opengreeks.black76 as ogb

BASELINE = "docs/benchmarks/greeks_baseline_pyvollib.json"
OUT_JSON = "docs/benchmarks/greeks_parity_opengreeks.json"

with open(BASELINE) as f:
    baseline = json.load(f)


def to_inputs(sample: dict) -> dict:
    """Extract Black-76 inputs from a recorded baseline sample."""
    resp = sample["response"]
    return {
        "symbol": sample["symbol"],
        "type": sample["type"],
        "moneyness": sample["moneyness"],
        "F": resp["spot_price"],
        "K": resp["strike"],
        "t": resp["days_to_expiry"] / 365.0,
        "r": resp["interest_rate"] / 100.0,
        "price": resp["option_price"],
        "flag": "c" if sample["type"] == "CE" else "p",
        "baseline_iv": resp["implied_volatility"] / 100.0,
        "baseline": resp["greeks"],
    }


def bench_one(fn: Callable, args: tuple, n: int = 5000) -> tuple[float, float]:
    """Return (median_microseconds, value)."""
    # warmup
    for _ in range(50):
        v = fn(*args)
    # timed
    samples = []
    for _ in range(n):
        t0 = time.perf_counter_ns()
        v = fn(*args)
        samples.append(time.perf_counter_ns() - t0)
    samples.sort()
    median_ns = samples[n // 2]
    return median_ns / 1000.0, v  # microseconds


def run_parity():
    rows = []
    pyv_total_ns = 0
    og_total_ns = 0

    for s in baseline["samples"]:
        inp = to_inputs(s)
        flag, F, K, t, r, price = inp["flag"], inp["F"], inp["K"], inp["t"], inp["r"], inp["price"]

        # ---- IV ----
        try:
            iv_pyv = pyv_iv(price, F, K, r, t, flag)
        except Exception:
            iv_pyv = None
        try:
            iv_og = ogb.implied_volatility(price, F, K, r, t, flag)
        except Exception:
            iv_og = None

        # Use opengreeks IV for both Greek calculations (need a sigma; pick the engine under test for fairness on its own output, but also compare delta etc. recomputed from py_vollib IV — for parity we use SAME sigma on both libs).
        # For TRUE parity we pass the same sigma to both. Use py_vollib's IV result.
        sigma = iv_pyv if iv_pyv is not None else (iv_og if iv_og is not None else 0.0)

        row = {
            **{k: inp[k] for k in ("symbol", "type", "moneyness", "F", "K", "t", "r", "price", "flag")},
            "iv_pyvollib": iv_pyv,
            "iv_opengreeks": iv_og,
            "iv_abs_err": abs((iv_pyv or 0) - (iv_og or 0)) if (iv_pyv is not None and iv_og is not None) else None,
            "greeks": {},
        }

        if sigma and sigma > 0:
            for name, py_fn, og_fn in [
                ("delta", pyvg.delta, ogb.delta),
                ("gamma", pyvg.gamma, ogb.gamma),
                ("theta", pyvg.theta, ogb.theta),
                ("vega",  pyvg.vega,  ogb.vega),
                ("rho",   pyvg.rho,   ogb.rho),
            ]:
                try:
                    g_pyv = py_fn(flag, F, K, t, r, sigma)
                except Exception as e:
                    g_pyv = None
                try:
                    g_og = og_fn(flag, F, K, t, r, sigma)
                except Exception as e:
                    g_og = None
                row["greeks"][name] = {
                    "pyvollib": g_pyv,
                    "opengreeks": g_og,
                    "abs_err": (abs(g_pyv - g_og) if (g_pyv is not None and g_og is not None) else None),
                    "rel_err": (abs(g_pyv - g_og) / abs(g_pyv) if (g_pyv not in (None, 0) and g_og is not None) else None),
                }
        rows.append(row)

    return rows


def run_speedup():
    """Median single-call latency per function on a representative ATM input."""
    # ATM sample as canonical
    atm = next(s for s in baseline["samples"] if s["type"] == "CE" and s["moneyness"] == "ATM" and s["strike"] == 23650)
    inp = to_inputs(atm)
    F, K, t, r, price, flag = inp["F"], inp["K"], inp["t"], inp["r"], inp["price"], inp["flag"]
    sigma = inp["baseline_iv"]

    funcs = [
        ("implied_volatility", (pyv_iv, ogb.implied_volatility), (price, F, K, r, t, flag)),
        ("delta", (pyvg.delta, ogb.delta), (flag, F, K, t, r, sigma)),
        ("gamma", (pyvg.gamma, ogb.gamma), (flag, F, K, t, r, sigma)),
        ("theta", (pyvg.theta, ogb.theta), (flag, F, K, t, r, sigma)),
        ("vega",  (pyvg.vega,  ogb.vega),  (flag, F, K, t, r, sigma)),
        ("rho",   (pyvg.rho,   ogb.rho),   (flag, F, K, t, r, sigma)),
    ]

    results = []
    for name, (py_fn, og_fn), args in funcs:
        us_pyv, _ = bench_one(py_fn, args)
        us_og, _ = bench_one(og_fn, args)
        results.append({
            "function": name,
            "pyvollib_us": round(us_pyv, 3),
            "opengreeks_us": round(us_og, 3),
            "speedup": round(us_pyv / us_og, 1) if us_og > 0 else None,
        })
    return results


def run_chain_speedup():
    """Compute all 5 Greeks + IV for all baseline samples that aren't below-intrinsic."""
    all_inputs = [to_inputs(s) for s in baseline["samples"]]
    # Skip samples where py_vollib cannot compute IV (deep-ITM with no time value).
    inputs = []
    for i in all_inputs:
        try:
            pyv_iv(i["price"], i["F"], i["K"], i["r"], i["t"], i["flag"])
            ogb.implied_volatility(i["price"], i["F"], i["K"], i["r"], i["t"], i["flag"])
            inputs.append(i)
        except Exception:
            pass

    def chain_pyv():
        out = []
        for i in inputs:
            iv = pyv_iv(i["price"], i["F"], i["K"], i["r"], i["t"], i["flag"])
            out.append((
                iv,
                pyvg.delta(i["flag"], i["F"], i["K"], i["t"], i["r"], iv),
                pyvg.gamma(i["flag"], i["F"], i["K"], i["t"], i["r"], iv),
                pyvg.theta(i["flag"], i["F"], i["K"], i["t"], i["r"], iv),
                pyvg.vega(i["flag"], i["F"], i["K"], i["t"], i["r"], iv),
                pyvg.rho(i["flag"], i["F"], i["K"], i["t"], i["r"], iv),
            ))
        return out

    def chain_og():
        out = []
        for i in inputs:
            iv = ogb.implied_volatility(i["price"], i["F"], i["K"], i["r"], i["t"], i["flag"])
            out.append((
                iv,
                ogb.delta(i["flag"], i["F"], i["K"], i["t"], i["r"], iv),
                ogb.gamma(i["flag"], i["F"], i["K"], i["t"], i["r"], iv),
                ogb.theta(i["flag"], i["F"], i["K"], i["t"], i["r"], iv),
                ogb.vega(i["flag"], i["F"], i["K"], i["t"], i["r"], iv),
                ogb.rho(i["flag"], i["F"], i["K"], i["t"], i["r"], iv),
            ))
        return out

    # warmup
    chain_pyv(); chain_og()

    runs = 200
    samples_pyv = []
    samples_og = []
    for _ in range(runs):
        t0 = time.perf_counter_ns(); chain_pyv(); samples_pyv.append(time.perf_counter_ns() - t0)
        t0 = time.perf_counter_ns(); chain_og(); samples_og.append(time.perf_counter_ns() - t0)
    samples_pyv.sort(); samples_og.sort()
    return {
        "n_options": len(inputs),
        "iterations": runs,
        "pyvollib_median_ms": samples_pyv[runs // 2] / 1e6,
        "opengreeks_median_ms": samples_og[runs // 2] / 1e6,
        "speedup": (samples_pyv[runs // 2] / samples_og[runs // 2]),
    }


def main():
    print("Running parity check on 40 baseline samples...")
    parity = run_parity()
    print("Running per-function speedup bench on ATM sample (5000 reps each)...")
    speedup = run_speedup()
    print("Running full-chain timing (IV + 5 Greeks × 40 strikes, 200 iters)...")
    chain = run_chain_speedup()

    out = {
        "engine_a": "py_vollib==1.0.1",
        "engine_b": "opengreeks==0.1.0",
        "parity": parity,
        "per_function_speedup": speedup,
        "chain_speedup": chain,
    }
    with open(OUT_JSON, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved → {OUT_JSON}")

    # Print summary
    print("\n=== per-function speedup (ATM call, microseconds) ===")
    print(f"{'function':<22}{'py_vollib (µs)':>16}{'opengreeks (µs)':>18}{'speedup':>12}")
    for r in speedup:
        print(f"{r['function']:<22}{r['pyvollib_us']:>16.3f}{r['opengreeks_us']:>18.3f}{r['speedup']:>11.1f}x")

    print(f"\n=== chain refresh (40 options, IV+5 Greeks) ===")
    print(f"py_vollib  : {chain['pyvollib_median_ms']:.3f} ms")
    print(f"opengreeks : {chain['opengreeks_median_ms']:.3f} ms")
    print(f"speedup    : {chain['speedup']:.1f}x")

    # Parity summary
    print("\n=== parity max-abs error vs py_vollib (across 40 samples) ===")
    for name in ("iv", "delta", "gamma", "theta", "vega", "rho"):
        if name == "iv":
            errs = [r["iv_abs_err"] for r in parity if r["iv_abs_err"] is not None]
        else:
            errs = [r["greeks"][name]["abs_err"] for r in parity if r.get("greeks") and r["greeks"].get(name) and r["greeks"][name]["abs_err"] is not None]
        if errs:
            print(f"  {name:<6}: max {max(errs):.3e}")


if __name__ == "__main__":
    main()
