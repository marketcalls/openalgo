import { expect, test, type Page, type TestInfo } from '@playwright/test';
import type { Chart } from '../../src/index';

type Pane = 1 | 2;
type DemoWindow = Window & {
  __oac: { app: { chart: Chart; chart2: Chart | null; loading: boolean; loading2: boolean } };
};

const SAMPLE = 'Source signal sample';
const SAMPLE_ID = 'source-signal-sample';

test.use({ viewport: { width: 1440, height: 1000 } });
test.beforeEach(async ({ page, request }) => {
  const up = await request.get('/api/history?symbol=AAPL&interval=1d&period=1mo').then(response => response.ok(), () => false);
  test.skip(!up, 'the yfinance fixture server is not available');
  const bars = Array.from({ length: 48 }, (_, index) => ({
    time: 1_789_776_000 + index * 86400, open: 100, high: 130, low: 70, close: 102, volume: 2000,
  }));
  await page.route('**/api/history?**', route => route.fulfill({ json: bars }));
  await page.goto('/examples/yfinance/index.html?test=1');
  await page.waitForFunction(() => Boolean((window as unknown as DemoWindow).__oac?.app.chart)
    && !(window as unknown as DemoWindow).__oac.app.loading);
  await expect(page.locator(`#indpick option[value="${SAMPLE_ID}"]`)).toHaveCount(1);
});

async function paint(page: Page): Promise<void> {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function addSample(page: Page, pane: Pane): Promise<string> {
  await page.locator(pane === 1 ? '#chart' : '#chart2').focus();
  await page.getByRole('button', { name: /^Add an indicator, / }).click();
  await expect(page.locator('.oac-pick')).toHaveCount(1);
  await page.locator(`.oac-pick__row[data-id="${SAMPLE_ID}"]`).click();
  return page.evaluate(({ pane, id }) => {
    const app = (window as unknown as DemoWindow).__oac.app;
    const studies = (pane === 1 ? app.chart : app.chart2!).indicators().filter(study => study.indicatorId === id);
    return studies[studies.length - 1].id;
  }, { pane, id: SAMPLE_ID });
}

async function split(page: Page): Promise<void> {
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => Boolean((window as unknown as DemoWindow).__oac.app.chart2?.primaryBars().length)
    && !(window as unknown as DemoWindow).__oac.app.loading2);
  await paint(page);
}

async function clickSource(page: Page, pane: Pane, row = 0): Promise<void> {
  const point = await page.evaluate(({ pane, row, name }) => {
    const app = (window as unknown as DemoWindow).__oac.app;
    const chart = pane === 1 ? app.chart : app.chart2!;
    const host = document.querySelector(pane === 1 ? '#chart' : '#chart2')!;
    const box = host.getBoundingClientRect();
    const svg = new DOMParser().parseFromString(chart.exportSVG(), 'image/svg+xml');
    const texts = [...svg.querySelectorAll('text')];
    const title = texts.filter(text => text.textContent === name)[row];
    if (!title) throw new Error('The sample legend has not rendered');
    const y = Number(title.getAttribute('y'));
    const start = Number(title.getAttribute('x'));
    const sameRow = texts.filter(text => Number(text.getAttribute('y')) === y
      && Number(text.getAttribute('x')) >= start && Number(text.getAttribute('x')) < box.width / 2);
    const context = document.createElement('canvas').getContext('2d')!;
    // The export identifies the visible text; real font metrics locate its canvas controls.
    let right = start;
    for (const text of sameRow) {
      context.font = `${text.getAttribute('font-weight') ?? ''} ${text.getAttribute('font-size')}px ${text.getAttribute('font-family')}`.trim();
      right += context.measureText(text.textContent ?? '').width + 6;
    }
    const size = chart.legendIconSize() ?? 16;
    return { x: box.left + right + 2 + 2 * (size + 2) + size / 2, y: box.top + y, hoverX: box.left + start + 10 };
  }, { pane, row, name: SAMPLE });
  await page.mouse.move(point.hoverX, point.y);
  await paint(page);
  await page.mouse.move(point.x, point.y);
  await page.mouse.down();
  await paint(page);
  await page.mouse.up();
  await expect(page.locator('#indsource')).toBeVisible();
}

async function readoutSettings(page: Page, pane: Pane): Promise<void> {
  await page.locator(pane === 1 ? '#chart' : '#chart2').focus();
  await page.getByRole('button', { name: 'Chart settings (or right-click the chart)', exact: true }).click();
  await page.locator('#cset-tabs').getByRole('button', { name: 'Readout', exact: true }).click();
}

async function shot(page: Page, info: TestInfo, name: string): Promise<void> {
  const path = info.outputPath(`${name}.png`);
  await page.screenshot({ path });
  await info.attach(name, { path, contentType: 'image/png' });
}

test.afterEach(async ({ page }, info) => {
  if (info.status !== info.expectedStatus) await shot(page, info, 'failure');
});

test('source clicks retain instance and chart ownership across a split', async ({ page }, info) => {
  const first = await addSample(page, 1);
  const second = await addSample(page, 1);
  await split(page);
  const other = await addSample(page, 2);
  await clickSource(page, 1, 1);
  // A study is numbered by its place among its name, never named by its internal id.
  await expect(page.locator('#indsource-owner')).toContainText('Chart 1');
  await expect(page.locator('#indsource-owner')).toHaveText(new RegExp(`, ${SAMPLE} \\(2\\)$`));
  await expect(page.locator('#indsource-owner')).not.toContainText(second);
  await expect(page.locator('#indsource-code')).toContainText("markerAnchor: 'price'");
  expect(first).not.toBe(second);
  await page.locator('#indsource-close').click();
  await clickSource(page, 2);
  await expect(page.locator('#indsource-owner')).toContainText('Chart 2');
  await expect(page.locator('#indsource-owner')).toHaveText(new RegExp(`, ${SAMPLE}$`));
  await expect(page.locator('#indsource-owner')).not.toContainText(other);
  await expect(page.locator('#indsource-title')).toContainText(SAMPLE);
  await shot(page, info, 'source-second-chart');
  await page.keyboard.press('Escape');
  await expect(page.locator('#indsource')).toBeHidden();
});

test('the source viewer fits a narrow screen and supports scrolling and keyboard closure', async ({ page }, info) => {
  await addSample(page, 1);
  await clickSource(page, 1);
  await page.setViewportSize({ width: 390, height: 640 });
  const close = page.locator('#indsource-close');
  const fit = await close.evaluate(button => {
    const range = document.createRange();
    range.selectNodeContents(button);
    const text = range.getBoundingClientRect();
    const box = button.getBoundingClientRect();
    const card = button.closest('.source-card')!.getBoundingClientRect();
    return {
      textFits: text.left >= box.left && text.right <= box.right,
      buttonFits: box.left >= card.left && box.right <= card.right,
      cardFits: card.left >= 0 && card.right <= innerWidth && card.top >= 0 && card.bottom <= innerHeight,
    };
  });
  expect(fit).toEqual({ textFits: true, buttonFits: true, cardFits: true });
  const body = page.locator('.source-card .set-body');
  expect(await body.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true);
  await page.locator('#indsource-code').focus();
  await expect(page.locator('#indsource-code')).toBeFocused();
  await body.evaluate(element => { element.scrollTop = element.scrollHeight; });
  expect(await body.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
  await shot(page, info, 'source-narrow-scrolled');
  await close.focus();
  await expect(close).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#indsource')).toBeHidden();
});

test('legend size previews stay on their owner and survive type rebuild and reload', async ({ page }, info) => {
  await addSample(page, 1);
  await split(page);
  await addSample(page, 2);
  await readoutSettings(page, 2);
  const size = page.locator('[data-key="legend.iconSize"]');
  await expect(size).toHaveValue('16');
  await size.fill('28');
  await size.blur();
  expect(await page.evaluate(() => (window as unknown as DemoWindow).__oac.app.chart2!.legendIconSize())).toBe(28);
  expect(await page.evaluate(() => (window as unknown as DemoWindow).__oac.app.chart.legendIconSize() ?? 16)).toBe(16);
  await page.locator('#cset-cancel').click();
  expect(await page.evaluate(() => (window as unknown as DemoWindow).__oac.app.chart2!.legendIconSize() ?? 16)).toBe(16);
  await readoutSettings(page, 2);
  await size.fill('24');
  await size.blur();
  await page.locator('#cset-ok').click();
  await clickSource(page, 2);
  await page.locator('#indsource-close').click();
  await page.getByRole('button', { name: /^Chart type, / }).click();
  await page.getByRole('menuitemradio', { name: 'Bars', exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as DemoWindow).__oac.app.chart2!.primarySeriesInfo()?.type)).toBe('bar');
  expect(await page.evaluate(() => (window as unknown as DemoWindow).__oac.app.chart2!.legendIconSize())).toBe(24);
  await clickSource(page, 2);
  await expect(page.locator('#indsource-owner')).toContainText('Chart 2');
  await page.locator('#indsource-close').click();
  await page.getByRole('button', { name: 'Save layout', exact: true }).click();
  await page.reload();
  await page.waitForFunction(() => Boolean((window as unknown as DemoWindow).__oac?.app.chart2?.primaryBars().length)
    && !(window as unknown as DemoWindow).__oac.app.loading && !(window as unknown as DemoWindow).__oac.app.loading2);
  expect(await page.evaluate(() => (window as unknown as DemoWindow).__oac.app.chart2!.legendIconSize())).toBe(24);
  expect(await page.evaluate(() => (window as unknown as DemoWindow).__oac.app.chart.legendIconSize() ?? 16)).toBe(16);
  await clickSource(page, 2);
  await expect(page.locator('#indsource-owner')).toContainText('Chart 2');
  await shot(page, info, 'source-after-rebuild-and-reload');
});

test('the sample paints every alternating signal outside candle extremes on both charts', async ({ page }, info) => {
  await split(page);
  await page.evaluate(() => {
    const app = (window as unknown as DemoWindow).__oac.app;
    for (const chart of [app.chart, app.chart2!]) chart.setVisibleLogicalRange({ from: -2, to: 50 });
  });
  await paint(page);
  const markerInk = (pane: Pane) => page.evaluate(pane => {
    const app = (window as unknown as DemoWindow).__oac.app;
    const chart = pane === 1 ? app.chart : app.chart2!;
    const canvas = chart.takeScreenshot();
    const box = document.querySelector(pane === 1 ? '#chart' : '#chart2')!.getBoundingClientRect();
    const ratio = canvas.width / box.width;
    const data = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
    const bars = chart.primaryBars();
    return [12, 24, 36].map(index => {
      const up = index === 24;
      const x = chart.timeToCoordinate(bars[index].time);
      const edge = chart.priceToCoordinate(up ? bars[index].low : bars[index].high)!;
      const rgb = up ? [38, 166, 154] : [239, 83, 80];
      let count = 0;
      for (let py = Math.ceil((edge + (up ? 1 : -40)) * ratio); py < (edge + (up ? 40 : -1)) * ratio; py++) {
        for (let px = Math.ceil((x - 24) * ratio); px < (x + 24) * ratio; px++) {
          const offset = (py * canvas.width + px) * 4;
          if (rgb.every((channel, index) => Math.abs(data[offset + index] - channel) < 12)) count++;
        }
      }
      return count;
    });
  }, pane);
  for (const pane of [1, 2] as const) {
    const before = await markerInk(pane);
    await addSample(page, pane);
    await paint(page);
    const after = await markerInk(pane);
    for (let index = 0; index < 3; index++) {
      expect(after[index] - before[index], `Chart ${pane} signal ${index + 1} must paint beyond its candle`).toBeGreaterThan(30);
    }
  }
  await page.mouse.move(5, 995);
  await shot(page, info, 'sample-candle-anchors');
});
