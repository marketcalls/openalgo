/**
 * Pane legend (ARCHITECTURE.md §8): the row at the top-left
 * of a pane: a color swatch, the source's name, its parameters, the value under
 * the crosshair, and inline action buttons on the right.
 *
 * Drawn on the canvas rather than in the DOM, like `BuySellButtons` and
 * `DomLadder`, so it composites into screenshots and costs no DOM per pane.
 * Buttons hit-test as `${id}::close`, `${id}::hide`, and `${id}::settings`, so
 * the host routes them through the same `subscribeClick` path as order pills.
 *
 * Rows stack: several legends on one pane offset each other vertically, which
 * the host does by giving each a `row` index.
 *
 * This row is also the chart's status line, so `statusLine` carries the
 * per-field switches a settings dialog expects (logo, title, market status,
 * chart values, bar change, volume, last day change, background). Every switch
 * defaults to the behaviour that predates it, so a caller that passes none sees
 * the row it always saw. Fields the primitive cannot compute (a logo bitmap,
 * whether the market is open, the change since yesterday's close) arrive
 * through `status`; with no source they draw nothing at all rather than a
 * placeholder.
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, PrimitiveHit, ZOrder } from './primitive';
import { withAlpha } from '../render/pill';
import type { LooseOptional } from '../helpers/types';

export type PaneLegendAction = 'hide' | 'settings' | 'source' | 'up' | 'down' | 'collapse' | 'maximize' | 'close';

/**
 * One reading on a legend row. Multi-plot sources show one per plot, each in
 * that plot's own color (an MA ribbon's four averages, MACD's three lines):
 * a single string in a single color cannot say which number is which.
 */
export interface LegendValue {
  /** Dimmed prefix, e.g. `O` / `H` / `Vol`. */
  label?: string;
  text: string;
  /** Defaults to the row's `valueColor`, then `color`, then the theme text. */
  color?: string;
  /**
   * Which status-line switch owns this reading. Untagged readings are the
   * source's own last value, governed by `statusLine.lastValueLabel`.
   */
  field?: LegendField;
  /** Higher values retain this whole reading on narrow rows. Series readings default to 1; status metadata ranks lower. */
  priority?: number;
}

/**
 * Status-line groups a host can feed and switch off independently. The legend
 * never derives these: it tags what the host hands it, so one switch hides one
 * group and leaves the rest of the row alone.
 */
export type LegendField = 'ohlc' | 'change' | 'volume' | 'openInterest';

/**
 * Which name the title shows. `description` and `ticker` come from `status`;
 * with neither supplied the title falls back to `title`, which always exists.
 */
export type LegendTitleMode = 'symbol' | 'description' | 'ticker';

/**
 * The parts of the status line the primitive has no way to know. The host
 * supplies what it has; anything missing is simply not drawn.
 */
export interface LegendStatusData {
  /** Already-decoded logo (an `<img>`, an `ImageBitmap`, a canvas). */
  logo?: CanvasImageSource;
  /** Long name for `titleMode: 'description'`, e.g. `Apple Inc.`. */
  description?: string;
  /** Exchange ticker for `titleMode: 'ticker'`, e.g. `NASDAQ:AAPL`. */
  ticker?: string;
  /** Session state, e.g. `{ text: 'Market open', color: '#26a69a' }`. */
  marketStatus?: LegendValue;
  /** Change against the previous close, e.g. `{ text: '+1.20 (+0.75%)' }`. */
  lastDayChange?: LegendValue;
}

/**
 * A snapshot, or a getter the legend calls each frame, so live fields (market
 * status, day change) can change without the host patching options at tick
 * speed. Returning `null` means "nothing to show".
 */
export type LegendStatusSource = LegendStatusData | (() => LegendStatusData | null);

/**
 * Per-field switches for the status line. Existing reading fields default to
 * on; open interest and the background plate default to off. A missing reading
 * draws nothing whether its switch is on or off.
 */
export interface LegendStatusLineOptions {
  /** Symbol logo, when `status` supplies one. */
  logo?: boolean;
  /** The bold name. Also the "name label" switch for an indicator row. */
  title?: boolean;
  /** Which name the title shows. Default `symbol`. */
  titleMode?: LegendTitleMode;
  /** Session state from `status.marketStatus`. */
  marketStatus?: boolean;
  /** The OHLC readout: readings tagged `field: 'ohlc'`. */
  chartValues?: boolean;
  /** Change over the hovered bar: readings tagged `field: 'change'`. */
  barChange?: boolean;
  /** Readings tagged `field: 'volume'`. */
  volume?: boolean;
  /** Readings tagged `field: 'openInterest'`. Off by default. */
  openInterest?: boolean;
  /** Change since the previous close, from `status.lastDayChange`. */
  lastDayChange?: boolean;
  /**
   * The source's own reading (untagged values). This is the scales-and-lines
   * "last value label" control, which lands here because the legend is what
   * draws that number on this row.
   */
  lastValueLabel?: boolean;
  /**
   * Plate behind the row's text, for legibility over candles. Off by default:
   * the row has never had one, and turning it on is a deliberate choice.
   */
  background?: boolean;
  /** Plate opacity, 0..1. Default 0.8, matching the hover plate. */
  backgroundOpacity?: number;
  /** Plate color. Defaults to the theme background. */
  backgroundColor?: string;
}

export interface PaneLegendOptions {
  /** Explicit false suppresses OI without discarding its saved switch. Set by an owning chart. */
  hasOpenInterest?: boolean;
  /** Stable id; buttons hit-test as `${id}::close` etc. */
  id: string;
  /** Bold source name, e.g. `RSI`. */
  title: string;
  /** Dimmed parameter summary after the title, e.g. `14 close`. */
  params?: string;
  /** Swatch color; omitted draws no swatch. */
  color?: string;
  /**
   * Color for the live value. Defaults to `color`, then the theme's text, so a
   * row can tint its reading (an up/down change) without being forced to show a
   * swatch in that same color.
   */
  valueColor?: string;
  /** Vertical slot on the pane (0 = topmost). */
  row?: number;
  /**
   * Which inline action buttons to draw, left to right. Each hit-tests as
   * `${id}::<action>`:
   *  - `up` / `down`: move this pane one slot (`::up` / `::down`)
   *  - `hide`: toggle visibility (`::hide`)
   *  - `settings`: open this source's settings (`::settings`)
   *  - `source`: show the code this source was written from (`::source`)
   *  - `collapse`: fold this pane to a header strip, or open it again (`::collapse`)
   *  - `maximize`: expand this pane to fill the chart (`::maximize`)
   *  - `close`: remove the source, and its pane if it empties (`::close`)
   *
   * When only some actions fit, the end of this list stays visible.
   * Defaults to `['hide', 'settings', 'close']`. A chart drawing a study's row
   * adds the pane's own controls to it: on the first row of a pane other than
   * the price pane it puts `up`, `down`, `collapse` and `maximize` before
   * `close` (last when the row has none), and it leaves out `close` or
   * `settings` where the study's policy refuses them.
   */
  actions?: readonly PaneLegendAction[];
  /** Rendered as hidden (dimmed, eye hollow). */
  hidden?: boolean;
  /** False removes this row and its hit areas. Independent of the dimmed study visibility state. */
  visible?: boolean;
  /** Rendered as maximized (the maximize glyph becomes restore). */
  maximized?: boolean;
  /** Rendered as collapsed (the collapse glyph points the other way). */
  collapsed?: boolean;
  /** Text size in media px. Default 11. */
  font?: number;
  /**
   * Square side of one action button in media px. Default 16.
   *
   * The row grows to hold it, so raising this moves every legend row below it
   * down by the same amount and nothing overlaps. It is a chart-wide setting
   * for that reason: two legends on one pane with different button sizes would
   * stack against different row heights and collide.
   */
  iconSize?: number;
  /** Left inset from the plot edge in media px. Default 8. */
  left?: number;
  /** Top inset in media px. Default 6. */
  top?: number;
  /** Per-field status-line switches. Patching merges field by field. */
  statusLine?: LegendStatusLineOptions;
  /** Host-supplied status-line data (logo, names, market state, day change). */
  status?: LegendStatusSource;
}

const ROW_H = 18;
const GAP = 6;
/** Default square side of an action button, in media px. */
const BTN = 16;
/** The range `iconSize` is held to: smaller is unhittable, larger is a toolbar. */
const BTN_MIN = 12;
const BTN_MAX = 28;
/**
 * Clearance above and below a button, in media px.
 *
 * One, because that is exactly what the default 16px button has always had
 * inside an 18px row. Anything larger would raise the height of every row on
 * every chart to gain nothing: the row only has to grow once a button asks for
 * more than the default gives it.
 */
const BTN_MARGIN = 1;
/**
 * The glyph's half-extent as a fraction of its button.
 *
 * A fraction of the *button* rather than of the text, which is what it used to
 * be: an icon lives in its box, not beside a word, so tying it to the font left
 * a 9px drawing adrift in a 16px square and reading as an afterthought. At the
 * default size this makes each glyph about a quarter larger than it was.
 */
const GLYPH = 0.36;
/** Square side of the symbol logo, in media px: fits the row with margin. */
const LOGO = 12;
/** Extra hover width past the text, so the controls can appear without a gap. */
const REVEAL_PAD = 130;
const FONT = 'ui-sans-serif, system-ui, sans-serif';
/** Shared empties, so the common "no options, no data" path allocates nothing. */
const NO_SWITCHES: LegendStatusLineOptions = {};
const NO_STATUS: LegendStatusData = {};

/** One button's side in media px, held inside the range the row can carry. */
function buttonSize(o: { iconSize?: number | undefined }): number {
  const wanted = o.iconSize;
  if (typeof wanted !== 'number' || !Number.isFinite(wanted)) return BTN;
  return Math.max(BTN_MIN, Math.min(BTN_MAX, wanted));
}

/**
 * The row's height in media px: the default, or whatever the buttons need.
 *
 * Both the stacking offset and the hit box are measured from this, so a taller
 * row moves the rows below it instead of drawing through them.
 */
export function paneLegendRowHeight(o: { iconSize?: number | undefined }): number {
  return Math.max(ROW_H, buttonSize(o) + BTN_MARGIN * 2);
}

/**
 * One measured piece of the row. The whole row is measured before any of it is
 * drawn: the background plate has to be filled first to sit behind the text,
 * and it cannot know its width until the text has been measured.
 */
type Seg =
  | { k: 'logo'; img: CanvasImageSource; w: number; gap: number }
  | { k: 'dot'; color: string; w: number; gap: number }
  | { k: 'text'; text: string; color: string; bold: boolean; w: number; gap: number };

interface SegmentGroup { parts: Seg[]; priority: number; reading?: boolean }
const groupWidth = (group: SegmentGroup): number => group.parts.reduce((sum, part) => sum + part.w + part.gap, 0);

/** Fit whole readings; a clipped numeric suffix can look like a different price. */
function fitGroups(ctx: CanvasRenderingContext2D, groups: SegmentGroup[], title: Seg | undefined, width: number): Seg[] {
  if (groups.reduce((sum, group) => sum + groupWidth(group), 0) <= width) return groups.flatMap(group => group.parts);
  const ranked = groups.filter(group => !group.parts.includes(title!)).sort((a, b) => b.priority - a.priority);
  if (title?.k === 'text') {
    const preferred = ranked.find(group => group.reading);
    const readingWidth = preferred ? groupWidth(preferred) : 0;
    const reserved = readingWidth <= width * 0.75 ? readingWidth : 0;
    const budget = Math.max(0, width - reserved - title.gap);
    if (title.w > budget) {
      const chars = Array.from(title.text);
      let from = 0, to = chars.length;
      while (from < to) {
        const mid = Math.ceil((from + to) / 2);
        if (ctx.measureText(chars.slice(0, mid).join('') + '...').width <= budget) from = mid;
        else to = mid - 1;
      }
      title.text = ctx.measureText('...').width <= budget ? chars.slice(0, from).join('') + '...' : '';
      title.w = ctx.measureText(title.text).width;
      if (!title.text) title.gap = 0;
    }
    width -= title.w + title.gap;
  }
  const kept = new Set<SegmentGroup>();
  for (const group of ranked) {
    const size = groupWidth(group);
    if (size <= width) { kept.add(group); width -= size; }
  }
  return groups.filter(group => group.parts.includes(title!) || kept.has(group)).flatMap(group => group.parts);
}

/** Each group follows its own default and the instrument's capability. */
function fieldOn(s: LegendStatusLineOptions, field: LegendField | undefined, hasOpenInterest?: boolean): boolean {
  if (field === 'ohlc') return s.chartValues !== false;
  if (field === 'change') return s.barChange !== false;
  if (field === 'volume') return s.volume !== false;
  if (field === 'openInterest') return s.openInterest === true && hasOpenInterest !== false;
  return s.lastValueLabel !== false;
}

/**
 * Per-source actions, mirroring the indicator legend toolbar: show/hide,
 * settings, delete. Pane-level actions (`up`/`down`/`collapse`/`maximize`) are
 * added by the host to the *first* legend on a pane, so extra rows stay uncluttered.
 */
const DEFAULT_ACTIONS: readonly PaneLegendAction[] = ['hide', 'settings', 'close'];

/**
 * Action icons as vector strokes rather than text glyphs: the maximize square,
 * the trash can and the arrows render inconsistently (or as emoji) across
 * platforms and font stacks, and a stroked path stays crisp at any DPR.
 */
function drawGlyph(
  ctx: CanvasRenderingContext2D,
  action: PaneLegendAction,
  cx: number,
  cy: number,
  btn: number,
  dpr: number,
  o: PaneLegendOptions,
): void {
  const r = btn * GLYPH * dpr;           // half-extent of the icon box
  // The stroke thickens with the button, or a larger icon reads as a fainter
  // one: the same hairline stretched over more area.
  const w = Math.max(1, Math.round((1.4 * btn * dpr) / BTN));
  ctx.save();
  ctx.strokeStyle = ctx.fillStyle;
  ctx.lineWidth = w;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.beginPath();
  switch (action) {
    case 'up':
      ctx.moveTo(cx, cy + r); ctx.lineTo(cx, cy - r);
      ctx.moveTo(cx - r * 0.62, cy - r * 0.35); ctx.lineTo(cx, cy - r);
      ctx.lineTo(cx + r * 0.62, cy - r * 0.35);
      break;
    case 'down':
      ctx.moveTo(cx, cy - r); ctx.lineTo(cx, cy + r);
      ctx.moveTo(cx - r * 0.62, cy + r * 0.35); ctx.lineTo(cx, cy + r);
      ctx.lineTo(cx + r * 0.62, cy + r * 0.35);
      break;
    case 'hide': {
      // Eye: two arcs forming a lens, with a pupil. Hidden state strikes it through.
      ctx.moveTo(cx - r, cy);
      ctx.quadraticCurveTo(cx, cy - r * 1.15, cx + r, cy);
      ctx.quadraticCurveTo(cx, cy + r * 1.15, cx - r, cy);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(cx, cy, r * 0.34, 0, Math.PI * 2);
      if (o.hidden === true) {
        ctx.moveTo(cx - r, cy + r * 0.85); ctx.lineTo(cx + r, cy - r * 0.85);
      }
      break;
    }
    case 'maximize':
      if (o.maximized === true) {
        // restore: inward corner brackets
        ctx.moveTo(cx - r, cy - r * 0.25); ctx.lineTo(cx - r * 0.25, cy - r * 0.25); ctx.lineTo(cx - r * 0.25, cy - r);
        ctx.moveTo(cx + r, cy + r * 0.25); ctx.lineTo(cx + r * 0.25, cy + r * 0.25); ctx.lineTo(cx + r * 0.25, cy + r);
      } else {
        // maximize: four outward corner brackets
        ctx.moveTo(cx - r, cy - r * 0.4); ctx.lineTo(cx - r, cy - r); ctx.lineTo(cx - r * 0.4, cy - r);
        ctx.moveTo(cx + r * 0.4, cy - r); ctx.lineTo(cx + r, cy - r); ctx.lineTo(cx + r, cy - r * 0.4);
        ctx.moveTo(cx + r, cy + r * 0.4); ctx.lineTo(cx + r, cy + r); ctx.lineTo(cx + r * 0.4, cy + r);
        ctx.moveTo(cx - r * 0.4, cy + r); ctx.lineTo(cx - r, cy + r); ctx.lineTo(cx - r, cy + r * 0.4);
      }
      break;
    case 'collapse': {
      // A header bar with a chevron under it: pointing up folds the pane into
      // its header, pointing down opens it again.
      const tip = o.collapsed === true ? r * 0.6 : 0;
      ctx.moveTo(cx - r, cy - r * 0.7); ctx.lineTo(cx + r, cy - r * 0.7);
      ctx.moveTo(cx - r * 0.6, cy + r * 0.6 - tip); ctx.lineTo(cx, cy + tip); ctx.lineTo(cx + r * 0.6, cy + r * 0.6 - tip);
      break;
    }
    case 'settings': {
      // Gear: a ring plus eight short teeth.
      ctx.arc(cx, cy, r * 0.46, 0, Math.PI * 2);
      for (let i = 0; i < 8; i++) {
        const a = (i * Math.PI) / 4;
        const dx = Math.cos(a);
        const dy = Math.sin(a);
        ctx.moveTo(cx + dx * r * 0.68, cy + dy * r * 0.68);
        ctx.lineTo(cx + dx * r, cy + dy * r);
      }
      break;
    }
    case 'source': {
      // A pair of braces, the one mark that reads as "code" without a word.
      // Each is three strokes: a top hook, a middle notch, a bottom hook, so
      // the shape survives at eleven pixels where a curly outline would blur.
      const x = r * 0.62;                // how far out each brace sits
      const lip = r * 0.34;              // the horizontal reach of a hook
      const notch = r * 0.28;            // how far the waist pinches inward
      // `side` is which brace: -1 is the opening one on the left. Its hooks
      // reach INWARD, toward what it encloses, and its waist pinches OUTWARD,
      // away from it. Getting those two signs the same way round draws the
      // pair mirrored, `} {`, which is a mark that means nothing.
      for (const side of [-1, 1]) {
        const ox = cx + side * x;
        ctx.moveTo(ox - side * lip, cy - r);
        ctx.quadraticCurveTo(ox, cy - r, ox, cy - r * 0.55);
        ctx.lineTo(ox, cy - r * 0.2);
        ctx.quadraticCurveTo(ox, cy, ox + side * notch, cy);
        ctx.quadraticCurveTo(ox, cy, ox, cy + r * 0.2);
        ctx.lineTo(ox, cy + r * 0.55);
        ctx.quadraticCurveTo(ox, cy + r, ox - side * lip, cy + r);
      }
      break;
    }
    case 'close':
      // Trash: lid, can, and two tick marks.
      ctx.moveTo(cx - r * 0.8, cy - r * 0.55); ctx.lineTo(cx + r * 0.8, cy - r * 0.55);
      ctx.moveTo(cx - r * 0.3, cy - r * 0.55); ctx.lineTo(cx - r * 0.3, cy - r * 0.85);
      ctx.lineTo(cx + r * 0.3, cy - r * 0.85); ctx.lineTo(cx + r * 0.3, cy - r * 0.55);
      ctx.moveTo(cx - r * 0.6, cy - r * 0.55); ctx.lineTo(cx - r * 0.45, cy + r * 0.85);
      ctx.lineTo(cx + r * 0.45, cy + r * 0.85); ctx.lineTo(cx + r * 0.6, cy - r * 0.55);
      break;
  }
  ctx.stroke();
  ctx.restore();
}

export class PaneLegend implements IPrimitive {
  private _opts: Required<Pick<PaneLegendOptions, 'id' | 'title'>> & PaneLegendOptions;
  private _host: PrimitiveHost | null = null;
  private _values: LegendValue[] = [];
  /** Button geometry from the last draw, in media px, for hit-testing. */
  private _buttons: { id: string; x: number; y: number }[] = [];
  /** Right edge of the drawn row, in media px. */
  private _width = 0;
  private _plotWidth = 0;
  private _plotHeight = 0;
  private _suppressed = false;

  public constructor(opts: PaneLegendOptions) {
    this._opts = { font: 11, left: 8, top: 6, row: 0, ...opts };
  }

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; }
  public zOrder(): ZOrder { return 'top'; }
  public autoscaleInfo(): null { return null; }

  /** @internal Chart display policy, kept separate from the row's own options. */
  public setSuppressed(on: boolean): void {
    if (this._suppressed === on) return;
    this._suppressed = on;
    if (on) this._clearGeometry();
    this._host?.requestUpdate();
  }

  private _clearGeometry(): void {
    this._buttons = [];
    this._width = this._plotWidth = this._plotHeight = 0;
  }

  /** A single live reading after the params (typically crosshair-driven). */
  public setValue(text: string, color?: string): void {
    // An omitted color arrives as undefined, which every reader treats as absent.
    this.setValues(text === '' ? [] : [{ text, color } satisfies LooseOptional<LegendValue> as LegendValue]);
  }

  /** One reading per plot, each in its own color. */
  public setValues(values: readonly LegendValue[]): void {
    // The lengths match before `every` reads the old list at the new one's indices.
    const same = values.length === this._values.length
      && values.every((v, i) => v.text === this._values[i]!.text
        && v.label === this._values[i]!.label && v.color === this._values[i]!.color
        && v.field === this._values[i]!.field && v.priority === this._values[i]!.priority);
    if (same) return;
    this._values = values.map((v) => ({ ...v }));
    this._host?.requestUpdate();
  }

  public setOptions(patch: Partial<PaneLegendOptions>): void {
    // Switches merge field by field: a settings dialog toggles one checkbox at
    // a time, and a shallow spread would silently reset the other nine.
    const prev = this._opts.statusLine;
    this._opts = { ...this._opts, ...patch };
    if (patch.statusLine !== undefined) {
      this._opts.statusLine = { ...prev, ...patch.statusLine };
    }
    if (this._opts.visible === false) this._clearGeometry();
    this._host?.requestUpdate();
  }

  /** Resolve the host's status data for this frame; `{}` when it has none. */
  private _status(): LegendStatusData {
    const src = this._opts.status;
    if (src === undefined) return NO_STATUS;
    return (typeof src === 'function' ? src() : src) ?? NO_STATUS;
  }

  public options(): PaneLegendOptions {
    return this._opts;
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    const o = this._opts;
    if (this._suppressed || o.visible === false) { this._clearGeometry(); return; }
    const dpr = rc.dpr;
    const f = (o.font ?? 11) * dpr;
    const btn = buttonSize(o);
    const rowH = paneLegendRowHeight(o);
    const y = ((o.top ?? 6) + (o.row ?? 0) * rowH) * dpr;
    const cy = y + (rowH * dpr) / 2;
    const x0 = (o.left ?? 8) * dpr;
    let x = x0;
    const dim = o.hidden === true;
    const s = o.statusLine ?? NO_SWITCHES;
    const data = this._status();
    const dimText = withAlpha(rc.theme.axisText, 0.55);
    this._plotWidth = Math.max(0, rc.plotWidth);
    this._plotHeight = Math.max(0, rc.plotHeight);
    const available = Math.max(0, (this._plotWidth - 4) * dpr - x0);
    const active = typeof rc.hoverId === 'string' && rc.hoverId.startsWith(`${o.id}::`);
    const capacity = Math.max(0, Math.floor((available / dpr - 6) / (btn + 2)));
    const actions = active && capacity > 0 ? (o.actions ?? DEFAULT_ACTIONS).slice(-capacity) : [];
    const actionWidth = actions.length ? (actions.length * (btn + 2) + 6) * dpr : 0;

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, this._plotWidth * dpr, rc.plotHeight * dpr);
    ctx.clip();
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    ctx.globalAlpha = dim ? 0.45 : 1;

    const groups: SegmentGroup[] = [];
    const text = (t: string, color: string, bold: boolean, gap: number): Seg => {
      ctx.font = `${bold ? '600 ' : ''}${f}px ${FONT}`;
      return { k: 'text', text: t, color, bold, w: ctx.measureText(t).width, gap: gap * dpr };
    };
    // Label plus number, the shape every reading takes: the crosshair values,
    // the market state and the day change all render through this.
    const reading = (v: LegendValue, fallback: string, priority = 1): void => {
      const parts: Seg[] = [];
      if (v.label !== undefined && v.label !== '') parts.push(text(v.label, dimText, false, 3));
      parts.push(text(v.text, v.color ?? fallback, false, GAP));
      groups.push({ parts, priority: Number.isFinite(v.priority) ? v.priority! : priority, reading: priority > 0 });
    };

    if (data.logo !== undefined && s.logo !== false) {
      groups.push({ parts: [{ k: 'logo', img: data.logo, w: LOGO * dpr, gap: 5 * dpr }], priority: -1 });
    }
    if (o.color !== undefined) groups.push({ parts: [{ k: 'dot', color: o.color, w: 6 * dpr, gap: 5 * dpr }], priority: -1 });
    let title: Seg | undefined;
    if (s.title !== false) {
      const mode = s.titleMode ?? 'symbol';
      const alt = mode === 'description' ? data.description : mode === 'ticker' ? data.ticker : undefined;
      title = text(alt ?? o.title, rc.theme.axisText, true, GAP);
      groups.push({ parts: [title], priority: 0 });
    }
    if (o.params !== undefined && o.params !== '') groups.push({ parts: [text(o.params, dimText, false, GAP)], priority: -3 });
    if (data.marketStatus !== undefined && s.marketStatus !== false) {
      reading(data.marketStatus, dimText, -4);
    }
    // Readings: one per plot, each in its plot's color, with a dimmed label.
    const valueColor = o.valueColor ?? o.color ?? rc.theme.axisText;
    for (const v of this._values) {
      if (fieldOn(s, v.field, o.hasOpenInterest)) reading(v, valueColor);
    }
    if (data.lastDayChange !== undefined && s.lastDayChange !== false) {
      reading(data.lastDayChange, valueColor, -2);
    }
    ctx.font = `600 ${f}px ${FONT}`;
    const segs = fitGroups(ctx, groups, title, Math.max(0, available - actionWidth));

    // The plate goes down before a single glyph does, which is the whole point
    // of measuring first: text over plate, never plate over text.
    const last = segs[segs.length - 1];
    if (s.background === true && last !== undefined) {
      const pad = 4 * dpr;
      const w = segs.reduce((a, sg) => a + sg.w + sg.gap, 0) - last.gap + pad * 2;
      ctx.globalAlpha = 1;
      ctx.fillStyle = withAlpha(s.backgroundColor ?? rc.theme.background, s.backgroundOpacity ?? 0.8);
      ctx.beginPath();
      ctx.roundRect(x0 - pad, cy - (rowH / 2) * dpr, w, rowH * dpr, 4 * dpr);
      ctx.fill();
      ctx.globalAlpha = dim ? 0.45 : 1;
    }

    for (const sg of segs) {
      if (sg.k === 'text') {
        ctx.font = `${sg.bold ? '600 ' : ''}${f}px ${FONT}`;
        ctx.fillStyle = sg.color;
        ctx.fillText(sg.text, x, cy);
      } else if (sg.k === 'dot') {
        ctx.fillStyle = sg.color;
        ctx.beginPath();
        ctx.arc(x + 3 * dpr, cy, 3 * dpr, 0, Math.PI * 2);
        ctx.fill();
      } else {
        ctx.drawImage(sg.img, x, cy - sg.w / 2, sg.w, sg.w);
      }
      x += sg.w + sg.gap;
    }

    // Actions appear on hover only, so a row of legends reads as clean text
    // until you approach one. The row itself hit-tests (as `::row`), which is
    // what makes the pointer "arrive" and reveal them.
    this._buttons = [];
    if (actions.length > 0) {
      // Soft plate behind the controls, so glyphs stay legible over candles.
      const plateW = (actions.length * (btn + 2) + 6) * dpr;
      ctx.globalAlpha = 1;
      ctx.fillStyle = withAlpha(rc.theme.background, 0.82);
      ctx.beginPath();
      ctx.roundRect(x - 3 * dpr, cy - (rowH / 2) * dpr, plateW, rowH * dpr, 5 * dpr);
      ctx.fill();
      x += 2 * dpr;
      for (const action of actions) {
        const id = `${o.id}::${action}`;
        const bx = x;
        this._buttons.push({ id, x: bx / dpr, y: y / dpr });
        const hovered = rc.hoverId === id;
        if (hovered) {
          ctx.fillStyle = withAlpha(rc.theme.axisText, 0.16);
          ctx.beginPath();
          ctx.roundRect(bx, cy - (btn / 2) * dpr, btn * dpr, btn * dpr, 4 * dpr);
          ctx.fill();
        }
        ctx.globalAlpha = dim ? 0.5 : hovered ? 1 : 0.75;
        ctx.fillStyle = action === 'close' && hovered ? '#ff6b6b' : rc.theme.axisText;
        drawGlyph(ctx, action, bx + (btn / 2) * dpr, cy, btn, dpr, o);
        ctx.globalAlpha = 1;
        x += (btn + 2) * dpr;
      }
    }

    this._width = x / dpr;
    ctx.restore();
  }

  public hitTest(x: number, y: number): PrimitiveHit | null {
    if (this._suppressed || this._opts.visible === false) return null;
    if (x < 0 || x >= this._plotWidth || y < 0 || y >= this._plotHeight) return null;
    const o = this._opts;
    const rowH = paneLegendRowHeight(o);
    const top = (o.top ?? 6) + (o.row ?? 0) * rowH;
    if (y < top || y > top + rowH) return null;
    const btn = buttonSize(o);
    for (const b of this._buttons) {
      if (x >= b.x && x <= b.x + btn) {
        return { externalId: b.id, zOrder: 'top', distance: 0, cursor: 'pointer' };
      }
    }
    // The row itself: reveals the controls and swallows the click so it never
    // reaches the host's click handler as a phantom id.
    const right = Math.max(this._width, (o.left ?? 8) + 40) + REVEAL_PAD;
    if (x >= (o.left ?? 8) - 4 && x <= right) {
      return { externalId: `${o.id}::row`, zOrder: 'top', distance: 0, cursor: 'default' };
    }
    return null;
  }
}
