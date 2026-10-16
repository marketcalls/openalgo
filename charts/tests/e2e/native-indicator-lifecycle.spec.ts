import { test, expect, type Page } from '@playwright/test';
import type { Chart, IndicatorApi, IndicatorCalcContext, SeriesApi } from '../../src/index';
import type * as Charts from '../../src/index';

declare global {
  interface Window {
    __lifecycleChart: { chart: Chart; series: SeriesApi; indicator: IndicatorApi; context: () => IndicatorCalcContext | undefined };
  }
}

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function snapshot(page: Page) {
  await paint(page);
  return page.evaluate(() => {
    const state = window.__lifecycleChart;
    const values = state.indicator.values().total;
    const context = state.context()!;
    return { values, ...context.barState, execution: context.execution };
  });
}

test('history replacement, live confirmation and replay reach rendered indicator outputs', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 960, height: 600 });
  await page.route('**/native-lifecycle.html', route => route.fulfill({
    contentType: 'text/html', body: '<!doctype html><html><head><style>html,body{margin:0;height:100%;background:#101010}#chart{height:100%}</style></head><body><div id="chart"></div></body></html>',
  }));
  await page.goto('/native-lifecycle.html');
  await page.evaluate(async () => {
    const url = '/dist/openalgo-charts.mjs';
    const lib = await import(url) as typeof Charts;
    const chart = lib.createChart(document.getElementById('chart')!, { branding: false, theme: lib.darkTheme, axisChrome: { clock: () => 10000 } });
    chart.setDataContext({ symbol: 'SAMPLE', interval: '100t' });
    const series = chart.addSeries('candlestick');
    series.setData([{ time: 120, open: 1, high: 3, low: 0, close: 2 }, { time: 180, open: 2, high: 4, low: 1, close: 3 }], { confirmation: 'forming' });
    let context: IndicatorCalcContext | undefined;
    const calculate = (bars: readonly Charts.Bar[], from: number, start: number, ctx?: IndicatorCalcContext) => {
      context = ctx;
      let total = start;
      return { total: bars.slice(from).map(bar => total += bar.close) };
    };
    lib.registerIndicator({
      id: 'native-lifecycle', name: 'Accumulated values', placement: 'onchart', inputs: [],
      plots: [{ key: 'total', title: 'Total', type: 'line', style: { color: '#4488ff', lineWidth: 2 } }],
      calc: (bars, _settings, _store, ctx) => calculate(bars, 0, 0, ctx),
      calcTail: (bars, _settings, from, previous, _store, ctx) => calculate(bars, from, from > 0 ? previous.total[from - 1]! : 0, ctx),
      markers: ({ bars }) => context?.barState.isConfirmed && bars.length ? [{
        time: bars[bars.length - 1].time, position: 'aboveBar', shape: 'circle', color: '#ffaa00', size: 'big', text: 'Settled',
      }] : [],
      tables: () => [{ id: 'state', rows: [[{ text: `${context?.execution?.provenance} / ${context?.barState.isConfirmed ? 'confirmed' : 'forming'}` }]],
        options: { position: 'bottom-left', cellWidth: 210, cellHeight: 30, background: '#253044' } }],
    });
    const indicator = chart.addIndicator('native-lifecycle');
    chart.setVisibleLogicalRange({ from: -1, to: 3 });
    window.__lifecycleChart = { chart, series, indicator, context: () => context };
  });
  expect(await snapshot(page)).toMatchObject({ values: [2, 5], isRealtime: false, isConfirmed: false, execution: { provenance: 'history' } });
  await page.evaluate(() => {
    const { series } = window.__lifecycleChart;
    series.update(series.getData()[1], { confirmation: 'confirmed' });
  });
  expect(await snapshot(page)).toMatchObject({ values: [2, 5], isRealtime: true, isConfirmed: true, execution: { provenance: 'live' } });
  await page.screenshot({ path: info.outputPath('provider-confirmed.png') });
  await page.evaluate(() => {
    window.__lifecycleChart.series.setData([
      { time: 120, open: 19, high: 21, low: 18, close: 20 }, { time: 180, open: 29, high: 31, low: 28, close: 30 },
    ], { confirmation: 'confirmed' });
  });
  expect(await snapshot(page)).toMatchObject({ values: [20, 50], isRealtime: false, execution: { provenance: 'history' } });
  await page.screenshot({ path: info.outputPath('replaced-history.png') });
  const replay = await page.evaluate(async () => {
    const url = '/dist/openalgo-charts.mjs';
    const { ReplayController } = await import(url) as typeof Charts;
    const { chart, series, indicator, context } = window.__lifecycleChart;
    const controller = new ReplayController(chart, { series, startIndex: 0 });
    const capture = () => { indicator.values(); return { ...context()!.barState, execution: context()!.execution }; };
    const first = capture();
    controller.step();
    const next = capture();
    controller.stepBack();
    const backward = capture();
    controller.stop();
    return { first, next, backward, restored: capture() };
  });
  for (const frame of [replay.first, replay.next, replay.backward]) {
    expect(frame).toMatchObject({ isRealtime: false, isConfirmed: true, execution: { provenance: 'replay' } });
  }
  expect(replay.restored).toMatchObject({ isRealtime: false, isConfirmed: true, execution: { provenance: 'history' } });
  expect(errors).toEqual([]);
});
