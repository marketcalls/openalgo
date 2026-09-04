# 32 - Charting Terminal

## Introduction

The **Charting Terminal** at `/trading` is where you read a chart and trade from
it. It is powered by the `openalgo-charts` package: a from-scratch canvas
charting engine with 15 chart types, 102 built-in indicators plus any you write
yourself, and 51 drawing tools, wired to the same broker session and market-data
feed as the rest of OpenAlgo.

Everything on the page is live over the WebSocket feed. Nothing on it polls for
prices.

## Opening It

Navigate to **Trading** in the top bar, or go to
`http://127.0.0.1:5000/trading`.

You need an API key before the chart can load history. If none exists the page
says so and links to `/apikey`.

## The Layout

| Region | What it holds |
|---|---|
| Top bar | Symbol, interval, chart type, product, quantity, indicators, layout, sync, One-Click, replay, undo and redo, feed light, full screen, camera |
| Left rail | Drawing tools in eight groups, magnet, keep-armed lock, undo, redo, delete |
| Centre | One to eight chart panes in a grid |
| Right panel | Watchlist, option chain, or the chart assistant |
| Right rail | The three buttons that open those panels |
| Bottom dock | Orders, positions, trades and GTT across every symbol |

The chart grid takes whatever the rails and panels leave. Only the right panel
and the dock can be resized; the panes follow the layout preset you pick.

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

Two controls change how the tools behave:

- **Magnet** snaps an anchor to the nearest open, high, low or close.
- **Keep tool armed** (the padlock) keeps the tool after you finish a drawing.
  Without it the tool disarms after one shape and the rail returns to the
  cursor, so three trend lines mean three trips to the rail. Both settings are
  remembered per pane.

Select a drawing to get a floating bar with colour, width, dash, lock, delete
and, on text tools, an editor. Double-click a text drawing to reopen its editor.

Drawings are saved per pane and survive a reload.

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

## Market Replay

The replay button steps the chart forward bar by bar from a point you choose.
You pick the starting bar yourself, with everything to its right shaded, because
choosing a start with the next twenty bars visible is choosing with hindsight.

The transport gives you previous, play or pause, next, a scrub bar, a speed
selector and exit. A watermark marks the chart as replayed and the trading
panel comes off it.

**No order can leave the chart during replay.** Every order route on the page,
including the dock's and the GTT tab's, refuses with the same message. Replay is
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
and per pane: the symbol, interval, chart type, product, indicators, drawings,
magnet, keep-armed, grid and volume settings.

Watchlists are stored on the server, so they follow you between devices.
Everything else above is stored in the browser.

## Related

- [Writing your own chart indicators](../../custom-indicators.md)
- [Order Types Explained](../11-order-types/README.md)
- [Analyzer Mode](../15-analyzer-mode/README.md)
- [Scalping Terminal](../../scalping)
