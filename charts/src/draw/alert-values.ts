import type { AlertDrawingLevel, AlertDrawingValue } from 'openalgo-charts';
import type { AtLeast, Drawing, DrawingValueContext, FibLevel, ScreenPoint } from './types';
import { activeLevels, formatRatio } from './levels';

type Value = Omit<AlertDrawingValue, 'paneIndex'>;

// A drawing's alert value is asked of whatever anchors it holds, so each reader
// checks the count before it reads them. `pts` are `drawing.points` projected
// one for one, so a count checked on one holds for the other.

/** Matches extendSegment: extension flags name screen edges, including reversed anchors. */
function yAt(a: ScreenPoint, b: ScreenPoint, x: number, left: boolean, right: boolean): number | undefined {
  if (a.x === b.x) return undefined;
  const start = left ? -Infinity : a.x;
  const end = right ? Infinity : b.x;
  if (x < Math.min(start, end) - 1e-7 || x > Math.max(start, end) + 1e-7) return undefined;
  return a.y + (b.y - a.y) * (x - a.x) / (b.x - a.x);
}

function priceAt(c: DrawingValueContext, y: number | undefined): Value | undefined {
  if (y === undefined) return undefined;
  const price = c.fromY(y);
  return price !== null && Number.isFinite(price) ? { price } : undefined;
}

export function lineAlertValue(left = false, right = false): (c: DrawingValueContext, level?: string) => Value | undefined {
  return (c, level) => {
    if (c.pts.length < 2 || (level !== undefined && level !== 'line')) return undefined;
    return priceAt(c, yAt(c.pts[0]!, c.pts[1]!, c.x, c.drawing.style.extendLeft ?? left, c.drawing.style.extendRight ?? right));
  };
}

export function horizontalAlertValue(ray = false): (c: DrawingValueContext, level?: string) => Value | undefined {
  return (c, level) => {
    if (!c.pts[0] || (ray && c.x < c.pts[0].x) || (level !== undefined && level !== 'line')) return undefined;
    return { price: c.drawing.points[0]!.price };
  };
}

export function channelAlertLevels(): readonly AlertDrawingLevel[] {
  return [{ id: 'band', title: 'Channel band' }, { id: 'base', title: 'First boundary' },
    { id: 'boundary', title: 'Second boundary' }, { id: 'middle', title: 'Middle' }];
}

export function channelAlertValue(kind: 'parallel' | 'disjoint' | 'flat'): (c: DrawingValueContext, level?: string) => Value | undefined {
  return (c, level = 'band') => {
    if (c.pts.length < (kind === 'disjoint' ? 4 : 3)) return undefined;
    const [a, b, t] = c.pts as AtLeast<ScreenPoint, 3>;
    const dy = t.y - (a.y + b.y) / 2;
    const bottom: [ScreenPoint, ScreenPoint] = kind === 'disjoint' ? [t, c.pts[3]!] : kind === 'flat'
      ? [{ x: a.x, y: t.y }, { x: b.x, y: t.y }]
      : [{ x: a.x, y: a.y + dy }, { x: b.x, y: b.y + dy }];
    // The original parallel channel renders finite segments without extension controls.
    const left = kind !== 'parallel' && c.drawing.style.extendLeft === true;
    const right = kind !== 'parallel' && c.drawing.style.extendRight === true;
    const at = (p: ScreenPoint, q: ScreenPoint): number | undefined => kind !== 'parallel' && p.x > q.x
      ? yAt(q, p, c.x, left, right) : yAt(p, q, c.x, left, right);
    const first = at(a, b);
    const second = at(bottom[0], bottom[1]);
    if (level === 'base') return priceAt(c, first);
    if (level === 'boundary') return priceAt(c, second);
    if (first === undefined || second === undefined) return undefined;
    if (level === 'middle') return priceAt(c, (first + second) / 2);
    if (level !== 'band') return undefined;
    const low = priceAt(c, first), high = priceAt(c, second);
    return low && high ? { price: Math.min(low.price, high.price), upperPrice: Math.max(low.price, high.price) } : undefined;
  };
}

export function fibAlertLevels(fallback: readonly FibLevel[]): (drawing: Drawing) => readonly AlertDrawingLevel[] {
  return drawing => [...new Map(activeLevels(drawing.style.levels, fallback).map(level => {
    const id = `ratio:${level.ratio}`;
    return [id, { id, title: level.label ?? formatRatio(level.ratio) }];
  })).values()];
}

export function fibAlertValue(anchors: 2 | 3 | 'channel', fallback: readonly FibLevel[]): (c: DrawingValueContext, level?: string) => Value | undefined {
  return (c, level) => {
    const rung = activeLevels(c.drawing.style.levels, fallback).find(item => `ratio:${item.ratio}` === level);
    if (!rung || c.pts.length < (anchors === 2 ? 2 : 3)) return undefined;
    const [a, b, w] = c.pts as AtLeast<ScreenPoint, 2>;
    const left = c.drawing.style.extendLeft === true, right = c.drawing.style.extendRight === true;
    if (anchors === 'channel') {
      const shift = (p: ScreenPoint): ScreenPoint => ({ x: p.x + (w!.x - b.x) * rung.ratio, y: p.y + (w!.y - b.y) * rung.ratio });
      return priceAt(c, yAt(shift(a), shift(b), c.x, left, right));
    }
    const end = c.pts[anchors - 1]!;
    if ((!left && c.x < Math.min(a.x, end.x)) || (!right && c.x > Math.max(a.x, end.x))) return undefined;
    const points = c.drawing.points;
    const from = anchors === 2 ? points[0]!.price : points[2]!.price;
    // Horizontal fib rungs are defined in price units even on logarithmic panes.
    return { price: from + (points[1]!.price - points[0]!.price) * rung.ratio };
  };
}
