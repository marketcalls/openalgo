#!/usr/bin/env python3
"""
OpenAlgo resource-leak soak test.

Drives a code path repeatedly against a RUNNING instance while sampling file
descriptors and RSS, then classifies the trend: leak, cache fill, or clean.

Stdlib only -- no install step, runs anywhere the app runs.

    # Passive: just watch the worker for 10 minutes
    python .claude/skills/fd-audit/soak.py --duration 600

    # Drive a public endpoint 300 times
    python .claude/skills/fd-audit/soak.py --url http://127.0.0.1:5000/ -n 300

    # Drive an authenticated /api/v1 endpoint
    python .claude/skills/fd-audit/soak.py \\
        --url http://127.0.0.1:5000/api/v1/quotes \\
        --api-key YOUR_KEY --json '{"symbol":"RELIANCE","exchange":"NSE"}' -n 300

    # Drive an arbitrary command instead of HTTP
    python .claude/skills/fd-audit/soak.py --cmd "uv run python myscript.py" -n 50

Read-only with respect to the app: it never restarts or reconfigures anything.
Point it at a DEV instance -- an authenticated run places real API calls if you
aim it at an order endpoint.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shlex
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

IS_LINUX = platform.system() == "Linux"


# --------------------------------------------------------------------------
# Process discovery and sampling
# --------------------------------------------------------------------------
def find_pid() -> int | None:
    """Locate the OpenAlgo worker. Prefers the gunicorn worker over the master."""
    for pattern in (r"gunicorn.*app:app", r"[p]ython.*app\.py"):
        try:
            out = subprocess.run(["pgrep", "-f", pattern], capture_output=True,
                                 text=True, check=False).stdout.split()
        except FileNotFoundError:
            return None
        pids = [int(p) for p in out if p.isdigit()]
        if not pids:
            continue
        if len(pids) == 1:
            return pids[0]
        # With gunicorn the master spawns workers; the worker has the FDs.
        # Highest PID is almost always the most recently spawned worker.
        return max(pids)
    return None


def fd_list(pid: int) -> list[str]:
    """Return one descriptor descriptor-type token per open FD."""
    if IS_LINUX:
        fddir = Path(f"/proc/{pid}/fd")
        try:
            out = []
            for link in fddir.iterdir():
                try:
                    target = os.readlink(link)
                except OSError:
                    target = "unknown"
                if target.startswith("socket:"):
                    out.append("socket")
                elif target.startswith("pipe:"):
                    out.append("pipe")
                elif target.startswith("anon_inode:"):
                    out.append("anon_inode")
                elif target.endswith((".db", ".duckdb", ".sqlite")):
                    out.append("database")
                elif "/log/" in target or target.endswith(".log"):
                    out.append("logfile")
                else:
                    out.append("file")
            return out
        except (OSError, PermissionError):
            return []
    # macOS
    try:
        res = subprocess.run(["lsof", "-p", str(pid)], capture_output=True,
                             text=True, check=False)
    except FileNotFoundError:
        return []
    out = []
    for line in res.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 5:
            continue
        t = parts[4]
        name = parts[-1] if parts else ""
        if t in ("IPv4", "IPv6", "unix"):
            out.append("socket")
        elif t == "PIPE":
            out.append("pipe")
        elif t == "KQUEUE":
            out.append("anon_inode")
        elif name.endswith((".db", ".duckdb", ".sqlite")):
            out.append("database")
        elif "/log/" in name or name.endswith(".log"):
            out.append("logfile")
        elif t in ("REG", "DIR", "CHR"):
            out.append("file")
        else:
            out.append("other")
    return out


def rss_kb(pid: int) -> int:
    if IS_LINUX:
        try:
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
        except OSError:
            return 0
        return 0
    try:
        res = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)],
                             capture_output=True, text=True, check=False)
        return int(res.stdout.strip() or 0)
    except (FileNotFoundError, ValueError):
        return 0


def thread_count(pid: int) -> int:
    if IS_LINUX:
        try:
            return len(list(Path(f"/proc/{pid}/task").iterdir()))
        except OSError:
            return 0
    try:
        res = subprocess.run(["ps", "-M", "-p", str(pid)], capture_output=True,
                             text=True, check=False)
        return max(len(res.stdout.strip().splitlines()) - 1, 0)
    except FileNotFoundError:
        return 0


def sample(pid: int) -> dict:
    fds = fd_list(pid)
    return {
        "t": time.time(),
        "fd_total": len(fds),
        "fd_by_type": Counter(fds),
        "rss_kb": rss_kb(pid),
        "threads": thread_count(pid),
    }


# --------------------------------------------------------------------------
# Load drivers
# --------------------------------------------------------------------------
def drive_http(url: str, payload: dict | None, api_key: str | None,
               timeout: float) -> tuple[bool, str]:
    data, headers = None, {"User-Agent": "openalgo-soak/1.0"}
    if payload is not None or api_key:
        body = dict(payload or {})
        if api_key:
            body["apikey"] = api_key
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
            return True, str(resp.status)
    except urllib.error.HTTPError as e:
        try:
            e.read()
        except Exception:
            pass
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, type(e).__name__


def drive_cmd(cmd: str, timeout: float) -> tuple[bool, str]:
    try:
        p = subprocess.run(shlex.split(cmd), capture_output=True,
                           timeout=timeout, check=False)
        return p.returncode == 0, f"rc={p.returncode}"
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, type(e).__name__


# --------------------------------------------------------------------------
# Trend classification
# --------------------------------------------------------------------------
def slope_per_iter(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Least-squares slope and r^2. xs is iteration index, ys the metric."""
    n = len(xs)
    if n < 3:
        return 0.0, 0.0
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, 0.0
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    syy = sum((y - my) ** 2 for y in ys)
    r2 = (sxy ** 2) / (sxx * syy) if syy > 0 else 0.0
    return slope, r2


def classify(name: str, xs: list[float], ys: list[float], per_unit: str,
             leak_threshold: float) -> tuple[str, str]:
    """LEAK / CACHE-FILL / CLEAN, with the reasoning."""
    if len(ys) < 3:
        return "UNKNOWN", "too few samples"
    first, last, peak = ys[0], ys[-1], max(ys)
    delta = last - first
    slope, r2 = slope_per_iter(xs, ys)

    # Compare growth in the first half against the second half. A cache fills
    # early then flattens; a leak keeps climbing at the same rate.
    mid = len(ys) // 2
    s1, _ = slope_per_iter(xs[:mid + 1], ys[:mid + 1])
    s2, _ = slope_per_iter(xs[mid:], ys[mid:])

    if delta <= leak_threshold:
        return "CLEAN", f"net change {delta:+.0f} over the run"
    if s2 <= max(s1 * 0.25, 0) or last < peak * 0.98:
        return "CACHE-FILL", (
            f"grew {delta:+.0f} then flattened "
            f"(early {s1:+.3f}/{per_unit}, late {s2:+.3f}/{per_unit})")
    if r2 >= 0.75 and slope > 0:
        return "LEAK", (
            f"linear growth {slope:+.3f} {name}/{per_unit} "
            f"(r2={r2:.2f}), net {delta:+.0f}")
    return "SUSPECT", (
        f"grew {delta:+.0f} but the trend is noisy "
        f"(slope {slope:+.3f}/{per_unit}, r2={r2:.2f}) -- rerun longer")


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="OpenAlgo resource-leak soak test")
    ap.add_argument("--pid", type=int, help="target PID (default: auto-detect)")
    ap.add_argument("--url", help="HTTP endpoint to drive")
    ap.add_argument("--json", dest="payload", help="JSON body for the request")
    ap.add_argument("--api-key", help="OpenAlgo API key, injected as 'apikey'")
    ap.add_argument("--cmd", help="shell command to run per iteration instead of HTTP")
    ap.add_argument("-n", "--iterations", type=int, default=200)
    ap.add_argument("--duration", type=int, help="passive watch for N seconds (no driver)")
    ap.add_argument("--interval", type=float, default=0.0, help="delay between iterations")
    ap.add_argument("--samples", type=int, default=20, help="metric samples across the run")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--settle", type=float, default=2.0,
                    help="seconds to wait before the final sample, for GC/close")
    args = ap.parse_args()

    pid = args.pid or find_pid()
    if not pid:
        print("Could not find a running OpenAlgo process. Start it, or pass --pid.",
              file=sys.stderr)
        return 2
    try:
        os.kill(pid, 0)
    except OSError:
        print(f"PID {pid} is not running.", file=sys.stderr)
        return 2

    probe = sample(pid)
    if probe["fd_total"] == 0:
        print(f"Cannot read descriptors for PID {pid}. On macOS try sudo, "
              f"or run as the same user as the worker.", file=sys.stderr)
        return 2

    payload = json.loads(args.payload) if args.payload else None
    passive = args.duration is not None
    total = args.iterations if not passive else args.samples
    every = max(1, total // max(args.samples, 1))

    print(f"OpenAlgo soak test -- {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  target PID : {pid}")
    if passive:
        print(f"  mode       : passive watch, {args.duration}s")
    elif args.cmd:
        print(f"  driver     : cmd  {args.cmd}")
        print(f"  iterations : {args.iterations}")
    elif args.url:
        print(f"  driver     : {'POST' if (payload or args.api_key) else 'GET'} {args.url}")
        print(f"  iterations : {args.iterations}")
    else:
        print("  driver     : none (use --url, --cmd, or --duration)", file=sys.stderr)
        return 2
    print(f"  baseline   : {probe['fd_total']} fds, "
          f"{probe['rss_kb'] / 1024:.1f} MB rss, {probe['threads']} threads\n")

    samples, errors = [probe], Counter()
    idx = []

    if passive:
        step = args.duration / max(args.samples, 1)
        for i in range(args.samples):
            time.sleep(step)
            samples.append(sample(pid))
            idx.append(i + 1)
            s = samples[-1]
            print(f"  t={int((i + 1) * step):>5}s  fds={s['fd_total']:<6} "
                  f"rss={s['rss_kb'] / 1024:>8.1f}MB  threads={s['threads']}")
    else:
        for i in range(1, args.iterations + 1):
            if args.cmd:
                ok, note = drive_cmd(args.cmd, args.timeout)
            else:
                ok, note = drive_http(args.url, payload, args.api_key, args.timeout)
            if not ok:
                errors[note] += 1
            if args.interval:
                time.sleep(args.interval)
            if i % every == 0 or i == args.iterations:
                samples.append(sample(pid))
                idx.append(i)
                s = samples[-1]
                print(f"  iter={i:<6} fds={s['fd_total']:<6} "
                      f"rss={s['rss_kb'] / 1024:>8.1f}MB  threads={s['threads']}")

    # Let deferred closes and GC settle before the final reading.
    time.sleep(args.settle)
    final = sample(pid)
    samples.append(final)
    idx.append((idx[-1] if idx else 0) + 1)

    xs = [float(i) for i in idx]
    unit = "sample" if passive else "iter"
    print("\n" + "=" * 68)
    print("VERDICT")
    print("=" * 68)

    rows = [
        ("descriptors", [s["fd_total"] for s in samples[1:]], 4.0),
        ("rss_kb", [s["rss_kb"] for s in samples[1:]], 8192.0),  # 8 MB noise floor
        ("threads", [s["threads"] for s in samples[1:]], 1.0),
    ]
    worst = "CLEAN"
    for name, ys, thresh in rows:
        verdict, why = classify(name, xs, [float(y) for y in ys], unit, thresh)
        label = name if name != "rss_kb" else "memory (rss)"
        print(f"  {label:<16} {verdict:<11} {why}")
        if verdict == "LEAK" or (verdict == "SUSPECT" and worst != "LEAK"):
            worst = verdict

    # Which descriptor class grew tells you what to go and look at.
    base_types, final_types = samples[0]["fd_by_type"], final["fd_by_type"]
    grown = {k: final_types.get(k, 0) - base_types.get(k, 0)
             for k in set(base_types) | set(final_types)}
    grown = {k: v for k, v in sorted(grown.items(), key=lambda kv: -kv[1]) if v > 0}
    if grown:
        print("\n  descriptor growth by type:")
        hint = {
            "socket": "HTTP client, WebSocket adapter, or ZMQ socket not closed",
            "database": "SQLAlchemy session or DuckDB connection not released",
            "pipe": "subprocess with PIPE stdout not drained or not reaped",
            "logfile": "log handler opened per call instead of once",
            "anon_inode": "selector/epoll or eventlet hub object retained",
            "file": "file opened without a context manager",
        }
        for k, v in grown.items():
            print(f"    {k:<12} +{v:<5} {hint.get(k, '')}")

    if errors:
        print("\n  driver errors (a failing driver invalidates the run):")
        for k, v in errors.most_common(5):
            print(f"    {k:<24} {v}")

    print(f"\n  baseline {samples[0]['fd_total']} fds / "
          f"{samples[0]['rss_kb'] / 1024:.1f} MB  ->  final {final['fd_total']} fds / "
          f"{final['rss_kb'] / 1024:.1f} MB")

    if worst == "LEAK":
        print("\n  LEAK: growth is linear and did not plateau. Identify the resource "
              "from the type breakdown above, then audit that acquisition site's "
              "success, exception AND retry paths (see the fd-audit skill).")
        return 1
    if worst == "SUSPECT":
        print("\n  INCONCLUSIVE: rerun with more iterations (-n 1000) before "
              "concluding either way.")
        return 1
    print("\n  No leak detected. Growth, if any, plateaued -- consistent with a "
          "bounded cache rather than a leak.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
