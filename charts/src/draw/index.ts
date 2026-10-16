/**
 * Drawing tier (opt-in: "openalgo-charts/draw").
 *
 * The built-in tools plus a headless controller. Importing this module
 * registers every built-in tool as a side effect. The named descriptor
 * re-exports below cover the most-customised subset; `BUILTIN_DRAWING_TOOLS`
 * is the full list and `registeredDrawingTools()` reads the live registry.
 *
 * ```ts
 * import { createChart } from 'openalgo-charts';
 * import { DrawingController } from 'openalgo-charts/draw';
 *
 * const chart = createChart(el);
 * chart.addSeries('candlestick').setData(bars);
 *
 * const draw = new DrawingController(chart, { magnet: true });
 * draw.setTool('trend-line');   // next two clicks place it
 * ```
 *
 * The controller ships **no UI**: no toolbar, no dialogs. It exposes the model
 * and the interactions; a host wires its own buttons (or the widget package)
 * to `setTool` / `undo` / `remove`, and its own `keydown` to
 * `keyToDrawingAction`.
 *
 * The drawing-tool registry is this tier's own (registry.ts), and importing
 * the tier fills it with the built-ins. What the tier needs from the base at
 * run time, the interval and indicator lookups (`tryResolveInterval`,
 * `getIndicator`, `plotStyleKeys`), it imports from the package entry rather
 * than a deep path, because those registries live in the base bundle and a
 * deep import would inline a second, empty copy of them; see rollup.config.js.
 */
import { registerBuiltinDrawingTools } from './tools';

export const DRAW_TIER = 'draw' as const;

export { ANCHORED_VWAP, FIXED_RANGE_VOLUME_PROFILE } from './analysis-tools';
export { anchoredVwapAnalysis, fixedRangeVolumeProfileAnalysis } from './analysis';
export type {
  AnalysisStatus, AnchoredVwapSource, AnchoredVwapOptions, AnchoredVwapPoint, AnchoredVwapResult,
  FixedRangeVolumeProfileOptions, AnalysisProfileRow, FixedRangeVolumeProfileResult,
} from './analysis';
export { DrawingLinkGroup, createDrawingLinkGroup } from './drawing-link';
export type { DrawingLinkContext, DrawingLinkContextSource, DrawingLinkOptions, DrawingLinkChart } from './drawing-link';
// Drawings per instrument. DOM-free: the store is the host's, localStorage
// only when the host hands it over.
export {
  InstrumentDrawings, createInstrumentDrawings, instrumentDrawingsKey, memoryDrawingStore, webStorageDrawingStore,
  migrateUnscopedDrawings,
} from './instrument-drawings';
export type {
  DrawingInstrument, DrawingDocumentStore, DrawingTextStorage, InstrumentDrawingsChart, InstrumentDrawingsError,
  InstrumentDrawingsOptions,
} from './instrument-drawings';

registerBuiltinDrawingTools(); // side effect on tier import

export {
  registerDrawingTool,
  getDrawingTool,
  hasDrawingTool,
  registeredDrawingTools,
  matchDrawingShortcut,
  drawingShortcuts,
  // A registry lookup, so it lives with the registry rather than in schema.ts.
  drawingSettingsSchema,
} from './registry';
export {
  registerBuiltinDrawingTools,
  BUILTIN_DRAWING_TOOLS,
  TREND_LINE, RAY, EXTENDED_LINE, ARROW,
  HORIZONTAL_LINE, HORIZONTAL_RAY, VERTICAL_LINE, CROSS_LINE,
  RECTANGLE, ELLIPSE, PARALLEL_CHANNEL,
  PATH,
  // The 2.0 additions: shape, freehand and cycle families.
  CIRCLE, TRIANGLE, POLYLINE, ARC, CURVE, ROTATED_RECTANGLE, DOUBLE_CURVE,
  HIGHLIGHTER, BRUSH,
  CYCLIC_LINES, TIME_CYCLES, SINE_LINE,
} from './tools';
export {
  FIB_RETRACEMENT, FIB_EXTENSION,
  FIB_CHANNEL, FIB_TIME_ZONE, FIB_FAN, GANN_FAN, GANN_BOX,
} from './fib-tools';
export { LONG_POSITION, SHORT_POSITION, MEASURE, FORECAST, PRICE_RANGE, DATE_RANGE } from './measure-tools';
export {
  TEXT,
  // Annotations: the marks whose job is a human sentence on the chart.
  NOTE, BALLOON, COMMENT, SIGNPOST, PRICE_NOTE, TABLE,
  ARROW_UP, ARROW_DOWN, ARROW_LEFT, ARROW_RIGHT,
  PRICE_LABEL, CALLOUT, FLAG_MARK,
} from './annotation-tools';

// Per-tool settings schema. Pure and DOM-free: a host renders its own dialog
// from the field list and writes the result back through
// `applyDrawingSettings`, which coerces form strings and drops anything the
// schema does not declare.
export {
  composeSettings, readDrawingSetting, readDrawingSettings, coerceSettingValue, applyDrawingSettings,
  LINE_FIELDS, FILL_FIELDS, EXTEND_FIELDS, LEVEL_FIELDS, TEXT_FIELDS, FONT_FIELDS, SHAPE_TEXT_FIELDS, PLATE_TEXT_FIELDS,
  COLOR_FIELD, LINE_WIDTH_FIELD, LINE_STYLE_FIELD, SHOW_LABELS_FIELD, TEXT_VALUE_FIELD, SPACE_FIELD, INTERVAL_FIELDS,
  LINE_STYLE_OPTIONS, ALIGN_OPTIONS, VALIGN_OPTIONS, TEXT_POSITION_OPTIONS, FONT_OPTIONS, SPACE_OPTIONS,
  type FieldKind, type FieldGroup, type SettingsField, type SettingsSchema,
} from './schema';

// Level ladders shared by the fib and gann family, and the colour convention a
// host wants when it builds a level editor of its own.
export {
  levelColor, cycleColor, formatRatio, gannLabel, cloneLevels,
  LEVEL_NEUTRAL, CYCLE_PALETTE, DEFAULT_FIB, DEFAULT_FIB_FAN, DEFAULT_GANN_BOX, DEFAULT_GANN_FAN, DEFAULT_FIB_TIME_ZONE,
} from './levels';

// Glyphs. Path data for both grids lives in icons.ts; icon-svg.ts derives
// inline markup, a sprite and a CSS cursor from it, so every surface that
// shows a tool reads from one source.
export {
  DRAWING_TOOL_ICONS, drawingToolIcon, drawingToolIconIds,
  DRAWING_TOOL_ACCENTS, drawingToolAccent,
  ICON_VIEWBOX, ICON_SIZE, ICON_STROKE, ICON_ATTRS,
  CHROME_ICONS, CHROME_ICON_FILLED, chromeIcon, chromeIconIds,
  CHROME_ICON_ACCENTS, chromeIconAccent,
  CHROME_ICON_VIEWBOX, CHROME_ICON_SIZE, CHROME_ICON_STROKE, CHROME_ICON_ATTRS,
  chartTypeIcon, layoutIconPath,
  type IconAttrs, type LayoutIconSlot,
} from './icons';
export {
  iconSvg, chromeIconSvg, iconSprite, iconUse, toolCursor, ICON_SYMBOL_PREFIX,
  type IconSvgOptions, type ToolCursorOptions,
} from './icon-svg';

export { DrawingLayer, sortByZIndex, type DrawingLayerOrder, type DrawingPointerKind } from './layer';
export {
  DrawingController,
  type DrawingControllerOptions,
  type DrawingChangeKind,
  type DrawingChangeEvent,
  type DrawingEditOptions,
  type DrawingPlacementOptions,
  type DrawingGestureOptions,
} from './controller';

// Keyboard editing. Pure: the host owns the listener and asks what a key means.
export {
  keyToDrawingAction,
  NUDGE_STEP_PX,
  NUDGE_STEP_SHIFT_PX,
  type DrawingKeyAction,
  type DrawingKeyEvent,
  type DrawingKeyContext,
} from './keys';

// Clipboard transfer. `DrawingControllerOptions.clipboard` is typed as
// `ClipboardPort` and `DrawingController.clipboard()` returns a
// `DrawingClipboard`, so both have to be nameable from the tier entry or a
// TypeScript host can use neither. The encode and decode pair is exported for
// a host moving drawings over its own transport (a websocket, a saved
// template): decoding validates exactly as a paste does. `sanitizeDrawing` is
// the paste's per-entry gate alone, without the migration a paste runs after
// it, so it keeps a style key this build does not declare, which a paste drops.
export {
  DrawingClipboard,
  clearMemoryClipboard,
  systemClipboard,
  encodeClipboardPayload,
  decodeClipboardPayload,
  sanitizeDrawing,
  cloneDrawing,
  DRAWING_CLIPBOARD_KEY,
  DRAWING_CLIPBOARD_VERSION,
  type ClipboardPort,
  type DrawingClipboardOptions,
} from './clipboard';

// Persistence. `fromJSON` runs the migration itself; it is exported for a host
// that reads a saved layout for its own purposes (a template list, a preview)
// and wants the 2.0 shape without a controller.
export { migrateDrawings } from './migrate';
export { DRAWING_STATE_VERSION } from './types';
// Visibility per interval, for a host marking what a range hides without a
// controller at hand; the controller's own answer is `shownOnInterval`.
export { drawingShownOnInterval } from './intervals';
export type {
  Drawing,
  DrawingInput,
  DrawingPatch,
  DrawingPolicy,
  // Where `placeInStack` puts a drawing: next to another drawing or a series-band entry.
  DrawingStackTarget,
  DrawingPoint,
  // Viewport anchoring: a drawing pinned to the screen instead of to time and price.
  DrawingSpace,
  ViewportPoint,
  // The chart intervals a drawing is shown on.
  DrawingIntervalRange,
  DrawingGroup,
  DrawingStyle,
  DrawingText,
  DrawingsDocument,
  FibLevel,
  DrawingTool,
  DrawContext,
  HitContext,
  ScreenPoint,
  // `DrawingControllerOptions.magnet` accepts it; a host with a snap picker
  // wants the three names as one type.
  MagnetMode,
  // `DrawingTool.expand` receives this; a custom tool cannot type its own
  // implementation without it.
  ExpandContext,
  DrawingValueContext,
} from './types';

// What `new DrawingController(chart)` accepts. Exported so a host wiring the
// controller to something other than a Chart can state what it must provide.
export type { DrawingChartHost } from './controller';

// The tier's payloads on the chart bus. './events' adds the `draw:*` and
// `drawing:*` names to the base's `ChartEventMap` by declaration merging, so
// importing the tier types `chart.on('draw:add', ...)`. It holds types alone.
export type {
  DrawingEvent, DrawingListEvent, DrawingIdsEvent, DrawingIdEvent, DrawingToolEvent, DrawingModeEvent,
} from './controller-types';
import './events';

// Where a study's price input is picked and anchored. The controller draws a
// paired input's anchor there; a host's own settings form asks the same
// question before it offers a pick.
export { studyInputTarget } from './input-anchors';
export type { StudyInputTarget, InputAnchorStep } from './input-anchors';

export type { ShortcutEvent } from './registry';

export {
  distToSegment, distToLine, distToPolyline,
  distToRect, distToEllipse, rectOf, boundsOf, extendSegment,
} from './geometry';

// Freehand stroke geometry. Pure and DOM-free: a host or a custom tool that
// captures its own pointer trail can thin, smooth and weight it the way the
// brush and highlighter do.
export { rdpSimplify, catmullRom, pressureWidth } from './freehand';

export { ADVANCED_LINE_TOOLS } from './advanced-lines';
export { ADVANCED_GEOMETRY_TOOLS } from './advanced-geometry';
export { PATTERN_DRAWING_TOOLS } from './pattern-tools';
