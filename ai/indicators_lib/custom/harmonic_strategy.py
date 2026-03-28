"""
Harmonic Pattern Strategy using pyharmonics + manual ZigZag
Scans RELIANCE OHLCV data across all timeframes for XABCD harmonic patterns.

Outputs:
  - Per-timeframe CSV with harmonic signal columns merged into OHLCV
  - _ALL_PATTERNS.csv summary of every pattern found
  - Per-timeframe pyharmonics results (XABCD, ABCD, ABC families)

Usage:
    python harmonic_strategy.py              # Scan all timeframes
    python harmonic_strategy.py --scan-all   # Same
    python harmonic_strategy.py --file path/to/file.csv
"""

import pandas as pd
import numpy as np
import os
import sys
import glob
from pathlib import Path

DATA_DIR = Path(__file__).parent / "indicator_data" / "reliance_timeframes"
OUTPUT_DIR = Path(__file__).parent / "harmonic_results"
OUTPUT_DIR.mkdir(exist_ok=True)

# pyharmonics interval mapping
PH_INTERVALS = {
    '1m': '1',  '3m': '3',  '5m': '5',  '15m': '15', '30m': '30',
    '1hr': '60', '2hr': '120', '4hr': '240', '1day': '1d', '1month': '1M',
}


def load_ohlcv(filepath):
    df = pd.read_csv(filepath)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df.set_index('datetime', inplace=True)
    return df


def detect_timeframe_label(filename):
    """Extract timeframe label from filename like RELIANCE_1day_7772bars.csv"""
    parts = filename.replace('.csv', '').split('_')
    if len(parts) >= 2:
        return parts[1]  # e.g. '1day', '1hr', '4hr'
    return '1day'


# ──────────────────────────────────────────────────────────────────
# Method 1: pyharmonics (library-based XABCD, ABCD, ABC detection)
# ──────────────────────────────────────────────────────────────────
def scan_pyharmonics(df, label, interval_code):
    from pyharmonics.technicals import OHLCTechnicals
    from pyharmonics.search import HarmonicSearch

    print(f"\n  [pyharmonics] Scanning {label}...")

    # Adjust peak_spacing based on timeframe
    spacing_map = {'1m': 3, '3m': 4, '5m': 5, '15m': 6, '30m': 6,
                   '1hr': 6, '2hr': 8, '4hr': 10, '1day': 6, '1month': 4}
    tf_label = detect_timeframe_label(label)
    peak_spacing = spacing_map.get(tf_label, 6)

    tech = OHLCTechnicals(df, 'RELIANCE', interval_code, peak_spacing=peak_spacing)
    hs = HarmonicSearch(tech, fib_tolerance=0.05)
    hs.search()

    formed = hs.get_patterns(formed=True)
    forming = hs.get_patterns(formed=False)

    all_patterns = []

    for family, patterns in formed.items():
        for p in patterns:
            d = p.to_dict()
            row = {
                'family': family,
                'name': d['name'],
                'bullish': d['bullish'],
                'formed': True,
                'timeframe': label,
            }
            # Extract XABCD points
            dates = d.get('x', [])
            prices = d.get('y', [])
            for i, point_name in enumerate(['X', 'A', 'B', 'C', 'D']):
                if i < len(dates):
                    row[f'{point_name}_date'] = str(dates[i])
                    row[f'{point_name}_price'] = float(prices[i])
            # Retraces
            for k, v in d.get('retraces', {}).items():
                row[f'retrace_{k}'] = round(float(v), 4)
            row['completion_min'] = float(d.get('completion_min_price', 0))
            row['completion_max'] = float(d.get('completion_max_price', 0))
            all_patterns.append(row)

    for family, patterns in forming.items():
        for p in patterns:
            d = p.to_dict()
            row = {
                'family': family,
                'name': d['name'],
                'bullish': d['bullish'],
                'formed': False,
                'timeframe': label,
            }
            dates = d.get('x', [])
            prices = d.get('y', [])
            for i, point_name in enumerate(['X', 'A', 'B', 'C', 'D']):
                if i < len(dates):
                    row[f'{point_name}_date'] = str(dates[i])
                    row[f'{point_name}_price'] = float(prices[i])
            for k, v in d.get('retraces', {}).items():
                row[f'retrace_{k}'] = round(float(v), 4)
            row['completion_min'] = float(d.get('completion_min_price', 0))
            row['completion_max'] = float(d.get('completion_max_price', 0))
            all_patterns.append(row)

    formed_count = sum(1 for p in all_patterns if p['formed'])
    forming_count = sum(1 for p in all_patterns if not p['formed'])

    # Count by family
    xabcd = [p for p in all_patterns if p['family'] == 'XABCD']
    abcd = [p for p in all_patterns if p['family'] == 'ABCD']
    abc = [p for p in all_patterns if p['family'] == 'ABC']

    print(f"    Formed: {formed_count}, Forming: {forming_count}")
    print(f"    XABCD: {len(xabcd)}, ABCD: {len(abcd)}, ABC: {len(abc)}")

    # Show notable XABCD patterns
    for p in xabcd[:5]:
        direction = 'BULL' if p['bullish'] else 'BEAR'
        print(f"    {direction} {p['name']}: X={p.get('X_price','')} → D={p.get('D_price','')}")

    return all_patterns


# ──────────────────────────────────────────────────────────────────
# Method 2: Manual ZigZag harmonic (gives per-bar ML signal columns)
# ──────────────────────────────────────────────────────────────────
HARMONIC_RATIOS = {
    'Gartley':   {'XB': (0.618, 0.618), 'AC': (0.382, 0.886), 'BD': (1.272, 1.618), 'XD': (0.786, 0.786)},
    'Bat':       {'XB': (0.382, 0.500), 'AC': (0.382, 0.886), 'BD': (1.618, 2.618), 'XD': (0.886, 0.886)},
    'Butterfly': {'XB': (0.786, 0.786), 'AC': (0.382, 0.886), 'BD': (1.618, 2.618), 'XD': (1.272, 1.618)},
    'Crab':      {'XB': (0.382, 0.618), 'AC': (0.382, 0.886), 'BD': (2.240, 3.618), 'XD': (1.618, 1.618)},
    'Shark':     {'XB': (0.382, 0.618), 'AC': (1.130, 1.618), 'BD': (1.618, 2.236), 'XD': (0.886, 1.130)},
    'Cypher':    {'XB': (0.382, 0.618), 'AC': (1.130, 1.414), 'BD': (1.272, 2.000), 'XD': (0.786, 0.786)},
    'ABCD':      {'XB': (0.000, 1.000), 'AC': (0.618, 0.786), 'BD': (1.272, 1.618), 'XD': (0.000, 2.000)},
}
TOLERANCE = 0.08


def ratio_ok(actual, lo, hi):
    return lo * (1 - TOLERANCE) <= actual <= hi * (1 + TOLERANCE)


def zigzag_scan(df, label):
    print(f"\n  [zigzag] Scanning {label} ({len(df)} bars)...")

    h = df['high'].values
    l = df['low'].values
    c = df['close'].values
    n = len(df)

    # Adaptive threshold based on data range
    price_range = (h.max() - l.min()) / l.min()
    pct = max(0.015, min(0.05, price_range / 50))

    pivots = []
    last_type = None
    last_price = c[0]

    for i in range(1, n):
        if h[i] >= last_price * (1 + pct) and last_type != 'H':
            pivots.append((i, h[i], 'H'))
            last_type, last_price = 'H', h[i]
        elif l[i] <= last_price * (1 - pct) and last_type != 'L':
            pivots.append((i, l[i], 'L'))
            last_type, last_price = 'L', l[i]
        else:
            if last_type == 'H' and h[i] > last_price:
                pivots[-1] = (i, h[i], 'H')
                last_price = h[i]
            elif last_type == 'L' and l[i] < last_price:
                pivots[-1] = (i, l[i], 'L')
                last_price = l[i]

    print(f"    Swing points: {len(pivots)}")

    # Per-bar signal columns
    signals = pd.DataFrame(index=df.index)
    signals['harmonic_bullish'] = 0
    signals['harmonic_bearish'] = 0
    signals['harmonic_pattern'] = ''
    signals['harmonic_D_price'] = np.nan

    results = []

    for i in range(4, len(pivots)):
        Xi, Xp, _ = pivots[i - 4]
        Ai, Ap, _ = pivots[i - 3]
        Bi, Bp, _ = pivots[i - 2]
        Ci, Cp, _ = pivots[i - 1]
        Di, Dp, Dt = pivots[i]

        XA = abs(Ap - Xp)
        if XA == 0:
            continue
        AB = abs(Bp - Ap)
        BC = abs(Cp - Bp)
        CD = abs(Dp - Cp)

        xb = AB / XA
        ac = BC / AB if AB > 0 else 0
        bd = CD / BC if BC > 0 else 0
        xd = abs(Dp - Xp) / XA

        for pname, ratios in HARMONIC_RATIOS.items():
            if (ratio_ok(xb, *ratios['XB']) and ratio_ok(ac, *ratios['AC']) and
                    ratio_ok(bd, *ratios['BD']) and ratio_ok(xd, *ratios['XD'])):
                is_bull = Dt == 'L'
                results.append({
                    'direction': 'BULLISH' if is_bull else 'BEARISH',
                    'pattern': pname,
                    'D_bar': Di,
                    'D_date': str(df.index[Di]) if Di < n else '',
                    'X': round(Xp, 2), 'A': round(Ap, 2),
                    'B': round(Bp, 2), 'C': round(Cp, 2), 'D': round(Dp, 2),
                    'XB': round(xb, 3), 'AC': round(ac, 3),
                    'BD': round(bd, 3), 'XD': round(xd, 3),
                })
                if Di < n:
                    if is_bull:
                        signals.iloc[Di, 0] = 1
                    else:
                        signals.iloc[Di, 1] = 1
                    signals.iloc[Di, 2] = pname
                    signals.iloc[Di, 3] = Dp

    bull = sum(1 for r in results if r['direction'] == 'BULLISH')
    bear = sum(1 for r in results if r['direction'] == 'BEARISH')
    print(f"    Patterns: {len(results)} ({bull} bull, {bear} bear)")
    for r in results[:5]:
        print(f"    {r['direction']} {r['pattern']} @ {r['D_date']}: D={r['D']}")

    return results, signals


# ──────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────
def scan_file(filepath):
    fname = os.path.basename(filepath)
    label = fname.replace('.csv', '')
    tf_label = detect_timeframe_label(fname)

    df = load_ohlcv(filepath)

    print(f"\n{'='*60}")
    print(f"{label} ({len(df)} bars)")
    print('=' * 60)

    # 1. ZigZag method (per-bar signals for ML)
    zz_results, signals = zigzag_scan(df, label)
    merged = df.join(signals)
    merged.to_csv(OUTPUT_DIR / f"{label}_harmonic_signals.csv")

    # 2. pyharmonics (library patterns)
    ph_results = []
    try:
        interval_code = PH_INTERVALS.get(tf_label, '1d')
        ph_results = scan_pyharmonics(df, label, interval_code)
        if ph_results:
            pd.DataFrame(ph_results).to_csv(
                OUTPUT_DIR / f"{label}_pyharmonics.csv", index=False)
    except Exception as e:
        print(f"    pyharmonics error: {e}")

    return zz_results, ph_results


def scan_all():
    csv_files = sorted(glob.glob(str(DATA_DIR / "RELIANCE_*.csv")))
    if not csv_files:
        print(f"No CSV files in {DATA_DIR}")
        return

    all_zz = []
    all_ph = []

    for filepath in csv_files:
        zz, ph = scan_file(filepath)
        fname = os.path.basename(filepath).replace('.csv', '')
        if zz:
            for r in zz:
                r['timeframe'] = fname
            all_zz.extend(zz)
        all_ph.extend(ph)

    # Save combined results
    if all_zz:
        zdf = pd.DataFrame(all_zz)
        zdf.to_csv(OUTPUT_DIR / "_ALL_ZIGZAG_PATTERNS.csv", index=False)
    if all_ph:
        pdf = pd.DataFrame(all_ph)
        pdf.to_csv(OUTPUT_DIR / "_ALL_PYHARMONICS.csv", index=False)

    print(f"\n{'='*60}")
    print("GRAND SUMMARY")
    print('=' * 60)
    print(f"  ZigZag patterns: {len(all_zz)}")
    print(f"  pyharmonics patterns: {len(all_ph)}")
    print(f"\n  Output: {OUTPUT_DIR}/")
    print(f"  Files:")
    for f in sorted(OUTPUT_DIR.glob("*.csv")):
        size = f.stat().st_size / 1024
        print(f"    {f.name} ({size:.0f} KB)")


if __name__ == '__main__':
    if '--file' in sys.argv:
        idx = sys.argv.index('--file')
        scan_file(sys.argv[idx + 1])
    else:
        scan_all()
