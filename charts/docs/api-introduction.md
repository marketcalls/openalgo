<div class="oac-api-eyebrow">THE REFERENCE</div>

## Every detail. One place.

Explore the types, options and methods behind your charts. This reference is
generated from the source used by the current website build; the package version
appears in the page title.

<div class="oac-api-links">
<a href="/openalgo-charts/docs/getting-started/">Start with the guides</a>
<a href="/openalgo-charts/examples/">Try the live examples</a>
</div>

### Find your starting point

| What you are building | Reference | Guide |
| --- | --- | --- |
| A chart with your own interface | [Chart API](/openalgo-charts/api/classes/index.Chart.html) | [Core concepts](/openalgo-charts/docs/core-concepts/) |
| A complete chart with controls | [Widget](/openalgo-charts/api/modules/widget.html) | [Widget guide](/openalgo-charts/docs/widget/) |
| Named workspaces and indicator templates | [Workspace](/openalgo-charts/api/modules/workspace.html) | [Workspaces guide](/openalgo-charts/docs/workspaces/) |
| Price, drawing and study alerts | [AlertController](/openalgo-charts/api/classes/index.AlertController.html) | [Alerts guide](/openalgo-charts/docs/alerts/) |
| Open interest observations and studies | [Bar](/openalgo-charts/api/interfaces/index.Bar.html) | [Open interest guide](/openalgo-charts/docs/open-interest/) |
| CSV and structured chart observations | [Chart API](/openalgo-charts/api/classes/index.Chart.html) | [Chart data export](/openalgo-charts/docs/chart-data-export/) |
| A searchable object inventory | [ChartObjects](/openalgo-charts/api/classes/index.ChartObjects.html) | [Objects guide](/openalgo-charts/docs/objects/) |
| Interactive drawing tools | [Drawing controller](/openalgo-charts/api/classes/draw.DrawingController.html) | [Drawing playground](/openalgo-charts/docs/drawing-tools/) |
| A depth ladder | [Depth of market](/openalgo-charts/api/classes/trade.DomLadder.html) | [Simulated live demo](/openalgo-charts/docs/depth-of-market/) |
| Daily TPO profiles | [Market profile](/openalgo-charts/api/classes/profile.MarketProfile.html) | [Profile demo and themes](/openalgo-charts/docs/market-profile-examples/) |

### Alert dragging in 2.4.7

`AlertController` supplies draggable price and study-threshold lines.
Pointer movement is visual preview; release commits one `alert:updated` event.
Drawing-owned levels remain tied to the drawing. The
[live example](/openalgo-charts/examples/#alert-threshold-dragging) demonstrates
preview, release and cancellation without a trading connection. The
[Alerts guide](/openalgo-charts/docs/alerts/) covers construction, source binding,
delivery, expiry and persistence.

### Indicator controls in 2.4.6

Set `IndicatorDescriptor.hasSource` to show the source action and handle
`indicatorSource` in your host. Use `markerAnchor: 'price'` for overlay signals
measured against candle highs and lows; plot anchoring remains the default.
`ChartOptions.legendIconSize` and `chart.setLegendIconSize()` size every legend
row consistently. See the [indicator guide](/openalgo-charts/docs/indicators/)
for a runnable source-button and signal example.

### Host contracts in 2.4.5

Use [Instrument](/openalgo-charts/api/classes/index.Instrument.html) for validated
source, calendar and formatting rules. The optional workspace tier adds portable
named layouts and indicator templates; the widget accepts per-instance translation
and trading capabilities. Trader alerts use host-delivered events and restore
their drawing/study anchors without firing on history. Open interest remains an
optional level with explicit instrument support and missing-data gaps.

Read the [instrument guide](/openalgo-charts/docs/instruments/),
[widget guide](/openalgo-charts/docs/widget/) and
[compatibility policy](/openalgo-charts/docs/compatibility/) before wiring these
contracts into a trading host. The library does not assume broker order authority.

### Navigation and mobile controls in 2.1.8

Wheel input respects pixel, line and page deltas. Horizontal input pans time; wheel input
over a visible price axis scales that axis. `ChartOptions.animAutoscale` eases automatic
price changes during navigation. `WidgetOptions.mobile` controls the responsive header,
bottom bar and drawing sheets while sharing existing drawings and object state.
See the [interaction guide](/openalgo-charts/docs/interactions/),
[mobile guide](/openalgo-charts/docs/mobile/) for the responsive controls and
their touch behavior.

### Object management in 2.1.7

`ChartObjects` shares inventory, supported actions and lifecycle notifications
between widget and custom hosts. `widget.openObjects()` opens the packaged panel.
Indicator visibility is part of saved layouts, and dialogs fit the chart's actual
container width and height. See the [Objects guide](/openalgo-charts/docs/objects/).

### New in 2.1.1

The [Footprint API](/openalgo-charts/api/classes/profile.Footprint.html) adds
profile, ladder and heatmap styles, independent text coloring, configurable
`tableRows`, and `volumeDivisor` for quantity or lot display. Batch and live
footprints preserve actual OHLC, trade counts and intrabar delta extremes.
See the [orderflow guide](/openalgo-charts/docs/profiles-and-orderflow/) and
[release notes](/openalgo-charts/docs/release-notes/#211).

### Compact profiles since 2.1.0

The profile reference includes `blockDisplay: 'compact'`, per-session
`setSessionSplit` / `isSessionSplit`, and the `showSessionOpen` / `showLastPrice`
marker options. See the [release notes](/openalgo-charts/docs/release-notes/#210)
for the full release details.

Use search to find a symbol, or browse the modules in the navigation. Each member links to
its source definition so you can inspect the exact implementation.
