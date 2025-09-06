# OI/COI Real Data Integration Guide

This guide explains how to feed real CE/PE Open Interest (OI) and Change in OI (COI) data into the dual-band horizontal overlays implemented in `Nifty_OI_profile.html`.

- File: `D:/MadhaN/Nifty_OI_profile.html`
- Renderers: `SeparateOIRenderer.draw()`, `SeparateCOIRenderer.draw()`
- Profiles: `SeparateOI`, `SeparateCOI`

## Visual Conventions

- CE bars: upper band, red, anchored with the bottom edge at the strike price (spanning strike→strike+15).
- PE bars: lower band, green, anchored with the top edge at the strike price (spanning strike→strike-15).
- COI sign handling: positive values extend toward the selected view side, negative values extend opposite.

## Data Formats

Send normalized data in these structures.

- OI payload
```json
{
  "strikes": [
    { "price": 25200, "ceOI": 18500, "peOI": 16250 },
    { "price": 25250, "ceOI": 17200, "peOI": 17500 }
  ]
}
```

- COI payload
```json
{
  "strikes": [
    { "price": 25200, "ceOI": -1200, "peOI": 800 },
    { "price": 25250, "ceOI": 950, "peOI": -400 }
  ]
}
```

Requirements:
- `price`: number (same units as your chart price scale).
- `ceOI`/`peOI`: numbers.
  - OI: absolute counts (>= 0).
  - COI: signed deltas (can be negative).
- Recommended: sort by ascending `price`.

## Initialization (Attach Profiles)

Option A — Use the provided update functions in `horizontal_dual_range_oi_example.html` (`updateOIData()`, `updateCOIData()`). They create profiles if missing, attach them to the candlestick series, and toggle visibility.

Option B — Manual setup:
```js
// OI
const oiData = { strikes: realOiArray }; // as per OI payload
const oiProfile = new SeparateOI(chart, candlestickSeries, oiData);
candlestickSeries.attachPrimitive(oiProfile);
oiProfile.setView('right');           // 'left' or 'right'
oiProfile.setAnchorRatio(0.95);       // 0..1 across chart width
oiProfile.setShowStrikeLabels(true);
oiProfile.setShowValueLabels(true);
oiProfile.toggleOI();                 // show

// COI
const coiData = { strikes: realCoiArray }; // as per COI payload
const coiProfile = new SeparateCOI(chart, candlestickSeries, coiData);
candlestickSeries.attachPrimitive(coiProfile);
coiProfile.setView('right');
coiProfile.setAnchorRatio(0.70);
coiProfile.setShowStrikeLabels(true);
coiProfile.setShowValueLabels(true);
coiProfile.toggleCOI();               // show

// repaint after attach
const lastCandle = priceData[priceData.length - 1];
candlestickSeries.update({ ...lastCandle });
```

## Updating with Real Data

Use the profile update APIs to push incoming data at any interval.

```js
function applyRealOI(oiProfile, realOi) {
  // realOi: { strikes: [{ price, ceOI, peOI }, ...] }
  oiProfile.updateData(realOi);
  const lastCandle = priceData[priceData.length - 1];
  candlestickSeries.update({ ...lastCandle });
}

function applyRealCOI(coiProfile, realCoi) {
  // realCoi: { strikes: [{ price, ceOI, peOI }, ...] }
  coiProfile.updateData(realCoi);
  const lastCandle = priceData[priceData.length - 1];
  candlestickSeries.update({ ...lastCandle });
}
```

Relevant methods defined in the file:
- `SeparateOI.updateData(newOiData)`
- `SeparateCOI.updateData(newData)`

## Mapping Your API Schema

If your API uses a different structure, normalize to the expected format.

Input (example):
```json
[
  { "strike": 25200, "CE_OI": 18450, "PE_OI": 16300, "CE_COI": -900, "PE_COI": 600 },
  { "strike": 25250, "CE_OI": 17100, "PE_OI": 17650, "CE_COI": 1000, "PE_COI": -450 }
]
```

Adapter:
```js
function normalizeToOI(apiRows) {
  return {
    strikes: apiRows.map(r => ({
      price: Number(r.strike),
      ceOI: Number(r.CE_OI),
      peOI: Number(r.PE_OI),
    })).sort((a, b) => a.price - b.price),
  };
}

function normalizeToCOI(apiRows) {
  return {
    strikes: apiRows.map(r => ({
      price: Number(r.strike),
      ceOI: Number(r.CE_COI), // can be negative
      peOI: Number(r.PE_COI), // can be negative
    })).sort((a, b) => a.price - b.price),
  };
}
```

## End-to-End Example

```js
// 1) Fetch
const rows = await fetch('/api/oi-coi').then(r => r.json());

// 2) Normalize
const oiData = normalizeToOI(rows);
const coiData = normalizeToCOI(rows);

// 3) Initialize once
if (!window.oiProfile) {
  window.oiProfile = new SeparateOI(chart, candlestickSeries, oiData);
  candlestickSeries.attachPrimitive(window.oiProfile);
  window.oiProfile.setView('right');
  window.oiProfile.setAnchorRatio(0.95);
  window.oiProfile.setShowStrikeLabels(true);
  window.oiProfile.setShowValueLabels(true);
  window.oiProfile.toggleOI();
}
if (!window.coiProfile) {
  window.coiProfile = new SeparateCOI(chart, candlestickSeries, coiData);
  candlestickSeries.attachPrimitive(window.coiProfile);
  window.coiProfile.setView('right');
  window.coiProfile.setAnchorRatio(0.70);
  window.coiProfile.setShowStrikeLabels(true);
  window.coiProfile.setShowValueLabels(true);
  window.coiProfile.toggleCOI();
}

// 4) Subsequent refreshes
applyRealOI(window.oiProfile, oiData);
applyRealCOI(window.coiProfile, coiData);
```

## UI Controls in the HTML

- OI
  - View: `#oiView` → `SeparateOI.setView('left'|'right')`
  - Anchor: `#oiX` (0–100) → `SeparateOI.setAnchorRatio(ratio)`
  - Labels: `#oiShowStrike`, `#oiShowValues`
  - Toggle: `toggleOI()`
- COI
  - View: `#coiView`
  - Anchor: `#coiX`
  - Labels: `#coiShowStrike`, `#coiShowValues`
  - Toggle: `toggleCOI()`

## Troubleshooting

- Bars not visible
  - Ensure profile is toggled on (`toggleOI()` / `toggleCOI()`).
  - Check strikes cover the visible price range.
  - Verify data arrays are non-empty.
- Bars inverted vs. expectations
  - CE is always upper/red, PE lower/green by renderer design.
- COI direction confusion
  - Positive extends toward the active view side; negative extends opposite.

## Performance Tips

- Batch updates and repaint once using the last candle update.
- Keep strike count reasonable for the visible window.
- Avoid unnecessary re-attachments of primitives; reuse profiles and call `updateData`.

## Security & API Notes

- Do not embed secrets in the client. Proxy requests through a server if needed.
- Validate and sanitize API responses before normalizing.

## Version Notes

- Built with Lightweight Charts and custom primitives/pane views inside the single HTML.
- The renderer uses `series.priceToCoordinate()` per frame for precise strike alignment.

## FAQ

- Can I omit CE or PE at a strike? Yes, set the missing side to 0 to preserve layout.
- Do I have to use 50-pt strike steps? No, any step is supported if consistent with your market.
- Can COI be fractional? Yes, values are numbers; formatting is up to you.

## Changelog

- 2025-08-26: Documentation created. CE upper/red and PE lower/green conventions clarified. Added adapters and end-to-end sample.
