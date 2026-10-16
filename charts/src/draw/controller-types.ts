/**
 * The public shapes of the drawing controller: the slice of the chart it
 * drives, its options, and the events and edit options its methods take.
 * Kept apart from the controller so the class reads as behaviour, and so a
 * module that needs one of these (the gestures read the gesture switches)
 * names it without importing the controller itself.
 */
// Shared types come from the package entry, not a relative path; see the
// note in controller.ts.
import type {
  IPrimitive, DataLayer, PlotRect, Bar, IndicatorApi, SeriesApi,
} from 'openalgo-charts';
import type { Drawing, DrawingStyle, DrawingSpace, MagnetMode } from './types';
import type { ClipboardPort } from './clipboard';

/**
 * The slice of the chart this controller needs.
 *
 * Declared structurally rather than as `Chart` on purpose. Each tier ships its
 * own bundled `.d.ts`, so naming the class here made the draw tier re-declare
 * `Chart`, and because `Chart` has private members, TypeScript treats the two
 * declarations as *different* types. A TS consumer passing the chart from
 * `createChart()` got "separate declarations of a private property", which made
 * the tier unusable from TypeScript at all. An interface with no private
 * members is structural, so the real `Chart` satisfies it with nothing to cast.
 */
export interface DrawingChartHost {
  readonly isDestroyed?: boolean;
  /**
   * The event bus, with the names and payloads of `ChartEventMap`. The
   * controller listens for `click`, `crosshair:move`, `drag`, `drag:end`,
   * `drag:cancel`, `dblclick` and `hover` (`{ id }`, the hit id under the pointer
   * whenever it changes), which is what drives the hover state: the chart has
   * already hit-tested the move, so the controller reads its answer rather than
   * testing a second time. A host that never emits `hover` has drawings that
   * select and drag but do not light up. It also follows `data:context`,
   * `drawings:restore`, `pick:start`, `pick:end`, `paneRemoved`, `paneMoved`,
   * `objects:change` and `indicatorRemoved`; a host that moves or removes panes
   * without `paneRemoved` and `paneMoved` leaves drawings on the old slots. It
   * emits the `draw:*` and `drawing:*` names this tier adds to `ChartEventMap`.
   */
  on(event: string, handler: (payload: unknown) => void): () => void;
  emit(event: string, payload: unknown): void;
  addPrimitive(primitive: IPrimitive, paneIndex?: number): void;
  removePrimitive(primitive: IPrimitive): void;
  readonly dataLayer: DataLayer;
  getVisibleLogicalRange(): { from: number; to: number } | null;
  drawingState(): unknown;
  setDrawingState(state: unknown): void;
  setPlacementMode?(active: boolean): void;
  /**
   * Optional, and used only to move a drawing by a fixed screen distance (a
   * paste offset, an arrow-key nudge, a multi-drag across panes). Going
   * through pixels rather than adding a price delta keeps the offset the same
   * visible nudge on a log scale as on a linear one, and the same on an RSI
   * pane as on the price pane. A host without them still gets the time half.
   */
  priceToCoordinate?(price: number, paneIndex?: number): number | null;
  coordinateToPrice?(y: number, paneIndex?: number): number | null;
  /**
   * Optional, the time-axis half of the same conversion. coordinateToTime also
   * keeps previews and freehand strokes active in empty space beyond the bars.
   * Without these methods a horizontal nudge assumes the default bar spacing.
   */
  timeToCoordinate?(time: number): number;
  coordinateToTime?(x: number): number;
  /**
   * Optional, for drawings anchored to the viewport (`space: 'viewport'`):
   * the time axis, which turns a data anchor's time into a place on the plot
   * and back when a drawing is pinned or unpinned.
   */
  readonly timeScale?: { indexToX(index: number): number; xToIndex(x: number): number };
  /**
   * Optional, for drawings anchored to the viewport: a pane's plot in
   * container px, as `Chart.plotRect` reports it, which is what a viewport
   * anchor is a fraction of. A host without it still paints them, since the
   * layer reads the plot size from its render context, but cannot place,
   * move or convert them.
   */
  plotRect?(paneIndex: number): PlotRect | null;
  /**
   * Optional. It keeps a paste from a chart with more panes than this one
   * landing on a pane the user cannot see: adding a primitive creates the pane
   * it names, so without this a drawing copied out of an indicator pane would
   * conjure an empty pane in a single-pane chart. An entry with `priceToY` and
   * `yToPrice`, as a chart pane has, also lets an alert read a drawing on a
   * pane the chart maps no price for, one collapsed to its header strip.
   */
  panes?(): readonly unknown[];
  /**
   * Optional. Slot of the price pane, the one pane whose drawings the magnet
   * snaps to candle prices and a drawing link shares. It moves when a host
   * puts the price pane below its studies; without it the price pane is slot 0.
   */
  primaryPaneIndex?(): number;
  /**
   * Optional, all three, for the magnet: the price series' bars, the studies
   * and a series' style. The chart reports no bar while a drawing is in hand,
   * so a handle or a shape snaps against `primaryBars`; a study pane snaps
   * to the values of the studies plotted on it, skipping a hidden plot. A
   * host without them snaps placements on the price pane only.
   */
  primaryBars?(): readonly Bar[];
  indicators?(): readonly IndicatorApi[];
  seriesStyle?(series: SeriesApi): { readonly visible?: boolean; readonly color?: string } | null;
  /**
   * Optional, both: a pane's series band, back to front, and the call that
   * paints a layer directly above one of its entries. Without them no drawing
   * can be placed in the series band, and one saved there paints by its
   * `zIndex`.
   */
  seriesStack?(paneIndex: number): readonly string[];
  setPrimitiveStackAbove?(primitive: IPrimitive, above: string | null): boolean;
  /**
   * Optional: the host's data context, whose `interval` decides which
   * drawings with an interval range are shown (`Drawing.intervals`). Read
   * when the controller is built and on every `data:context`, whose payload
   * is the context itself; a host without it that emits `data:context` is
   * followed through the payload alone. With no interval every drawing shows.
   * The instrument is declared too, as the chart's context carries it, so one
   * host object also satisfies `DrawingLinkChart`.
   */
  getDataContext?(): { readonly symbol?: string; readonly exchange?: string; readonly interval?: string } | undefined;
}

export interface DrawingControllerOptions {
  /**
   * Snap new anchors to the O/H/L/C of the bar under the cursor. `'strong'`
   * always takes the nearest of the four; `'weak'` only when one sits within
   * a few pixels of the pointer, so a click on open space stays where it was
   * made. `true` means `'strong'` and `false` means `'off'`, which is what
   * the boolean meant before the modes existed. Default `'off'`. While a
   * tool is armed the layer paints a ring where the next click will land.
   */
  magnet?: boolean | MagnetMode;
  /** Style merged under every tool's own defaults. */
  defaultStyle?: DrawingStyle;
  /** Stay in the active tool after finishing a drawing. Default false. */
  stayInDrawingMode?: boolean;
  /** Undo depth. Default 50. */
  historyLimit?: number;
  /**
   * Where copy and paste move text. Defaults to `navigator.clipboard`; pass a
   * port to route through a host's own transfer, or `null` to stay in the
   * process-local clipboard entirely.
   */
  clipboard?: ClipboardPort | null;
  /**
   * Whether a refused or failing clipboard write still lands in the in-process
   * clipboard. Defaults to true, which is what makes copy and paste work between
   * two charts on a page where the browser has denied clipboard permission.
   *
   * Pass false for a host that would rather a failed copy be a failed copy: with
   * it off, `cut` leaves the drawing alone when the write does not land, so a
   * shape is never destroyed for a transfer that did not happen.
   */
  clipboardFallbackToMemory?: boolean;
  /**
   * How far a pasted or duplicated copy lands from its original, in bars along
   * time and in screen pixels down the price axis. A copy that lands exactly on
   * top of the original reads as nothing having happened. Defaults: 2 bars,
   * 16 px.
   */
  pasteOffsetBars?: number;
  pasteOffsetPixels?: number;
  /**
   * Draw the anchor of every study input that declares one (a `price` input
   * with a `timeKey` and `anchor: true`): a handle at the point the pair
   * names that drags both as one settings change and one step of this undo
   * history. Default true; false draws none, and the inputs are still edited
   * in settings and picked with `Chart.beginPick('point')`. Read when the
   * controller is built: `setOptions` does not change it.
   */
  inputAnchors?: boolean;
  /**
   * The pointer gestures a held modifier key starts, each on unless set to
   * false here, for a host whose own chart gestures already use that key.
   * `setOptions` merges it flag by flag.
   */
  gestures?: DrawingGestureOptions;
}

/**
 * The modifier gestures `DrawingControllerOptions.gestures` turns off. Ctrl
 * means Cmd as well, for macOS. None of them is a key chord, so none can
 * shadow one of `matchDrawingShortcut` or `keyToDrawingAction`.
 */
export interface DrawingGestureOptions {
  /**
   * Ctrl held while placing an anchor or dragging a handle or a shape: the
   * strong magnet for as long as it is held, whatever `magnet` is set to.
   */
  snapModifier?: boolean;
  /**
   * Shift+click on empty chart space, with no tool armed: a ruler from the
   * click to the pointer, gone on the next click or `cancel()`. A preview,
   * never a drawing: not saved, not an undo step, never linked.
   */
  measure?: boolean;
  /**
   * Ctrl plus a drag on empty chart space, with no tool armed: a box that
   * selects every drawing whose geometry it touches, as a click there would
   * find it, leaving out drawings that are hidden, locked or unselectable.
   * Shift held as well adds them to the selection. While Ctrl is held over
   * empty space the chart is in placement mode, so the press is not a pan.
   */
  boxSelect?: boolean;
  /**
   * Alt (Option) plus a drag on a drawing's body: the drawing stays where it
   * is and a copy of it moves instead, as one undo step. The whole movable
   * selection is copied, as a plain drag would move it, and each copy is the
   * user's own drawing, with no policy and no link lineage. A copy waits for
   * the pointer to travel three pixels, so a jitter leaves none behind.
   */
  dragCopy?: boolean;
}

/** How `DrawingController.setTool` arms a tool. */
export interface DrawingPlacementOptions {
  /**
   * The space the placed drawing is anchored in. `'viewport'` pins it to the
   * screen: the anchors are placed where they are clicked, as usual, and kept
   * as fractions of the pane's plot from then on. Only a tool that declares
   * `viewport` accepts it. Default `'data'`.
   */
  space?: DrawingSpace;
}

/**
 * What `drawing:change` reports happened to the listed ids. The list is empty
 * for a step of the undo history that changed no drawing, a study input
 * anchor's drag and its undo or redo, so a control showing whether Undo is
 * available still refreshes.
 */
export type DrawingChangeKind = 'add' | 'update' | 'remove' | 'reorder' | 'undo' | 'redo';

/** The `drawing:change` payload. */
export interface DrawingChangeEvent {
  ids: string[];
  kind: DrawingChangeKind;
  /** Set on a change another chart's link applied; it records no step here. */
  linked?: true;
  /**
   * The undo step this change was recorded as, on the change that closes it.
   * Absent for everything the history does not hold: a host's forced edit, a
   * linked commit, a restore, and a move along the branches (`undo`, `redo`).
   * {@link DrawingController.historySteps} lists the step by this number.
   */
  step?: number;
}

/**
 * Payload of `draw:add`, `draw:update` and `draw:remove`: the drawing itself.
 * `history` is set when an undo or redo step applied the change.
 */
export interface DrawingEvent {
  drawing: Drawing;
  history?: true | undefined;
}

/** Payload of `draw:copy`, `draw:cut`, `draw:paste` and `draw:preview`. */
export interface DrawingListEvent {
  drawings: Drawing[];
}

/** Payload of `drawing:select` (the whole selection, in pick order) and `draw:preview-clear`. */
export interface DrawingIdsEvent {
  ids: string[];
}

/** Payload of `draw:select` (the primary selection) and `drawing:hover`; null when there is none. */
export interface DrawingIdEvent {
  id: string | null;
}

/** Payload of `draw:tool`: the active tool, null when none; `space` only for a screen-pinned placement. */
export interface DrawingToolEvent {
  tool: string | null;
  space?: 'viewport' | undefined;
}

/** Payload of `draw:measure` and `draw:eraser`: the mode switched on or off. */
export interface DrawingModeEvent {
  active: boolean;
}

/** Options for a call that changes, groups or deletes drawings. */
export interface DrawingEditOptions {
  /**
   * Reach drawings whose policy sets `editable: false` as well, and the
   * groups that hold them. Without it they are left exactly as they are,
   * which is what keeps every control a host wires to the user off them. The
   * host that placed such a drawing passes it to move, restyle, regroup or
   * retire it. A forced call is the host's own act, not the user's, so it
   * records no undo step, and every step already recorded takes it too: no
   * later undo or redo reverses it, and a step it leaves with nothing to do
   * is dropped.
   *
   * Cost: taking a call into the recorded steps is one pass over the undo
   * and redo history, parsing and rewriting both snapshots of every step, so
   * it grows with the number of recorded steps (see `historyLimit`) times
   * the drawing count. A forced delete, a forced grouping call, a forced
   * patch to a drawing the user may edit or one that carries `zIndex`, any
   * patch that carries `policy` and a linked chart's change of policy make
   * that pass. A forced patch to a read-only drawing that carries neither
   * `policy` nor `zIndex` (a level the host trails on every tick) makes
   * none: history cannot reach that drawing's content while it stays
   * read-only, so the patch is held and goes in with the next pass, which a
   * change of its policy always makes.
   */
  force?: boolean;
}
