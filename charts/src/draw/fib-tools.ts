/**
 * The fibonacci and gann family: retracement and extension, the channel, time
 * zone and fan, the gann fan and box. Ladders read `FibLevel[]` and stroke each
 * level in its own colour, taken from the shared palette in levels.ts.
 */
import type { AnchoredTool, DrawingTool, FibLevel } from './types';
import { fibAlertValue, fibAlertLevels } from './alert-values';
import { distToSegment, distToRect, rectOf, extendSegment } from './geometry';
import {
  type SettingsSchema,
  LINE_FIELDS, FILL_FIELDS, LEVEL_FIELDS, EXTEND_FIELDS, FONT_FIELDS, LINE_WIDTH_FIELD, LINE_STYLE_FIELD,
  composeSettings,
} from './schema';
import {
  DEFAULT_FIB, DEFAULT_FIB_FAN, DEFAULT_GANN_FAN, DEFAULT_GANN_BOX, DEFAULT_FIB_TIME_ZONE,
  activeLevels, cloneLevels, cycleColor, levelColor, formatRatio, gannLabel,
} from './levels';
import { applyStroke, withFill, label } from './tool-paint';

// ── levels ────────────────────────────────────────────────────────────────

/** A fib level's colour: its own, else the convention for its ratio. */
function fibColor(lv: FibLevel): string {
  return lv.color ?? levelColor(lv.ratio);
}

/** A fib level's text: its own, else the ratio as a percentage. */
function fibText(lv: FibLevel): string {
  return lv.label ?? formatRatio(lv.ratio);
}

// ── fibonacci ─────────────────────────────────────────────────────────────

const FIB_SETTINGS: SettingsSchema = composeSettings([LINE_FIELDS, LEVEL_FIELDS, FILL_FIELDS, EXTEND_FIELDS, FONT_FIELDS]);

/** Retracement (2 anchors) and extension (3) share the level-drawing body. */
function fibTool(id: string, name: string, anchors: 2 | 3): DrawingTool {
  return {
    id, name, points: anchors,
    alertValue: fibAlertValue(anchors, DEFAULT_FIB), alertLevels: fibAlertLevels(DEFAULT_FIB),
    defaultStyle: { showLabels: true, levels: cloneLevels(DEFAULT_FIB), fill: true, fillOpacity: 0.06 },
    settings: FIB_SETTINGS,
    draw: (c) => {
      const levels = activeLevels(c.style.levels, DEFAULT_FIB);
      const p = c.drawing.points;
      const d = c.rc.dpr;
      // Retracement measures p0 to p1; extension projects that leg from p2.
      const from = anchors === 2 ? p[0].price : p[2]!.price; // an extension declares three anchors
      const span = p[1].price - p[0].price;
      const xa = Math.min(c.pts[0].x, c.pts[anchors - 1]!.x); // the last anchor it declares
      const xb = Math.max(c.pts[0].x, c.pts[anchors - 1]!.x);
      const x0 = c.style.extendLeft === true ? 0 : xa;
      const x1 = c.style.extendRight === true ? c.rc.plotWidth * d : xb;
      // The leg the ratios are ratios of, in the drawing's own colour. The
      // levels are horizontal, so nothing else shows where the swing ran.
      applyStroke(c);
      c.ctx.beginPath();
      c.ctx.moveTo(c.pts[0].x, c.pts[0].y);
      c.ctx.lineTo(c.pts[1].x, c.pts[1].y);
      if (anchors === 3) c.ctx.lineTo(c.pts[2]!.x, c.pts[2]!.y);
      c.ctx.stroke();
      let prevY: number | null = null;
      for (const lv of levels) {
        const price = from + span * lv.ratio;
        const y = Math.round(c.rc.priceScale.priceToY(price) * d) + 0.5;
        const color = fibColor(lv);
        // Each band is tinted by the level that closes it, so the fill reads
        // as part of the ladder rather than as one wash behind it.
        if (c.style.fill === true && prevY !== null) {
          c.ctx.save();
          c.ctx.globalAlpha = c.style.fillOpacity ?? 0.06;
          c.ctx.fillStyle = c.style.fillColor ?? color;
          c.ctx.fillRect(x0, Math.min(prevY, y), x1 - x0, Math.abs(y - prevY));
          c.ctx.restore();
        }
        prevY = y;
        c.ctx.strokeStyle = color;
        c.ctx.beginPath();
        c.ctx.moveTo(x0, y);
        c.ctx.lineTo(x1, y);
        c.ctx.stroke();
        if (c.style.showLabels !== false) {
          label(c, `${fibText(lv)}  ${c.formatPrice(price)}`, x0 + 4 * d, y - 8 * d, color);
        }
      }
      c.ctx.setLineDash([]);
    },
    distance: (x, y, h) => {
      const levels = activeLevels(h.drawing.style.levels, DEFAULT_FIB);
      const p = h.drawing.points;
      const from = anchors === 2 ? p[0].price : p[2]!.price; // p2 and anchors - 1: anchors the tool declares
      const span = p[1].price - p[0].price;
      const x0 = h.drawing.style.extendLeft === true ? 0 : Math.min(h.pts[0].x, h.pts[anchors - 1]!.x);
      const x1 = h.drawing.style.extendRight === true
        ? h.rc.plotWidth : Math.max(h.pts[0].x, h.pts[anchors - 1]!.x);
      if (x < x0 - 4 || x > x1 + 4) return null;
      let best = Infinity;
      for (const lv of levels) {
        const dd = Math.abs(y - h.rc.priceScale.priceToY(from + span * lv.ratio));
        if (dd < best) best = dd;
      }
      return best;
    },
  } satisfies AnchoredTool<2 | 3>;
}

export const FIB_RETRACEMENT = fibTool('fib-retracement', 'Fib Retracement', 2);
export const FIB_EXTENSION = fibTool('fib-extension', 'Fib Extension', 3);

// ── fibonacci & gann ──────────────────────────────────────────────────────

/**
 * A ladder whose colours live entirely in its levels: the drawing's own colour
 * would touch nothing on screen, so it is not offered. Width and dash apply to
 * every rung.
 */
const LADDER_SETTINGS: SettingsSchema = composeSettings([LINE_WIDTH_FIELD, LINE_STYLE_FIELD, LEVEL_FIELDS, FONT_FIELDS]);

/** Fib channel: fib levels spread across a trend leg, parallel to it. */
export const FIB_CHANNEL: DrawingTool = {
  id: 'fib-channel', name: 'Fib Channel', points: 3,
  alertValue: fibAlertValue('channel', DEFAULT_FIB), alertLevels: fibAlertLevels(DEFAULT_FIB),
  defaultStyle: { showLabels: true, levels: cloneLevels(DEFAULT_FIB) },
  settings: composeSettings([LINE_WIDTH_FIELD, LINE_STYLE_FIELD, LEVEL_FIELDS, EXTEND_FIELDS, FONT_FIELDS]),
  draw: (c) => {
    const levels = activeLevels(c.style.levels, DEFAULT_FIB);
    const [a, b, w] = c.pts;
    const d = c.rc.dpr;
    // The third anchor sets the channel width; each level is a fraction of it.
    const offX = w.x - b.x;
    const offY = w.y - b.y;
    const left = c.style.extendLeft === true;
    const right = c.style.extendRight === true;
    applyStroke(c);
    for (const lv of levels) {
      const [s, e] = extendSegment(
        { x: a.x + offX * lv.ratio, y: a.y + offY * lv.ratio },
        { x: b.x + offX * lv.ratio, y: b.y + offY * lv.ratio },
        c.rc.plotWidth * d, left, right,
      );
      const color = fibColor(lv);
      c.ctx.strokeStyle = color;
      c.ctx.beginPath();
      c.ctx.moveTo(s.x, s.y);
      c.ctx.lineTo(e.x, e.y);
      c.ctx.stroke();
      if (c.style.showLabels !== false) {
        label(c, fibText(lv), b.x + offX * lv.ratio + 4 * d, b.y + offY * lv.ratio, color);
      }
    }
    c.ctx.setLineDash([]);
  },
  distance: (x, y, h) => {
    const levels = activeLevels(h.drawing.style.levels, DEFAULT_FIB);
    const [a, b, w] = h.pts;
    const left = h.drawing.style.extendLeft === true;
    const right = h.drawing.style.extendRight === true;
    let best = Infinity;
    for (const lv of levels) {
      const [s, e] = extendSegment(
        { x: a.x + (w.x - b.x) * lv.ratio, y: a.y + (w.y - b.y) * lv.ratio },
        { x: b.x + (w.x - b.x) * lv.ratio, y: b.y + (w.y - b.y) * lv.ratio },
        h.rc.plotWidth, left, right,
      );
      const dd = distToSegment(x, y, s, e);
      if (dd < best) best = dd;
    }
    return best;
  },
} satisfies AnchoredTool<3>;

/**
 * Fib time zone: vertical lines at Fibonacci multiples of the base leg's width.
 * Its levels count bars rather than divide a leg, so they carry no convention
 * colour and fall back to the drawing's own.
 */
export const FIB_TIME_ZONE: DrawingTool = {
  id: 'fib-time-zone', name: 'Fib Time Zone', points: 2,
  defaultStyle: { showLabels: true, levels: cloneLevels(DEFAULT_FIB_TIME_ZONE) },
  settings: composeSettings([LINE_FIELDS, LEVEL_FIELDS, FONT_FIELDS]),
  draw: (c) => {
    const [a, b] = c.pts;
    const unit = b.x - a.x;
    if (Math.abs(unit) < 0.5) return;
    const d = c.rc.dpr;
    const maxX = c.rc.plotWidth * d;
    const levels = activeLevels(c.style.levels, DEFAULT_FIB_TIME_ZONE);
    applyStroke(c);
    for (const lv of levels) {
      const x = a.x + unit * lv.ratio;
      if (x < -10 || x > maxX + 10) continue;
      const color = lv.color ?? c.style.color;
      c.ctx.strokeStyle = color;
      c.ctx.beginPath();
      c.ctx.moveTo(Math.round(x) + 0.5, 0);
      c.ctx.lineTo(Math.round(x) + 0.5, c.rc.plotHeight * d);
      c.ctx.stroke();
      if (c.style.showLabels !== false) label(c, lv.label ?? String(lv.ratio), x + 3 * d, 12 * d, color);
    }
    c.ctx.setLineDash([]);
  },
  distance: (x, y, h) => {
    void y;
    const [a, b] = h.pts;
    const unit = b.x - a.x;
    if (Math.abs(unit) < 0.5) return null;
    let best = Infinity;
    for (const lv of activeLevels(h.drawing.style.levels, DEFAULT_FIB_TIME_ZONE)) {
      best = Math.min(best, Math.abs(x - (a.x + unit * lv.ratio)));
    }
    return Number.isFinite(best) ? best : null;
  },
} satisfies AnchoredTool<2>;

/** Rays from the anchor at fib fractions of the leg: the speed resistance fan. */
export const FIB_FAN: DrawingTool = {
  id: 'fib-fan', name: 'Fib Fan', points: 2,
  defaultStyle: { showLabels: true, levels: cloneLevels(DEFAULT_FIB_FAN) },
  settings: LADDER_SETTINGS,
  draw: (c) => {
    const levels = activeLevels(c.style.levels, DEFAULT_FIB_FAN);
    const [a, b] = c.pts;
    const d = c.rc.dpr;
    const maxX = c.rc.plotWidth * d;
    applyStroke(c);
    for (const lv of levels) {
      // Each ray takes the full run but a fraction of the rise.
      const end = extendSegment(a, { x: b.x, y: a.y + (b.y - a.y) * lv.ratio }, maxX, false, true)[1];
      const color = fibColor(lv);
      c.ctx.strokeStyle = color;
      c.ctx.beginPath();
      c.ctx.moveTo(a.x, a.y);
      c.ctx.lineTo(end.x, end.y);
      c.ctx.stroke();
      if (c.style.showLabels !== false) label(c, fibText(lv), b.x + 4 * d, a.y + (b.y - a.y) * lv.ratio, color);
    }
    c.ctx.setLineDash([]);
  },
  distance: (x, y, h) => {
    const levels = activeLevels(h.drawing.style.levels, DEFAULT_FIB_FAN);
    const [a, b] = h.pts;
    let best = Infinity;
    for (const lv of levels) {
      best = Math.min(best, distToSegment(x, y, a,
        extendSegment(a, { x: b.x, y: a.y + (b.y - a.y) * lv.ratio }, h.rc.plotWidth, false, true)[1]));
    }
    return Number.isFinite(best) ? best : null;
  },
} satisfies AnchoredTool<2>;

/**
 * Gann fan: rays from one anchor at the classic price/time angles. A level's
 * ratio is price per unit of time, so the 1x1 is 1, the 1x2 is 0.5 and the
 * 2x1 is 2; each angle keeps its own colour from the cycle palette.
 */
export const GANN_FAN: DrawingTool = {
  id: 'gann-fan', name: 'Gann Fan', points: 2,
  defaultStyle: { showLabels: true, levels: cloneLevels(DEFAULT_GANN_FAN) },
  settings: LADDER_SETTINGS,
  draw: (c) => {
    const [a, b] = c.pts;
    const d = c.rc.dpr;
    const maxX = c.rc.plotWidth * d;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    if (Math.abs(dx) < 0.5) return;
    const levels = activeLevels(c.style.levels, DEFAULT_GANN_FAN);
    applyStroke(c);
    levels.forEach((lv, i) => {
      const end = extendSegment(a, { x: a.x + dx, y: a.y + dy * lv.ratio }, maxX, false, true)[1];
      const color = lv.color ?? cycleColor(i);
      c.ctx.strokeStyle = color;
      c.ctx.beginPath();
      c.ctx.moveTo(a.x, a.y);
      c.ctx.lineTo(end.x, end.y);
      c.ctx.stroke();
      if (c.style.showLabels !== false) label(c, lv.label ?? gannLabel(lv.ratio), b.x + 4 * d, a.y + dy * lv.ratio, color);
    });
    c.ctx.setLineDash([]);
  },
  distance: (x, y, h) => {
    const [a, b] = h.pts;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    if (Math.abs(dx) < 0.5) return null;
    let best = Infinity;
    for (const lv of activeLevels(h.drawing.style.levels, DEFAULT_GANN_FAN)) {
      best = Math.min(best, distToSegment(x, y, a,
        extendSegment(a, { x: a.x + dx, y: a.y + dy * lv.ratio }, h.rc.plotWidth, false, true)[1]));
    }
    return Number.isFinite(best) ? best : null;
  },
} satisfies AnchoredTool<2>;

/**
 * Gann box: the drawn rectangle divided at its levels on both axes, plus the
 * 1x1 diagonal. Ratio 0 is the first anchor's price and time, ratio 1 the
 * second's, so the box reads like a retracement laid over a date range.
 */
export const GANN_BOX: DrawingTool = {
  id: 'gann-box', name: 'Gann Box', points: 2,
  defaultStyle: { fill: true, fillOpacity: 0.05, showLabels: true, levels: cloneLevels(DEFAULT_GANN_BOX) },
  settings: composeSettings([LINE_FIELDS, FILL_FIELDS, LEVEL_FIELDS, FONT_FIELDS]),
  draw: (c) => {
    const [a, b] = c.pts;
    const r = rectOf(a, b);
    const d = c.rc.dpr;
    const p = c.drawing.points;
    const levels = activeLevels(c.style.levels, DEFAULT_GANN_BOX);
    withFill(c, () => c.ctx.fillRect(r.x0, r.y0, r.x1 - r.x0, r.y1 - r.y0));
    // The diagonal first, in the drawing's colour: it is the 1x1 and the one
    // line of the box that is not a level.
    applyStroke(c);
    c.ctx.beginPath();
    c.ctx.moveTo(a.x, a.y);
    c.ctx.lineTo(b.x, b.y);
    c.ctx.stroke();
    for (const lv of levels) {
      const x = Math.round(a.x + (b.x - a.x) * lv.ratio) + 0.5;
      const price = p[0].price + (p[1].price - p[0].price) * lv.ratio;
      const y = Math.round(c.rc.priceScale.priceToY(price) * d) + 0.5;
      const color = fibColor(lv);
      c.ctx.strokeStyle = color;
      c.ctx.beginPath();
      c.ctx.moveTo(x, r.y0); c.ctx.lineTo(x, r.y1);
      c.ctx.moveTo(r.x0, y); c.ctx.lineTo(r.x1, y);
      c.ctx.stroke();
      if (c.style.showLabels !== false) label(c, fibText(lv), r.x1 + 4 * d, y, color);
    }
    c.ctx.setLineDash([]);
  },
  distance: (x, y, h) => distToRect(x, y, h.pts[0], h.pts[1], h.drawing.style.fill === true),
} satisfies AnchoredTool<2>;
