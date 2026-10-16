/**
 * Three axis defects reported off a live NIFTY chart, side by side with a
 * professional terminal:
 *
 *   1. the price ladder printed six labels whatever the pane measured, so a tall
 *      chart read one price every 120 px where the reference read one every 30
 *   2. a session that had just opened carried no date on the time axis, because
 *      labels were only ever placed on the regular grid and the new day had too
 *      few bars to reach the next grid tick
 *   3. bars painted past the plot's right edge, into the price-axis strip
 *
 * All three are about what the axis prints, not about the numbers behind it.
 */
import { describe, it, expect } from 'vitest';
import { DataLayer } from '../src/model/data-layer';
import { TimeScale } from '../src/scale/time-scale';
import { PriceScale } from '../src/scale/price-scale';
import { drawTimeAxis, drawPriceAxis, priceTickCount, type PlotLayout } from '../src/render/axis';
import type { Bar } from '../src/model/bar';
import { RecordingContext } from './helpers/fake-ctx';

const utc = (y: number, mo: number, d: number, h = 0, mi = 0): number =>
  Math.floor(Date.UTC(y, mo - 1, d, h, mi) / 1000);

const layout = (plotHeight: number, plotWidth = 900): PlotLayout => ({
  plotWidth, plotHeight, priceAxisWidth: 56, timeAxisHeight: 22, plotLeft: 0,
});

function scale(min: number, max: number, height: number): PriceScale {
  const ps = new PriceScale();
  ps.setHeight(height);
  ps.setPriceRange({ min, max });
  return ps;
}

const drawn = (rec: RecordingContext): string[] =>
  rec.ops.filter((o) => o.type === 'fillText').map((o) => o.text ?? '');

describe('the price ladder follows the pane height', () => {
  it('gives a tall pane more prices than a short one', () => {
    expect(priceTickCount(200)).toBeLessThan(priceTickCount(800));
  });

  it('keeps the spacing roughly constant rather than the count', () => {
    // The count is what changed; the point of changing it is that the gap
    // between two labels stays about the same at any height.
    for (const h of [200, 400, 800, 1200]) {
      const gap = h / Math.max(1, priceTickCount(h) - 1);
      expect(gap).toBeGreaterThan(20);
      expect(gap).toBeLessThan(80);
    }
  });

  it('clamps rather than printing a label per pixel, or none at all', () => {
    expect(priceTickCount(0)).toBeGreaterThanOrEqual(2);
    expect(priceTickCount(-50)).toBeGreaterThanOrEqual(2);
    expect(priceTickCount(Number.NaN)).toBeGreaterThanOrEqual(2);
    expect(priceTickCount(100000)).toBeLessThanOrEqual(30);
  });

  it('prints appreciably more of the ladder on a real pane than the old six', () => {
    // The reported chart: a ~700px pane over a 200 point range showed five
    // prices where the reference terminal showed about twenty.
    const ps = scale(23980, 24200, 700);
    const rec = new RecordingContext();
    drawPriceAxis(rec as unknown as CanvasRenderingContext2D, ps, layout(700), 1);
    // Twelve rungs, 23980 to 24200: the two on the pane's edges are left out,
    // since the edges would cut their labels in half, which leaves ten whole
    // prices where the old ladder printed six.
    expect(drawn(rec).length).toBeGreaterThanOrEqual(10);
  });
});

describe('the time axis always dates a new day', () => {
  /**
   * A session that opened a few bars ago, which is the reported case: bars run
   * to the close of one day, then the next day opens and only three bars exist
   * so far. The grid stride is far wider than three bars, so before the fix no
   * grid tick landed inside the new day and the date was never drawn.
   */
  // 61 bars, so the boundary lands at index 61. At the spacing below the grid
  // stride is 20, putting ticks on 0, 20, 40, 60, 80: index 61 is not one of
  // them, and with only a few bars after it the run ends before tick 80. No grid
  // tick falls inside the new day at all, which is the state that produced the
  // report. A round 60 would have put the boundary exactly on tick 60 and the
  // old code would have dated it by luck, so this count is load-bearing.
  const DAY1 = 61;
  const SPACING = 4;
  const STRIDE = Math.max(1, Math.round(80 / SPACING));

  function twoSessions(tailBars: number): Bar[] {
    const day1 = Array.from({ length: DAY1 }, (_, i) => ({
      time: utc(2026, 8, 31, 3, 45) + i * 300,
      open: 100, high: 101, low: 99, close: 100,
    }));
    const day2 = Array.from({ length: tailBars }, (_, i) => ({
      time: utc(2026, 9, 1, 3, 45) + i * 300,
      open: 100, high: 101, low: 99, close: 100,
    }));
    return [...day1, ...day2];
  }

  /** The fixture only proves anything while the grid really does miss the day. */
  function assertGridMissesDay2(tailBars: number): void {
    const lastIndex = DAY1 + tailBars - 1;
    for (let i = 0; i <= lastIndex; i += STRIDE) expect(i).toBeLessThan(DAY1);
  }

  function timeLabels(data: Bar[], barSpacing: number): string[] {
    const dl = new DataLayer();
    dl.setSeriesData(dl.createSeries(), data);
    const ts = new TimeScale({ barSpacing });
    ts.setWidth(900);
    ts.setRightOffset(0);
    ts.setBaseIndex(dl.baseIndex);
    const rec = new RecordingContext();
    drawTimeAxis(rec as unknown as CanvasRenderingContext2D, ts, dl, layout(400), 1);
    return drawn(rec);
  }

  it('dates the new session even when only a few of its bars exist', () => {
    assertGridMissesDay2(3);
    // 01 Sep in IST, the shipped default zone.
    const labels = timeLabels(twoSessions(3), SPACING);
    expect(labels.some((l) => l.includes('Sep'))).toBe(true);
  });

  it('dates it for a single bar, the first tick of the day', () => {
    assertGridMissesDay2(1);
    const labels = timeLabels(twoSessions(1), SPACING);
    expect(labels.some((l) => l.includes('Sep'))).toBe(true);
  });

  it('still dates the day that ends the run, not only the one that starts it', () => {
    const labels = timeLabels(twoSessions(3), SPACING);
    expect(labels.some((l) => l.includes('Aug'))).toBe(true);
  });

  it('does not print the same date twice in a row', () => {
    const labels = timeLabels(twoSessions(3), SPACING);
    const dates = labels.filter((l) => /[A-Za-z]/.test(l));
    expect(new Set(dates).size).toBe(dates.length);
  });

  it('leaves a single-day window alone', () => {
    // One session, no boundary in view: the forced mark must add nothing.
    const oneDay = Array.from({ length: 40 }, (_, i) => ({
      time: utc(2026, 8, 31, 3, 45) + i * 300,
      open: 100, high: 101, low: 99, close: 100,
    }));
    const dates = timeLabels(oneDay, SPACING).filter((l) => /[A-Za-z]/.test(l));
    // Only the leftmost label, which has no predecessor to compare against.
    expect(dates.length).toBeLessThanOrEqual(1);
  });
});
