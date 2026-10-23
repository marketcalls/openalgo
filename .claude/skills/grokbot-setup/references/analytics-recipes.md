# Analytics recipes, charting and chart screenshots

Recipes proven on the box with the OpenAlgo Python SDK and Historify data. Use
daily data from Historify (section 1 of [historify.md](historify.md)) for long
lookbacks, and `client.history(...)` for intraday or for anything Historify
does not hold.

## Output rules for market analysis

- Give analysis, statistics and a factual summary only. No trade
  recommendations, no "key levels to watch", no "what would change the view"
  lines, unless the user explicitly asks.
- State the window, data source and caveats (sample size, adjustments) in one
  line under each table.

## Recipes

### Weekly return histogram
Resample daily closes to weekly (`W-FRI`, last close), `pct_change()`. For a
distribution, plot a histogram per symbol plus a stats table (mean, std, % up,
best, worst, latest week). For "last week" requests, a single sorted column chart
of the latest week is usually what the user wants.

### Event study (policy announcement, budget, recap)
Pick the announcement date and the first session that could react (rule below).
Compute: reaction-day return (prior close to reaction close), then 6-month and
1-year returns from the reaction close, and also versus the pre-announcement
close. Include the sector index and NIFTY 50 as reference bars. Note symbols
missing from the database (renamed, merged, delisted) instead of silently
dropping them. When explaining later moves, cite sources.

### Post-earnings drift
Reaction-day rule:
- Results **before market open** -> reaction day is the same day.
- Results **during market hours** -> window starts from the **prior day's
  close**.
- Results **after close, or on a weekend/holiday** -> reaction day is the next
  trading session; start from the last close before it.

Report gap %, reaction-day return, drift from reaction close to the latest close,
and abnormal return = stock return minus NIFTY 50 over the same window. Companies
whose reaction day has not traded yet get no number. Check index membership as of
the date (constituents change). With a handful of companies and short windows,
say it is descriptive, not statistically meaningful.

### Dividend and corporate-action caveat
Historify and broker history are not dividend-adjusted. For long windows, check
`get_corporate_actions` or exchange data for splits, bonuses and large dividends
and note or adjust them; renamed tickers need the new symbol.

### Rolling ATM straddle (5m)
For each 5-minute bar, take the underlying (futures or spot) close, round to the
strike step (NIFTY 50), and add that bar's CE and PE closes of the current weekly
expiry at that strike. Re-pick the strike every bar (rolling), fetch each needed
option's 5m history once and cache it. Plot the combined premium with the ATM
strike as a step line underneath.

### Option chain OI by strike and PCR
`client.optionchain(underlying="NIFTY", exchange="NSE_INDEX",
expiry_date="27OCT26", strike_count=40)`. Plot grouped call (red) and put
(green) OI bars per strike, a vertical spot line, and a lower panel of put minus
call OI. PCR = total put OI / total call OI. Report the highest call and put OI
strikes as facts.

### VIX vs historical volatility
INDIAVIX daily close versus 20-day HV of NIFTY (`std(log returns) * sqrt(252) *
100`). Add daily range (high-low %) bars for the month and week/month range
comparisons if asked.

### Top-down analysis
World indices week -> NIFTY 50 and sector indices -> breadth -> stocks inside the
leading and lagging sectors. Use Historify for the daily series; one chart per
layer, a short factual summary at the end.

## Charting conventions

- Vivid dark theme: matplotlib `plt.style.use("dark_background")` or plotly
  `template="plotly_dark"`; bright, saturated colors, not the defaults.
- Column charts sorted best to worst; green for positive, red for negative;
  the index bar (NIFTY 50, NIFTY IT, sector index) highlighted in gold.
- Value labels on each bar, a title with the exact window, source line at the
  bottom. Save PNG at 150-200 dpi and open it with Read to check before sending.

## Screenshots from the /trading UI

- Market profile: on `/trading`, choose the TPO chart type and set the
  timeframe (for example 30m) for the symbol (for example the current month
  NIFTY future).
- Supertrend on candles: add the Supertrend study (default 10, 3) with chart
  type candles.
- Prefer OpenScript studies over JavaScript indicators.
- Capture: if `scrot` and ImageMagick are missing, use ffmpeg:
  `ffmpeg -f x11grab -video_size WxH -i :DISPLAY -frames:v 1 shot.png`, then
  crop with ffmpeg's `crop` filter.
- Always crop out any toolbar or badge that names the broker, and never capture
  funds or margin panels, before sharing.
