import { expect, test, type Page } from '@playwright/test';
import type { Chart, IndicatorApi } from '../../src/index';
import type * as Charts from '../../src/index';
import type * as Widgets from '../../src/widget/index';

type Surface = 'widget' | 'demo';
type SourceUi = { chart: Chart; producer: IndicatorApi; consumer: IndicatorApi; open(id: string): void };
type DemoHost = Window & { __oac: { app: { chart: Chart; loading: boolean } } };
declare global { interface Window { __studySourceUi: SourceUi } }

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function mount(page: Page, surface: Surface) {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1200, height: 850 });
  if (surface === 'widget') {
    await page.route('**/native-study-source-ui.html', route => route.fulfill({ contentType: 'text/html', body:
      '<!doctype html><html><head><style>html,body{margin:0;background:#111318}#host{height:800px}</style></head><body><div id="host"></div></body></html>' }));
    await page.goto('/native-study-source-ui.html');
  } else {
    const base = `http://127.0.0.1:${process.env.OAC_E2E_DEMO_PORT || '8124'}`;
    const response = await page.request.get(`${base}/api/history?symbol=AAPL&interval=1d&period=1mo`);
    expect(response.ok()).toBe(true);
    await page.goto(`${base}/examples/yfinance/index.html?test=1`);
    await page.waitForFunction(() => Boolean((window as DemoHost).__oac?.app.chart)
      && !(window as DemoHost).__oac.app.loading);
  }
  await page.evaluate(async kind => {
    const baseUrl = '/dist/openalgo-charts.mjs', widgetUrl = '/dist/openalgo-charts.widget.mjs';
    const lib = await import(baseUrl) as typeof Charts;
    const widgets = await import(widgetUrl) as typeof Widgets;
    let chart: Chart, open: SourceUi['open'];
    if (kind === 'widget') {
      const widget = widgets.createWidget(document.getElementById('host')!, {
        persist: false, rail: false, symbol: 'SOURCE', interval: '1m',
        branding: false, animZoom: false, animAutoscale: false, timeNavigator: false,
      });
      chart = widget.chart;
      open = id => { widgets.mountIndicatorSettings(widget.context, undefined, { instanceId: id }); };
    } else {
      chart = (window as DemoHost).__oac.app.chart;
      const path = '/examples/yfinance/src/indicators.js';
      const settings = await import(path) as { openSettings(id: string): void };
      open = id => settings.openSettings(id);
    }
    for (const study of [...chart.indicators()]) chart.removeIndicator(study.id);
    lib.registerIndicator({ id: 'browser-source-choice', name: 'Source choice', placement: 'onchart',
      inputs: [
        { key: 'source', type: 'source', label: 'Source', default: 'close', allowStudyOutputs: true },
        { key: 'factor', type: 'number', label: 'Factor', default: 1 },
        { key: 'color', type: 'color', label: 'Color', default: '#3366ff' },
      ],
      plots: [{ key: 'value', type: 'line', title: 'Signal', colorKey: 'color', style: { lineWidth: 4 } }],
      calc: (bars, settings, _store, context) => ({ value:
        lib.sourceValues(bars, settings.source as Charts.IndicatorStudySource, context)
          .map(value => value === null || !Number.isFinite(value) ? null : value * Number(settings.factor)),
      }),
    });
    chart.primarySeries()!.setData(Array.from({ length: 32 }, (_, index) => ({
      time: 1700000040 + index * 60, open: 100 + index, high: 102 + index, low: 98 + index, close: 100 + index,
    })));
    const producer = chart.addIndicator('browser-source-choice', { factor: 2, color: '#ff9933' });
    const consumer = chart.addIndicator('browser-source-choice', { factor: 3, color: '#3366ff' });
    producer.setVisible(false);
    chart.setVisibleLogicalRange({ from: -2, to: 34 });
    window.__studySourceUi = { chart, producer, consumer, open };
    open(consumer.id);
  }, surface);
  await paint(page);
  return errors;
}

function controls(page: Page, surface: Surface) {
  const dialog = page.locator(surface === 'widget' ? '.oac-indset' : '#setmodal');
  return { dialog, source: surface === 'widget' ? dialog.getByLabel('Source', { exact: true }) : dialog.locator('select[data-key="source"]'),
    accept: surface === 'widget' ? dialog.getByRole('button', { name: 'OK', exact: true }) : dialog.locator('#set-ok'),
    cancel: surface === 'widget' ? dialog.getByRole('button', { name: 'Cancel', exact: true }) : dialog.locator('#set-x') };
}

async function lastValue(page: Page) {
  return page.evaluate(() => {
    const values = window.__studySourceUi.consumer.values().value;
    return values[values.length - 1];
  });
}

async function blueInk(page: Page) {
  await paint(page);
  return page.evaluate(() => {
    const { chart, consumer } = window.__studySourceUi;
    const canvas = chart.panes()[consumer.paneIndex].base.element;
    const pixels = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
    let count = 0;
    for (let i = 0; i < pixels.length; i += 4) if (pixels[i] === 51 && pixels[i + 1] === 102 && pixels[i + 2] === 255) count++;
    return count;
  });
}

async function legendText(page: Page) {
  return page.evaluate(() => {
    const svg = new DOMParser().parseFromString(window.__studySourceUi.chart.exportSVG(), 'image/svg+xml');
    return [...svg.querySelectorAll('text')].map(node => node.textContent ?? '');
  });
}

for (const surface of ['widget', 'demo'] as const) {
  test(`${surface} source controls select real outputs, reject cycles and retain unavailable references`, async ({ page }, info) => {
    const errors = await mount(page, surface);
    let { dialog, source, accept, cancel } = controls(page, surface);
    const producerId = await page.evaluate(() => window.__studySourceUi.producer.id);
    // Numbered by their place among their name, never named by an internal id.
    const producerLabel = 'Source choice (1) / Signal';
    const consumerLabel = 'Source choice (2) / Signal';
    await expect(source.locator('option', { hasText: producerLabel })).toHaveCount(1);
    await expect(source.locator('option', { hasText: consumerLabel })).toHaveCount(0);
    expect(await lastValue(page)).toBe(393);
    const token = await source.locator('option', { hasText: producerLabel }).getAttribute('value');
    expect(token).not.toContain(producerId);
    await source.selectOption({ label: producerLabel });
    if (surface === 'widget') await expect.poll(() => lastValue(page)).toBe(786);
    else expect(await lastValue(page)).toBe(393);
    await page.screenshot({ path: info.outputPath(`${surface}-selected-source.png`) });
    await cancel.click();
    await expect(dialog).toBeHidden();
    await expect.poll(() => lastValue(page)).toBe(393);
    expect(await page.evaluate(() => window.__studySourceUi.consumer.settings().source)).toBe('close');

    await page.evaluate(() => window.__studySourceUi.open(window.__studySourceUi.consumer.id));
    ({ dialog, source, accept, cancel } = controls(page, surface));
    await source.selectOption({ label: producerLabel });
    await accept.click();
    await expect.poll(() => lastValue(page)).toBe(786);
    expect(await page.evaluate(() => window.__studySourceUi.consumer.settings().source)).toEqual({
      kind: 'indicator', instanceId: producerId, plotKey: 'value',
    });
    const dependentLegend = await legendText(page);
    expect(dependentLegend.join(' ')).not.toContain('[object Object]');
    expect(dependentLegend.some(text => text.includes(producerId) && text.includes('value'))).toBe(true);
    expect(await blueInk(page)).toBeGreaterThan(100);
    await page.screenshot({ path: info.outputPath(`${surface}-dependent-output.png`) });

    await page.evaluate(() => window.__studySourceUi.open(window.__studySourceUi.producer.id));
    ({ dialog, source, accept, cancel } = controls(page, surface));
    await source.selectOption({ label: consumerLabel });
    if (surface === 'demo') await accept.click();
    await expect(dialog).toBeVisible();
    expect(await page.evaluate(() => window.__studySourceUi.producer.settings().source)).toBe('close');
    expect(await lastValue(page)).toBe(786);
    const errorsUi = page.locator(surface === 'widget' ? '.oac-toast' : '#toasts');
    await expect(errorsUi).toContainText(/cycle/i);
    if (surface === 'widget') await expect(source).toHaveValue('close');
    else {
      await expect(source.locator('option:checked')).toHaveText(consumerLabel);
      await dialog.locator('.set-tab[data-tab="style"]').click();
      await expect(source).toBeVisible();
      await expect(source.locator('option:checked')).toHaveText(consumerLabel);
    }
    await page.screenshot({ path: info.outputPath(`${surface}-cycle-rejected.png`) });
    await cancel.click();
    await expect(dialog).toBeHidden();

    await page.evaluate(() => {
      const state = window.__studySourceUi;
      state.open(state.consumer.id);
      state.chart.removeIndicator(state.producer.id);
    });
    ({ dialog, source, cancel } = controls(page, surface));
    await expect(source.locator('option:checked')).toHaveText(`Unavailable study output: ${producerId} / value`);
    expect(await page.evaluate(() => window.__studySourceUi.consumer.settings().source)).toEqual({
      kind: 'indicator', instanceId: producerId, plotKey: 'value',
    });
    expect(await page.evaluate(() => window.__studySourceUi.consumer.values().value.every(value => value === null))).toBe(true);
    const unavailableLegend = await legendText(page);
    expect(unavailableLegend.join(' ')).not.toContain('[object Object]');
    expect(unavailableLegend.some(text => text.includes(producerId) && text.includes('value'))).toBe(true);
    await page.screenshot({ path: info.outputPath(`${surface}-unavailable-source.png`) });
    if (surface === 'widget') await source.press('Escape'); else await cancel.click();
    await expect(dialog).toBeHidden();
    expect(errors).toEqual([]);
  });
}
