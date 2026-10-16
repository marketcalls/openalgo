import { test, expect, type Page } from '@playwright/test';
import type { Chart, IndicatorStudySource, SeriesApi } from '../../src/index';
import type * as Charts from '../../src/index';

declare global {
  interface Window {
    __studyDependencies: { chart: Chart; source: SeriesApi; producerId: string; consumerId: string };
  }
}

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function loadExample(page: Page) {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const response = await page.request.get('/website/pages/examples.mdx');
  expect(response.ok()).toBe(true);
  const markdown = await response.text();
  const code = markdown.split('## Study outputs as moving-average inputs')[1].split('code={`')[1].split('`} />')[0];
  await page.setViewportSize({ width: 960, height: 550 });
  await page.route('**/study-dependencies.html', route => route.fulfill({ contentType: 'text/html', body:
    '<!doctype html><html><head><style>html,body{margin:0;background:#101010}#example{width:960px;height:540px}</style></head><body><div id="example"></div></body></html>' }));
  await page.goto('/study-dependencies.html');
  await page.evaluate(async sourceCode => {
    const url = '/dist/openalgo-charts.all.mjs', lib = await import(url) as typeof Charts;
    const themed = { ...lib, createChart: (host: HTMLElement, options: Charts.ChartOptions) =>
      lib.createChart(host, { ...options, theme: lib.darkTheme, animZoom: false, timeNavigator: false }) };
    const chart = new Function('el', 'lib', sourceCode)(document.getElementById('example'), themed) as Chart;
    const [producer, consumer] = chart.indicators();
    window.__studyDependencies = { chart, source: chart.primarySeries()!, producerId: producer.id, consumerId: consumer.id };
  }, code);
  await paint(page);
  return errors;
}

async function inspect(page: Page, samplePrice?: number) {
  return page.evaluate(priceToSample => {
    const { chart, source, producerId, consumerId } = window.__studyDependencies;
    const display = chart.indicators(), consumer = display.find(item => item.id === consumerId)!;
    const producer = display.find(item => item.id !== consumerId);
    const values = consumer.values().ma, price = priceToSample ?? values[3];
    let ink = 0;
    if (typeof price === 'number') {
      const canvas = chart.panes()[consumer.paneIndex].base.element, context = canvas.getContext('2d')!;
      const ratio = canvas.width / canvas.getBoundingClientRect().width;
      const x = chart.timeScale.indexToX(3), y = consumer.series('ma')!.priceScale().priceToY(price);
      const pixels = context.getImageData(Math.round((x - 5) * ratio), Math.round((y - 5) * ratio),
        Math.round(10 * ratio), Math.round(10 * ratio)).data;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i] === 245 && pixels[i + 1] === 166 && pixels[i + 2] === 35) ink++;
      }
    }
    const dataStatus = consumer.dataStatus();
    const message = dataStatus?.state === 'error'
      ? dataStatus.error instanceof Error ? dataStatus.error.message : String(dataStatus.error) : undefined;
    return {
      values, ink, status: dataStatus?.state ?? 'ready', message,
      reference: consumer.settings().source as IndicatorStudySource,
      producerId: producer?.id, initialProducerId: producerId, consumerId,
      producerVisible: producer?.visible(), producerPane: producer?.paneIndex,
      order: display.map(item => item.id), paneCount: chart.panes().length,
      sameSource: chart.primarySeries() === source, prices: source.getData().map(bar => bar.close),
      saved: chart.getState().indicators ?? [],
    };
  }, samplePrice);
}

async function click(page: Page, label: string) {
  await page.getByRole('button', { name: label, exact: true }).click();
  await paint(page);
}

test('the documented dependent average plots its warmup, same-time update and settings-only result', async ({ page }, info) => {
  const errors = await loadExample(page);
  let state = await inspect(page);
  expect(state).toMatchObject({ values: [null, null, 3, 5], status: 'ready', prices: [1, 3, 5, 7], sameSource: true });
  expect(state.ink).toBeGreaterThan(3);
  await expect(page.getByRole('status')).toContainText('downstream [null,null,3,5]');
  await page.screenshot({ path: info.outputPath('study-input-initial.png') });

  await click(page, 'Last close 9');
  state = await inspect(page);
  expect(state).toMatchObject({ values: [null, null, 3, 5.5], prices: [1, 3, 5, 9], sameSource: true });
  expect(state.ink).toBeGreaterThan(3);
  await page.screenshot({ path: info.outputPath('study-input-same-time.png') });

  await click(page, 'Reset prices');
  const prices = (await inspect(page)).prices;
  await click(page, 'Producer length 3');
  state = await inspect(page);
  expect(state).toMatchObject({ values: [null, null, null, 4], prices, status: 'ready' });
  expect(state.ink).toBeGreaterThan(3);
  await expect(page.getByRole('status')).toContainText('Producer: length 3');
  await page.screenshot({ path: info.outputPath('study-input-settings.png') });
  expect(errors).toEqual([]);
});

test('visibility, pane and display changes preserve dependencies through reverse-order restore', async ({ page }, info) => {
  const errors = await loadExample(page);
  const initial = await inspect(page);
  expect(initial.values).toEqual([null, null, 3, 5]);

  await click(page, 'Toggle producer');
  expect(await inspect(page)).toMatchObject({ values: initial.values, producerVisible: false });
  await click(page, 'Move producer');
  let state = await inspect(page);
  expect(state).toMatchObject({ values: initial.values, producerPane: 1, paneCount: 2, producerVisible: false });
  expect(state.ink).toBeGreaterThan(3);
  await page.screenshot({ path: info.outputPath('study-input-hidden-moved.png') });
  await click(page, 'Move producer');
  await click(page, 'Toggle producer');
  await click(page, 'Swap order');
  state = await inspect(page);
  expect(state.order).toEqual([state.consumerId, state.producerId]);
  expect(state.values).toEqual(initial.values);

  await click(page, 'Restore reversed save');
  state = await inspect(page);
  expect(state).toMatchObject({ values: initial.values, sameSource: true, producerId: initial.producerId, paneCount: 1 });
  expect(state.order).toEqual([state.consumerId, state.producerId]);
  const savedConsumer = state.saved.find(item => item.instanceId === state.consumerId)!;
  expect(savedConsumer.studyInputs).toEqual(['source']);
  expect(savedConsumer.settings.source).toEqual(state.reference);
  expect(state.reference.instanceId).toBe(initial.producerId);
  expect(state.ink).toBeGreaterThan(3);
  await page.screenshot({ path: info.outputPath('study-input-restored.png') });
  await click(page, 'Producer length 3');
  expect((await inspect(page)).values).toEqual([null, null, null, 4]);
  expect(errors).toEqual([]);
});

test('removal clears plotted input until the replacement is explicitly selected', async ({ page }, info) => {
  const errors = await loadExample(page);
  const initial = await inspect(page);
  expect(initial.values).toEqual([null, null, 3, 5]);
  await click(page, 'Remove producer');
  let state = await inspect(page, 5);
  expect(state).toMatchObject({ values: [null, null, null, null], status: 'error', ink: 0 });
  expect(state.message).toMatch(/unavailable/i);
  expect(state.reference.instanceId).toBe(initial.producerId);
  await page.screenshot({ path: info.outputPath('study-input-removed.png') });

  await click(page, 'Add replacement');
  state = await inspect(page, 5);
  expect(state.producerId).not.toBe(initial.producerId);
  expect(state).toMatchObject({ values: [null, null, null, null], status: 'error', ink: 0 });
  expect(state.reference.instanceId).toBe(initial.producerId);
  await click(page, 'Rebind source');
  state = await inspect(page);
  expect(state).toMatchObject({ values: [null, null, 3, 5], status: 'ready', sameSource: true });
  expect(state.reference.instanceId).toBe(state.producerId);
  expect(state.ink).toBeGreaterThan(3);
  await page.screenshot({ path: info.outputPath('study-input-rebound.png') });
  expect(errors).toEqual([]);
});
