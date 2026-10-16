/**
 * Measurement and positions: the measure box, the price and date ranges, the
 * forecast and the long and short position calculators. Measurers are tinted
 * by direction, so they read width, dash and opacity but not a colour.
 */
import type { AnchoredTool, AtLeast, DrawingPoint, DrawingTool, ExpandContext } from './types';
import { distToSegment, distToRect, rectOf } from './geometry';
import {
  type SettingsField, type SettingsSchema,
  LINE_FIELDS, FONT_FIELDS, LINE_WIDTH_FIELD, LINE_STYLE_FIELD, SHOW_LABELS_FIELD,
  composeSettings,
} from './schema';
import { timeBound } from './analysis';
import {
  OPACITY_FIELD, applyStroke, label, chip, grouped, arrowHead, tintOf, VALID_COLOR, INVALID_COLOR,
} from './tool-paint';

/**
 * The position tools' own controls. Sizing inputs live in the style bag as
 * they did in 1.9.x; the readout toggles and zone colours are per-tool extras
 * and sit in `props`, so the base style stays closed.
 */
const POSITION_FIELDS: readonly SettingsField[] = [
  { path: 'style.accountSize', label: 'Account size', kind: 'number', min: 0, step: 1000, group: 'behavior' },
  { path: 'style.risk', label: 'Risk %', kind: 'number', min: 0, max: 100, step: 0.1, group: 'behavior' },
  { path: 'props.showHeader', label: 'Show direction and ratio', kind: 'boolean', group: 'behavior' },
  { path: 'props.showLossSize', label: 'Show loss and size', kind: 'boolean', group: 'behavior' },
  { path: 'props.showTargetLabel', label: 'Show target label', kind: 'boolean', group: 'behavior' },
  { path: 'props.showStopLabel', label: 'Show stop label', kind: 'boolean', group: 'behavior' },
  { path: 'props.showPrices', label: 'Show level prices', kind: 'boolean', group: 'behavior' },
  { path: 'props.profitColor', label: 'Profit zone', kind: 'color', group: 'fill' },
  { path: 'props.lossColor', label: 'Loss zone', kind: 'color', group: 'fill' },
];

/** `YYYY-MM-DD` in UTC: enough to anchor a label to its bar. */
function isoDate(sec: number): string {
  const dt = new Date(sec * 1000);
  const p = (n: number): string => String(n).padStart(2, '0');
  return `${dt.getUTCFullYear()}-${p(dt.getUTCMonth() + 1)}-${p(dt.getUTCDate())}`;
}

/** Coarse elapsed span: `76d 23h`, `5h 12m`, `12m`. */
function humanSpan(sec: number): string {
  const s = Math.max(0, Math.round(Math.abs(sec)));
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  const mins = Math.floor((s % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${mins}m`;
  return `${mins}m`;
}

/** 172.79M / 1.2K: a raw volume sum is unreadable in a label. */
function compactNumber(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(2)}K`;
  return grouped(n);
}

// ── measurement & positions ───────────────────────────────────────────────

/** Measurers are tinted by direction, so they read width, dash and opacity but not a colour. */
const MEASURE_SETTINGS: SettingsSchema = composeSettings([
  LINE_WIDTH_FIELD, LINE_STYLE_FIELD, OPACITY_FIELD, SHOW_LABELS_FIELD, FONT_FIELDS,
]);

export const MEASURE: DrawingTool = {
  id: 'measure', name: 'Measure', points: 2,
  defaultStyle: { fill: true, showLabels: true, fillOpacity: 0.14 },
  settings: MEASURE_SETTINGS,
  draw: (c) => {
    const r = rectOf(c.pts[0], c.pts[1]);
    const d = c.rc.dpr;
    const p = c.drawing.points;
    const chg = p[1].price - p[0].price;
    const pct = p[0].price !== 0 ? (chg / p[0].price) * 100 : 0;
    const up = chg >= 0;
    const tint = tintOf(c, up);
    c.ctx.save();
    c.ctx.globalAlpha = c.style.fillOpacity ?? 0.14;
    c.ctx.fillStyle = tint;
    c.ctx.fillRect(r.x0, r.y0, r.x1 - r.x0, r.y1 - r.y0);
    c.ctx.restore();
    applyStroke(c);
    c.ctx.strokeStyle = tint;
    c.ctx.strokeRect(r.x0, r.y0, r.x1 - r.x0, r.y1 - r.y0);
    c.ctx.setLineDash([]);

    // Two arrows: one along price at the start level, one along time. They are
    // what make the box read as a measurement rather than a highlight.
    const midX = (r.x0 + r.x1) / 2;
    const y0 = c.pts[0].y;
    const y1 = c.pts[1].y;
    c.ctx.strokeStyle = tint;
    c.ctx.beginPath();
    c.ctx.moveTo(r.x0, y0);
    c.ctx.lineTo(r.x1, y0);
    c.ctx.stroke();
    arrowHead(c, { x: r.x0, y: y0 }, { x: r.x1, y: y0 });
    c.ctx.beginPath();
    c.ctx.moveTo(midX, y0);
    c.ctx.lineTo(midX, y1);
    c.ctx.stroke();
    arrowHead(c, { x: midX, y: y0 }, { x: midX, y: y1 });

    if (c.style.showLabels === false) return;
    // Bars come from logical indices, so the count matches the gapless axis
    // rather than raw elapsed time; the calendar span comes from the times.
    const i0 = c.rc.dataLayer.timeToIndexFloat(p[0].time);
    const i1 = c.rc.dataLayer.timeToIndexFloat(p[1].time);
    const bars = Math.abs(Math.round(i1 - i0));
    const sign = up ? '+' : '';
    const lines = [
      `${sign}${c.formatPrice(chg)} (${sign}${pct.toFixed(2)}%)`,
      `${grouped(bars)} bars, ${humanSpan(p[1].time - p[0].time)}`,
    ];
    // Volume over the span, when the pane can hand us the bars.
    const src = c.rc.bars?.();
    if (src !== undefined && src.length > 0) {
      const lo = Math.min(p[0].time, p[1].time);
      const hi = Math.max(p[0].time, p[1].time);
      let vol = 0;
      let seen = false;
      // Read the window again on every paint because its last bar may be live.
      for (let i = timeBound(src, lo); i < src.length; i++) {
        const b = src[i]!; // i is in range
        if (b.time > hi) break;
        if (b.volume !== undefined) { vol += b.volume; seen = true; }
      }
      if (seen) lines.push(`Vol ${compactNumber(vol)}`);
    }
    chip(c, lines, midX, Math.max(y0, y1) + 6 * d, tint, { align: 'center', place: 'below' });
  },
  distance: (x, y, h) => distToRect(x, y, h.pts[0], h.pts[1], true),
} satisfies AnchoredTool<2>;

/** Reward per unit of risk for a default box and a derived stop. */
const POSITION_RR = 2;
/** A bare click's stop distance on screen, in media px. */
const POSITION_RISK_PX = 64;
/** A bare click's box width on screen, in media px. */
const POSITION_WIDTH_PX = 150;
/** The narrowest a placed box may be: below this the handles overlap. */
const POSITION_MIN_WIDTH_PX = 48;
/** Under this much vertical travel the second click is a bare click. */
const POSITION_MIN_DRAG_PX = 6;

/**
 * The full anchor set from the two placed: entry and target as clicked (or a
 * default target for a bare click), the stop derived opposite at the ratio.
 */
function positionAnchors(clicked: AtLeast<DrawingPoint, 1>, ctx: ExpandContext, long: boolean): DrawingPoint[] {
  const entry = clicked[0];
  const second = clicked[1] ?? entry;
  const face = long ? 1 : -1;
  if (ctx.toPixel !== undefined && ctx.fromPixel !== undefined) {
    const e = ctx.toPixel(entry);
    const t = ctx.toPixel(second);
    if (e !== null && t !== null) {
      const dragged = Math.abs(t.y - e.y) >= POSITION_MIN_DRAG_PX;
      // Screen y grows downward, so a long's target sits at a smaller y.
      const targetY = dragged ? t.y : e.y - face * POSITION_RISK_PX * POSITION_RR;
      const endX = e.x + (dragged ? Math.max(Math.abs(t.x - e.x), POSITION_MIN_WIDTH_PX) : POSITION_WIDTH_PX);
      const stopY = e.y - (targetY - e.y) / POSITION_RR;
      const target = ctx.fromPixel({ x: endX, y: targetY });
      const stop = ctx.fromPixel({ x: endX, y: stopY });
      if (target !== null && stop !== null) return [{ ...entry }, target, stop];
    }
  }
  // Chart units: the second click's price if it moved, else two percent of
  // price (one of risk, two of reward), and a width of a few visible bars.
  const dragged = second.price !== entry.price;
  const reward = dragged ? second.price - entry.price : face * (Math.abs(entry.price) * 0.02 || 2);
  const bars = Math.max(5, Math.round(ctx.visibleBars * 0.08));
  const span = Math.max(1, ctx.barSeconds) * bars;
  const far = dragged && second.time > entry.time ? second.time : entry.time + span;
  return [
    { ...entry },
    { time: far, price: entry.price + reward },
    { time: far, price: entry.price - reward / POSITION_RR },
  ];
}

/**
 * Keep the stop and the target on opposite sides of the entry. When a move
 * puts them on the same side, the level that was NOT moved is reflected
 * across the entry, so the one under the hand stays where it was put and the
 * trade turns around with each side's distance, and so the ratio, preserved.
 */
function opposeLevels(points: readonly DrawingPoint[], handle: number | null): DrawingPoint[] {
  const out = points.map((p) => ({ ...p }));
  if (out.length < 3) return out;
  const [entry, target, stop] = out as AtLeast<DrawingPoint, 3>; // by the length check above
  const targetSide = Math.sign(target.price - entry.price);
  const stopSide = Math.sign(stop.price - entry.price);
  if (targetSide === 0 || stopSide === 0 || targetSide !== stopSide) return out;
  if (handle === 1) stop.price = 2 * entry.price - stop.price;
  else target.price = 2 * entry.price - target.price;
  return out;
}

/** A position size the way a trader reads one: whole above a hundred, else to the cent. */
function sizeText(qty: number): string {
  if (!Number.isFinite(qty) || qty <= 0) return '0';
  if (qty >= 100) return grouped(qty);
  if (qty >= 1) return grouped(qty, 2).replace(/\.?0+$/, '');
  return qty.toPrecision(3).replace(/\.?0+$/, '');
}

/**
 * Long / short position calculator: entry, target, stop, anchored in that
 * order (the order 1.9.x saved, so an old layout loads unchanged).
 *
 * Placed in two clicks: the entry, then the target. The second click is also
 * the profit direction: release above the entry and the trade is a long,
 * below and it is a short, whichever tool was armed. The armed tool only
 * decides which way a bare click faces. The stop lands opposite the entry at
 * one part risk to {@link POSITION_RR} parts reward, and all three levels
 * stay handles; a level dragged through the entry flips the other side across
 * it rather than piling both on one side, so a long turns into a short in
 * place with its ratio intact.
 *
 * A bare click's box is sized on screen, not as a fraction of price. One
 * percent of a 2.87 stock and one percent of a 24,000 index are the same
 * fraction and very different boxes, and either turns into a hairline or a
 * pane-filler with the zoom; 64 px of risk and 150 px of width read the same
 * everywhere. A host with no pixel mapping falls back to chart units.
 */
function positionTool(id: string, name: string, long: boolean): DrawingTool {
  return {
    id, name, points: 2,
    defaultStyle: { showLabels: true, fillOpacity: 0.13, accountSize: 100000, risk: 1 },
    settings: composeSettings([LINE_FIELDS, OPACITY_FIELD, SHOW_LABELS_FIELD, POSITION_FIELDS, FONT_FIELDS]),
    expand: (clicked, ctx) => positionAnchors(clicked, ctx, long),
    constrain: (points, handle) => opposeLevels(points, handle),
    draw: (c) => {
      const pts = c.drawing.points;
      if (pts.length < 2 || c.pts.length < 2) return;
      const [entry, target] = pts;
      // Between the first click and the second the drawing has two anchors
      // and previews against the cursor: the stop is derived for the frame,
      // exactly where `expand` will put it. The third anchor is read only once it is there.
      const stop = pts.length >= 3 ? pts[2]! : { time: target.time, price: entry.price - (target.price - entry.price) / POSITION_RR };
      const d = c.rc.dpr;
      const xs = c.pts.map((p) => p.x);
      const x0 = Math.min(...xs);
      const x1 = Math.max(...xs);
      const yE = c.rc.priceScale.priceToY(entry.price) * d;
      const yT = c.rc.priceScale.priceToY(target.price) * d;
      const yS = c.rc.priceScale.priceToY(stop.price) * d;
      const props = c.drawing.props ?? {};
      const profitColor = typeof props.profitColor === 'string' ? props.profitColor : tintOf(c, true);
      const lossColor = typeof props.lossColor === 'string' ? props.lossColor : tintOf(c, false);
      const band = (yA: number, yB: number, color: string): void => {
        c.ctx.save();
        c.ctx.globalAlpha = c.style.fillOpacity ?? 0.13;
        c.ctx.fillStyle = color;
        c.ctx.fillRect(x0, Math.min(yA, yB), x1 - x0, Math.abs(yB - yA));
        c.ctx.restore();
      };
      band(yE, yT, profitColor);
      band(yE, yS, lossColor);
      applyStroke(c);
      // Each level in its zone's colour; the entry keeps the tool's accent.
      for (const [y, color] of [[yT, profitColor], [yS, lossColor], [yE, c.style.color]] as const) {
        const yy = Math.round(y) + 0.5;
        c.ctx.strokeStyle = color;
        c.ctx.beginPath();
        c.ctx.moveTo(x0, yy);
        c.ctx.lineTo(x1, yy);
        c.ctx.stroke();
      }
      c.ctx.setLineDash([]);
      if (c.style.showLabels === false) return;
      const risk = Math.abs(entry.price - stop.price);
      const reward = Math.abs(target.price - entry.price);
      const rr = risk > 0 ? reward / risk : 0;
      const pctOf = (delta: number): string =>
        (entry.price !== 0 ? (delta / entry.price) * 100 : 0).toFixed(2);
      // The direction is read off the geometry so it flips live as a drag
      // crosses the entry; only a box with no height yet takes the tool's.
      const direction = target.price === entry.price ? (long ? 'Long' : 'Short')
        : target.price > entry.price ? 'Long' : 'Short';
      // Money at risk is what the account and risk percent say; size is what
      // that buys at the stop distance. Neither exists without an account.
      const account = c.style.accountSize ?? 0;
      const loss = account > 0 ? account * (c.style.risk ?? 0) / 100 : 0;
      const qty = risk > 0 ? loss / risk : 0;
      const cx = (x0 + x1) / 2;
      const top = Math.min(yE, yT, yS);
      const at = (price: number): string => (props.showPrices === true ? `  @ ${c.formatPrice(price)}` : '');
      // The header and the loss/size line stack above the box, out of the way
      // of the candles; each zone carries its own reading at its centre.
      let above = top;
      if (props.showLossSize !== false && loss > 0) {
        above -= chip(c, [`Loss ${grouped(loss, 2)}  Size ${sizeText(qty)}`], cx, above, c.rc.theme.background,
          { align: 'center', place: 'above' }) + 4 * d;
      }
      if (props.showHeader !== false) {
        chip(c, [`${direction}  R:R ${rr.toFixed(2)}`], cx, above, c.rc.theme.background, { align: 'center', place: 'above' });
      }
      if (props.showTargetLabel !== false && reward > 0) {
        chip(c, [`Target +${pctOf(reward)}%${at(target.price)}`], cx, (yE + yT) / 2, profitColor, { align: 'center', place: 'middle' });
      }
      if (props.showStopLabel !== false && risk > 0) {
        chip(c, [`Stop -${pctOf(risk)}%${at(stop.price)}`], cx, (yE + yS) / 2, lossColor, { align: 'center', place: 'middle' });
      }
    },
    distance: (x, y, h) => {
      const pts = h.drawing.points;
      if (h.pts.length < 2 || pts.length < 2) return null;
      const xs = h.pts.map((p) => p.x);
      const x0 = Math.min(...xs);
      const x1 = Math.max(...xs);
      if (x < x0 - 4 || x > x1 + 4) return null;
      const [entry, target] = pts;
      const stopPrice = pts.length >= 3 ? pts[2]!.price : entry.price - (target.price - entry.price) / POSITION_RR; // by the length check
      const ys = [entry.price, target.price, stopPrice].map((p) => h.rc.priceScale.priceToY(p));
      const lo = Math.min(...ys);
      const hi = Math.max(...ys);
      return y >= lo && y <= hi ? 0 : Math.min(Math.abs(y - lo), Math.abs(y - hi));
    },
  } satisfies AnchoredTool<2>;
}

export const LONG_POSITION = positionTool('long-position', 'Long Position', true);
export const SHORT_POSITION = positionTool('short-position', 'Short Position', false);

/**
 * Measurers. `measure` reports price *and* time together; these two constrain it
 * to one axis, which is what you want when the other one is noise: sizing a
 * retracement without caring how long it took, or counting bars to an event
 * without caring where price went.
 */
export const PRICE_RANGE: DrawingTool = {
  id: 'price-range', name: 'Price Range', points: 2,
  defaultStyle: { fill: true, showLabels: true, fillOpacity: 0.1 },
  settings: MEASURE_SETTINGS,
  draw: (c) => {
    const d = c.rc.dpr;
    const p = c.drawing.points;
    const chg = p[1].price - p[0].price;
    const pct = p[0].price !== 0 ? (chg / p[0].price) * 100 : 0;
    const up = chg >= 0;
    const tint = tintOf(c, up);
    // Span the drawn x-range so the band reads as a price zone, not a bare line.
    const x0 = Math.min(c.pts[0].x, c.pts[1].x);
    const x1 = Math.max(c.pts[0].x, c.pts[1].x) + (c.pts[0].x === c.pts[1].x ? 60 * d : 0);
    const y0 = c.pts[0].y;
    const y1 = c.pts[1].y;
    c.ctx.save();
    c.ctx.globalAlpha = c.style.fillOpacity ?? 0.1;
    c.ctx.fillStyle = tint;
    c.ctx.fillRect(x0, Math.min(y0, y1), x1 - x0, Math.abs(y1 - y0));
    c.ctx.restore();
    applyStroke(c);
    c.ctx.strokeStyle = tint;
    c.ctx.beginPath();
    for (const y of [y0, y1]) { c.ctx.moveTo(x0, Math.round(y) + 0.5); c.ctx.lineTo(x1, Math.round(y) + 0.5); }
    // The measured leg, with arrow heads at both ends.
    const mx = (x0 + x1) / 2;
    c.ctx.moveTo(mx, y0); c.ctx.lineTo(mx, y1);
    const dir = y1 > y0 ? 1 : -1;
    c.ctx.moveTo(mx - 4 * d, y1 - 5 * d * dir); c.ctx.lineTo(mx, y1); c.ctx.lineTo(mx + 4 * d, y1 - 5 * d * dir);
    c.ctx.moveTo(mx - 4 * d, y0 + 5 * d * dir); c.ctx.lineTo(mx, y0); c.ctx.lineTo(mx + 4 * d, y0 + 5 * d * dir);
    c.ctx.stroke();
    c.ctx.setLineDash([]);
    if (c.style.showLabels === false) return;
    const sign = up ? '+' : '';
    label(c, `${sign}${c.formatPrice(chg)}  (${sign}${pct.toFixed(2)}%)`, mx + 6 * d, (y0 + y1) / 2, tint);
  },
  distance: (x, y, h) => distToRect(x, y, h.pts[0], h.pts[1], true),
} satisfies AnchoredTool<2>;

export const DATE_RANGE: DrawingTool = {
  id: 'date-range', name: 'Date Range', points: 2,
  defaultStyle: { fill: true, showLabels: true, fillOpacity: 0.1 },
  settings: composeSettings([LINE_FIELDS, OPACITY_FIELD, SHOW_LABELS_FIELD, FONT_FIELDS]),
  draw: (c) => {
    const d = c.rc.dpr;
    const p = c.drawing.points;
    const tint = c.style.color;
    const x0 = c.pts[0].x;
    const x1 = c.pts[1].x;
    const y0 = Math.min(c.pts[0].y, c.pts[1].y);
    const y1 = Math.max(c.pts[0].y, c.pts[1].y) + (c.pts[0].y === c.pts[1].y ? 40 * d : 0);
    c.ctx.save();
    c.ctx.globalAlpha = c.style.fillOpacity ?? 0.1;
    c.ctx.fillStyle = tint;
    c.ctx.fillRect(Math.min(x0, x1), y0, Math.abs(x1 - x0), y1 - y0);
    c.ctx.restore();
    applyStroke(c);
    c.ctx.beginPath();
    for (const x of [x0, x1]) { c.ctx.moveTo(Math.round(x) + 0.5, y0); c.ctx.lineTo(Math.round(x) + 0.5, y1); }
    const my = (y0 + y1) / 2;
    c.ctx.moveTo(x0, my); c.ctx.lineTo(x1, my);
    const dir = x1 > x0 ? 1 : -1;
    c.ctx.moveTo(x1 - 5 * d * dir, my - 4 * d); c.ctx.lineTo(x1, my); c.ctx.lineTo(x1 - 5 * d * dir, my + 4 * d);
    c.ctx.moveTo(x0 + 5 * d * dir, my - 4 * d); c.ctx.lineTo(x0, my); c.ctx.lineTo(x0 + 5 * d * dir, my + 4 * d);
    c.ctx.stroke();
    c.ctx.setLineDash([]);
    if (c.style.showLabels === false) return;
    // Counted on logical indices, so it matches the gapless axis rather than
    // raw elapsed time (a weekend is not 48 bars).
    const i0 = c.rc.dataLayer.timeToIndexFloat(p[0].time);
    const i1 = c.rc.dataLayer.timeToIndexFloat(p[1].time);
    const bars = Math.abs(Math.round(i1 - i0));
    label(c, `${bars} bars`, (x0 + x1) / 2, y0 - 10 * d, tint);
  },
  distance: (x, y, h) => distToRect(x, y, h.pts[0], h.pts[1], true),
} satisfies AnchoredTool<2>;

/**
 * Position forecast: project a move from an anchor. Two anchors give the
 * projected leg; the shape extends the same slope past the target as a dashed
 * cone, so the drawing says "if this continues" rather than just marking a line.
 */
export const FORECAST: DrawingTool = {
  id: 'forecast', name: 'Forecast', points: 2,
  defaultStyle: { fill: true, showLabels: true, fillOpacity: 0.12, lineStyle: 'dashed' },
  settings: MEASURE_SETTINGS,
  draw: (c) => {
    const d = c.rc.dpr;
    const p = c.drawing.points;
    const [a, b] = c.pts;
    const chg = p[1].price - p[0].price;
    const pct = p[0].price !== 0 ? (chg / p[0].price) * 100 : 0;
    const up = chg >= 0;
    const tint = tintOf(c, up);
    // The cone widens with the projected distance: a forecast is less certain
    // the further out it runs, and the shape should say so.
    const spread = Math.abs(b.y - a.y) * 0.35 + 6 * d;
    c.ctx.save();
    c.ctx.globalAlpha = c.style.fillOpacity ?? 0.12;
    c.ctx.fillStyle = tint;
    c.ctx.beginPath();
    c.ctx.moveTo(a.x, a.y);
    c.ctx.lineTo(b.x, b.y - spread);
    c.ctx.lineTo(b.x, b.y + spread);
    c.ctx.closePath();
    c.ctx.fill();
    c.ctx.restore();
    applyStroke(c);
    c.ctx.strokeStyle = tint;
    c.ctx.beginPath();
    c.ctx.moveTo(a.x, a.y);
    c.ctx.lineTo(b.x, b.y);
    c.ctx.stroke();
    c.ctx.setLineDash([]);
    c.ctx.beginPath();
    c.ctx.arc(a.x, a.y, 3 * d, 0, Math.PI * 2);
    c.ctx.fillStyle = tint;
    c.ctx.fill();
    if (c.style.showLabels === false) return;
    const sign = up ? '+' : '';
    // Anchor chip: where the projection was struck from.
    chip(c, [c.formatPrice(p[0].price), isoDate(p[0].time)], a.x, a.y, tint, { align: 'center' });
    // Projection chip: the move, and what it lands on when.
    chip(c, [
      `${sign}${c.formatPrice(chg)} (${sign}${pct.toFixed(2)}%) in ${humanSpan(p[1].time - p[0].time)}`,
      `${c.formatPrice(p[1].price)}, ${isoDate(p[1].time)}`,
    ], b.x, b.y, tint, { align: 'center', place: 'below' });
    // Verdict, once the window has actually elapsed: did price get there? A
    // forecast nobody scores is just a line.
    const bars = c.rc.bars?.();
    if (bars !== undefined && bars.length > 0 && bars[bars.length - 1]!.time >= p[1].time) {
      let hit = false;
      for (const bar of bars) {
        if (bar.time < p[0].time) continue;
        if (bar.time > p[1].time) break;
        if (up ? bar.high >= p[1].price : bar.low <= p[1].price) { hit = true; break; }
      }
      chip(c, [hit ? 'SUCCESS' : 'MISSED'], b.x, b.y + 36 * d,
        hit ? VALID_COLOR : INVALID_COLOR, { align: 'center', place: 'below' });
    }
  },
  distance: (x, y, h) => distToSegment(x, y, h.pts[0], h.pts[1]),
} satisfies AnchoredTool<2>;
