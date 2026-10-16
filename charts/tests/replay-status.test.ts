import { expect, it } from 'vitest';
import { isReplaying } from '../src/index';
import { Chart } from '../src/core/chart';
import { ReplayController } from '../src/replay/controller';
import { fakeDocument } from './helpers/fake-dom';

it('reports the real replay boundary through start, pause and stop', () => {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), { document: doc, shortcuts: false, raf: { schedule: () => 0 } });
  chart.applySize(800, 600);
  const series = chart.addSeries('candlestick');
  const bars = [60, 120, 180].map(time => ({ time, open: 10, high: 12, low: 9, close: 11 }));
  series.setData(bars);
  expect(isReplaying(chart)).toBe(false);
  const replay = new ReplayController(chart, { series, bars, startIndex: 1 });
  try {
    expect(isReplaying(chart)).toBe(true);
    replay.pause();
    expect(isReplaying(chart)).toBe(true);
    replay.stop();
    expect(isReplaying(chart)).toBe(false);
  } finally { replay.stop(); chart.destroy(); }
});
