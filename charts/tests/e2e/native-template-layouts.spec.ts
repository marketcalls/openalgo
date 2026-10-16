import { test, expect, type Page } from '@playwright/test';
import type { Chart, SeriesApi } from '../../src/index';
import type * as Charts from '../../src/all';

declare global {
  interface Window {
    __templateExample: Chart;
    __templateSource: SeriesApi;
  }
}

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function snapshot(page: Page) {
  return page.evaluate(() => {
    const chart = window.__templateExample;
    const main = chart.panes()[0];
    const pixels = main.base.ctx.getImageData(0, 0, main.base.element.width, main.base.element.height).data;
    let orange = 0;
    for (let index = 0; index < pixels.length; index += 4) {
      if (pixels[index] === 232 && pixels[index + 1] === 162 && pixels[index + 2] === 58) orange++;
    }
    return {
      sameSource: chart.primarySeries() === window.__templateSource,
      bars: chart.primarySeries()!.getData(),
      weights: chart.getState().panes.map(pane => pane.weight),
      left: chart.priceAxisLayout(0).filter(axis => axis.side === 'left').map(axis => axis.scaleId),
      studies: chart.indicators().map(study => ({
        id: study.id, pane: study.paneIndex, values: study.values(),
        metric: study.plotPriceScaleId('metric'),
        auto: study.series('metric')?.priceScale().autoScale,
        range: study.series('metric')?.priceScale().priceRange(),
        inverted: study.series('signal')?.priceScale().options.inverted,
        followsPrimary: study.series('price') ? study.series('price')!.priceScale() === chart.primarySeries()!.priceScale() : null,
      })),
      orange,
    };
  });
}

for (const width of [900, 390]) test(`documented template controls retain source data and scale relationships at ${width}px`, async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const response = await page.request.get('/website/pages/examples.mdx');
  expect(response.ok()).toBe(true);
  let code = (await response.text()).split('## Copy study layouts with templates')[1].split('code={`')[1].split('`} />')[0];
  // The site's template splices the shared bar generator in; do the same here.
  const market = await (await page.request.get('/website/components/synthetic-market.ts')).text();
  code = code.replace('${STOCK_BARS_SOURCE}', market.split('STOCK_BARS_SOURCE = `')[1].split('`;')[0]);
  await page.setViewportSize({ width, height: 620 });
  await page.route('**/template-example.html', route => route.fulfill({ contentType: 'text/html', body:
    `<!doctype html><html><head><style>html,body{margin:0;background:#101010}#example{width:${width}px;height:600px}</style></head><body><div id="example"></div></body></html>` }));
  await page.goto('/template-example.html');
  await page.evaluate(async source => {
    const bundle = '/dist/openalgo-charts.all.mjs';
    const lib = await import(bundle) as typeof Charts;
    window.__templateExample = new Function('el', 'lib', source)(document.getElementById('example'),
      { ...lib, createChart: (host: HTMLElement, options: object) => lib.createChart(host,
        { theme: lib.darkTheme, pixelRatio: () => 1, animZoom: false, ...options }) }) as Chart;
    window.__templateSource = window.__templateExample.primarySeries()!;
  }, code);
  await paint(page);
  const initial = await snapshot(page);
  expect(initial.studies).toHaveLength(2);
  expect(initial.studies[0]).toMatchObject({ auto: false, range: { min: 0, max: 100 }, followsPrimary: true });
  expect(initial.studies[1].inverted).toBe(true);
  expect(initial.orange).toBeGreaterThan(50);
  for (const [label, shared, automatic] of [
    ['Copy, automatic view', false, true],
    ['Copy, saved view', false, false],
    ['Share scales', true, false],
  ] as const) {
    await page.getByRole('button', { name: label, exact: true }).click();
    await paint(page);
    const state = await snapshot(page);
    expect(state.sameSource).toBe(true);
    expect(state.bars).toEqual(initial.bars);
    expect(state.studies).toHaveLength(4);
    expect(state.weights).toEqual([initial.weights[0], 0.55, 0.55]);
    expect(new Set(state.studies.map(study => study.id)).size).toBe(4);
    expect(state.studies[0].id).toBe(initial.studies[0].id);
    expect(state.studies[2].values).toEqual(initial.studies[0].values);
    expect(state.studies[3].values).toEqual(initial.studies[1].values);
    expect(state.studies[3]).toMatchObject({ pane: 2, inverted: true });
    expect(state.studies[2].followsPrimary).toBe(true);
    expect(state.studies[2].auto).toBe(automatic);
    expect(state.studies[2].metric === state.studies[0].metric).toBe(shared);
    expect(state.left).toHaveLength(shared ? 1 : 2);
    if (automatic) {
      expect(state.studies[2].range!.min).toBeGreaterThan(0);
      expect(state.studies[2].range!.max).toBeLessThan(100);
    } else expect(state.studies[2].range).toEqual({ min: 0, max: 100 });
    expect(state.orange).toBeGreaterThan(50);
    await expect(page.getByRole('status')).toContainText(shared ? 'Metric scale: shared' : 'Metric scale: independent');
    for (const button of await page.getByRole('button').all()) {
      const bounds = await button.boundingBox();
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    }
    await page.locator('#example').screenshot({ path: info.outputPath(label.toLowerCase().replace(/[^a-z]+/g, '-') + '.png') });
  }
  await page.getByRole('button', { name: 'Reset studies', exact: true }).click();
  await paint(page);
  expect(await snapshot(page)).toMatchObject({ sameSource: true, bars: initial.bars, weights: initial.weights, studies: initial.studies });
  expect(errors).toEqual([]);
});

test('template restoration keeps panes that render levels without plot series', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 900, height: 640 });
  await page.route('**/template-levels.html', route => route.fulfill({ contentType: 'text/html', body:
    '<!doctype html><html><body style="margin:0"><div id="example" style="height:630px;width:900px"></div></body></html>' }));
  await page.goto('/template-levels.html');
  await page.evaluate(async () => {
    const bundle = '/dist/openalgo-charts.all.mjs';
    const lib = await import(bundle) as typeof Charts;
    lib.registerIndicator({ id: 'browser-template-levels', name: 'Reference levels', placement: 'pane', inputs: [], plots: [],
      levels: () => [{ price: 50, color: '#33ccff', title: 'Middle' }], range: () => ({ min: 0, max: 100 }), calc: () => ({}),
    });
    const chart = lib.createChart(document.getElementById('example')!, {
      branding: false, theme: lib.darkTheme, animZoom: false, animAutoscale: false, pixelRatio: () => 1,
    });
    window.__templateExample = chart;
    chart.addSeries('line').setData(Array.from({ length: 32 }, (_, index) => ({ time: 1700000000 + index * 60, value: 100 + index })));
    const study = chart.addIndicator('browser-template-levels', {}, { priceScaleId: 'left' });
    chart.setPaneWeight(study.paneIndex, 0.5);
    chart.fitContent();
    const plan = lib.planIndicatorTemplateState(chart, lib.captureIndicatorTemplate(chart), 'append');
    if (!chart.restoreState({ ...chart.getState(), ...plan }, plan.restoreOptions).applied) throw new Error('Level template restore failed');
  });
  await paint(page);
  const rendered = await page.evaluate(() => {
    const chart = window.__templateExample;
    return { count: chart.indicators().length, ids: chart.indicators().map(study => study.id),
      panes: chart.panes().slice(1).map(pane => {
        const pixels = pane.base.ctx.getImageData(0, 0, pane.base.element.width, pane.base.element.height).data;
        let levelInk = 0;
        for (let index = 0; index < pixels.length; index += 4) {
          if (pixels[index] === 51 && pixels[index + 1] === 204 && pixels[index + 2] === 255) levelInk++;
        }
        return { levelInk, range: pane.scaleFor('left').fixedRange, series: pane.series().length };
      }) };
  });
  expect(rendered.count).toBe(2);
  expect(new Set(rendered.ids).size).toBe(2);
  expect(rendered.panes).toHaveLength(2);
  for (const pane of rendered.panes) {
    expect(pane).toMatchObject({ range: { min: 0, max: 100 }, series: 0 });
    expect(pane.levelInk).toBeGreaterThan(100);
  }
  await page.locator('#example').screenshot({ path: info.outputPath('template-level-only-panes.png') });
  expect(errors).toEqual([]);
});

test('templates retain destination formatters while independent copies install their declared units', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 900, height: 520 });
  await page.route('**/template-formats.html', route => route.fulfill({ contentType: 'text/html', body:
    '<!doctype html><html><body style="margin:0"><div id="example" style="height:500px;width:900px"></div></body></html>' }));
  await page.goto('/template-formats.html');
  for (const policy of ['copy', 'share'] as const) {
    const result = await page.evaluate(async scalePolicy => {
      const bundle = '/dist/openalgo-charts.all.mjs';
      const lib = await import(bundle) as typeof Charts;
      window.__templateExample?.destroy();
      lib.registerIndicator({ id: 'browser-template-formats', name: 'Distinct formats', placement: 'onchart', inputs: [],
        plots: [
          { key: 'metric', title: 'Metric', type: 'line', priceScaleId: 'overlay:metric',
            priceFormat: { type: 'percent', precision: 2 }, style: { color: '#33ccff', lineWidth: 2 } },
          { key: 'price', title: 'Price guide', type: 'line', priceFormat: { type: 'volume' }, style: { color: '#b16bdf' } },
        ],
        calc: bars => ({ metric: bars.map(() => 1.25), price: bars.map(bar => bar.close) }),
      });
      const chart = lib.createChart(document.getElementById('example')!, {
        branding: false, theme: lib.darkTheme, animZoom: false, animAutoscale: false, pixelRatio: () => 1, priceAxisWidth: 90,
      });
      window.__templateExample = chart;
      const primary = chart.addSeries('line');
      primary.setData(Array.from({ length: 32 }, (_, index) => ({ time: 1700000000 + index * 60, value: 100 + index / 4 })));
      const original = chart.addIndicator('browser-template-formats');
      chart.setPriceAxisPlacement(0, 'overlay:metric', 'left');
      const template = lib.captureIndicatorTemplate(chart);
      primary.priceScale().setPriceFormatter(value => `Price ${value.toFixed(3)}`);
      original.series('metric')!.priceScale().setPriceFormatter(value => `Units ${value.toFixed(1)}`);
      chart.fitContent();
      const plan = lib.planIndicatorTemplateState(chart, template, 'append', { scalePolicy });
      if (!chart.restoreState({ ...chart.getState(), ...plan }, plan.restoreOptions).applied) throw new Error('Formatter template restore failed');
      const studies = chart.indicators();
      return { primary: primary.priceScale().format(12.3456), original: studies[0].series('metric')!.priceScale().format(1.25),
        copied: studies[1].series('metric')!.priceScale().format(1.25), sourceRetained: chart.primarySeries() === primary };
    }, policy);
    expect(result).toEqual({ primary: 'Price 12.346', original: 'Units 1.3',
      copied: policy === 'share' ? 'Units 1.3' : '1.25%', sourceRetained: true });
    await paint(page);
    await page.locator('#example').screenshot({ path: info.outputPath(`template-formats-${policy}.png`) });
  }
  expect(errors).toEqual([]);
});
