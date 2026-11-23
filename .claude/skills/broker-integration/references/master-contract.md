# Master contract — verify against the LIVE symtoken table

`SymToken` columns (canonical, `database/symbol.py`): `id, symbol, brsymbol,
name, exchange, brexchange, token, expiry, strike, lotsize, instrumenttype,
tick_size, contract_value`. **Declare `contract_value`** in your model (left
NULL) so a fresh-install `create_all()` matches the shared table.

Entry point: **`master_contract_download()`** (no args) — download and parse
every segment, validate, replace the table in one transaction, then
`socketio.emit('master_contract_download', {...})`. Release the scoped session
in a `finally:` (`db_session.remove()`) — it runs in a background thread. Do
not empty the table before every segment has arrived: see "a failed refresh
keeps yesterday's symbols" below.

## NUANCES verified against the live zerodha symtoken (do NOT guess)

- **`instrumenttype` is ONLY `EQ` / `FUT` / `CE` / `PE`.** There is **no
  "INDEX"** type — **indices use `EQ`**; the `NSE_INDEX` / `BSE_INDEX` exchange
  is what distinguishes them.
- **Everything on a cash exchange that is not a derivative is `EQ`**: indices,
  government securities, NCDs, warrants, InvIT units, ETFs and every series
  code (BE, SG, GB, N0...), as Kite types them. Fyers stored `GB`, 5paisa `BE`,
  TradeSmart the Noren series column and Kotak a blank-padded `"  "`, and each
  failed MC-04 (#2124, #2195, #2475, #2114). Trim the type column; a row that
  is none of these is `''`, never a padded string.
- **An expiry sentinel (0, -1, epoch) means no expiry.** Read it from the raw
  column before any epoch offset, and clear the type with it: a row with no
  expiry is not a future. Kotak stored 54 rows as `GOLD01JAN70` and
  `EURINR31DEC79FUT` (#2114). Never `fillna("-1")` an expiry (Dhan, #2306).
- **`name` is never blank**: fall back to the tradingsymbol. Kite ships about
  8.2k cash rows with no name (debt series, NCO spot rows), #2123.
- **`expiry` format = `DD-MMM-YY` uppercase** (e.g. `30-JUN-26`), empty string
  `''` for EQ/index. Use `pd.to_datetime(x).strftime("%d-%b-%y").upper()`. This
  drives expiry-dropdown logic elsewhere — get it exact.
- **Symbol construction** (OpenAlgo common format):
  - EQ: bare base symbol (strip broker suffix like `-EQ`, and the series suffix of a stock traded outside EQ; keep `brsymbol` = full broker tradingsymbol). See "series suffixes" below.
  - FUT: `f"{underlying}{DDMMMYY}FUT"` e.g. `NIFTY30JUN26FUT`
  - CE/PE: `f"{underlying}{DDMMMYY}{strike}{CE|PE}"` e.g. `NIFTY09JUN2623100CE`
    (strike preserves decimals: `187.5`, drops `.0` for whole numbers)
  - INDEX: the OpenAlgo index symbol (`NIFTY`, `BANKNIFTY`, `SENSEX`), `brsymbol`
    = broker index name (`NIFTY 50`), exchange `NSE_INDEX`/`BSE_INDEX`
- **`name` column**: underlying for FUT/CE/PE (e.g. `NIFTY`); company/full name
  for EQ; display name for index.
- **`brexchange`** = the raw broker exchange code (kept for quote/history calls);
  `exchange` = OpenAlgo code.
- **Indices**: split the broker's single index space into `NSE_INDEX` /
  `BSE_INDEX` by parent exchange. `GLOBAL_INDEX` is zerodha/upstox-only — omit it
  unless your broker truly has global index feeds.
- **Normalise every index the broker lists, and keep no allow-list copy of the
  canonical list in the plugin.** Dhan's copy predated the indices added in
  #2140, so 56 indices stayed under raw names (#2306). A listed index with no
  canonical name gets one on the existing pattern, added to
  `docs/prompt/symbol-format.md` in the same change.
- **Key a rename table on what the column holds at that stage.** Angel keyed
  `SNSX50` after the symbol had already become `BSESENSEX50`, so SENSEX50
  never resolved (#2290).
- **Where the broker publishes a reference table** (Fyers' index display names
  for its feed), load it at download time with a bundled fallback rather than
  keeping a copy in the repo (#2140).
- **Drop rows OpenAlgo cannot place**: no OpenAlgo exchange (NCDEX indices, CDS
  bond underlyings), no exchange or symbol, or an unusable tradingsymbol. Left
  in, they collide with real rows (Angel #2290, Flattrade #2198, TradeSmart
  #2475).
- **Duplicate (symbol, exchange) from one contract listed twice: keep the
  newest listing** (highest token), and compare tokens as strings (5paisa
  #2195, Firstock #2198).
- **The canonical index symbol lists are in `docs/prompt/symbol-format.md`** —
  it enumerates the expected NSE_INDEX, BSE_INDEX, MCX_INDEX, NCO and
  GLOBAL_INDEX symbol sets. Reproduce those exact spellings; the options tools
  and expiry dropdowns look symbols up by them.
- **`MCX_INDEX` exists in `symbol-format.md` and in zerodha's
  `supported_exchanges`, but is NOT listed in `docs/prompt/order-constants.md`.**
  It is quote-only. Don't be surprised by the gap, and don't add it to
  `plugin.json` unless the broker really serves MCX index quotes.
- **NEVER hardcode market timings** in the broker folder. (Day-boundary strings
  like `00:00:00`/`23:59:59` for history `from`/`to` params are fine.)

## NUANCE — a failed refresh keeps yesterday's symbols

The download runs in a background thread and its failures are easy to swallow.
Fyers' downloader returned a success flag nobody read; Kotak, Shoonya,
Flattrade, Firstock and Tradejini each emptied symtoken before every segment
had arrived. One failed file left that segment, or the whole table, empty while
the status page said success (#2108, #2198, #2235).

- Download and parse every segment first. Raise on a failed download, an empty
  file, or a known segment that parses to zero rows.
- Only then replace the table, in one transaction, so a failed insert rolls
  back to the previous contract (`replace_symtoken_table` in
  `broker/kotak/database/master_contract_db.py`).
- Re-raise after emitting the socketio error. The shared caller records
  success unless the download raises.
- Download into `tmp/<broker>/` and clear stale files first. Noren brokers
  share file names (`NSE.csv`), so a shared `tmp/` cleanup deletes another
  broker's download, and a stale file from an earlier run must never load as
  today's (Shoonya, Zebu, TradeSmart, #2235).
- If an auxiliary list (an index endpoint) fails, carry the stored rows forward.
- Skip a scrip group or segment the parser does not know (Tradejini added an
  undocumented ETF group, #2341) rather than failing the whole download; still
  fail on a known group that yields nothing. Remove from `supported_exchanges`
  an exchange the master lists nothing for (Tradejini BCD).

## NUANCE — derivative symbols are rebuilt, never copied

Take the underlying, expiry, strike and option type from structured columns and
build the OpenAlgo symbol from them. Broker tradingsymbols are not OpenAlgo
format: Groww ships BSE weeklies as `SENSEX26O2274900CE` and NSE commodity
futures as `GOLD26NOVFUT` (#2194). Where the underlying must come from the
tradingsymbol, strip the expiry, strike and FUT/CE/PE anchored on the expiry,
never "the first run of letters": TradeSmart turned SENSEX50 futures into
SENSEX futures and M&M into M (#2475). Underlyings contain digits, `&` and `-`
(360ONE, M&M, BAJAJ-AUTO), so any parser over symbols allows them and is
anchored (#2206).

Strike and tick size share one per-segment scale. Derive it from the file's own
precision and multiplier columns, not from another segment's rule: Kotak
`cde_fo` is 10^7 (a USDINR strike of 10175000 went into the symbol, tick 250,
#2235), while TradeSmart's NSE and BSE files already give ticks in rupees and
dividing by 100 stored RELIANCE at 0.001 (#2475).

## NUANCE — lot size is units, per contract row

`lotsize` is the exchange's market lot in units on every broker (CRUDEOIL 100).
Kite reports an MCX lot of 1 because it counts contracts; Zerodha stores the
real lot and converts units to contracts and back at every Kite boundary, so
nothing outside `broker/zerodha/` knows (#1998). Lot size belongs to the
contract, not the underlying: a revision applies to newly listed expiries while
near ones keep the old lot (MCXBULLDEX 30 and 15 live together). Take it from
each row, never from an underlying-level table. An unconfigured freeze quantity
is 0, not 1.

## NUANCE — download the REAL instrument file before writing the parser

Code written from the docs alone WILL be wrong. Arrow's docs implied
`NSE`/`NFO`-style codes and "strike x100"; the live CSV actually has:

- exchange-segment codes `NSECM/NSEFO/BSEFO/NSECD/NSECO/MCXFO/NSEIDX/...`
  (mapping by the documented names dropped **every non-index row**)
- strikes **unscaled** for equity/index derivatives but **x100000** for
  currency derivatives, whose ticks arrive in **paise** — scaling is
  per-segment, not global (cross-check `StrikePrice` against the strike
  embedded in `TradingSymbol` for one row per segment)
- futures flagged by `OptionType == "XX"`, not by an empty option-type
- index rows carrying display names ("Nifty 50") in the `Symbol` column

So: pull the live file with a stored token FIRST, print
`df[seg_col].value_counts()` + 3 sample rows per segment, and only then write
the mapping. Watch for renamed listings too (TATAMOTORS -> TMPV post-demerger)
— a "missing" symbol may simply no longer exist.

## NUANCE: series suffixes (the OpenAlgo symbol is NSE's Symbol, not the broker's)

NSE lists a stock's base symbol and its series separately (Symbol `HFCL`,
Series `BE`). Brokers fold the series into the tradingsymbol for anything
outside EQ: Kite ships `HFCL-BE` and `EMBASSY-RR`, the Noren plugins strip
`-EQ` and `-BE` from theirs, and Sahi's comment says it keeps every non-EQ
series. The OpenAlgo `symbol` is the base symbol; `brsymbol` keeps the
broker's tradingsymbol exactly, because that is what `get_br_symbol()` sends
on every order, quote and history call.

- **Which suffixes.** On Zerodha's NSE cash rows: `-BE`, `-BZ`, `-RR` (the
  REITs), `-IV` (the InvITs), `-SM` and `-ST`. Counted in a live Zerodha
  symtoken on 2026-11-17: 195, 34, 6, 21, 482 and 100 rows, none with a bare
  twin. Strip by the row's own series column when
  the broker has one (Sahi does); Kite has none, so Zerodha matches the
  suffix (`strip_nse_series_suffix` in `broker/zerodha/database/master_contract_db.py`).
- **Which not.** Debt and government securities (`-SG`, `-GS`, `-TB`, `-GB`,
  `-N0` to `-NX`) are not equity and keep their tradingsymbol. `-RL` rows have a
  bare twin (`HDFCSIINAV` and `HDFCSIINAV-RL` both exist): stripping would give
  two rows one symbol.
- **Never create a duplicate.** Keep the suffix wherever the bare name is
  already a symbol on that exchange, or two suffixed rows would claim it.
- **Map it back on the way in.** Every book (orders, trades, positions,
  holdings) converts the broker's tradingsymbol with `get_oa_symbol()`, falling
  back to the broker's own when there is no match. Zerodha's holdings skipped
  this, which was harmless only while the two were equal.
- **Changing it on a live broker is a breaking change.** A trader's saved
  `HFCL-BE` (strategy, alert, Flow node, watchlist) stops resolving after the
  next master contract download. Say so in the release notes.
- **Prove it with the Nifty 500 check** (`scripts/check_nifty500.py`, described
  in `SKILL.md`): it must print `NIFTY 500 COMPLETE`.

## NUANCE — vectorize the processing (iterrows is 45x slower)

A per-row Python loop (`df.iterrows()` + dict building) took ~45s for Arrow's
221k rows; the same logic as whole-column pandas ops (mirroring zerodha's
implementation) takes ~1s. Read the CSV with `dtype=str` (kills mixed-type
DtypeWarning at the source) and convert numerics explicitly with
`pd.to_numeric(errors="coerce")`. Beware `-0.0` surviving `clip(lower=0)` —
add `+ 0.0` to normalize. Verify the vectorized output is **byte-identical**
to a known-good run before trusting it.

## NUANCE — auth-token resolution in the download thread

`master_contract_download()` runs in a background thread and several templates
resolve the user via `os.getenv("LOGIN_USERNAME")` — which is often **unset**,
yielding a `None` token and the cryptic httpx error "Header value must be str
or bytes, not <class 'NoneType'>". Resolve via LOGIN_USERNAME first, then fall
back to the single non-revoked row for your broker in the `Auth` table
(OpenAlgo is single-user), and raise a clear error if neither exists — never
let `None` reach a header.
