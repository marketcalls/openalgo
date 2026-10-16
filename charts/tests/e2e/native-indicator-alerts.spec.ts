import { test, expect, type Page } from '@playwright/test';
import type { Chart, IndicatorAlertPayload, IndicatorApi, SeriesApi } from '../../src/index';
import type * as Charts from '../../src/index';

type AlertEvent = Pick<IndicatorAlertPayload, 'alertId' | 'time' | 'index' | 'instanceId'>;
type Control = { clock: number | null; refresh?: () => void };
declare global {
  interface Window {
    __indicatorAlerts: { chart: Chart; study: IndicatorApi; source: SeriesApi; plot: SeriesApi;
      events: AlertEvent[]; control: Control };
    __otherAlertChart: { chart: Chart; source: SeriesApi; events: string[]; clock: number };
  }
}
const START = 1700000040;

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function loadExample(page: Page) {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const response = await page.request.get('/website/pages/examples.mdx');
  expect(response.ok()).toBe(true);
  const code = (await response.text()).split('## Indicator alerts on live updates')[1].split('code={`')[1].split('`} />')[0];
  await page.setViewportSize({ width: 960, height: 620 });
  await page.route('**/native-indicator-alerts.html', route => route.fulfill({ contentType: 'text/html', body:
    '<!doctype html><html><head><style>html,body{margin:0;background:#101010}#example{width:960px;height:600px}</style></head><body><div id="example"></div></body></html>' }));
  await page.goto('/native-indicator-alerts.html');
  await page.evaluate(async sourceCode => {
    const url = '/dist/openalgo-charts.all.mjs', lib = await import(url) as typeof Charts;
    const control: Control = { clock: null };
    const instrumented = { ...lib,
      createChart: (host: HTMLElement, options: Charts.ChartOptions) => lib.createChart(host, {
        ...options, theme: lib.darkTheme, animZoom: false, timeNavigator: false,
        axisChrome: { ...options.axisChrome, clock: () => control.clock ?? options.axisChrome!.clock!() },
      }),
      registerIndicator: (descriptor: Charts.IndicatorDescriptor) => lib.registerIndicator({ ...descriptor,
        attach: context => { control.refresh = () => context.requestRecompute(); },
      }),
    };
    const chart = new Function('el', 'lib', sourceCode)(document.getElementById('example'), instrumented) as Chart;
    const study = chart.indicators()[0], events: AlertEvent[] = [];
    chart.on('indicator:alert', payload => {
      const { alertId, time, index, instanceId } = payload as IndicatorAlertPayload;
      events.push({ alertId, time, index, instanceId });
    });
    window.__indicatorAlerts = { chart, study, source: chart.primarySeries()!, plot: study.series('value')!, events, control };
  }, code);
  await paint(page);
  return errors;
}

async function act(page: Page, label: string) {
  await page.getByRole('button', { name: label, exact: true }).click();
  await paint(page);
}

async function eventSequence(page: Page) {
  return page.evaluate(start => window.__indicatorAlerts.events.map(event =>
    `${event.alertId}:${(event.time - start) / 60}`), START);
}

async function rendered(page: Page) {
  return page.evaluate(() => {
    const { chart, study, source, plot } = window.__indicatorAlerts;
    const values = study.values().value, index = values.length - 1, value = values[index];
    const canvas = chart.panes()[study.paneIndex].base.element;
    const ratio = canvas.width / canvas.getBoundingClientRect().width;
    const x = chart.timeScale.indexToX(index), y = plot.priceScale().priceToY(value!);
    const pixels = canvas.getContext('2d')!.getImageData(Math.round((x - 5) * ratio),
      Math.round((y - 5) * ratio), Math.round(10 * ratio), Math.round(10 * ratio)).data;
    let ink = 0;
    for (let i = 0; i < pixels.length; i += 4) if (pixels[i] === 79 && pixels[i + 1] === 140 && pixels[i + 2] === 255) ink++;
    return { value, ink, time: source.getData()[index].time, samePlot: study.series('value') === plot };
  });
}

test('runnable alert example distinguishes live policies and preserves one-time delivery through reset and replay', async ({ page }, info) => {
  const errors = await loadExample(page);
  const expected: string[] = [];
  expect(await eventSequence(page)).toEqual(expected);
  expect(await rendered(page)).toMatchObject({ value: 100, time: START + 660, samePlot: true });
  await act(page, 'Below threshold');
  expect(await eventSequence(page)).toEqual(expected);
  await act(page, 'Cross threshold');
  expected.push('everyUpdate:11', 'oncePerBar:11', 'once:11');
  expect(await eventSequence(page)).toEqual(expected);
  expect(await rendered(page)).toMatchObject({ value: 110, time: START + 660, samePlot: true });
  expect((await rendered(page)).ink).toBeGreaterThan(15);
  await page.screenshot({ path: info.outputPath('alerts-first-match.png') });

  await act(page, 'Repeat tick');
  expected.push('everyUpdate:11');
  expect(await eventSequence(page)).toEqual(expected);
  await act(page, 'Confirm bar');
  expected.push('everyUpdate:11', 'onBarClose:11');
  expect(await eventSequence(page)).toEqual(expected);
  await act(page, 'Repeat tick');
  expected.push('everyUpdate:11');
  expect(await eventSequence(page)).toEqual(expected);
  await page.screenshot({ path: info.outputPath('alerts-provider-close.png') });

  await act(page, 'Append bar');
  expect(await eventSequence(page)).toEqual(expected);
  await act(page, 'Cross threshold');
  expected.push('everyUpdate:12', 'oncePerBar:12');
  expect(await eventSequence(page)).toEqual(expected);
  await act(page, 'Append bar');
  expected.push('onBarClose:12');
  expect(await eventSequence(page)).toEqual(expected);
  expect(await rendered(page)).toMatchObject({ value: 100, time: START + 780, samePlot: true });
  await page.screenshot({ path: info.outputPath('alerts-append-close.png') });

  await act(page, 'Reset history');
  expect(await eventSequence(page)).toEqual(expected);
  await act(page, 'Cross threshold');
  expected.push('everyUpdate:11', 'oncePerBar:11');
  expect(await eventSequence(page)).toEqual(expected);
  await act(page, 'Toggle replay');
  expect(await eventSequence(page)).toEqual(expected);
  expect(await rendered(page)).toMatchObject({ value: 110, time: START + 300, samePlot: true });
  expect((await rendered(page)).ink).toBeGreaterThan(15);
  await expect(page.getByRole('status')).toContainText('Replay');
  await expect(page.getByRole('button', { name: 'Cross threshold', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Cross threshold', exact: true })).toHaveCSS('opacity', '0.45');
  await expect(page.getByRole('button', { name: 'Cross threshold', exact: true })).toHaveCSS('cursor', 'not-allowed');
  await page.screenshot({ path: info.outputPath('alerts-replay-silent.png') });
  await act(page, 'Toggle replay');
  expect(await eventSequence(page)).toEqual(expected);
  await expect(page.getByRole('button', { name: 'Cross threshold', exact: true })).toHaveCSS('opacity', '1');
  await expect(page.getByRole('button', { name: 'Cross threshold', exact: true })).toHaveCSS('cursor', 'pointer');
  await act(page, 'Append bar');
  expected.push('onBarClose:11');
  expect(await eventSequence(page)).toEqual(expected);
  await act(page, 'Cross threshold');
  expected.push('everyUpdate:12', 'oncePerBar:12');
  expect(await eventSequence(page)).toEqual(expected);
  expect((await rendered(page)).ink).toBeGreaterThan(15);
  await page.screenshot({ path: info.outputPath('alerts-restored-live.png') });
  await expect(page.getByRole('log')).toHaveText(expected.map(event => event.replace(':', ' @ bar ')).join('\n'));
  expect(await page.evaluate(() => window.__indicatorAlerts.events.every(event => event.instanceId === window.__indicatorAlerts.study.id))).toBe(true);
  expect(errors).toEqual([]);
});

test('observed batching, asynchronous refresh and chart clock use separate alert checkpoints', async ({ page }, info) => {
  const errors = await loadExample(page);
  await page.evaluate(() => {
    const { source } = window.__indicatorAlerts;
    const time = source.getData().slice(-1)[0].time;
    source.update({ time, value: 110 }, { confirmation: 'forming' });
    source.update({ time, value: 100 }, { confirmation: 'forming' });
    source.update({ time, value: 110 }, { confirmation: 'forming' });
  });
  await paint(page);
  const expected = ['everyUpdate:11', 'oncePerBar:11', 'once:11'];
  expect(await eventSequence(page)).toEqual(expected);
  await page.evaluate(() => {
    const { study, chart, control } = window.__indicatorAlerts;
    study.setSettings({ 'value:width': 4 });
    control.clock = 1700000040 + 720;
    chart.invalidate(mask => mask.invalidateGlobal(3));
  });
  await paint(page);
  await page.evaluate(async () => { await Promise.resolve(); window.__indicatorAlerts.control.refresh!(); });
  await paint(page);
  expect(await eventSequence(page)).toEqual(expected);
  await act(page, 'Repeat tick');
  expected.push('everyUpdate:11');
  expect(await eventSequence(page)).toEqual(expected);
  // The explicit forming override wins even though the chart clock is past close.
  await page.evaluate(() => { window.__indicatorAlerts.control.clock = null; });
  await act(page, 'Close by clock');
  expected.push('everyUpdate:11', 'onBarClose:11');
  expect(await eventSequence(page)).toEqual(expected);
  await act(page, 'Close by clock');
  expected.push('everyUpdate:11');
  expect(await eventSequence(page)).toEqual(expected);
  expect((await rendered(page)).ink).toBeGreaterThan(15);
  await page.screenshot({ path: info.outputPath('alerts-clock-close.png') });

  await act(page, 'Append bar');
  await act(page, 'Close by clock');
  expect(await eventSequence(page)).toEqual(expected);
  await act(page, 'Cross threshold');
  expected.push('everyUpdate:12', 'oncePerBar:12');
  await act(page, 'Confirm bar');
  expected.push('everyUpdate:12');
  expect(await eventSequence(page)).toEqual(expected);
  await page.screenshot({ path: info.outputPath('alerts-false-close-final.png') });

  await page.evaluate(() => {
    const state = window.__indicatorAlerts;
    state.study.remove();
    state.study = state.chart.addIndicator('demo-indicator-alert-policies');
    state.plot = state.study.series('value')!;
  });
  await paint(page);
  expect(await eventSequence(page)).toEqual(expected);
  await act(page, 'Append bar');
  await act(page, 'Cross threshold');
  expected.push('everyUpdate:13', 'oncePerBar:13', 'once:13');
  expect(await eventSequence(page)).toEqual(expected);
  expect(errors).toEqual([]);
});

test('count-bar append closes matching observations and another chart keeps its own clock', async ({ page }, info) => {
  const errors = await loadExample(page);
  await page.evaluate(async start => {
    const url = '/dist/openalgo-charts.all.mjs', lib = await import(url) as typeof Charts;
    const state = window.__indicatorAlerts;
    state.chart.setDataContext({ symbol: 'COUNT', interval: '100t' });
    state.control.clock = start + 100000;
    state.source.setData([{ time: start, value: 100 }, { time: start + 60, value: 100 }]);
    state.chart.fitContent();
    const host = document.createElement('div');
    host.style.cssText = 'height:220px;width:960px';
    document.body.appendChild(host);
    const other = window.__otherAlertChart = { chart: null as unknown as Chart, source: null as unknown as SeriesApi,
      events: [] as string[], clock: start + 119 };
    other.chart = lib.createChart(host, { theme: lib.darkTheme, branding: false, timeNavigator: false, axisChrome: { clock: () => other.clock } });
    other.chart.setDataContext({ symbol: 'CLOCK', interval: '1m' });
    other.source = other.chart.addSeries('line');
    other.source.setData([{ time: start, value: 100 }, { time: start + 60, value: 100 }]);
    other.chart.addIndicator('demo-indicator-alert-policies');
    other.chart.on('indicator:alert', event => other.events.push((event as IndicatorAlertPayload).alertId));
    other.chart.fitContent();
  }, START);
  await paint(page);
  await page.evaluate(start => {
    window.__indicatorAlerts.source.update({ time: start + 60, value: 110 }, { confirmation: 'auto' });
    window.__otherAlertChart.source.update({ time: start + 60, value: 110 }, { confirmation: 'auto' });
  }, START);
  await paint(page);
  const expected = ['everyUpdate:1', 'oncePerBar:1', 'once:1'];
  expect(await eventSequence(page)).toEqual(expected);
  expect(await page.evaluate(() => window.__otherAlertChart.events)).toEqual(['everyUpdate', 'oncePerBar', 'once']);
  await page.evaluate(start => {
    const other = window.__otherAlertChart;
    other.clock = start + 120;
    other.source.update(other.source.getData().slice(-1)[0]);
    window.__indicatorAlerts.source.update({ time: start + 120, value: 100 }, { confirmation: 'forming' });
    window.__indicatorAlerts.chart.fitContent();
  }, START);
  await paint(page);
  expected.push('onBarClose:1');
  expect(await eventSequence(page)).toEqual(expected);
  expect(await page.evaluate(() => window.__otherAlertChart.events)).toEqual(['everyUpdate', 'oncePerBar', 'once', 'everyUpdate', 'onBarClose']);
  expect((await rendered(page)).ink).toBeGreaterThan(15);
  await page.setViewportSize({ width: 960, height: 850 });
  await page.screenshot({ path: info.outputPath('alerts-independent-clocks-count-bars.png') });
  expect(errors).toEqual([]);
});
