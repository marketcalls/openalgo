/** Time-anchored analysis drawings use the owning pane's bars, never a tier cache. */
import type { DrawContext, Drawing, DrawingTool, HitContext, ScreenPoint } from './types';
import type { AnalysisStatus, AnchoredVwapSource } from './analysis';
import { analysisNumber, anchoredVwapAnalysis, fixedRangeVolumeProfileAnalysis } from './analysis';
import { clippedLine } from './advanced-shared';
import { fontOf, projectPoint, strokeWidth, textOf } from './tool-paint';
import { dashFor } from '../render/line';
import { distToSegment, distToRect } from './geometry';
import { composeSettings, FONT_FIELDS, LINE_FIELDS, SHOW_LABELS_FIELD } from './schema';

interface AnalysisRect { left: number; right: number; top: number; bottom: number; area: boolean }
interface AnalysisGeometry {
  /** Clipped segments, each of two points: an empty clip is never kept. Bands too. */
  lines: ScreenPoint[][];
  bands: ScreenPoint[][];
  rects: AnalysisRect[];
  label: string;
  labelAt: ScreenPoint;
  status: AnalysisStatus;
}
function emptyGeometry(): AnalysisGeometry {
  return { lines: [], bands: [], rects: [], label: '', labelAt: { x: 0, y: 0 }, status: 'empty' };
}
function source(drawing: Drawing): AnchoredVwapSource {
  const value = drawing.props?.source;
  return value === 'close' || value === 'hl2' || value === 'ohlc4' ? value : 'hlc3';
}
function statusLabel(result: { status: AnalysisStatus; historyPartial: boolean; missingVolumeBars: number; invalidPriceBars: number }): string {
  const history = result.historyPartial ? ' (partial history)' : '';
  switch (result.status) {
    case 'partial': return history + (result.missingVolumeBars > 0 || result.invalidPriceBars > 0 ? ' (partial volume/data)' : '');
    case 'missing-volume': return ': volume unavailable' + history;
    case 'zero-volume': return ': zero volume' + history;
    case 'invalid-data': return ': data unavailable' + history;
    case 'empty': return ': no bars in range' + history;
    default: return '';
  }
}
function unavailableAnchors(g: AnalysisGeometry, c: HitContext): void {
  // Keep a restored analysis editable when its instrument has no volume or
  // when its anchored history has not loaded yet.
  for (const anchor of c.drawing.points) {
    const p = projectPoint(c.rc, anchor);
    for (const [a, b] of [
      [{ x: p.x - 4, y: p.y }, { x: p.x + 4, y: p.y }],
      [{ x: p.x, y: p.y - 4 }, { x: p.x, y: p.y + 4 }],
    ] as const) {
      const path = clippedLine(a, b, c.rc);
      if (path.length > 0) g.lines.push(path);
    }
  }
}
function curve(c: HitContext): AnalysisGeometry {
  const g = emptyGeometry(), anchor = c.drawing.points[0];
  if (!anchor) return g;
  const result = anchoredVwapAnalysis(c.rc.bars?.() ?? [], anchor.time, { source: source(c.drawing) });
  g.status = result.status;
  const bands = c.drawing.props?.showBands !== false;
  const multiplier = analysisNumber(c.drawing.props?.bandMultiplier, 1, 0, 5);
  const last = result.points[result.points.length - 1];
  g.labelAt = last ? projectPoint(c.rc, { time: last.time, price: last.value }) : projectPoint(c.rc, anchor);
  g.label = `AVWAP${last ? ` ${c.rc.priceScale.format(last.value)}` : ''}${statusLabel(result)}`;
  for (const factor of bands && multiplier > 0 ? [0, -multiplier, multiplier] : [0]) {
    let previous: ScreenPoint | undefined;
    for (const sample of result.points) {
      const next = projectPoint(c.rc, { time: sample.time, price: sample.value + sample.deviation * factor });
      if (sample.breakBefore) previous = undefined;
      const path = previous ? clippedLine(previous, next, c.rc) : clippedLine({ x: next.x - 2, y: next.y }, next, c.rc);
      if (path.length > 0) (factor === 0 ? g.lines : g.bands).push(path);
      previous = next;
    }
  }
  if (!last) unavailableAnchors(g, c);
  return g;
}
function profile(c: HitContext): AnalysisGeometry {
  const g = emptyGeometry(), [a, b] = c.drawing.points;
  if (!a || !b) return g;
  const result = fixedRangeVolumeProfileAnalysis(c.rc.bars?.() ?? [], a.time, b.time, {
    rows: analysisNumber(c.drawing.props?.rows, 48, 4, 200),
    valueArea: analysisNumber(c.drawing.props?.valueArea, 70, 1, 100),
  });
  g.status = result.status;
  const pa = projectPoint(c.rc, a), pb = projectPoint(c.rc, b);
  const left = Math.min(pa.x, pb.x), right = Math.max(pa.x, pb.x);
  const max = Math.max(0, ...result.rows.map(row => row.volume));
  const width = Math.max(12, right - left) * analysisNumber(c.drawing.props?.width, 35, 5, 100) / 100;
  const fromRight = c.drawing.props?.side === 'right';
  const showArea = c.drawing.props?.showValueArea !== false;
  g.label = `Volume profile (estimated)${statusLabel(result)}`;
  g.labelAt = { x: left, y: Math.min(pa.y, pb.y) };
  for (const row of result.rows) {
    const y1 = c.rc.priceScale.priceToY(row.low), y2 = c.rc.priceScale.priceToY(row.high);
    if (![y1, y2].every(Number.isFinite) || max <= 0 || row.volume <= 0) continue;
    const w = width * row.volume / max;
    const l = fromRight ? right - w : left, r = fromRight ? right : left + w;
    const top = Math.max(0, Math.min(y1, y2)), bottom = Math.min(c.rc.plotHeight, Math.max(y1, y2) + (y1 === y2 ? 1 : 0));
    const rect = { left: Math.max(0, l), right: Math.min(c.rc.plotWidth, r), top, bottom, area: showArea && row.valueArea };
    if (rect.left < rect.right && rect.top < rect.bottom) g.rects.push(rect);
  }
  const level = (price: number | null, into: ScreenPoint[][]): void => {
    if (price === null) return;
    const y = c.rc.priceScale.priceToY(price);
    const line = clippedLine({ x: left, y }, { x: right === left ? right + 12 : right, y }, c.rc);
    if (line.length > 0) into.push(line);
  };
  if (c.drawing.props?.showPoc !== false) level(result.poc, g.lines);
  if (showArea) { level(result.valueAreaLow, g.bands); level(result.valueAreaHigh, g.bands); }
  // A value area is set only on a profile with rows.
  if (result.valueAreaHigh !== null) g.labelAt.y = c.rc.priceScale.priceToY(result.rows[result.rows.length - 1]!.high);
  if (result.rows.length === 0) unavailableAnchors(g, c);
  return g;
}
function paint(c: DrawContext, build: (c: HitContext) => AnalysisGeometry): void {
  const { ctx, rc, drawing, style } = c, dpr = rc.dpr;
  if (!(rc.plotWidth > 0 && rc.plotHeight > 0)) return;
  const g = build({ drawing, rc, pts: [] });
  ctx.save();
  ctx.beginPath(); ctx.rect(0, 0, rc.plotWidth * dpr, rc.plotHeight * dpr); ctx.clip();
  ctx.strokeStyle = style.color;
  ctx.fillStyle = style.color;
  ctx.lineWidth = strokeWidth(style.lineWidth, dpr);
  ctx.setLineDash(dashFor(style.lineStyle, dpr));
  for (const rect of g.rects) {
    ctx.save();
    ctx.globalAlpha *= analysisNumber(style.fillOpacity, 0.4, 0, 1) * (rect.area ? 1 : 0.45);
    ctx.fillRect(rect.left * dpr, rect.top * dpr, (rect.right - rect.left) * dpr, (rect.bottom - rect.top) * dpr);
    ctx.restore();
  }
  const stroke = (lines: ScreenPoint[][]): void => {
    if (lines.length === 0) return;
    ctx.beginPath();
    for (const line of lines) {
      ctx.moveTo(line[0]!.x * dpr, line[0]!.y * dpr); // a segment's two points
      ctx.lineTo(line[1]!.x * dpr, line[1]!.y * dpr);
    }
    ctx.stroke();
  };
  stroke(g.lines);
  ctx.save(); ctx.globalAlpha *= 0.6; stroke(g.bands); ctx.restore();
  // Data-quality notices remain visible when optional numeric labels are hidden.
  if ((style.showLabels !== false || g.status !== 'ready') && g.label && Number.isFinite(g.labelAt.x) && Number.isFinite(g.labelAt.y)) {
    const text = drawing.text, size = analysisNumber(text?.fontSize, 11, 6, 96);
    ctx.fillStyle = text?.color ?? style.color;
    ctx.font = fontOf(textOf(drawing), size * dpr);
    ctx.textAlign = 'left'; ctx.textBaseline = 'bottom';
    const width = ctx.measureText(g.label).width / dpr;
    const x = Math.max(4, Math.min(rc.plotWidth - width - 4, g.labelAt.x + 4));
    const y = Math.max(size + 3, Math.min(rc.plotHeight - 3, g.labelAt.y - 5));
    ctx.fillText(g.label, x * dpr, y * dpr);
  }
  ctx.restore();
}
function distance(x: number, y: number, c: HitContext, build: (c: HitContext) => AnalysisGeometry): number | null {
  if (x < 0 || y < 0 || x > c.rc.plotWidth || y > c.rc.plotHeight) return null;
  const g = build(c);
  let best = Infinity;
  for (const line of [...g.lines, ...g.bands]) best = Math.min(best, distToSegment(x, y, line[0]!, line[1]!)); // two points each
  if (analysisNumber(c.drawing.style.fillOpacity, 0.4, 0, 1) > 0) {
    for (const rect of g.rects) best = Math.min(best, distToRect(x, y, { x: rect.left, y: rect.top }, { x: rect.right, y: rect.bottom }, true));
  }
  return Number.isFinite(best) ? best : null;
}

export const ANCHORED_VWAP: DrawingTool = {
  id: 'anchored-vwap', name: 'Anchored VWAP', points: 1,
  defaultStyle: { showLabels: true, lineWidth: 2 },
  settings: composeSettings([LINE_FIELDS, SHOW_LABELS_FIELD, FONT_FIELDS,
    { path: 'props.source', label: 'Price source', kind: 'select', group: 'behavior', defaultValue: 'hlc3', options: [
      { value: 'hlc3', label: 'HLC3' }, { value: 'close', label: 'Close' }, { value: 'hl2', label: 'HL2' }, { value: 'ohlc4', label: 'OHLC4' },
    ] },
    { path: 'props.showBands', label: 'Deviation bands', kind: 'boolean', group: 'behavior', defaultValue: true },
    { path: 'props.bandMultiplier', label: 'Band multiplier', kind: 'number', min: 0, max: 5, step: 0.25, group: 'behavior', defaultValue: 1 },
  ]),
  draw: c => paint(c, curve), distance: (x, y, c) => distance(x, y, c, curve),
};
export const FIXED_RANGE_VOLUME_PROFILE: DrawingTool = {
  id: 'fixed-range-volume-profile', name: 'Fixed Range Volume Profile', points: 2,
  defaultStyle: { showLabels: true, fillOpacity: 0.4 },
  settings: composeSettings([LINE_FIELDS, SHOW_LABELS_FIELD, FONT_FIELDS,
    { path: 'style.fillOpacity', label: 'Histogram opacity', kind: 'opacity', min: 0, max: 1, step: 0.05, group: 'fill', defaultValue: 0.4 },
    { path: 'props.rows', label: 'Price rows', kind: 'number', min: 4, max: 200, step: 1, group: 'behavior', defaultValue: 48 },
    { path: 'props.valueArea', label: 'Value area (%)', kind: 'number', min: 1, max: 100, step: 1, group: 'behavior', defaultValue: 70 },
    { path: 'props.width', label: 'Range width (%)', kind: 'number', min: 5, max: 100, step: 1, group: 'behavior', defaultValue: 35 },
    { path: 'props.side', label: 'Histogram side', kind: 'select', group: 'behavior', defaultValue: 'left', options: [
      { value: 'left', label: 'Left' }, { value: 'right', label: 'Right' },
    ] },
    { path: 'props.showPoc', label: 'Point of control', kind: 'boolean', group: 'behavior', defaultValue: true },
    { path: 'props.showValueArea', label: 'Value area levels', kind: 'boolean', group: 'behavior', defaultValue: true },
  ]),
  draw: c => paint(c, profile), distance: (x, y, c) => distance(x, y, c, profile),
};
