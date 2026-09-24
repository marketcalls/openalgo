# 32 - Charting Terminal

## Introduction

The **Charting Terminal** at `/trading` is where you read a chart and trade from
it. The terminal uses published `openalgo-charts` 2.4.5: a from-scratch canvas
charting engine with 17 chart types, 105 built-in indicators plus any you write
yourself, and 85 drawing tools, wired to the same broker session and market-data
feed as the rest of OpenAlgo.

Price updates arrive over the WebSocket feed. History refreshes reconcile bars
and supply fields the live quote stream does not report.

## Opening It

Navigate to **Trading** in the top bar, or go to
`http://127.0.0.1:5000/trading`.

You need an API key before the chart can load history. If none exists the page
says so and links to `/apikey`.

## The Layout

| Region | What it holds |
|---|---|
| Top bar | Symbol, interval, chart type, product, quantity, indicators, comparisons, layout, sync, One-Click, replay, undo and redo, feed light, full screen, camera and CSV export |
| Left rail | Drawing tools in ten groups, magnet, keep-armed lock, undo, redo, delete |
| Centre | Chart grid with up to eight panes in presets, or sixteen in an imported workspace |
| Right panel | Watchlist, option chain, Objects, or the chart assistant |
| Right rail | The four controls that open those panels |
| Bottom dock | Orders, positions, trades and GTT across every symbol |

The chart grid takes whatever the rails and panels leave. Only the right panel
and the dock can be resized; the panes follow the layout preset you pick.

One toolbar serves the whole grid. Click a chart, move keyboard focus to its
chart region, or use the **Chart 1 / Chart 2** selector to choose the chart that
the toolbar controls. The selected chart has a highlighted border. Its symbol,
interval, chart type, studies, alerts, comparisons and quantity remain
independent when you select another chart. Enabled sync options still apply.
Replay keeps the chart that started it as its owner until the session ends.

Adding panes does not repeat the toolbar. Removing the selected pane selects a
surviving chart, and a saved workspace restores its selected chart. In full
screen, the selected chart's controls move inside that chart; grid controls
return when you leave full screen. On narrow screens, scroll the toolbar
horizontally to reach its remaining controls. The selected-chart selector stays
visible as the controls scroll.

## Comparing Symbols

Select a chart, open **Compare**, then choose **Add comparison**. Search for a
broker-supported instrument in **Add comparison symbol** and select its row.
You can add several independent symbols. The menu lists each one with its
colour and shows loading or unavailable-history messages beside that symbol.
**Remove** affects only the comparison on that row.

Choose **Price** to compare quoted prices or **Percentage** to compare relative
moves. Comparisons use the selected chart's interval. Missing observations stay
as gaps. Comparison search accepts instruments; arithmetic expressions remain
available through the chart's main symbol search.

Each chart retains its comparison list and scale mode. Named workspaces save
these settings with the rest of that chart. Comparison controls are unavailable
during replay selection, loading and playback.

## Saving Images and Data

Open the selected chart's camera menu and choose **Download image**, **Copy image**
or **Download CSV**. CSV contains the displayed price data, study outputs and
comparison columns. Missing readings remain blank. A chart without available
history reports an error instead of downloading a file.

CSV is unavailable while selecting a replay start or loading replay history.
During active replay it exports the revealed chart data without future rows.
In selected-chart replay, a chart outside the replay continues to export its
displayed live data. Exporting does not change the saved workspace.

## Interval Sync and Volume

In a multi-chart layout, open **Chart sync** and enable **Interval** to follow
interval changes across panes. This switch is independent of symbol, time-range
and crosshair sync. A pane whose feed or session-profile chart cannot use the
selected interval keeps its current interval and explains why.

In **Chart settings > Appearance**, **Snap to candle center** keeps the vertical
crosshair on the nearest candle. The horizontal price cursor still follows the
pointer unless the separate price magnet is enabled.

The **Volume** settings tab controls candle-direction colours and an optional
simple moving average. Its period, colour, thickness and line style are saved
per pane. The average shares the volume scale, starts after a full period and
updates as the current bar forms. Hiding volume hides the average as well.
During replay, both use only the bars revealed by the playhead, including the
formed portion of an intrabar candle.

The readout includes zero volume as `V 0`. Index symbols have no traded volume,
so their volume bars, average and volume readout stay hidden. Switching back to
a traded instrument restores your volume preference.

For a combined symbol, volume is the sum of each distinct expression leg's
reported volume, once per matching candle. Subtraction and price coefficients
do not subtract or multiply that activity. An unavailable leg amount leaves the
combined volume unavailable. Price-only live quotes preserve the last reported
amount; history reconciliation supplies updated volume.

Hover a candle to read its OHLC, volume and study values while live data continues
arriving. Crosshair sync makes each follower read its own candle at the mapped
time. Moving outside the chart or beyond its data returns to the latest displayed
candle, including during replay.

## Open Interest

The indicator picker includes **Open Interest**, **Open Interest Change** and
**Open Interest Buildup**. The first plots the reported level, the second plots
the change between adjacent available readings, and the third colours candles
for the four price/OI regimes. Missing readings leave gaps. A reported zero is
a real reading, and folded bars keep the latest level instead of adding levels.

Enable **Chart settings > Readout > Open interest** to include the selected
candle's OI in the chart readout and exported image. It starts off. Hovered OI
stays on the selected candle while prices continue updating. If the forming bar
has no OI, its reading is absent; the terminal does not carry a historical level
forward as a live observation.

Capability comes from instrument metadata and known exchange segments. Cash,
index and crypto spot instruments suppress placeholder history OI. Futures,
options and perpetual futures retain supplied readings. An unclassified
instrument's capability stays unknown. The readout switch is disabled for an
unsupported instrument while retaining your preference for the next supported
one. Capability says whether OI applies, not whether the broker supplies it on
every bar. The current quote stream does not supply OI.

Study templates and chart workspaces retain OI studies and appearance. Workspaces
also retain the readout preference; observations come from the restored
instrument's history. Expressions and price-generated chart elements do not
have a meaningful position level and omit OI.

## Chart Workspaces

Open **Workspaces**, enter a name, and choose **Save as** to save the complete
grid. It retains each chart's instrument, interval, chart type, settings,
studies, comparisons, drawings and drawing preferences, along with grid proportions, selected
chart and sync switches. **Save** updates the current named workspace.

Choose a saved workspace and select **Open** to restore it. The displayed charts
remain available until every replacement chart has loaded successfully. Loading
locks chart interactions and order entry; a failed load leaves the previous grid
in place and displays the error. **Cancel workspace loading** keeps the previous
grid and releases the pending charts. Workspace changes turn One-Click off. The last
successfully opened workspace is restored when the trading page reloads.

**New workspace** opens a clean single chart for BHEL on NSE at a five-minute
interval, using the entered name. **Rename**, **Duplicate** and **Delete** manage
saved entries. Deleting an entry keeps its displayed charts available as an
unnamed grid. Recent entries list successfully opened workspaces.

Enable **Autosave chart changes** to save configuration edits after a short pause.
Price ticks do not trigger workspace writes. Autosave applies only to a named
workspace. Storage errors remain visible and leave changes unsaved; use **Save**
to retry or **Refresh** to reread the saved catalog.

Replay selection, history loading and playback pause autosave. Unsaved changes
remain dirty and resume saving after cancellation or exit restores the live
charts. Stop replay before explicitly saving a workspace.

**Export JSON** downloads the selected saved workspace. **Import workspace JSON**
accepts files up to 5 MB, gives the imported workspace a new identity and prepares
its charts before displaying them. Unsupported intervals, missing studies and
unsupported comparison configurations are rejected with an error.

Workspaces belong to your account in this browser and do not synchronize across
devices. Files contain chart configuration only; credentials, order books,
positions and One-Click state are excluded. The first named save preserves your
existing per-chart browser preferences.

## Indicator Templates

Click the chart you want to work with, then open **Templates** beside the grid
controls. Enter a name and choose **Save current studies**. A template retains
every study instance, including repeated studies, parameters, plot styles,
visibility and shared oscillator panes. It can be used on another symbol.

Select a saved template and choose **Replace studies** to replace the selected
chart's studies, or **Add studies** to keep them and append the template. Added
oscillators get new panes while studies grouped together stay together. An empty
template shows **No studies**; replacing with it clears the studies. If a custom
study is unavailable, the terminal lists its ID and keeps the current studies.

Use **Rename**, **Duplicate**, or **Delete** to manage the selected template.
**Export JSON** downloads a portable file; **Import template JSON** accepts a
template file up to 5 MB and creates a new saved entry. This importer accepts
indicator templates only.

Templates are private to your account in this browser. They are not synchronized
to another device. Browser-storage failures remain visible and preserve the
entered name so you can retry; **Refresh templates** reads changes from another
tab. Template files contain study configuration, not credentials or orders.
Applying a template preserves chart prices, drawings and the visible time range.

## Chart Branding and Watermark

Each chart shows the OpenAlgo mark in its bottom-left corner. Activate the mark
with a completed click or tap to open the OpenAlgo site. The matching **Chart by
OpenAlgo** link in the pane toolbar provides the same destination for keyboard
and assistive-technology users. Dragging the mark does not activate the link.

The larger text watermark is a separate, optional background label. Open
**Chart settings**, choose **Appearance**, and use the Watermark controls:

- **Show watermark** turns the watermark on. It is off by default, including
  for panes saved before watermark support was added.
- **Text** sets a custom label. Leave it blank to use the current symbol and
  interval automatically.
- **Color**, **Opacity**, and **Text size** control its appearance.

Automatic text follows symbol and interval changes. Replay keeps the selected
watermark and adds its own Replay marker, so the two meanings remain separate.
**Reset to defaults** turns the optional watermark off again. **Cancel** leaves
the saved settings unchanged, and **OK** applies and remembers the changes for
that pane. PNG and SVG snapshots include the corner branding and any visible
watermark.

## Session Profiles

Choose **Time Price Opportunity** or **Session Volume Profile** from the chart
type menu in the pane toolbar. Both appear in the last group, below Line Break.

Right-click the chart and open **Chart settings...**. The existing
**Price** tab changes to the selected profile's settings. Switching back to
candles restores the candle controls. Each pane remembers both profile types'
settings independently; **Reset to defaults** resets the active profile and
the shared chart settings.

**Session Volume Profile** draws one horizontal volume distribution per session.
Set its width as a percentage of the session, placement, total/up-down/delta
display, row count or ticks per row, colors, and POC/VAH/VAL lines. Value-area
colors, volume values, a histogram background, line extensions, and developing
POC/value area are available in the same tab. Developing lines use a bounded
sample of cumulative snapshots over each session.

**Time Price Opportunity (TPO)** counts time blocks at each price. Set the
day/week/month period, number of periods to combine, block size, automatic or
manual rows, value-area percentage, letters/blocks, gradient colors and split
layout. The tab also controls initial balance, single prints, poor extremes,
session open/close, midpoint, and an optional volume profile with its own levels.

To split one TPO session, right-click its letters or blocks and choose **Split
this session**. Other sessions keep their layout. Right-click the same session
and choose **Unsplit this session** to collapse it again. The selection follows
that session through live updates and replay. The split setting in the Price tab
sets the default layout for all sessions; changing it resets individual overrides.
Individual splits last for the current chart view and reset when the chart is rebuilt.

Both types use loaded intraday history and follow live updates and replay.
Selecting a profile from a daily chart switches to a compatible broker interval,
preferring five minutes. TPO requires a source interval that divides the block
size. Indian exchange sessions use Asia/Kolkata even when the display timezone
changes. Choose **Custom hours** to filter a session; the start/end also support
overnight sessions.

Volume is estimated by distributing each OHLCV bar's volume across its price
range. Up/down volume follows candle direction, and delta is the difference
between those estimates. Smaller source intervals provide more detail; these
values are not historical bid/ask trade classifications. Instruments without
volume have no volume distribution. Load earlier history to include additional
sessions. Very fine rows or large TPO composites may reach the calculation limit;
the terminal reports this so you can increase row size or reduce the period.

## One-Click Trading

**This is the setting to understand before you trade from the chart.**

The chart carries a SELL and BUY panel in its top-left corner, and a right-click
menu with market, limit and stop rows. What those do depends on one switch in
the top bar, which reads either **One-Click off** or **One-Click ARMED**.

- **Off (the default).** A click runs every check first (replay lock, tradable
  segment, freeze quantity, stop side) and then opens an order ticket prefilled
  with exactly what the chart would have sent. You see the order before it goes.
- **ARMED.** A click places the order immediately, with no confirmation. A
  second fire within 120 milliseconds is ignored, so a stray double-click cannot
  send two orders.

The switch is remembered between sessions. The badge beside it always shows the
current state.

**Arming only gates new risk.** Closing a position, cancelling an order and
dragging an order to a new price work whether One-Click is on or off. Disarming
must never take away your exit.

Orders placed from the chart are tagged with the `chart-trading` strategy and
respect Live and Analyze mode exactly like every other order path in OpenAlgo.

## The Bottom Dock

The dock is a strip under the chart carrying a live count per tab. Click a tab
to open it; drag its top edge to resize; the height and the open tab are
remembered.

| Tab | Shows |
|---|---|
| Orders | Every order in today's book, across all symbols |
| Positions | Every position row, one per symbol, exchange and product |
| Trades | Today's fills |
| GTT | Good-till-triggered orders |

The badge on each tab is the number of rows behind it. The two figures about
live risk sit in the dock's header instead, where they are labelled: the running
open P&L and the number of working orders.

What you can do from a row:

- **Cancel** a working order.
- **Modify** a working order's price, trigger or quantity.
- **Close** one position. This squares off that row only, never everything.
- **Click the row** to chart that symbol in the focused pane.

**Cancel all** and **Close all** sit in the header behind a confirmation.

Rows update from the account order stream as fills and rejections arrive, and
reconcile against the broker's book shortly after. Every write refuses while a
pane is replaying, since a replayed chart must never send an order at a live
price.

## Drawing Tools

Pick a tool from the left rail. A group button re-arms whatever you last used
from that group; the small corner wedge opens the full list without changing the
armed tool.

The terminal exposes all 85 drawing tools from openalgo-charts 2.2.0. Channels
include regression and pitchfork variants; Fibonacci and Gann include fans,
arcs, circles and squares. Patterns include XABCD, Elliott waves and harmonic
patterns with measured ratios. Geometric studies include tessellation and
wavefronts. Use the scrollable group menus to reach the complete catalogue.

Two controls change how the tools behave:

- **Magnet** snaps an anchor to the nearest open, high, low or close.
- **Keep tool armed** (the padlock) keeps the tool after you finish a drawing.
  Without it the tool disarms after one shape and the rail returns to the
  cursor, so three trend lines mean three trips to the rail. Both settings are
  remembered per pane.

Select a drawing to get a floating bar with colour, width, dash, lock, delete
and, on text tools, an editor. Double-click a text drawing to reopen its editor.

Notes, balloons, comments, signposts and price notes use the same text editor.
For a Table drawing, separate columns with `|` and insert rows with
`Shift+Enter`; the first row supplies the headers. Press Enter to apply.

Drawings are saved per pane and survive a reload. Existing saved tool IDs and
anchor meanings are preserved by the upgrade.

## Pointer and Touch Navigation

- Scroll vertically over the plot to zoom the time axis. Horizontal trackpad
  input, or holding Shift while scrolling, pans through time instead.
- A browser pinch gesture reported as Ctrl-wheel or Cmd-wheel zooms around the
  pointer. It uses the same chart gesture on supported trackpads and browsers.
- Scroll over a visible price axis to expand or compress that price scale around
  the pointed price. This makes the scale manual, so it stays where you put it.
- Drag inside the plot with a mouse or pen to pan through time while preserving
  automatic price fitting. The Navigation setting can explicitly enable panning
  both axes. Dragging a price axis still adjusts it manually. Touch panning moves
  both axes.

While a price scale is automatic, its range eases as navigation brings a new
high or low into view. A manually adjusted or fixed scale stays authoritative.
Use **Reset chart view**, `Home` or `0` to restore the saved default bar count
and automatic price scaling.

On a narrow screen, the pane toolbar scrolls horizontally to keep its actions
reachable. Use the drawing rail, side panels and bottom dock for the remaining
chart and trading controls.

## Objects Panel

The **Objects** control on the right rail opens an inventory for the active
chart pane. Click anywhere in a pane, including its toolbar, to make that pane
the panel's target. The panel lists the protected price source, indicator
instances, drawings and an active session profile. Search filters the list by
object name, kind or source id.

Each row offers only actions that object supports. Indicators can be selected,
shown or hidden, configured and removed. Drawings can also be locked and focused;
focusing moves future or off-screen anchors into view. Drawing changes use the
same undo history and per-pane save as edits on the canvas. Profile rows open the
existing chart settings form. The primary price source can be configured but
cannot be hidden, locked or removed.

The panel follows selection and direct changes made on the canvas. Indicator
visibility is remembered with its settings; older saved panes open their
indicators as visible. Removing an external-data indicator also releases its
data requests and empty indicator pane. Object actions do not place, modify or
cancel orders, and replay keeps every existing order restriction in force.

## Keyboard Shortcuts

Chart shortcuts fire while the pointer is over a pane, or while that pane has
focus, so two panes never both respond to one press.

### Navigation

| Key | Action |
|---|---|
| Left, Right | Pan |
| Ctrl or Cmd + Left, Right | Pan faster |
| Up, Down | Pan vertically |
| `=`, `Shift` + `=`, Numpad `+` | Zoom in |
| `-`, Numpad `-` | Zoom out |
| `Home` or `0` | Reset the view |
| `Alt` + `F` | Fit every loaded bar |
| `Alt` + `M` | Toggle crosshair magnet |
| `Alt` + `Shift` + `S` | Save a chart image |

Double-clicking a pane maximizes it, and a second double-click puts the stack
back. On a chart with one pane nothing moves. Double-clicking a text drawing
opens its editor instead.

### Drawing tools

| Key | Arms |
|---|---|
| `Alt` + `T` | Trend line |
| `Alt` + `H` | Horizontal line |
| `Alt` + `J` | Horizontal ray |
| `Alt` + `V` | Vertical line |
| `Alt` + `C` | Cross line |

### Editing a selection

| Key | Action |
|---|---|
| `Delete` or `Backspace` | Delete the selected drawing |
| `Ctrl` or `Cmd` + `Z` | Undo a drawing |
| `Ctrl` or `Cmd` + `Shift` + `Z` | Redo |
| `Ctrl` or `Cmd` + `D` | Duplicate the selection |
| Arrow keys | Nudge the selection one pixel |
| `Shift` + arrow keys | Nudge ten pixels |
| `Esc` | Disarm the tool, then close the open panel |

While you are placing a multi-point tool, `Enter` finishes the shape and
`Backspace` drops the last anchor.

### Elsewhere on the page

| Key | Action |
|---|---|
| Up, Down and `Enter` | Move and choose in symbol search |
| `Delete` | Remove the focused watchlist row |
| Left, Right | Resize the focused right panel |
| `Shift` + click the camera | Save the image without opening its menu |

There is no keyboard shortcut that places, modifies or cancels an order from the
chart. Order entry is deliberately pointer-driven here; the keyboard-driven
order surface is the [Scalping Terminal](../../scalping).

## Chart Alerts

**Right-click the chart at a price and the alert is made there and then.** No
form: the price is the one thing a form would ask for, and pointing at it has
already given it. The same action on a study plot or a supported drawing watches
that instead, keeping the exact study instance and plot you clicked, or the
clicked drawing even if another one is selected. A notice names the alert it
made, and the alert is editable from the rail the moment it exists.

It is armed to fire once, the moment the price is reached, expiring in two months, with a
sound and a desktop notification. Those are the same defaults the form opens
with, so a right-click produces exactly the alert the form would have proposed.

**Alerts** on the toolbar opens that form, for an alert needing a condition, a
trigger, an expiry or a message the defaults do not give it. **Create alert...**
in the right-click menu opens the same form.

**Alerts** on the right rail lists what is already watching, with a **Log** tab
of what has fired. Rows carry the name, the level read from the alert itself,
the instrument and the state, and hover actions to stop, edit or delete one. The
overflow menu starts, stops or removes them all at once.

**An alert that has fired or expired stops drawing its line.** Its row stays in
the list, with its state, and its record is kept: a once-only alert that has
fired is still fired after a reload, which is what stops it firing again on a
price it already reported. What goes is the line on the chart, because a level
nothing is watching is a level in the way, and a chart carrying a week of them
is one you stop reading. An alert anchored to a drawing leaves that drawing
alone. Start a finished alert again from the rail, and if its expiry has passed,
give it a new one first.

**The log outlives the tab.** A firing is written to the database as it happens
and read back the next time `/trading` opens, so closing the browser at four
o'clock no longer takes the afternoon with it, and an alert that fired while you
were on another screen still leaves a row. Each row also names the channels that
accepted the message, so a firing that reached nobody can be told apart from one
that never happened. **Clear** on the Log tab empties it for good.

This is a record, not a scheduler. Alerts are still evaluated by the chart that
is open, so an alert still only fires while `/trading` is running; what changed
is what is left behind afterwards. Firings are kept for 90 days.

**Intrabar touch** is the default. It fires the moment the price is reached,
which is what an alert on a level is for: waiting for the candle to close would
report a level touched at 13:15 on an hourly chart at 14:15, and on a daily
chart the next session. The cost is that it fires on a wick the finished candle
does not keep, so a level brushed once and rejected still sends the message.

**Bar close** is the other choice, one field away on the form. It evaluates the
confirmed candle when the next candle arrives, which is what you want when the
level only counts if it held. Intrabar touch can fire on a wick or study reading
that is absent from the final candle. Missing readings remain unavailable, including
open interest missing from the live quote stream. Alerts retain the symbol,
exchange and interval where they were created.

**Point at a line and press Delete or Backspace to remove it.** The key removes
one thing, and it looks for it in a fixed order: a drawing being placed is
cancelled first, then selected drawings, then the drawing under the pointer,
and only then an alert. An alert's line runs the width of the pane, so it sits
under the pointer far more often than a shape does; taking it last is what
stops Delete removing an alert while you meant to remove a drawing. A field or
a dialog always keeps the key, so erasing a character never erases a drawing.

**An alert stays visible on other timeframes, and is evaluated only on the one
it was made on.** A 5m alert can be seen from the 1h chart, with its own
interval on the label, but it is not watching there. The rail says so under the
row rather than leaving it reading Active on a chart where nothing will fire.
Go back to the interval it was made on to arm it again.

### Being told when one fires

**When it fires** on the create form is how you are told, chosen per alert. A
price you are waiting on all week and a level you are watching for the next ten
minutes do not deserve the same interruption.

| | Default | Reaches you |
|---|---|---|
| **Sound** | on | A short tone from the tab, including behind another window |
| **Desktop notification** | on | Your operating system's own notification, shown only while the tab is hidden |
| **Telegram** | off | A message through the Telegram bot, which must be running with your account linked |
| **WhatsApp** | off | A message through the paired WhatsApp device |

Sound and the desktop notification never leave the machine. The two messaging
channels send the alert out through the same services order notifications use,
which is why neither is on unless you ask: see
[23 - Telegram Bot](../23-telegram-bot/README.md) and the WhatsApp page for
setting each up. A channel that refuses says so by name and the others still
go; nothing is retried, because a queue growing behind a fired alert is worth
less than the next alert arriving on time.

The browser asks permission for notifications at the moment you save an alert
with that box ticked, which is the only point at which it can. Refusing costs
the desktop notification and nothing else.

**A chart with an armed alert keeps working when its tab is hidden.** A chart
with nothing armed stops fetching while you are elsewhere, which is the saving a
background tab is for; an armed alert switches that off for as long as it is
armed. Chrome minimized or the tab behind another window makes no difference.
Closing the tab does: these are evaluated by the chart that is open.

### Putting values in the message

A message may carry placeholders, filled in from the bar that fired the alert:

```
{{ticker}} crossed {{price}}, close {{close}} on {{interval}}
```

`{{ticker}}`, `{{exchange}}`, `{{interval}}`, `{{price}}`, `{{close}}`,
`{{open}}`, `{{high}}`, `{{low}}`, `{{volume}}`, `{{time}}` and `{{timenow}}`
are available, and the create form lists them with a click to insert one.
`{{price}}` is the value that met the condition, which is not always the close.
Prices print at the instrument's own precision. A placeholder spelled wrong, or
one the chart has no value for, is left exactly as you typed it rather than
blanked: a sentence with a hole in it reads as a broken alert, and this reads as
the typo it is.

Alerts do not place orders. History loading, replay selection, replay history
loading and playback suppress evaluation. Leaving replay reseeds observations
without delivering historical matches. Named workspace configuration follows
the workspace's Save and Autosave controls.

For an alert already saved in a named workspace, its fired or expired state is
stored separately from chart configuration. A fired once-only alert remains
fired after reload even with Autosave off. New alerts and edited conditions
still require Save or Autosave. Runtime history is isolated by account,
workspace and pane; it applies only when the saved alert condition still
matches. Save as creates independent history, and deleting a workspace removes
its history. Browser storage failures produce an error notice.

## Market Replay

Select a chart and click **Replay**, then choose its starting bar. The shared
transport identifies that chart for the whole session. Selecting another chart
or moving keyboard focus does not redirect replay. **Selected chart** replays
only its owner; **All charts** uses one clock across every visible chart.
Hidden charts being prepared for another workspace do not join the session.

While picking, future bars are shaded on the owner and, with **All charts**,
on the other charts at the same time boundary. **Cancel** leaves selection or
history loading immediately. Every visible chart must be available, and replay
prepares their histories before playback starts. If a required history fails,
the session returns to live charts and displays the error.

The single transport provides previous, play or pause, next, a scrub bar, speed
and exit. Across different intervals, progress follows the combined observation
times, so a chart advances only when it has an available observation. Switch the
scope after loading to include all charts or return to the original chart.
The transport follows the fullscreen chart without creating a second session.
Replayed charts carry a watermark and hide their trading panel.

**Exit**, or the toolbar's **Replay** button during playback, asks whether to
leave. **Stay** keeps the playhead; **Leave** restores live charts. Changing a
symbol, interval, chart type, layout or workspace stops the session before that
change proceeds.

Live ticks and history refreshes continue in the background during replay.
They do not reveal candles beyond the playhead or move its viewport, including
when an older history page finishes loading. Exit replay to return to the
updated live chart.

**No order can leave the chart during replay.** Every order route on the page,
including sibling charts, the dock and the GTT tab, refuses during selection,
history loading and playback. Replay is
a simulation, and the prices on screen are not the market's.

## The Chart Assistant

The **Assistant** button on the right rail opens a chat that reads the chart you
are looking at: its symbol, interval, visible bars, indicators and your own
drawings. It can mark the chart up with levels, trend lines, zones and markers,
and add or remove indicators.

It places no orders. Its markup lives in its own named groups, so clearing what
it drew can never remove a drawing of yours.

It needs a model configured first, at `/agent/config`.

## What Is Remembered

Reloading the page brings back the grid layout, the pane sync settings, the open
right panel and its width, the dock's open tab and height, the One-Click state,
and per pane: the symbol, interval, chart type, product, indicators, comparisons, drawings,
magnet, keep-armed, grid, volume and watermark settings.

Watchlists are stored on the server, so they follow you between devices.
Everything else above is stored in the browser.

## Related

- [Writing your own chart indicators](../../custom-indicators.md)
- [Order Types Explained](../11-order-types/README.md)
- [Analyzer Mode](../15-analyzer-mode/README.md)
- [Scalping Terminal](../../scalping)
