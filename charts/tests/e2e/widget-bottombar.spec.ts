import { test, expect, type Page } from '@playwright/test';

// The widget's bottom bar in a real browser: where it sits, what a range
// fetches and shows, the clock and its timezone menu, the scale toggles
// against a real price-axis drag, the market status crossing the close, the
// session shading in pixels, the phone layout's sheet, one bar serving a
// grid's focused chart, and the option off.
const FIXTURE = '/tests/e2e/widget-bottombar-fixture.html';

async function open(page: Page, query = '', viewport = { width: 1280, height: 720 }): Promise<string[]> {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize(viewport);
  await page.goto(`${FIXTURE}${query === '' ? '' : '?' + query}`);
  await page.waitForFunction(() => (window as any).__loaded > 0);
  return errors;
}

const widget = <T>(page: Page, fn: string): Promise<T> => page.evaluate(`(() => { const w = window.__widget; return ${fn}; })()`) as Promise<T>;
const ist = (h: number, m: number): number => Date.UTC(2025, 9, 1, h, m) / 1000 - 5.5 * 3600;

test('sits under the chart and above the status line, in both themes', async ({ page }, info) => {
  for (const theme of ['dark', 'light']) {
    const errors = await open(page, `theme=${theme}`);
    const chart = await page.locator('.oac-chart').boundingBox();
    const bar = await page.locator('.oac-bottombar').boundingBox();
    const status = await page.locator('.oac-statusline').boundingBox();
    expect(bar!.height).toBe(28);
    expect(Math.abs(bar!.y - (chart!.y + chart!.height))).toBeLessThanOrEqual(1);
    expect(Math.abs(status!.y - (bar!.y + bar!.height))).toBeLessThanOrEqual(1);
    expect(bar!.width).toBe(1280);
    // Toasts rise above the bar rather than covering it.
    const toasts = await page.locator('.oac-toasts').boundingBox();
    expect(toasts!.y + toasts!.height).toBeLessThanOrEqual(bar!.y);
    // The market status reads the instrument calendar: NSE at 14:20 is open.
    await expect(page.locator('.oac-bottombar__status b')).toHaveText('Market open');
    await expect(page.locator('.oac-bottombar__detail')).toHaveText('closes 15:30');
    await expect(page.locator('.oac-bottombar__time')).toHaveText('14:20:00');
    await expect(page.locator('.oac-topbar__goto')).toHaveCount(0);
    await info.attach(`bottom bar ${theme}`, { body: await page.screenshot(), contentType: 'image/png' });
    expect(errors).toEqual([]);
  }
});

test('a range sets the interval, fetches the sessions it needs and fits them', async ({ page }, info) => {
  const errors = await open(page);
  await page.locator('.oac-bottombar__range[data-range="1D"]').click();
  await expect.poll(() => widget<string | null>(page, 'w.range()')).toBe('1D');
  await expect(page.locator('.oac-pills button[data-interval="1m"]')).toHaveAttribute('aria-pressed', 'true');
  const last = await page.evaluate(() => (window as any).__requests.at(-1));
  expect(last).toMatchObject({ interval: '1m', to: ist(14, 20) });
  // Never less than an ordinary load of 500 bars, and the session from 09:15 in it.
  expect(last.from).toBeLessThanOrEqual(ist(9, 15));
  await expect.poll(() => widget<number>(page, 'w.series.getData().filter(b => b.time >= ' + ist(9, 15) + ').length')).toBe(306);
  const view = await widget<{ from: number; to: number }>(page, 'w.chart.getVisibleLogicalRange()');
  const first = await widget<number>(page, `w.chart.dataLayer.timeToIndex(${ist(9, 15)})`);
  expect(view.from).toBeCloseTo(first - 0.5, 3);
  await expect(page.locator('.oac-bottombar__range[data-range="1D"]')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.oac-statusline__msg')).toContainText('1D:');
  await info.attach('one session', { body: await page.screenshot(), contentType: 'image/png' });

  // Five sessions at five minutes reach back across the weekend.
  await page.locator('.oac-bottombar__range[data-range="5D"]').click();
  await expect.poll(() => widget<string>(page, 'w.interval()')).toBe('5m');
  await expect.poll(() => widget<number>(page, 'w.chart.getVisibleLogicalRange().to - w.chart.getVisibleLogicalRange().from')).toBeCloseTo(4 * 75 + 62, 0);

  // A manual interval leaves the range.
  await page.locator('.oac-pills button[data-interval="15m"]').click();
  await expect.poll(() => widget<string | null>(page, 'w.range()')).toBeNull();
  await expect(page.locator('.oac-bottombar__range[aria-pressed="true"]')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('the keyboard reaches every control, and Enter applies a range', async ({ page }) => {
  const errors = await open(page, 'theme=light');
  await page.locator('.oac-bottombar__range[data-range="1D"]').focus();
  await page.keyboard.press('Tab');
  await expect(page.locator('.oac-bottombar__range[data-range="5D"]')).toBeFocused();
  await page.keyboard.press('Enter');
  await expect.poll(() => widget<string | null>(page, 'w.range()')).toBe('5D');
  const outline = await page.locator('.oac-bottombar__range[data-range="5D"]').evaluate(el => getComputedStyle(el).outlineStyle);
  expect(outline).toBe('solid');
  expect(errors).toEqual([]);
});

test('the clock opens the timezone menu upward and a zone picked moves the chart', async ({ page }, info) => {
  const errors = await open(page);
  const clock = page.locator('.oac-bottombar__clock');
  await expect(clock).toHaveAttribute('aria-label', 'Timezone: Asia/Kolkata');
  await clock.click();
  const menu = page.locator('.oac-menu');
  await expect(menu).toBeVisible();
  const box = await menu.boundingBox();
  const bar = await page.locator('.oac-bottombar').boundingBox();
  expect(box!.y + box!.height).toBeLessThanOrEqual(bar!.y + 1);
  await info.attach('zone menu', { body: await page.screenshot(), contentType: 'image/png' });
  await page.keyboard.type('New_York');
  await page.keyboard.press('Enter');
  await expect(menu).toHaveCount(0);
  expect(await widget<string>(page, 'w.chart.timezone()')).toBe('America/New_York');
  await expect(page.locator('.oac-bottombar__time')).toHaveText('04:50:00');
  await expect(page.locator('.oac-bottombar__clock small')).toHaveText('UTC-4');
  // The market status follows the chart's clock too.
  await expect(page.locator('.oac-bottombar__detail')).toHaveText('closes 06:00');
  // Escape closes the menu and gives focus back to the clock.
  await clock.click();
  await page.keyboard.press('Escape');
  await expect(page.locator('.oac-menu')).toHaveCount(0);
  await expect(clock).toBeFocused();
  expect(errors).toEqual([]);
});

test('the scale toggles drive the price scale and follow an axis drag', async ({ page }) => {
  const errors = await open(page);
  const axis = () => widget<{ mode: string; autoFit: boolean }>(page, 'w.chart.priceAxisState(w.chart.primaryPaneIndex(), "right")');
  const toggle = (id: string) => page.locator(`.oac-bottombar__icon[data-scale="${id}"]`);
  await expect(toggle('auto')).toHaveAttribute('aria-pressed', 'true');
  await toggle('log').click();
  expect((await axis()).mode).toBe('logarithmic');
  await expect(toggle('log')).toHaveAttribute('aria-pressed', 'true');
  await toggle('percent').click();
  expect((await axis()).mode).toBe('percentage');
  await expect(toggle('log')).toHaveAttribute('aria-pressed', 'false');
  await toggle('percent').click();
  expect((await axis()).mode).toBe('linear');
  // Dragging the price axis takes auto-fit off with no event; the bar sees it when the press ends.
  const chart = await page.locator('.oac-chart').boundingBox();
  const x = chart!.x + chart!.width - 20;
  await page.mouse.move(x, chart!.y + 200);
  await page.mouse.down();
  await page.mouse.move(x, chart!.y + 280, { steps: 6 });
  await page.mouse.up();
  expect((await axis()).autoFit).toBe(false);
  await expect(toggle('auto')).toHaveAttribute('aria-pressed', 'false');
  await toggle('auto').click();
  expect((await axis()).autoFit).toBe(true);
  expect(errors).toEqual([]);
});

test('the market status follows the calendar past the close', async ({ page }) => {
  const errors = await open(page);
  await page.evaluate(() => { (window as any).__now = Date.UTC(2025, 9, 1, 10, 1) - 0; });
  await expect(page.locator('.oac-bottombar__status b')).toHaveText('Market closed');
  await expect(page.locator('.oac-bottombar__detail')).toHaveText(/^opens \S+ 09:15$/);
  await expect(page.locator('.oac-bottombar__status')).toHaveAttribute('data-phase', 'closed');
  expect(errors).toEqual([]);
});

test('session shading washes the pre-open and post-close bars from the calendar', async ({ page }, info) => {
  const errors = await open(page, 'symbol=AAPL');
  await page.locator('.oac-bottombar__range[data-range="5D"]').click();
  await expect.poll(() => widget<string | null>(page, 'w.range()')).toBe('5D');
  await expect(page.locator('.oac-bottombar__status b')).toHaveText('Pre-open');
  // A pre-open bar and a regular bar of the same session, sampled at the top
  // of the plot where no candle reaches: the wash differs, the background not.
  const sample = async (shade: boolean): Promise<number[][]> => {
    if (!shade) {
      await page.goto(`${FIXTURE}?symbol=AAPL&shade=off`);
      await page.waitForFunction(() => (window as any).__loaded > 0);
      await page.locator('.oac-bottombar__range[data-range="5D"]').click();
      await expect.poll(() => widget<string | null>(page, 'w.range()')).toBe('5D');
    }
    return page.evaluate(async () => {
      // The capture composites the last painted frame: let the range's frame land first.
      await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
      const w = (window as any).__widget;
      const bars = w.series.getData();
      const day = bars[bars.length - 400].time;
      const pre = bars.find((b: { time: number }) => b.time > day && new Date(b.time * 1000).getUTCHours() === 9);
      const regular = bars.find((b: { time: number }) => b.time > pre.time && new Date(b.time * 1000).getUTCHours() === 15);
      const canvas = w.chart.takeScreenshot() as HTMLCanvasElement;
      const ctx = canvas.getContext('2d')!;
      const ratio = canvas.width / (document.querySelector('.oac-chart') as HTMLElement).getBoundingClientRect().width;
      return [pre, regular].map((b: { time: number }) => {
        const x = w.chart.timeToCoordinate(b.time);
        return Array.from(ctx.getImageData(Math.round(x * ratio), Math.round(6 * ratio), 1, 1).data);
      });
    });
  };
  const shaded = await sample(true);
  await info.attach('shaded five sessions', { body: await page.screenshot(), contentType: 'image/png' });
  expect(shaded[0]).not.toEqual(shaded[1]);
  const plain = await sample(false);
  expect(plain[0]).toEqual(plain[1]);
  expect(errors).toEqual([]);
});

test('the phone layout hides the bar and lists its controls in the More sheet', async ({ page }, info) => {
  const errors = await open(page, 'mobile=always', { width: 390, height: 844 });
  await expect(page.locator('.oac-bottombar')).toBeHidden();
  // Toasts keep the phone layout's place above its footer, not the hidden bar's.
  expect(await page.locator('.oac-toasts').evaluate(el => getComputedStyle(el).bottom)).toBe('54px');
  await page.locator('[data-mobile-action="more"]').click();
  const sheet = page.locator('.oac-mobile-sheet');
  await expect(sheet.locator('.oac-mobile-sheet__note')).toContainText('Market open');
  await expect(sheet.locator('.oac-mobile-sheet__note')).toContainText('14:20 UTC+5:30');
  await expect(sheet.locator('[data-mobile-action="range"]')).toHaveCount(9);
  await expect(sheet.locator('[data-mobile-action="scale"]')).toHaveCount(3);
  // Short choices share rows: nine ranges on two, the three toggles on one.
  const rows = (action: string) => sheet.locator(`[data-mobile-action="${action}"]`)
    .evaluateAll(els => new Set(els.map(el => Math.round(el.getBoundingClientRect().top))).size);
  expect(await rows('range')).toBe(2);
  expect(await rows('scale')).toBe(1);
  await info.attach('more sheet', { body: await page.screenshot(), contentType: 'image/png' });
  await sheet.locator('[data-mobile-action="range"][data-range="1D"]').click();
  await expect.poll(() => widget<string | null>(page, 'w.range()')).toBe('1D');
  await page.locator('[data-mobile-action="more"]').click();
  await page.locator('[data-mobile-action="timezone"]').click();
  await page.locator('[data-mobile-action="pick-zone"][data-zone="Europe/London"]').click();
  expect(await widget<string>(page, 'w.chart.timezone()')).toBe('Europe/London');
  expect(errors).toEqual([]);
});

test('on a narrow bar the ranges give way and scroll, never the status, the clock or the toggles', async ({ page }, info) => {
  for (const width of [560, 700]) {
    const errors = await open(page, 'mobile=never', { width, height: 520 });
    const bar = (await page.locator('.oac-bottombar').boundingBox())!;
    expect(bar.width).toBe(width);
    for (const selector of ['.oac-bottombar__clock', '.oac-bottombar__icon[data-scale="auto"]', '.oac-bottombar__icon[data-scale="log"]', '.oac-bottombar__icon[data-scale="percent"]']) {
      const box = (await page.locator(selector).boundingBox())!;
      expect(box.x).toBeGreaterThanOrEqual(bar.x);
      expect(box.x + box.width).toBeLessThanOrEqual(bar.x + bar.width + 0.5);
    }
    // The status reads whole, beside the clock rather than under it.
    await expect(page.locator('.oac-bottombar__status b')).toHaveText('Market open');
    expect(await page.locator('.oac-bottombar__status').evaluate(el => el.scrollWidth <= Math.ceil(el.getBoundingClientRect().width))).toBe(true);
    const status = (await page.locator('.oac-bottombar__status').boundingBox())!;
    const clock = (await page.locator('.oac-bottombar__clock').boundingBox())!;
    expect(status.x + status.width).toBeLessThanOrEqual(clock.x);
    // The last range is still reachable: the keyboard scrolls the whole of it
    // into view, from the start of the strip and from where the strip shows
    // only part of it (which a browser's own focus scroll leaves as it is).
    const all = page.locator('.oac-bottombar__range[data-range="ALL"]');
    const strip = page.locator('.oac-bottombar__ranges');
    for (const from of ['start', 'cut'] as const) {
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
      const cut = await strip.evaluate((el, from) => {
        const button = el.querySelector('[data-range="ALL"]') as HTMLElement;
        el.scrollLeft = 0;
        if (from === 'cut') el.scrollLeft += button.getBoundingClientRect().right - button.offsetWidth / 2 - el.getBoundingClientRect().right;
        const b = button.getBoundingClientRect(), s = el.getBoundingClientRect();
        return b.left < s.right && b.right > s.right + 0.5;
      }, from);
      if (width === 560 && from === 'cut') expect(cut, 'the strip cuts the last range in part').toBe(true);
      await all.focus();
      const box = (await all.boundingBox())!;
      const ranges = (await strip.boundingBox())!;
      expect(box.x + box.width, `from ${from}`).toBeLessThanOrEqual(ranges.x + ranges.width + 0.5);
      expect(box.x, `from ${from}`).toBeGreaterThanOrEqual(ranges.x - 0.5);
    }
    await info.attach(`narrow bar ${width}`, { body: await page.screenshot(), contentType: 'image/png' });
    expect(errors).toEqual([]);
  }
});

test('a widget with no top bar keeps the bar in the phone layout, where no More sheet takes it', async ({ page }, info) => {
  const errors = await open(page, 'mobile=always&topbar=off', { width: 390, height: 844 });
  const bar = page.locator('.oac-bottombar');
  await expect(bar).toBeVisible();
  await expect(page.locator('[data-mobile-action="more"]')).toHaveCount(0);
  const barBox = (await bar.boundingBox())!;
  const chart = (await page.locator('.oac-chart').boundingBox())!;
  const footer = (await page.locator('.oac-mobile__footer').boundingBox())!;
  expect(barBox.height).toBe(28);
  // Under the chart, above the phone footer, which keeps the bottom edge.
  expect(Math.abs(barBox.y - (chart.y + chart.height))).toBeLessThanOrEqual(1);
  expect(Math.abs(footer.y - (barBox.y + barBox.height))).toBeLessThanOrEqual(1);
  expect(footer.y + footer.height).toBeCloseTo(844, 0);
  // Toasts rise above both.
  expect(await page.locator('.oac-toasts').evaluate(el => getComputedStyle(el).bottom)).toBe('82px');
  await page.locator('.oac-bottombar__range[data-range="1D"]').click();
  await expect.poll(() => widget<string | null>(page, 'w.range()')).toBe('1D');
  await info.attach('phone without a top bar', { body: await page.screenshot(), contentType: 'image/png' });
  expect(errors).toEqual([]);
});

test('under a grid one bar acts on the focused chart', async ({ page }, info) => {
  const errors = await open(page, 'grid=1');
  const grid = <T>(fn: string): Promise<T> => page.evaluate(`(() => { const g = window.__grid; return ${fn}; })()`) as Promise<T>;
  await expect(page.locator('.oac-bottombar')).toHaveCount(1);
  await expect(page.locator('.oac-grid__cell .oac-bottombar')).toHaveCount(0);
  const bar = await page.locator('.oac-bottombar').boundingBox();
  const cells = await page.locator('.oac-grid__cells').boundingBox();
  expect(Math.abs(bar!.y - (cells!.y + cells!.height))).toBeLessThanOrEqual(1);
  expect(bar!.y + bar!.height).toBeCloseTo(720, 0);
  // The first chart has the focus: a range reaches it and not its neighbour.
  await page.locator('.oac-bottombar__range[data-range="1D"]').click();
  await expect.poll(() => grid<string>('g.cells().map(c => c.widget.interval()).join()')).toBe('1m,5m');
  await expect(page.locator('.oac-bottombar__range[data-range="1D"]')).toHaveAttribute('aria-pressed', 'true');
  // A press on the second chart moves the focus, and the bar with it.
  const second = await page.locator('.oac-grid__cell').nth(1).locator('.oac-chart').boundingBox();
  await page.mouse.click(second!.x + second!.width / 2, second!.y + 60);
  await expect.poll(() => grid<string>('g.active().id')).toBe(await grid<string>('g.cells()[1].id'));
  await expect(page.locator('.oac-bottombar__range[data-range="1D"]')).toHaveAttribute('aria-pressed', 'false');
  await page.locator('.oac-bottombar__icon[data-scale="log"]').click();
  expect(await grid<string[]>('g.cells().map(c => c.widget.chart.priceAxisState(c.widget.chart.primaryPaneIndex(), "right").mode)')).toEqual(['linear', 'logarithmic']);
  await expect(page.locator('.oac-bottombar__icon[data-scale="log"]')).toHaveAttribute('aria-pressed', 'true');
  // The zone menu opens above the bar, over the charts, and moves only the focused one.
  await page.locator('.oac-bottombar__clock').click();
  const menu = page.locator('.oac-menu');
  await expect(menu).toBeVisible();
  const box = await menu.boundingBox();
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.y + box!.height).toBeLessThanOrEqual(bar!.y + 1);
  await info.attach('grid bar zone menu', { body: await page.screenshot(), contentType: 'image/png' });
  await menu.locator('.oac-menu__row', { hasText: 'Europe/London' }).click();
  expect(await grid<string[]>('g.cells().map(c => c.widget.chart.timezone())')).toEqual(['Asia/Kolkata', 'Europe/London']);
  await expect(page.locator('.oac-bottombar__clock')).toHaveAttribute('aria-label', 'Timezone: Europe/London');
  expect(errors).toEqual([]);
});

test('turned off, the bar is gone and Go to is back in the top bar', async ({ page }) => {
  const errors = await open(page, 'bar=off');
  await expect(page.locator('.oac-bottombar')).toHaveCount(0);
  await expect(page.locator('.oac-topbar__goto')).toBeVisible();
  // The status line says the market status in its place.
  await expect(page.locator('.oac-statusline__market')).toHaveText('Market open · closes 15:30');
  const chart = await page.locator('.oac-chart').boundingBox();
  const status = await page.locator('.oac-statusline').boundingBox();
  expect(Math.abs(status!.y - (chart!.y + chart!.height))).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
});
