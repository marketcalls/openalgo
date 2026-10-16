/**
 * Time axis labels over a transformed series. Several bricks that form on one
 * bar sit a second apart (`ensureIncreasingTimes`), which is an artefact of
 * giving each its own index, not the chart's resolution: the axis must not
 * read it as a seconds chart.
 */
import { describe, it, expect } from 'vitest';
import { DataLayer } from '../src/model/data-layer';
import { TimeScale } from '../src/scale/time-scale';
import { drawTimeAxis, type PlotLayout } from '../src/render/axis';
import { RecordingContext } from './helpers/fake-ctx';
import type { Bar } from '../src/model/bar';

const LAYOUT: PlotLayout = { plotWidth: 600, plotHeight: 378, priceAxisWidth: 56, timeAxisHeight: 22, plotLeft: 0 };
const at = (seconds: number): Bar => ({ time: seconds, open: 100, high: 101, low: 99, close: 100 });

/** The labels one frame paints, a label per element (bar spacing 100 on a 600px plot). */
function labels(data: Bar[]): string[] {
  const dl = new DataLayer();
  dl.setSeriesData(dl.createSeries(), data);
  const ts = new TimeScale({ barSpacing: 100 });
  ts.setWidth(LAYOUT.plotWidth);
  ts.setRightOffset(0);
  ts.setBaseIndex(dl.baseIndex);
  const rec = new RecordingContext();
  drawTimeAxis(rec as unknown as CanvasRenderingContext2D, ts, dl, LAYOUT, 1);
  return rec.ops.filter(o => o.type === 'fillText').map(o => o.text ?? '');
}

describe('time axis over transformed elements', () => {
  it('labels bricks that formed on one five-minute bar by the minute', () => {
    const t0 = Date.UTC(2024, 2, 7, 4, 0) / 1000;
    // Two bricks on 10:00 IST, three on 10:05, one on 10:15: bumped a second apart within each bar.
    const bricks = [t0 + 1800, t0 + 1801, t0 + 2100, t0 + 2101, t0 + 2102, t0 + 2700].map(at);
    expect(labels(bricks)).toEqual(['07 Mar', '10:00', '10:05', '10:05', '10:05', '10:15']);
  });

  it('still reads bars under a minute apart as a seconds chart', () => {
    const t0 = Date.UTC(2024, 2, 7, 4, 0, 50) / 1000;
    expect(labels([0, 5, 10, 15, 20, 25].map(s => at(t0 + s)))).toEqual(
      ['07 Mar', '09:30:55', '09:31:00', '09:31:05', '09:31:10', '09:31:15']);
  });
});
