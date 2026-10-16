/**
 * Footprint layers drawn across bars rather than inside one column: zones that
 * extend right, unfinished auction lines, the visible-range profile, and the
 * flip markers. Kept apart from the column renderer, which they only read.
 */
import type { PrimitiveRenderContext } from 'openalgo-charts';
import type { FootprintAuction, FootprintZone } from './footprint-signals';
import type { FootprintBar } from './profile-model';
import { valueArea } from './profile-model';
import { readableTextColor } from './footprint-colors';
import { withAlpha } from '../render/pill';

export interface OverlayColors {
  stackedBuy: string;
  stackedSell: string;
  node: string;
  absorption: string;
  auctionHigh: string;
  auctionLow: string;
}

/** Right edge of the bar slot at `time`, or null when the bar is not in the data. */
function slotEdge(rc: PrimitiveRenderContext, time: number, side: -1 | 1): number | null {
  const index = rc.dataLayer.timeToIndex(time);
  return index === undefined ? null : rc.timeScale.indexToX(index) + side * rc.timeScale.barSpacing / 2;
}

/** Zones from the origin bar's right edge to the left edge of the bar that ended them, else to the plot edge. */
export function drawZones(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, zones: readonly FootprintZone[], colors: OverlayColors, bottom: number): void {
  const dpr = rc.dpr;
  for (const zone of zones) {
    const x0 = slotEdge(rc, zone.time, 1);
    const x1 = zone.endTime === null ? rc.plotWidth : slotEdge(rc, zone.endTime, -1);
    if (x0 === null || x1 === null || x1 <= Math.max(0, x0) || x0 >= rc.plotWidth) continue;
    const top = rc.priceScale.priceToY(zone.high), low = rc.priceScale.priceToY(zone.low);
    if (Math.min(top, low) >= bottom) continue;
    ctx.fillStyle = withAlpha(colors[zone.kind], 0.22);
    ctx.fillRect(x0 * dpr, Math.min(top, low) * dpr, (x1 - x0) * dpr, Math.abs(low - top) * dpr);
  }
}

/** Dash-dot lines on the outer edge of an unfinished extreme, `edge` giving that edge's y for a bar and side. */
export function drawAuctions(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, auctions: readonly FootprintAuction[],
  colors: OverlayColors, edge: (auction: FootprintAuction) => number): void {
  const dpr = rc.dpr;
  ctx.save();
  ctx.lineWidth = dpr;
  ctx.setLineDash([6 * dpr, 3 * dpr, dpr, 3 * dpr]);
  for (const auction of auctions) {
    const x0 = slotEdge(rc, auction.time, 1);
    const x1 = auction.endTime === null ? rc.plotWidth : slotEdge(rc, auction.endTime, -1);
    if (x0 === null || x1 === null || x1 <= Math.max(0, x0) || x0 >= rc.plotWidth) continue;
    const y = Math.round(edge(auction) * dpr) + 0.5;
    ctx.strokeStyle = auction.side === 'high' ? colors.auctionHigh : colors.auctionLow;
    ctx.beginPath(); ctx.moveTo(x0 * dpr, y); ctx.lineTo(x1 * dpr, y); ctx.stroke();
  }
  ctx.restore();
}

/** A filled triangle pointing up (buy) or down (sell) with its tip at `tipY`. */
export function drawFlip(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, x: number, tipY: number, size: number, up: boolean, color: string): void {
  const dpr = rc.dpr, base = up ? tipY + size : tipY - size;
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(x * dpr, tipY * dpr);
  ctx.lineTo((x + size / 2) * dpr, base * dpr);
  ctx.lineTo((x - size / 2) * dpr, base * dpr);
  ctx.closePath(); ctx.fill();
}

/**
 * Volume at price over the visible bars, against the left edge: a label column
 * with the row total, then the ask volume bar and the bid volume bar joined to it.
 */
export function drawVisibleProfile(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, bars: readonly FootprintBar[], step: number,
  width: number, bottom: number, buy: string, sell: string, bg: string, text: string, poc: string, format: (v: number) => string, font: number): void {
  const rows = new Map<number, [number, number]>();
  for (const bar of bars) {
    for (const cell of bar.cells) {
      const at = rows.get(cell.price) ?? [0, 0];
      at[0] += cell.bidVol; at[1] += cell.askVol;
      rows.set(cell.price, at);
    }
  }
  const prices = [...rows.keys()].sort((a, b) => b - a);
  const totals = prices.map(p => rows.get(p)![0] + rows.get(p)![1]);
  const peak = Math.max(0, ...totals);
  if (peak <= 0 || !(step > 0)) return;
  const pocRow = valueArea(totals, 0).poc;
  const dpr = rc.dpr, label = font * 5;
  ctx.save();
  ctx.beginPath(); ctx.rect(0, 0, (label + width + 2) * dpr, bottom * dpr); ctx.clip();
  ctx.font = `${font * dpr}px ui-monospace, SFMono-Regular, Menlo, monospace`;
  ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
  prices.forEach((price, i) => {
    const [bid, ask] = rows.get(price)!;
    const a = rc.priceScale.priceToY(price + step / 2), b = rc.priceScale.priceToY(price - step / 2);
    const top = Math.min(a, b), h = Math.max(1, Math.abs(b - a) - 1);
    if (top >= bottom || top + h <= 0) return;
    const shade = withAlpha(text, 0.08 + 0.4 * totals[i]! / peak);
    ctx.fillStyle = bg; ctx.fillRect(0, top * dpr, label * dpr, h * dpr);
    ctx.fillStyle = shade; ctx.fillRect(0, top * dpr, label * dpr, h * dpr);
    if (i === pocRow) { ctx.strokeStyle = poc; ctx.lineWidth = dpr; ctx.strokeRect(dpr / 2, top * dpr + dpr / 2, label * dpr - dpr, h * dpr - dpr); }
    if (h >= font * 0.8) {
      ctx.fillStyle = readableTextColor(text, bg);
      ctx.fillText(format(totals[i]!), (label - 3) * dpr, (top + h / 2) * dpr);
    }
    const askW = width * ask / peak, bidW = width * bid / peak;
    ctx.fillStyle = withAlpha(buy, 0.8); ctx.fillRect((label + 1) * dpr, top * dpr, askW * dpr, h * dpr);
    ctx.fillStyle = withAlpha(sell, 0.8); ctx.fillRect((label + 1 + askW) * dpr, top * dpr, bidW * dpr, h * dpr);
  });
  ctx.restore();
}
