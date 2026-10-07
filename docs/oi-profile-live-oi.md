# OI Profile: live open interest

The OI Profile has two sources for a strike's open interest. They are layered so
that a broker whose feed carries OI gets live numbers, and every other broker
keeps working exactly as before.

Both places the OI Profile is drawn use it: the `/oiprofile` page and the
**OI Profile** toggle on the `/trading` chart (`strategies/indicators/oi_profile_live.js`,
which reaches the feed through the loader's `subscribeQuotes`).

1. **Polled answer (every broker).** The server fetches one multiquote over the
   option legs and shares the answer for `OI_PROFILE_CACHE_TTL` seconds
   (default 60). The page re-asks every 3 minutes while the market is open.
2. **Live overlay (brokers whose feed carries OI).** The page subscribes to the
   same option legs on the WebSocket it already has open and lays each tick's
   `oi` over the polled value (`frontend/src/lib/oiProfileLive.ts` on the page,
   `overlayLiveOi` in the chart indicator; the two follow the same rules). The
   bars redraw every 2 seconds. This adds no broker API calls: the ticks are already
   flowing to the browser.

A leg whose feed sends no `oi`, or sends 0, keeps its polled number. A zero tick
is treated as "unknown", never as an emptied contract.

## Change in OI stays anchored

The server sends each leg with the OI its change is measured against
(`ce_legs` / `pe_legs`, `{symbol, oi, base}`). A live leg moves the change by
exactly what it moves the OI (`live - base`), so the anchor rules in
[oi-profile-anchors.md](oi-profile-anchors.md) are unchanged. A leg with no known
base (change not asked for, or still being fetched) leaves its polled change alone.

## Tick contract

A broker adapter publishes `oi` (an integer) in its Quote and Depth ticks when
the feed carries it, and omits the key when it does not. Omit rather than send 0:
the client keeps its last known value across a packet that lacks the field.

## Broker capability

"Publishes `oi`" means the adapter in `broker/<name>/streaming/` puts the
contract's OI on its Quote and Depth ticks. The OI Profile subscribes in Quote
mode, so a broker that sends OI only on depth frames still uses the polled numbers.

| Status | Brokers |
|---|---|
| Publishes `oi` on Quote ticks | angel, arrow, compositedge, definedge, deltaexchange, dhan, dhan_sandbox, firstock, fivepaisaxts, flattrade, fyers, groww, hdfcsecurities, hdfcsky, ibulls, iifl, iiflcapital, indmoney, jainamxts, kotak, motilal, mstock, paytm, pocketful, rmoney, samco, shoonya, tradejini, tradesmart, upstox, wisdom, zebu, zerodha |
| Publishes `oi` on Depth ticks only | aliceblue |
| Polled only | fivepaisa, nubra |

What this change added, and where each field is documented:

| Broker | Source field | Notes |
|---|---|---|
| upstox | `MarketFullFeed.oi` (`MarketDataFeedV3.proto`) | In the `full` feed that Quote and Depth already use. |
| flattrade, zebu, shoonya | Noren touchline `oi` | Noren defines `oi` as the contract's OI, `poi` as the previous close and `toi` as the total for the underlying. Shoonya used to publish `toi` as `open_interest`; that was the underlying's total, so it now publishes `oi`. The adapters merge partial `tf` frames before normalising, so the last value is kept across frames that omit it. |
| samco | `oI` on the `quote` stream | `quote2` frames do not carry it and normalise to 0; those are left out. |
| groww | `StocksLivePriceProto.openInterest`, field 14 (double) | From the official `growwapi` SDK's `StocksSocketResponse.proto`. The hand-written parser used to skip the field. |
| aliceblue | `oi` on depth frames (`dk`/`df`) | Aliceblue's websocket docs list `oi` under depth only; `toi` on tick frames is not the contract's OI. |

Why two brokers stay polled:

- **fivepaisa** sends OI on a third method, `GetScripInfoForFuture`, separate from
  `MarketFeedV3`. Forwarding it means the adapter subscribes and reference-counts a
  third method per token. That is a larger change to a sensitive part of the
  adapter, best done with a live 5paisa account to verify.
- **nubra** carries OI on its option-chain channel (`WebSocketMsgOptionChainItem.oi`),
  not on the order-book channel the adapter subscribes to. The same applies:
  a new channel, verified against a live account.

Both keep working exactly as before through the polled answer.

## Where the live path does not apply

- **Market closed.** The page does not subscribe; a closed market cannot move.
- **Brokers in the "Polled only" row, and aliceblue (depth only).** The page behaves exactly as it did.
- **Previous-session anchors** still come from history candles or the NSE
  bhavcopy. They are settled data and need no live feed.
