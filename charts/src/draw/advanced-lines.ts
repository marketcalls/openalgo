/** Channels, pitchforks and dedicated line tools. Geometry stays in media pixels. */
import type { AtLeast, DrawContext, DrawingPoint, DrawingTool, FibLevel, HitContext, ScreenPoint, ToolAnchors } from './types';
import { channelAlertValue, channelAlertLevels, fibAlertValue, fibAlertLevels, lineAlertValue } from './alert-values';
import { composeSettings, EXTEND_FIELDS, FILL_FIELDS, FONT_FIELDS, LEVEL_FIELDS, LINE_FIELDS, SHOW_LABELS_FIELD } from './schema';
import { activeLevels, cloneLevels, formatRatio, levelColor } from './levels';
import { timeBound } from './analysis';
import {
  clippedLine, clipPolygon, extendedLine, geometryTool, interpolate, midpoint, numericProp,
  paintGeometry, sampleArc, type DrawingGeometry, type GeometryPath,
} from './advanced-shared';
import { fontOf, projectPoint, textOf } from './tool-paint';

const CHANNEL_SETTINGS = composeSettings([LINE_FIELDS, FILL_FIELDS, EXTEND_FIELDS]);
const FORK_LEVELS: readonly FibLevel[] = [{ ratio: 0 }, { ratio: 0.5 }, { ratio: 1 }];
const EXTENSION_LEVELS: readonly FibLevel[] = [0, 0.382, 0.618, 1, 1.272, 1.618, 2, 2.618, 3.618, 4.236].map(ratio => ({ ratio }));
const FAN_LEVELS: readonly FibLevel[] = [0, 0.382, 0.5, 0.618, 1].map(ratio => ({ ratio, color: levelColor(ratio) }));
const empty = (): DrawingGeometry => ({ paths: [] });
const line = (a: ScreenPoint, b: ScreenPoint): GeometryPath => ({ points: [a, b] });

function fillEndpoints(a: ScreenPoint, b: ScreenPoint, c: HitContext): [ScreenPoint, ScreenPoint] {
  const dx = b.x - a.x;
  if (dx === 0) return [a, b];
  const left = c.drawing.style.extendLeft === true ? 0 : Math.min(a.x, b.x);
  const right = c.drawing.style.extendRight === true ? c.rc.plotWidth : Math.max(a.x, b.x);
  const at = (x: number): ScreenPoint => ({ x, y: a.y + (b.y - a.y) * (x - a.x) / dx });
  return dx > 0 ? [at(left), at(right)] : [at(right), at(left)];
}

function channel(c: HitContext & ToolAnchors<2>, lower: AtLeast<ScreenPoint, 2>): DrawingGeometry {
  const [a, b] = c.pts;
  const upper = extendedLine(a, b, c);
  const bottom = extendedLine(lower[0], lower[1], c);
  const paths: GeometryPath[] = [];
  if (c.drawing.style.fill === true) {
    const topFill = fillEndpoints(a, b, c), bottomFill = fillEndpoints(lower[0], lower[1], c);
    paths.push({ points: clipPolygon([topFill[0], topFill[1], bottomFill[1], bottomFill[0]], c.rc), closed: true, fill: true, stroke: false });
  }
  paths.push({ points: upper }, { points: bottom });
  return { paths };
}

const disjoint = geometryTool({
  id: 'disjoint-channel', name: 'Disjoint Channel', points: 4,
  alertValue: channelAlertValue('disjoint'), alertLevels: channelAlertLevels,
  defaultStyle: { fill: true }, settings: CHANNEL_SETTINGS,
}, c => c.pts.length < 4 ? empty() : channel(c, c.pts.slice(2, 4) as AtLeast<ScreenPoint, 2>)); // anchors 3 and 4 of four

const flat = geometryTool({
  id: 'flat-top-bottom', name: 'Flat Top/Bottom', points: 3,
  alertValue: channelAlertValue('flat'), alertLevels: channelAlertLevels,
  defaultStyle: { fill: true }, settings: CHANNEL_SETTINGS,
  constrain(points) {
    const out = points.map(p => ({ ...p }));
    if (out.length >= 3) out[2]!.time = (out[0]!.time + out[1]!.time) / 2; // by the length check
    return out;
  },
}, c => c.pts.length < 3 ? empty() : channel(c, [{ x: c.pts[0].x, y: c.pts[2].y }, { x: c.pts[1].x, y: c.pts[2].y }]));

const regression = geometryTool({
  id: 'regression-channel', name: 'Regression Channel', points: 2,
  defaultStyle: { fill: true, showLabels: true },
  settings: composeSettings([LINE_FIELDS, FILL_FIELDS, EXTEND_FIELDS, SHOW_LABELS_FIELD, FONT_FIELDS,
    { path: 'props.deviation', label: 'Deviation multiplier', kind: 'number', min: 0.01, max: 20, step: 0.1, group: 'behavior' }]),
}, c => {
  if (c.pts.length < 2) return empty();
  const bars = c.rc.bars?.() ?? [];
  const [a, b] = c.drawing.points;
  const first = timeBound(bars, Math.min(a.time, b.time));
  const last = timeBound(bars, Math.max(a.time, b.time), true);
  let n = 0, meanX = 0, meanY = 0, xx = 0, xy = 0, yy = 0;
  let firstTime = 0, lastTime = 0, firstIndex = 0, lastIndex = 0;
  // Bars are live and even historical closes can change in place. Recompute
  // exact moments instead of treating array identity as a revision signal.
  for (let i = first; i < last; i++) {
    const bar = bars[i]!, y = bar.close; // last <= length
    // Stored times have exact shared indices; the map avoids a binary search
    // per close and still includes timeline entries from secondary series.
    const x = c.rc.dataLayer.timeToIndex?.(bar.time) ?? c.rc.dataLayer.timeToIndexFloat(bar.time);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    if (n === 0) { firstTime = bar.time; firstIndex = x; }
    lastTime = bar.time; lastIndex = x;
    n++;
    const dx = x - meanX, dy = y - meanY;
    meanX += dx / n; meanY += dy / n;
    xx += dx * (x - meanX); xy += dx * (y - meanY); yy += dy * (y - meanY);
  }
  if (n === 0) return { paths: [], labels: c.drawing.style.showLabels === false ? [] : [{ at: c.pts[0], text: 'No bars in range' }] };
  const slope = xx > 0 ? xy / xx : 0;
  const value = (x: number): number => meanY + slope * (x - meanX);
  const deviation = Math.sqrt(Math.max(0, yy - slope * xy) / n) * numericProp(c.drawing, 'deviation', 2, 0.01, 20);
  const r2 = yy > 0 ? Math.max(0, Math.min(1, slope * xy / yy)) : 1;
  const endpoint = (time: number, index: number, offset: number) => projectPoint(c.rc, { time, price: value(index) + offset });
  const paths: GeometryPath[] = [0, deviation, -deviation].map(offset => ({ points: extendedLine(endpoint(firstTime, firstIndex, offset), endpoint(lastTime, lastIndex, offset), c) }));
  if (c.drawing.style.fill === true) {
    const upper = fillEndpoints(endpoint(firstTime, firstIndex, deviation), endpoint(lastTime, lastIndex, deviation), c);
    const lower = fillEndpoints(endpoint(firstTime, firstIndex, -deviation), endpoint(lastTime, lastIndex, -deviation), c);
    paths.push({ points: clipPolygon([upper[0], upper[1], lower[1], lower[0]], c.rc), closed: true, fill: true, stroke: false });
  }
  return { paths, labels: c.drawing.style.showLabels === false ? [] : [{ at: endpoint(firstTime, firstIndex, deviation), text: `R^2 ${r2.toFixed(3)}  ${n} bars` }] };
});

function pitchfork(id: string, name: string, variant: 'standard' | 'schiff' | 'modified' | 'inside'): DrawingTool {
  return geometryTool({ id, name, points: 3,
    defaultStyle: { fill: true, showLabels: true, levels: cloneLevels(FORK_LEVELS) },
    settings: composeSettings([LINE_FIELDS, FILL_FIELDS, LEVEL_FIELDS, FONT_FIELDS]),
  }, c => {
    if (c.pts.length < 3) return empty();
    const [a, b, end] = c.pts, middle = midpoint(b, end);
    const [p0, p1] = c.drawing.points;
    // Shift in data space so logarithmic scales map the intended price.
    const shifted: DrawingPoint = {
      time: variant === 'schiff' ? p0.time : (p0.time + p1.time) / 2,
      price: (p0.price + p1.price) / 2,
    };
    const base = variant === 'standard' ? a : projectPoint(c.rc, shifted);
    const origin = variant === 'inside' ? middle : base;
    const delta = variant === 'inside' ? { x: end.x - base.x, y: end.y - base.y } : { x: middle.x - base.x, y: middle.y - base.y };
    const ray = (start: ScreenPoint) => clippedLine(start, { x: start.x + delta.x, y: start.y + delta.y }, c.rc, 0, Infinity);
    const paths: GeometryPath[] = [];
    const labels: NonNullable<DrawingGeometry['labels']> = [];
    const levels = activeLevels(c.drawing.style.levels, FORK_LEVELS);
    for (const level of levels) {
      const color = level.color;
      const starts = level.ratio === 0 ? [origin] : [interpolate(middle, b, level.ratio), interpolate(middle, end, level.ratio)];
      for (const start of starts) {
        const points = ray(start);
        paths.push({ points, color });
        if (c.drawing.style.showLabels !== false && points.length === 2) labels.push({ at: { x: points[0].x + 4, y: points[0].y - 4 }, text: level.label ?? formatRatio(level.ratio), color });
      }
    }
    // Fill only enabled bands; no hidden outer level can keep a fill hittable.
    const outer = levels.reduce((max, level) => Math.max(max, Math.abs(level.ratio)), 0);
    if (c.drawing.style.fill === true && outer > 0) {
      const upper = interpolate(middle, b, outer), lower = interpolate(middle, end, outer);
      const length = Math.hypot(delta.x, delta.y);
      if (length > 0) {
        // Put the far end beyond every pane corner before clipping the area.
        // Joining independently clipped rays would leave an unfilled triangle.
        const reach = (Math.max(Math.hypot(upper.x, upper.y), Math.hypot(lower.x, lower.y)) + Math.hypot(c.rc.plotWidth, c.rc.plotHeight)) / length + 1;
        const far = (p: ScreenPoint): ScreenPoint => ({ x: p.x + delta.x * reach, y: p.y + delta.y * reach });
        paths.unshift({ points: clipPolygon([upper, far(upper), far(lower), lower], c.rc), closed: true, fill: true, stroke: false });
      }
    }
    paths.push(line(b, end));
    if (variant === 'inside') paths.push(line(base, end), line(a, b));
    return { paths, labels };
  });
}

const info = geometryTool({ id: 'info-line', name: 'Info Line', points: 2, angleLock: true,
  defaultStyle: { showLabels: true }, settings: composeSettings([LINE_FIELDS, EXTEND_FIELDS, SHOW_LABELS_FIELD, FONT_FIELDS]),
}, c => {
  if (c.pts.length < 2) return empty();
  const [a, b] = c.pts, [p0, p1] = c.drawing.points;
  const change = p1.price - p0.price, sign = change >= 0 ? '+' : '';
  const percent = p0.price === 0 ? 'n/a' : `${sign}${(change / Math.abs(p0.price) * 100).toFixed(2)}%`;
  const bars = Math.abs(Math.round(c.rc.dataLayer.timeToIndexFloat(p1.time) - c.rc.dataLayer.timeToIndexFloat(p0.time)));
  return { paths: [{ points: extendedLine(a, b, c) }], labels: c.drawing.style.showLabels === false ? [] : [{
    at: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 - 8 },
    text: `${sign}${c.rc.priceScale.format(change)} (${percent})  ${bars} bars`,
  }] };
});

const angle = geometryTool({ id: 'trend-angle', name: 'Trend Angle', points: 2, angleLock: true,
  alertValue: lineAlertValue(),
  defaultStyle: { showLabels: true }, settings: composeSettings([LINE_FIELDS, SHOW_LABELS_FIELD, FONT_FIELDS]),
}, c => {
  if (c.pts.length < 2) return empty();
  const [a, b] = c.pts, radians = Math.atan2(b.y - a.y, b.x - a.x);
  const radius = Math.max(12, Math.min(40, Math.hypot(b.x - a.x, b.y - a.y) / 3));
  return { paths: [line(a, b), line(a, { x: a.x + radius * 1.5, y: a.y }), { points: sampleArc(a, radius, radius, 0, radians) }],
    labels: c.drawing.style.showLabels === false ? [] : [{ at: { x: a.x + radius + 6, y: a.y - 6 }, text: `${(-radians * 180 / Math.PI).toFixed(1)} deg` }] };
});

const extension = geometryTool({ id: 'fib-extension-two-point', name: 'Fib Extension (Two Point)', points: 2,
  alertValue: fibAlertValue(2, EXTENSION_LEVELS), alertLevels: fibAlertLevels(EXTENSION_LEVELS),
  defaultStyle: { levels: cloneLevels(EXTENSION_LEVELS), showLabels: true, fill: true, fillOpacity: 0.06 },
  settings: composeSettings([LINE_FIELDS, LEVEL_FIELDS, FILL_FIELDS, EXTEND_FIELDS, FONT_FIELDS]),
}, c => {
  if (c.pts.length < 2) return empty();
  const [a, b] = c.pts, [p0, p1] = c.drawing.points;
  const paths: GeometryPath[] = [], labels: NonNullable<DrawingGeometry['labels']> = [];
  const levels = activeLevels(c.drawing.style.levels, EXTENSION_LEVELS);
  if (c.drawing.style.fill === true && a.x !== b.x) {
    const ys = levels.map(lv => c.rc.priceScale.priceToY(p0.price + (p1.price - p0.price) * lv.ratio)).filter(Number.isFinite).sort((x, y) => x - y);
    const left = c.drawing.style.extendLeft === true ? 0 : Math.min(a.x, b.x);
    const right = c.drawing.style.extendRight === true ? c.rc.plotWidth : Math.max(a.x, b.x);
    for (let i = 1; i < ys.length; i++) {
      if (ys[i] === ys[i - 1]) continue;
      // i is in range.
      paths.push({ points: clipPolygon([{ x: left, y: ys[i - 1]! }, { x: right, y: ys[i - 1]! }, { x: right, y: ys[i]! }, { x: left, y: ys[i]! }], c.rc), closed: true, fill: true, stroke: false });
    }
  }
  paths.push(line(a, b));
  for (const lv of levels) {
    const price = p0.price + (p1.price - p0.price) * lv.ratio;
    const y = c.rc.priceScale.priceToY(price), color = lv.color ?? levelColor(lv.ratio);
    paths.push({ points: extendedLine({ x: a.x, y }, { x: b.x, y }, c), color });
    if (c.drawing.style.showLabels !== false) labels.push({ at: { x: Math.min(a.x, b.x) + 4, y: y - 3 }, text: `${lv.label ?? formatRatio(lv.ratio)}  ${c.rc.priceScale.format(price)}`, color });
  }
  return { paths, labels };
});

interface FanLabelBox { x: number; y: number; width: number; height: number }

function fanGeometry(c: HitContext & ToolAnchors<2>, measure?: (text: string) => number): DrawingGeometry {
  if (c.pts.length < 2) return empty();
  const [a, b] = c.pts, paths: GeometryPath[] = [], labels: NonNullable<DrawingGeometry['labels']> = [];
  // The two far box edges locate the anchors without doubling any fan ray.
  paths.push({ points: [{ x: a.x, y: b.y }, b, { x: b.x, y: a.y }] });
  const size = c.drawing.text?.fontSize ?? 11;
  const height = size * 1.2, occupied: FanLabelBox[] = [];
  const addLabel = (target: ScreenPoint, edge: ScreenPoint, vertical: boolean, text: string, color: string): void => {
    const minX = Math.min(a.x, edge.x), maxX = Math.max(a.x, edge.x);
    const minY = Math.min(a.y, edge.y), maxY = Math.max(a.y, edge.y);
    if (!measure || c.drawing.style.showLabels === false || occupied.length >= 32) return;
    const width = measure(text);
    if (!Number.isFinite(width) || width <= 0 || !Number.isFinite(height) || height <= 0) return;
    if (vertical ? maxY - minY < height : maxX - minX < width) return;
    // At most three nearby positions per label. Crowded labels disappear,
    // rather than stacking rows of text over the rays or moving far from them.
    for (const offset of [0, -height, height]) {
      let x: number, baseline: number;
      if (vertical) {
        x = edge.x >= a.x ? edge.x + 4 : edge.x - width - 4;
        if (x < 0 || x + width > c.rc.plotWidth) x = edge.x >= a.x ? edge.x - width - 4 : edge.x + 4;
        baseline = Math.max(minY + height, Math.min(maxY, target.y + height / 2 + offset));
      } else {
        x = Math.max(minX, Math.min(maxX - width, target.x - width / 2 + offset));
        baseline = edge.y < a.y ? edge.y - 4 : edge.y + height + 4;
        if (baseline - height < 0 || baseline > c.rc.plotHeight) baseline = edge.y < a.y ? edge.y + height + 4 : edge.y - 4;
      }
      const box = { x, y: baseline - height, width, height };
      if (x < 0 || x + width > c.rc.plotWidth || box.y < 0 || baseline > c.rc.plotHeight) continue;
      if (occupied.some(other => x < other.x + other.width + 3 && x + width + 3 > other.x
        && box.y < other.y + other.height + 3 && box.y + height + 3 > other.y)) continue;
      occupied.push(box);
      labels.push({ at: { x, y: baseline }, text, color });
      return;
    }
  };
  for (const lv of activeLevels(c.drawing.style.levels, FAN_LEVELS)) {
    const targets = [{ x: b.x, y: a.y + (b.y - a.y) * lv.ratio }];
    if (lv.ratio !== 1) targets.push({ x: a.x + (b.x - a.x) * lv.ratio, y: b.y });
    targets.forEach((target, i) => {
      const points = clippedLine(a, target, c.rc, 0, Infinity), color = lv.color ?? levelColor(lv.ratio);
      paths.push({ points, color });
      if (points.length === 2) {
        // Negative ratios reflect one ray component across the origin. Reflect
        // its label box too, instead of clamping onto the positive-ratio edge.
        const edge = {
          x: a.x + (Math.sign(target.x - a.x) || Math.sign(b.x - a.x)) * Math.abs(b.x - a.x),
          y: a.y + (Math.sign(target.y - a.y) || Math.sign(b.y - a.y)) * Math.abs(b.y - a.y),
        };
        const ratio = Math.abs(lv.ratio), at = interpolate(a, target, 1 / Math.max(1, ratio));
        addLabel(at, edge, ratio <= 1 ? i === 0 : i !== 0, lv.label ?? String(lv.ratio), color);
      }
    });
  }
  return { paths, labels };
}

const fan: DrawingTool = {
  ...geometryTool({ id: 'fib-speed-resistance-fan', name: 'Fib Speed Resistance Fan', points: 2,
    defaultStyle: { levels: cloneLevels(FAN_LEVELS), showLabels: true }, settings: composeSettings([LINE_FIELDS, LEVEL_FIELDS, FONT_FIELDS]),
  }, c => fanGeometry(c)),
  draw(c: DrawContext & ToolAnchors<2>) {
    const { ctx, rc } = c, text = c.drawing.text;
    let geometry: DrawingGeometry;
    ctx.save();
    try {
      // Match the shared painter's font so collision checks use actual glyph
      // widths, including custom labels and font choices, at this DPR.
      ctx.font = fontOf(textOf(c.drawing), (text?.fontSize ?? 11) * rc.dpr);
      geometry = fanGeometry({ rc, drawing: { ...c.drawing, style: c.style }, pts: c.pts.map(p => ({ x: p.x / rc.dpr, y: p.y / rc.dpr })) as typeof c.pts }, value => ctx.measureText(value).width / rc.dpr);
    } finally { ctx.restore(); }
    paintGeometry(c, geometry);
  },
};

const STAMP_SHAPES = ['star', 'diamond', 'circle', 'arrow up', 'arrow down', 'check', 'cross'] as const;
const stamp = geometryTool({ id: 'icon-stamp', name: 'Icon Stamp', points: 1,
  defaultStyle: { fill: true, fillOpacity: 0.8 },
  settings: composeSettings([LINE_FIELDS, FILL_FIELDS,
    { path: 'props.shape', label: 'Shape', kind: 'select', group: 'behavior', options: STAMP_SHAPES.map(shape => ({ value: shape.replace(' ', '-'), label: shape[0]!.toUpperCase() + shape.slice(1) })) }, // no shape name is empty
    { path: 'props.size', label: 'Size', kind: 'number', min: 8, max: 160, step: 2, group: 'behavior' }]),
}, c => {
  if (c.pts.length < 1) return empty();
  const a = c.pts[0], r = numericProp(c.drawing, 'size', 28, 8, 160) / 2;
  const point = (x: number, y: number) => ({ x: a.x + x * r, y: a.y + y * r });
  const shape = c.drawing.props?.shape;
  let points: ScreenPoint[];
  if (shape === 'diamond') points = [point(0, -1), point(1, 0), point(0, 1), point(-1, 0)];
  else if (shape === 'circle') points = sampleArc(a, r, r, 0, 2 * Math.PI);
  else if (shape === 'arrow-up' || shape === 'arrow-down') {
    const sign = shape === 'arrow-up' ? 1 : -1;
    points = ([[0, -1], [1, 0], [0.35, 0], [0.35, 1], [-0.35, 1], [-0.35, 0], [-1, 0]] as const).map(([x, y]) => point(x, y * sign));
  } else if (shape === 'check') {
    points = ([[-1, 0], [-0.65, -0.3], [-0.2, 0.2], [0.75, -0.85], [1, -0.55], [-0.2, 0.85]] as const).map(([x, y]) => point(x, y));
  } else if (shape === 'cross') {
    points = ([[-1, -0.65], [-0.65, -1], [0, -0.35], [0.65, -1], [1, -0.65], [0.35, 0], [1, 0.65], [0.65, 1], [0, 0.35], [-0.65, 1], [-1, 0.65], [-0.35, 0]] as const).map(([x, y]) => point(x, y));
  } else {
    points = Array.from({ length: 10 }, (_, i) => {
      const theta = -Math.PI / 2 + i * Math.PI / 5, radius = i % 2 === 0 ? 1 : 0.45;
      return point(Math.cos(theta) * radius, Math.sin(theta) * radius);
    });
  }
  return { paths: [{ points, closed: true, fill: true }] };
});

export const ADVANCED_LINE_TOOLS: readonly DrawingTool[] = [
  disjoint, flat, regression,
  pitchfork('pitchfork', 'Pitchfork', 'standard'),
  pitchfork('schiff-pitchfork', 'Schiff Pitchfork', 'schiff'),
  pitchfork('modified-schiff-pitchfork', 'Modified Schiff Pitchfork', 'modified'),
  pitchfork('inside-pitchfork', 'Inside Pitchfork', 'inside'),
  info, angle, extension, fan, stamp,
];
