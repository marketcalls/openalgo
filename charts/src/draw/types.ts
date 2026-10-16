/**
 * Drawing model (ARCHITECTURE.md section 8). A drawing is **plain data**: anchors
 * in `{ time, price }`, a style bag, a tool id. It serialises straight into
 * `ChartState.drawings` with no custom encoder, and a tool is a registry entry
 * exactly like a chart type or an indicator.
 *
 * Anchors are stored in *data* space, never pixels: the chart's time axis is
 * gapless (section 5.3), so a pixel anchor would slide the moment a weekend
 * collapsed or the user zoomed. `DataLayer.timeToIndexFloat` maps them back,
 * which also gives anchors between bars and to the right of the last one,
 * where trend projections and forecasts live.
 *
 * Version 2 of the model split the text fields out of the style bag into
 * {@link DrawingText}, made `levels` a list of {@link FibLevel} rather than bare
 * ratios, and gave every drawing a `zIndex`. A 1.9.x document is upgraded by
 * `migrateDrawings` on the way in; nothing downstream sees the old shape.
 *
 * The one exception to data space is a drawing whose `space` is `'viewport'`:
 * a note or a box that belongs to the screen rather than to a bar. Its anchors
 * are {@link ViewportPoint} fractions of its pane's plot, kept in a field of
 * their own so a time or a price never has to mean a pixel. The field is
 * optional and additive, which is why the document stays version 2: a save
 * with no viewport drawing is byte for byte what it was.
 *
 * Version 3 added one field, {@link Drawing.intervals}: the range of chart
 * intervals a drawing is shown on. A version 2 document is a valid version 3
 * one and loads unchanged, and a document is written as version 3 only when a
 * drawing in it carries a range, so a save without one is still version 2.
 * The version is raised for a range because an earlier build would not keep
 * it: its migration drops the field, and the drawing would show on every
 * interval there and lose its range on the next save.
 */
import type { PrimitiveRenderContext, AlertDrawingValue, AlertDrawingLevel } from 'openalgo-charts';

/** One anchor, in data space. */
export interface DrawingPoint {
  /** UTC seconds. May fall between bars, or past the last one. */
  time: number;
  price: number;
  /**
   * Pen pressure at this sample, 0..1, on a freehand stroke only. Absent means
   * the pointer events stand-in of 0.5, which is what a mouse reports and what
   * a stroke's width is calibrated to, so a mouse stroke stores nothing here.
   */
  pressure?: number;
}

/**
 * Which coordinates a drawing's anchors are in. `'data'`, the default, is time
 * and price: the drawing moves with the bars when the chart pans or zooms.
 * `'viewport'` pins it to the screen: its anchors are fractions of its pane's
 * plot, so pan and zoom leave it where it is and a resize keeps it in
 * proportion.
 */
export type DrawingSpace = 'data' | 'viewport';

/**
 * One anchor of a viewport drawing, as a fraction of the plot area of the pane
 * that holds the drawing. Pane-relative, not whole-chart-relative: the pane's
 * layer paints, clips and hit-tests the drawing, so these are the coordinates
 * that follow the pane when it moves, resizes or folds.
 *
 * `x` is 0 at the plot's left edge and 1 at its right edge; the price axes are
 * outside that span. `y` is 0 at the top of the pane and 1 at the bottom of its
 * plot, which on the lowest pane is the top of the time axis. Sizes that a tool
 * sets in pixels (a font size, a wrap width) stay in pixels: a resize moves a
 * note in proportion without scaling its type.
 */
export interface ViewportPoint {
  x: number;
  y: number;
}

/**
 * How new anchors snap to the bar under the cursor. `weak` snaps only when an
 * O/H/L/C sits within a few pixels of the pointer, so a click on empty space
 * lands where it was made; `strong` always takes the nearest of the four.
 */
export type MagnetMode = 'off' | 'weak' | 'strong';

/**
 * The text a drawing carries, and how it is set. The text tool *is* this box;
 * a shape (rectangle, channel, callout) carries one as its label.
 *
 * Kept apart from {@link DrawingStyle} because the two answer different
 * questions: style is how the outline is stroked, text is what the label says
 * and how it is typeset. A purple rectangle with white bold text is one shape
 * with two colours, and a settings panel wants them on different tabs.
 */
export interface DrawingText {
  /** Body text. `\n` starts a new line; see `wrap` for soft wrapping. */
  value: string;
  /** Falls back to `style.color`. */
  color?: string;
  /** Media px. Default 12. */
  fontSize?: number;
  /** CSS font stack. Defaults to the UI sans-serif stack. */
  fontFamily?: string;
  bold?: boolean;
  italic?: boolean;
  /** Horizontal alignment within the box. Default 'left'. */
  align?: 'left' | 'center' | 'right';
  /** Vertical placement within the box. Default 'top'. */
  valign?: 'top' | 'middle' | 'bottom';
  /** Soft-wrap at `wrapWidth` instead of running off the pane. */
  wrap?: boolean;
  /** Wrap width in media px. Default 220. */
  wrapWidth?: number;
  /** Draw a filled plate behind the text. */
  background?: boolean;
  backgroundColor?: string;
  /** Plate opacity, 0..1. Default 1: a text background is usually opaque. */
  backgroundOpacity?: number;
  /** Stroke a border around the plate. */
  border?: boolean;
  borderColor?: string;
  /**
   * Where a shape's label sits relative to the shape: `inside` the outline, or
   * `outside` just above it. Shapes only; the text tool is its own box.
   */
  position?: 'inside' | 'outside';
}

/** One level of a Fibonacci-family tool. */
export interface FibLevel {
  /** The level as a fraction of the anchor span (0.618, 1.618, ...). */
  ratio: number;
  /** Stroke colour. Falls back to the conventional colour for the ratio. */
  color?: string;
  /** `false` hides the level without forgetting it. Default true. */
  enabled?: boolean;
  /** Printed instead of the ratio when set. */
  label?: string;
}

export interface DrawingStyle {
  color?: string;
  lineWidth?: number;
  lineStyle?: 'solid' | 'dashed' | 'dotted';
  /** Fill the shape's interior (rectangle, ellipse, channel, position boxes). */
  fill?: boolean;
  fillColor?: string;
  /** 0..1. Defaults to 0.12. */
  fillOpacity?: number;
  /** Extend the line past its anchors. */
  extendLeft?: boolean;
  extendRight?: boolean;
  /** Draw level / price / ratio labels where the tool has them. */
  showLabels?: boolean;
  /** Fibonacci-family levels. Defaults per tool. */
  levels?: FibLevel[];
  /** Position tools: capital base and risk per trade, for the size readout. */
  accountSize?: number;
  risk?: number;
  /** Line tools: print the bar count, price change and angle at the midpoint. */
  showStats?: boolean;
  /** Brush: let pen pressure drive the stroke width. */
  pressure?: boolean;
}

/**
 * What a host allows the user to do with one drawing. The flags are
 * independent of one another and of `locked`, and each defaults to true, so a
 * drawing without a policy behaves exactly as one did before policies
 * existed. A copy (paste, duplicate) never inherits a policy: it is the
 * user's own drawing.
 *
 * `selectable`, `persistent` and `listed` bind every caller. `editable`
 * restricts the user: the controller cannot tell a click from a call, so its
 * methods treat every call as the user's unless it passes `{ force: true }`
 * (see `DrawingEditOptions`), which is how the host that placed the drawing
 * moves or retires it. Stacking order (front, back, either side of the
 * series) is outside the policy.
 */
export interface DrawingPolicy {
  /**
   * `false`: never joins the selection, whoever asks. A click passes through
   * to what lies under it, and nothing hovers, drags or selects it.
   */
  selectable?: boolean;
  /**
   * `false`: read-only to the user. It still selects, copies and duplicates,
   * but nothing moves, reshapes, restyles, hides, locks, cuts, deletes or
   * regroups it, and undo and redo never touch it or the group it is in.
   */
  editable?: boolean;
  /**
   * `false`: transient. Left out of `toJSON`, and so out of the chart state
   * and every saved layout, while it renders and undoes as usual in the
   * session. A restore replaces it with what was saved.
   */
  persistent?: boolean;
  /** `false`: left out of the object inventory (`ChartObjects`) and every panel built on it. */
  listed?: boolean;
}

/**
 * The chart intervals a drawing is shown on, both ends included, as interval
 * codes the chart's data context names (`'1m'`, `'1h'`, `'D'`, or a code the
 * host registered). An absent end is no limit on that side, so `{ to: '1h' }`
 * shows the drawing up to hourly bars. Intervals compare by bar length, so the
 * two ends may be written either way round. See `drawingShownOnInterval`.
 */
export interface DrawingIntervalRange {
  /** The shortest interval the drawing is shown on. */
  from?: string;
  /** The longest interval the drawing is shown on. */
  to?: string;
}

export interface Drawing {
  id: string;
  /** Registered tool id. */
  tool: string;
  /** Anchors in time and price. Empty on a viewport drawing, whose anchors are `viewportPoints`. */
  points: DrawingPoint[];
  /**
   * Which coordinates the anchors are in. Absent means `'data'`. Only a tool
   * that declares {@link DrawingTool.viewport} can be anchored to the viewport.
   */
  space?: DrawingSpace;
  /** The anchors of a viewport drawing, one per handle. Present only when `space` is `'viewport'`. */
  viewportPoints?: ViewportPoint[];
  style: DrawingStyle;
  /** The label (or, for the text tool, the whole content). */
  text?: DrawingText;
  /**
   * Per-tool extras that do not belong on every drawing (a table's cells, a
   * callout's tail side). Keeps the base shape closed while a tool stays free
   * to carry what it needs. Must be JSON-safe: it is persisted verbatim.
   */
  props?: Record<string, unknown>;
  paneIndex: number;
  /**
   * Locked drawings render but cannot be selected or dragged on the chart.
   * The user toggles it; a host restriction the user cannot lift is a
   * {@link DrawingPolicy}.
   */
  locked?: boolean;
  /** Host restrictions on this drawing. Absent means none. */
  policy?: DrawingPolicy;
  /** Default true. */
  visible?: boolean;
  /**
   * The chart intervals the drawing is shown on. Absent means every interval.
   * On an interval outside the range the drawing is kept and saved but not
   * on the chart: it is not painted, hit-tested, boxed or erased there, and
   * the object inventory marks it. `visible` stays the user's own switch.
   */
  intervals?: DrawingIntervalRange;
  /**
   * Paint order. Below zero paints under the series, at or above zero paints
   * over it. Ties break by array order, so two drawings at 0 paint in the
   * order they sit in the list. With `stackAbove` it orders the drawings
   * placed above the same entry.
   */
  zIndex: number;
  /**
   * Placed inside the series band, directly above one entry of its pane's
   * `chart.seriesStack()`: `'source:primary'` or `'indicator:<id>'`. It paints
   * after that entry's series and before the next entry's. While the entry
   * plots no series on this drawing's pane (a study removed or moved away) it
   * paints by `zIndex` as if absent, and returns when the entry does. Absent
   * means the drawing is not in the series band. See
   * `DrawingController.placeInStack`.
   */
  stackAbove?: string;
  /** Epoch ms, set by the controller when the drawing is added. */
  createdAt?: number;
}

/**
 * What `DrawingController.add` accepts: a drawing minus the fields the
 * controller fills in. `zIndex` defaults to 0, `createdAt` to now, and an id is
 * minted unless one is supplied.
 */
export type DrawingInput = Omit<Drawing, 'id' | 'zIndex' | 'createdAt'> & {
  id?: string;
  zIndex?: number;
  createdAt?: number;
};

/**
 * The fields `DrawingController.update` and `updateMany` can change. `policy`
 * merges flag by flag, the way `style` does.
 *
 * `space` on its own converts the anchors at the view on screen, so the
 * drawing stays exactly where it is and only stops (or starts) following the
 * bars. With the new space's anchors in the same patch (`viewportPoints` for
 * the viewport, `points` for data) they are taken as given. A conversion the
 * controller cannot make (a tool without viewport support, a pane with no
 * place on screen) is left out of the patch and the rest of it applies, and
 * `DrawingController.update` returns false.
 */
export type DrawingPatch = Partial<Pick<Drawing,
  'points' | 'style' | 'text' | 'props' | 'locked' | 'visible' | 'zIndex' | 'policy' | 'space' | 'viewportPoints'>>
  & {
    /** A series-band entry to paint directly above, or null to leave the series band. */
    stackAbove?: string | null;
    /**
     * The intervals to show the drawing on, replacing any range it had, or
     * null (or a range with neither end) to show it on every interval.
     */
    intervals?: DrawingIntervalRange | null;
  };

/**
 * What `DrawingController.placeInStack` puts a drawing next to: another
 * drawing of its pane, or an entry of its pane's series band.
 */
export type DrawingStackTarget = { drawing: string } | { entry: string };

/**
 * The newest document version this build reads and writes; bumped when
 * {@link Drawing} changes in a way an earlier build would lose. A document is
 * written as the lowest version that holds it (see {@link DrawingsDocument}).
 */
export const DRAWING_STATE_VERSION = 3;

/** A named set of drawing ids. A drawing belongs to at most one group. */
export interface DrawingGroup {
  id: string;
  name: string;
  members: string[];
}

/**
 * What `toJSON` returns and `ChartState.drawings` carries. Versioned so a 1.9.x
 * save (a bare `Drawing[]`) is recognisable and upgraded rather than misread.
 */
export interface DrawingsDocument {
  /**
   * 3 when a drawing carries an interval range, else 2: the lowest version
   * that holds the content, so an earlier build reads a document without a
   * range exactly as it wrote one.
   */
  version: 2 | 3;
  drawings: Drawing[];
  groups?: DrawingGroup[];
}

/** A point mapped to the pane, in media px. */
export interface ScreenPoint {
  x: number;
  y: number;
}

export interface DrawContext {
  ctx: CanvasRenderingContext2D;
  rc: PrimitiveRenderContext;
  /** Anchors in **device** px, ready to stroke. */
  pts: ScreenPoint[];
  drawing: Drawing;
  style: Required<Pick<DrawingStyle, 'color' | 'lineWidth'>> & DrawingStyle;
  selected: boolean;
  /** Format a price the way the pane's axis does. */
  formatPrice(price: number): string;
}

export interface HitContext {
  /** Anchors in **media** px, the same space as the incoming x/y. */
  pts: ScreenPoint[];
  drawing: Drawing;
  rc: PrimitiveRenderContext;
}

/** What {@link DrawingTool.expand} needs to size a default in chart units. */
export interface ExpandContext {
  /** Seconds between adjacent bars, so a default can span a sane bar count. */
  barSeconds: number;
  /**
   * Bars currently on screen. A default sized in fixed bars is a hairline when
   * zoomed out and fills the pane when zoomed in, so size against this instead.
   */
  visibleBars: number;
  /**
   * Anchor to media px on the placing pane, and back. Present when the host
   * can map coordinates, absent otherwise. A default sized in pixels (a
   * position box 64 px of risk tall, 150 px wide) reads the same at every
   * zoom and on every instrument, which a price percentage cannot: 1% of a
   * 2.87 stock and 1% of an index are the same fraction and very different
   * boxes. Without the mapping a tool falls back to chart units.
   */
  toPixel?(p: DrawingPoint): ScreenPoint | null;
  fromPixel?(at: ScreenPoint): DrawingPoint | null;
}

/** Coordinate maps use the same pane and logical time axis as the rendered drawing. */
export interface DrawingValueContext {
  drawing: Drawing;
  pts: readonly ScreenPoint[];
  time: number;
  x: number;
  fromY(y: number): number | null;
}

// The settings schema a tool declares (`DrawingTool.settings`). schema.ts
// builds and reads it and re-exports these names.

/**
 * The control a field wants. `interval` is a chart interval code, which the
 * host offers from its own interval list (the engine has none), with an
 * empty choice for no limit.
 */
export type FieldKind = 'color' | 'number' | 'select' | 'lineStyle' | 'boolean' | 'text' | 'opacity' | 'levels' | 'interval';

/** The section a host groups a field under. */
export type FieldGroup = 'line' | 'fill' | 'text' | 'levels' | 'behavior' | 'visibility';

export interface SettingsField {
  /**
   * Dot path into the drawing. Two segments under `style`, `text`, `props`
   * or `intervals` (`style.lineWidth`, `intervals.to`), or one of the
   * top-level fields `locked`, `visible`, `zIndex`, `space`.
   */
  path: string;
  label: string;
  kind: FieldKind;
  min?: number;
  max?: number;
  step?: number;
  /** For `select` and `lineStyle`: the values a host may offer. */
  options?: ReadonlyArray<{ value: string; label: string }>;
  group?: FieldGroup;
  /** Value displayed when the drawing has not overridden this setting. */
  defaultValue?: string | number | boolean;
}

export interface SettingsSchema {
  fields: SettingsField[];
  /**
   * The text *is* the drawing (a note, a callout, the text tool) rather than a
   * label on a shape, so a host should ask for it the moment the tool is
   * placed instead of waiting for a settings dialog.
   */
  textIsContent?: boolean;
}

export interface DrawingTool {
  id: string;
  name: string;
  /** Opt in only when the geometry defines a numeric level or band at one time. */
  alertValue?(context: DrawingValueContext, level?: string): Omit<AlertDrawingValue, 'paneIndex'> | undefined;
  /** Named boundaries or active rungs, for a host's explicit level selector. */
  alertLevels?(drawing: Drawing): readonly AlertDrawingLevel[];
  /**
   * Anchors the tool needs before it is complete. `0` means free-form: the
   * drawing finishes on double-click.
   */
  points: number;
  /**
   * Sample the cursor continuously while the pointer is held, and finish on
   * release: one press-drag-release gesture is one stroke. Brushes want this;
   * without it a `points: 0` tool collects a vertex per click, which is
   * polyline behaviour and never terminates on its own.
   */
  freehand?: boolean;
  /**
   * Hold Shift to snap the free end of a two-anchor tool to 45 degree steps
   * on screen, while placing and while dragging a handle. The line family
   * sets it; a tool whose second anchor is not the far end of a line (a
   * rectangle's opposite corner) leaves it off, since a locked diagonal is
   * not what Shift means there.
   */
  angleLock?: boolean;
  /**
   * The tool can be anchored to the viewport (`Drawing.space`). Declare it
   * only when `draw` and `distance` read the screen anchors (`pts`) and never
   * `drawing.points`, which is empty in that space, and when nothing the tool
   * prints is a price or a time: a label that reads the axis under a pinned
   * shape would change every time the chart panned. `expand`, `constrain` and
   * `alertValue` apply to data space only.
   */
  viewport?: boolean;
  /**
   * The box the drawing covers at `pts`, its anchors in media px (the space
   * of {@link HitContext}). A drawing anchored to the viewport is always
   * painted, hit-tested and moved with this box inside its pane's plot, so it
   * can be seen and grabbed at every edge and after the chart resizes, and no
   * drag, nudge or handle can take it out. Declare it on a `viewport` tool
   * that paints beyond its anchors, as the text note and the table do from
   * their one corner, and the rectangle and the ellipse do for a label above
   * them or wider than they are; without it the box is the anchors' own
   * bounds. A handle dragged toward an edge the box reaches first stops short
   * of it, so the other anchors stay where they are.
   */
  bounds?(pts: readonly ScreenPoint[], drawing: Drawing): { x0: number; y0: number; x1: number; y1: number };
  /**
   * Turn the anchors actually clicked into the full anchor set. Lets a tool drop
   * a complete, immediately editable default from fewer clicks: the position
   * tools place a 1:1 box off a single click, which the user then drags, rather
   * than demanding entry/target/stop be clicked in turn.
   *
   * The returned points become the drawing's anchors, so each one stays a
   * draggable handle.
   */
  expand?(clicked: readonly DrawingPoint[], ctx: ExpandContext): DrawingPoint[];
  /**
   * Keep the anchors consistent after one of them moves: a handle drag
   * (`handle` is its index) or a patch to `points` (`handle` is null). Returns
   * the anchors to store. The position tools use it to keep the stop and the
   * target on opposite sides of the entry, so dragging the stop up through
   * the entry of a long turns the trade into a short instead of piling both
   * levels on one side. Pure: the same input always yields the same output.
   */
  constrain?(points: readonly DrawingPoint[], handle: number | null): DrawingPoint[];
  /**
   * Keyboard shortcut that arms this tool, as `'Alt+T'` / `'Shift+Alt+F'`:
   * modifiers in `Ctrl`, `Alt`, `Shift` order, then a single key. Hosts render
   * it beside the tool's name in a palette and bind it with
   * `matchDrawingShortcut`; the library itself installs no listener, since only
   * the host knows whether the chart has focus or a dialog is open.
   */
  shortcut?: string;
  /** Merged under the caller's style when a drawing is created. */
  defaultStyle?: DrawingStyle;
  /**
   * Merged under the caller's text when a drawing is created. The text tool
   * uses it for its placeholder content and default size; a shape leaves it
   * unset so it carries no label until the user gives it one.
   */
  defaultText?: DrawingText;
  /**
   * The fields a settings panel offers for this tool. Every built-in declares
   * one; a custom tool without it gets the plain line fields.
   */
  settings?: SettingsSchema;
  draw(c: DrawContext): void;
  /**
   * Distance in media px from the cursor to the shape, or `null` for a miss.
   * Return `0` for "inside" so a filled region is grabbable anywhere.
   */
  distance(x: number, y: number, c: HitContext): number | null;
}

/**
 * A list of at least `N` items: a tuple of `N`, then any number more. A count
 * of plain `number`, one not known where the tool is written, promises none.
 * Internal to the tier, like the two types below; the public contract stays
 * {@link DrawingTool}.
 */
export type AtLeast<T, N extends number, A extends T[] = []> =
  number extends N ? T[] : A['length'] extends N ? [...A, ...T[]] : AtLeast<T, N, [...A, T]>;

/**
 * The anchors a built-in tool that declares `points: N` is handed. The layer
 * paints and hit-tests a drawing only once it holds `max(1, points)` anchors
 * in its own space (layer.ts, `anchorCount`), and runs `expand` only on that
 * many clicks, so the first `N` screen anchors are there, and in data space
 * the first `N` points. A tool that can be pinned (`V` true) is promised the
 * screen anchors only: its `drawing.points` is empty in the viewport.
 */
export type ToolAnchors<N extends number, V extends boolean = false> =
  { pts: AtLeast<ScreenPoint, N extends 0 ? 1 : N> }
  & (V extends true ? unknown : { drawing: Drawing & { points: AtLeast<DrawingPoint, N extends 0 ? 1 : N> } });

/**
 * A built-in tool written against {@link ToolAnchors}. `satisfies` ties the
 * anchors its body reads to the `points` it declares, and since `draw` and
 * `distance` are methods of {@link DrawingTool}, the tool is still one. It
 * costs nothing at run time: the guarantee is the layer's, stated here once.
 * `bounds` is promised the full set too: it is asked only of a complete
 * anchor set (layer.ts, `toolBounds`).
 */
export type AnchoredTool<N extends number, V extends boolean = false> =
  Omit<DrawingTool, 'points' | 'viewport' | 'expand' | 'bounds' | 'draw' | 'distance'> & {
    points: N;
    viewport?: V;
    expand?(clicked: AtLeast<DrawingPoint, N>, ctx: ExpandContext): DrawingPoint[];
    bounds?(pts: ToolAnchors<N, V>['pts'], drawing: Drawing): { x0: number; y0: number; x1: number; y1: number };
    draw(c: DrawContext & ToolAnchors<N, V>): void;
    distance(x: number, y: number, c: HitContext & ToolAnchors<N, V>): number | null;
  };
