# Historical data — the most repeatedly-wrong part of an integration

`get_history` looks simple and is not. Every broker differs on timestamps,
chunking, endpoint shape, and date boundaries, and every one of those
differences fails *silently* — you get a DataFrame, just the wrong one. All
observations below are measured from `broker/{zerodha,upstox,fyers,dhan,flattrade}/api/data.py`.

The contract: return a pandas DataFrame with columns
`[timestamp, open, high, low, close, volume, oi]`, `timestamp` in **epoch
seconds**. `history_service` ships it via `df.to_dict(orient="records")`, so
your epoch convention is what the user sees.

## 1. Timestamps — daily and intraday are not the same

The convention to match (zerodha is canonical):

- **intraday** (minutes/hours): true UTC epoch of the IST candle time — no shift
- **daily**: shift **+5:30** so the candle represents IST midnight

```python
final_df["timestamp"] = pd.to_datetime(final_df["timestamp"], format="ISO8601")
if timeframe == "D":
    final_df["timestamp"] = final_df["timestamp"] + pd.Timedelta(hours=5, minutes=30)
final_df["timestamp"] = final_df["timestamp"].astype("int64") // 10**9
```

**Check what the broker already returns before converting anything.** Fyers
returns epoch directly and does no conversion at all — applying the zerodha
recipe there double-shifts every daily candle by 5:30. Dhan adds the offset as
raw seconds (`+ 19800`). Upstox and flattrade use `timedelta(hours=5, minutes=30)`.

Diagnostic: a daily candle landing at 18:30 the previous day means the shift is
missing; one landing at 05:30 means it was applied twice.

## 2. Chunk limits differ by roughly 80x

Every broker caps the date range per request, and you must loop. Real values:

| Broker | Daily | Minute / hour | Other |
| --- | --- | --- | --- |
| zerodha | 2000 days | 60 days | — |
| upstox | 3650 days | 30 (<=15m), 90 (>15m, hours) | 7300 for W/M |
| fyers | 300 days | 60 days | 25 days for seconds |
| dhan | 90 days | 90 days | — |
| flattrade | no chunking implemented | | |

Upstox keys its limits off `(unit, interval)` rather than a single number —
copy that shape if your broker's cap varies by interval.

**NUANCE — calendar days vs trading days.** Fyers' seconds cap is 30 *trading*
days; the plugin chunks 25 *calendar* days deliberately, to stay under it. A
chunk sized in calendar days against a trading-day quota silently overruns
around holiday clusters. Leave margin.

## 2a. The long-range download loop

Fetching 5 years of 1-minute data means ~30 sequential requests. The shape all
the working plugins share:

```python
chunk_days = 2000 if resolution == "day" else 60      # per-broker
current_start, dfs = start_date, []
while current_start <= end_date:
    current_end = min(current_start + timedelta(days=chunk_days - 1), end_date)
    ...fetch, append DataFrame...
    current_start = current_end + timedelta(days=1)

final_df = pd.concat(dfs, ignore_index=True)
# ...timestamp conversion...
final_df = final_df.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="first")
```

Details that matter:

- **`chunk_days - 1` on the end, `+ 1 day` on the next start.** Off-by-one here
  either duplicates the boundary day or drops it. The `drop_duplicates` at the
  end is the safety net, not the fix.
- **Always `sort_values` then `drop_duplicates(subset=["timestamp"])`.** Chunks
  can overlap at the seams and can arrive out of order.
- **Send day-boundary times, not bare dates** — zerodha uses
  `%Y-%m-%d+00:00:00` and `%Y-%m-%d+23:59:59` so the first and last sessions are
  not clipped.
- **Request OI explicitly if it is opt-in** (zerodha needs `&oi=1`; without it
  the column comes back empty for F&O).
- **Return the empty 7-column DataFrame** when no chunk yielded data, so callers
  can rely on the schema.

### NUANCE — most history loops are NOT throttled

Zerodha and upstox call `time.sleep` only in their **multiquote batch** loops;
their history chunk loops fire back to back. That is fine for a few chunks and
will hit the broker's historical rate limit on a multi-year 1-minute pull.

A long history pull is the single most likely thing to trip the broker's rate
limit, and a naive fixed-gap limiter turns parallel fetches into a serial crawl
(flattrade measured 45 symbols at ~25s before its limiter was rewritten). Pick
the pacing strategy that matches the broker's published limit shape — see
**`references/rate-limiting.md`** for the three patterns (fyers global, dhan
per-category, flattrade dual rolling window) and the invariants they share.

### NUANCE — a failed chunk can become a silent data gap

Fyers retries a chunk with exponential backoff, and **on exhausting retries it
advances to the next chunk and continues** rather than raising. The caller gets
a DataFrame with a hole in it and no error. If you copy that pattern, at minimum
log the skipped range loudly; preferably fail the request. A silently
short series is worse than an error, because it looks like a market holiday.

## 3. Intraday and daily may be different endpoints

- **upstox**: `/historical-candle/intraday/{symbol}/{unit}/{interval}` and
  `/historical-candle/{symbol}/{unit}/{interval}/{to_date}/{from_date}`
- **dhan**: `/v2/charts/intraday` and `/v2/charts/historical`
- **zerodha, fyers, flattrade**: one endpoint for both

If you wire only one, you lose either the current day or all history. Check for
a second route before assuming.

**NUANCE — upstox's path is `{to_date}/{from_date}`**, reversed from the
obvious order. Getting it backwards returns empty data, not an error.

## 4. Today's candle is usually missing from daily history

The daily endpoint typically excludes the in-progress session. Three of the five
plugins patch it explicitly, from **different** sources:

- **dhan** — fetches the current day from the **quotes API** and appends it
- **upstox** — falls back to the **v3 intraday endpoint** for the current day
- **flattrade** — checks `df["timestamp"].max() < today_ts` and appends
- **zerodha, fyers** — no workaround

Always test a range whose `end_date` is today, and confirm the last row is
today. This is the single most common "the chart is a day behind" bug.

## 5. Date boundaries are inclusive or exclusive, not both

Dhan and upstox add `+ timedelta(days=1)` to the end date to make it inclusive.
Verify by requesting a single day (`start == end`) and confirming you get that
day's candles rather than nothing.

## 6. Timeframe coverage is not uniform

| | Seconds | Minutes | Hours | D | W/M |
| --- | --- | --- | --- | --- | --- |
| zerodha | - | 1,3,5,10,15,30,60 | via 60m | yes | **no** |
| upstox | - | 1,2,3,5,10,15,30,60 | 1,2,3,4 | yes | **yes** |
| fyers | **5,10,15,30,45s** | 1,2,3,5,10,15,20,30 | 1,2,4 | yes | no |
| dhan | - | 1,5,15,**25**,60 | via 60m | yes | no |
| flattrade | - | 1,3,5,10,15,30 | 1,2 | yes | no |

- **Only upstox supports W and M.** A `if timeframe in ("D","W","M")` guard is
  wrong for the other four — they never receive W or M.
- **Zerodha has no native hourly**; `1h` is aliased onto `60minute`.
- **Fyers is the only one with sub-minute data**, and it carries an extra
  ~30-day lookback ceiling.
- Only expose what the broker actually serves. `timeframe_map` keys are what
  `intervals_service` advertises, so a key you cannot fulfil becomes a runtime
  failure in the UI.

## 7. The OI column is conditional

Fyers returns **6 columns for equity and 7 (with OI) for derivatives** — the
parser branches on which. Assuming 7 columns breaks equity; assuming 6 loses OI
on F&O. Normalize to the full 7-column contract, filling `oi` with 0 where the
broker omits it.

## Verification

- [ ] Daily candles land at IST midnight; intraday candles at the true IST bar time
- [ ] Round-trip one known candle against the broker's own web chart
- [ ] A range longer than the chunk limit returns continuous data with no gaps at chunk seams and no duplicate rows
- [ ] `end_date = today` includes today's candle
- [ ] `start == end` returns that single day
- [ ] Equity **and** an F&O symbol both return all 7 columns
- [ ] Every key in `timeframe_map` actually returns data
- [ ] Index symbols work (volume is often 0 — that is correct, not a bug)
- [ ] A multi-year 1-minute pull completes without tripping the rate limit
- [ ] A forced chunk failure surfaces as an error, not a silent hole in the series

## When the broker has no historical API at all

`broker/kotak/` is the case in point: Kotak Neo serves no historical data, so
`get_history` is a placeholder that logs a warning and `timeframe_map` is empty.
That is a legitimate integration — do not fake it by stitching candles from
quotes. Leave `timeframe_map` empty so `intervals_service` advertises nothing,
and let the UI show the capability as absent rather than broken.
