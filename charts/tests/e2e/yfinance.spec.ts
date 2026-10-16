import { test, expect, type Page } from '@playwright/test';
import type { AlertController, Chart, SeriesApi } from '../../src/index';

type AlertDragHost = Window & {
  __oac: { app: { chart: Chart; alerts: AlertController; loading: boolean } };
  __referenceAlertDrag: { writes: number; updates: number };
};

type AlertLoadHost = Window & {
  __oac: { app: {
    chart: Chart; chart2: Chart; price: SeriesApi; volume: SeriesApi; volume2: SeriesApi;
    alerts: AlertController; alerts2: AlertController; loading: boolean; loading2: boolean;
    p2: { symbol: string; interval: string; period: string };
    load(): Promise<void>; loadSecondary(): Promise<boolean>;
  } };
};

// The yfinance demo, the reference host, in a real browser.
//
// CLAUDE.md holds the demo to "usable, not just present", and the unit suite
// under examples/yfinance/tests runs against a document double: it cannot see
// a candle that never painted, a cursor the stylesheet did not pick up, or a
// click the chart swallowed. This spec drives the page the way a person does
// (the rail, the mouse over the plot, the transport's buttons) and reads the
// result back through `window.__oac = { chart, draw, app }`, which the page
// exposes only when opened as index.html?test=1.
//
// The page runs against its own server, examples/yfinance/server.py, in
// --fixture mode: deterministic synthetic bars for any symbol, no network and
// no yfinance, with FAIL, EMPTY and BUSY reserved for the 502, 404 and 429
// paths. playwright.config.ts starts that server when a Python 3 is on PATH.
// When none is, the probe in beforeEach finds nothing and every test here
// skips, rather than failing a run that never asked for Python.

const PAGE = '/examples/yfinance/index.html?test=1';
/** Only the demo server answers this; the static server has no /api. */
const PROBE = '/api/history?symbol=AAPL&interval=1d&period=1mo';
/** Distinct colours a real chart paints; a blank one is far below this. */
const MIN_DISTINCT_COLORS = 10;
/** Pixels that are not the background on a chart that has drawn its bars. */
const MIN_INK = 2000;

let serverUp: boolean | null = null;

test.beforeEach(async ({ request }) => {
  if (serverUp === null) serverUp = await request.get(PROBE).then((r) => r.ok(), () => false);
  test.skip(!serverUp, 'the yfinance demo server is not up (playwright.config.ts starts it when a Python 3 is on PATH)');
});

/** Console errors and uncaught exceptions from here on, in order. */
function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  return errors;
}

/** Open the page and wait for the first load to land: the handle, a chart, a controller and bars. */
async function openDemo(page: Page): Promise<void> {
  await page.goto(PAGE);
  await page.waitForFunction(() => {
    const o = (window as any).__oac;
    return Boolean(o && o.chart && o.draw && o.app.currentBars.length > 0);
  });
}

/**
 * Distinct colours across the chart's canvases, and how many pixels are not
 * the most common one. "Did it paint?" cannot be alpha != 0: the background
 * is opaque, so it has to be measured against the background itself, which
 * is the most common colour.
 */
const ink = (page: Page) => page.evaluate(() => {
  const planes = Array.from(document.querySelectorAll('#chart canvas')) as HTMLCanvasElement[];
  const counts = new Map<number, number>();
  for (const cv of planes) {
    const ctx = cv.getContext('2d', { willReadFrequently: true }) as CanvasRenderingContext2D;
    const { data } = ctx.getImageData(0, 0, cv.width, cv.height);
    for (let i = 0; i < data.length; i += 4) {
      if (data[i + 3] === 0) continue; // fully transparent overlay plane
      const key = (data[i] << 24) | (data[i + 1] << 16) | (data[i + 2] << 8) | data[i + 3];
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }
  let total = 0;
  let most = 0;
  for (const n of counts.values()) {
    total += n;
    if (n > most) most = n;
  }
  return { planes: planes.length, distinct: counts.size, nonBackground: total - most };
});

const drawingCount = (page: Page) => page.evaluate(() => (window as any).__oac.draw.drawings().length as number);
const activeTool = (page: Page) => page.evaluate(() => (window as any).__oac.draw.activeTool() as string | null);
const selectedId = (page: Page) => page.evaluate(() => (window as any).__oac.draw.selected() as string | null);
const cursorOf = (page: Page) => page.locator('#chart').evaluate((n) => getComputedStyle(n).cursor);
const chartBox = async (page: Page) => {
  const box = await page.locator('#chart').boundingBox();
  if (!box) throw new Error('#chart has no box: the stage did not lay out');
  return box;
};

test('loads a symbol and paints candles with no console or page errors', async ({ page }) => {
  const errors = watchErrors(page);
  await openDemo(page);

  await expect(page.locator('#status')).toHaveText(/AAPL .*\d+ bars/);
  const bars = await page.evaluate(() => (window as any).__oac.app.currentBars.length as number);
  expect(bars, 'a year of daily bars').toBeGreaterThan(200);

  // The first frame lands after the load resolves; wait for the pixels.
  await expect.poll(async () => (await ink(page)).nonBackground, { message: 'the chart never painted' }).toBeGreaterThan(MIN_INK);
  const shot = await ink(page);
  expect(shot.planes).toBeGreaterThan(0);
  expect(shot.distinct, `painted only ${shot.distinct} colours: the chart is blank`).toBeGreaterThan(MIN_DISTINCT_COLORS);
  expect(errors).toEqual([]);
});

test('arming a tool from the rail puts its glyph on the pointer', async ({ page }) => {
  const errors = watchErrors(page);
  await openDemo(page);
  expect(await cursorOf(page)).toBe('crosshair');

  // A group button arms the tool it stands for; the Lines group opens on the trend line.
  const lines = page.locator('#rail .rail__group[data-group="lines"]');
  await lines.click();
  expect(await activeTool(page)).toBe('trend-line');
  await expect(lines).toHaveAttribute('aria-pressed', 'true');
  // The rail sets --tool-cursor and the stylesheet reads it: a glyph, not a keyword.
  expect(await cursorOf(page)).toMatch(/^url\("data:image\/svg\+xml/);

  // The cursor button disarms it and the crosshair comes back.
  await page.locator('#rail .rail__tool[data-tools=""]').click();
  expect(await activeTool(page)).toBeNull();
  expect(await cursorOf(page)).toBe('crosshair');
  expect(errors).toEqual([]);
});

test('two clicks place a trend line, selecting it raises the properties bar, Escape closes it', async ({ page }) => {
  const errors = watchErrors(page);
  await openDemo(page);
  await page.locator('#rail .rail__group[data-group="lines"]').click();
  const box = await chartBox(page);
  // Both anchors in the price pane, clear of the legend rows at the top
  // left, the price axis on the right and the indicator pane below.
  const a = { x: box.x + box.width * 0.30, y: box.y + box.height * 0.40 };
  const b = { x: box.x + box.width * 0.55, y: box.y + box.height * 0.25 };
  await page.mouse.click(a.x, a.y);
  expect(await drawingCount(page), 'one anchor is not yet a drawing').toBe(0);
  await page.mouse.click(b.x, b.y);
  expect(await drawingCount(page)).toBe(1);
  const id = await page.evaluate(() => (window as any).__oac.draw.drawings()[0].id as string);

  // One drawing per pick: the tool is gone, and the new line is the selection.
  expect(await activeTool(page)).toBeNull();
  expect(await selectedId(page)).toBe(id);
  const bar = page.locator('#propbar');
  await expect(bar).toBeVisible();

  // A click on empty plot clears the selection, and the bar goes with it.
  await page.mouse.click(box.x + box.width * 0.75, box.y + box.height * 0.55);
  expect(await selectedId(page)).toBeNull();
  await expect(bar).toBeHidden();

  // A click on the line itself, at its midpoint as the chart maps it now
  // (the anchors sit on bar times, not exactly where the mouse went).
  const mid = await page.evaluate((id) => {
    const { chart, draw } = (window as any).__oac;
    const d = draw.get(id);
    const [p, q] = d.points;
    return {
      x: (chart.timeToCoordinate(p.time) + chart.timeToCoordinate(q.time)) / 2,
      y: (chart.priceToCoordinate(p.price, d.paneIndex) + chart.priceToCoordinate(q.price, d.paneIndex)) / 2,
    };
  }, id);
  await page.mouse.click(box.x + mid.x, box.y + mid.y);
  expect(await selectedId(page)).toBe(id);
  await expect(bar).toBeVisible();
  await expect(bar.locator('.pb-name')).toHaveText(/trend/i);

  // Escape closes the bar the way it closes every floating control, by
  // clearing the selection it belongs to; the line itself stays.
  await page.keyboard.press('Escape');
  await expect(bar).toBeHidden();
  expect(await selectedId(page)).toBeNull();
  expect(await drawingCount(page)).toBe(1);
  expect(errors).toEqual([]);
});

test('the rail is one tab stop and the arrow keys walk it', async ({ page }) => {
  await openDemo(page);
  const stops = page.locator('#rail .rail__btn[tabindex="0"]');
  await expect(stops, 'a roving tabindex: one stop for the whole rail').toHaveCount(1);
  await stops.focus();
  const focused = () => page.evaluate(() => {
    const a = document.activeElement as HTMLElement | null;
    if (!a) return null;
    return {
      id: a.id,
      cls: a.className,
      tools: a.dataset.tools ?? null,
      group: a.dataset.group ?? null,
      inRail: Boolean(a.closest('#rail')),
      inFlyout: Boolean(a.closest('.fly')),
    };
  });

  // The cursor button leads; ArrowDown reaches the first group.
  expect((await focused())?.tools).toBe('');
  await page.keyboard.press('ArrowDown');
  const next = await focused();
  expect(next?.inRail).toBe(true);
  expect(next?.group).toBe('lines');
  // The tab stop moves with the focus, so Tab later leaves from here.
  await expect(stops).toHaveCount(1);
  expect(await stops.evaluate((n) => (n as HTMLElement).dataset.group)).toBe('lines');

  // End and Home reach the redo button and the cursor button.
  await page.keyboard.press('End');
  expect((await focused())?.cls).toContain('rail__btn--chrome');
  await page.keyboard.press('Home');
  expect((await focused())?.tools).toBe('');

  // ArrowRight on a group opens its flyout with focus inside; Escape closes
  // it and returns to the button; Escape again hands focus to the plot.
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('ArrowRight');
  const fly = page.locator('.fly[role="menu"]');
  await expect(fly).toBeVisible();
  expect((await focused())?.inFlyout).toBe(true);
  await page.keyboard.press('Escape');
  await expect(fly).toHaveCount(0);
  expect((await focused())?.group).toBe('lines');
  await page.keyboard.press('Escape');
  expect((await focused())?.id).toBe('chart');
});

test('the theme switch flips the shell and keeps the choice, without throwing', async ({ page }) => {
  const errors = watchErrors(page);
  await openDemo(page);
  const shellBg = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const dark = await shellBg();

  // The switch lives in the shell module; the page's own instance of it is
  // what any button on the toolbar calls, so it is driven there.
  const flip = (url: string) => page.evaluate(async (u) => {
    const ui = await import(u);
    ui.toggleTheme();
    const root = document.documentElement;
    return { name: ui.currentTheme(), attr: root.dataset.theme, scheme: root.style.colorScheme, stored: localStorage.getItem(ui.THEME_KEY) };
  }, url);
  const UI = '/examples/yfinance/src/ui.js';

  expect(await flip(UI)).toEqual({ name: 'light', attr: 'light', scheme: 'light', stored: 'light' });
  const light = await shellBg();
  expect(light, 'the light palette repaints the shell').not.toBe(dark);

  expect(await flip(UI)).toEqual({ name: 'dark', attr: 'dark', scheme: 'dark', stored: 'dark' });
  expect(await shellBg()).toBe(dark);
  expect(errors).toEqual([]);
});

test('replay opens on a picked bar and steps forward one observation', async ({ page }) => {
  const errors = watchErrors(page);
  await openDemo(page);
  await page.locator('#shellbar button', { hasText: 'Replay' }).click();

  // Replay asks for the bar to start from before it starts.
  await expect(page.locator('#replaypick')).toBeVisible();
  await expect(page.locator('#chart')).toHaveClass(/is-picking/);
  const box = await chartBox(page);
  await page.mouse.click(box.x + box.width * 0.4, box.y + box.height * 0.35);
  await expect(page.locator('#replaybar')).toBeVisible();
  await expect(page.locator('#replaypick')).toBeHidden();

  const state = () => page.evaluate(() => {
    const r = (window as any).__oac.app.replay;
    return r ? (r.state() as { index: number; total: number; time: number;
      members: { state: { index: number; bar: { time: number } } }[] }) : null;
  });
  const s0 = await state();
  expect(s0).not.toBeNull();
  expect(s0!.total).toBeGreaterThan(s0!.index + 1);
  await expect(page.locator('#rp-count')).toHaveText(`${s0!.index + 1} / ${s0!.total}`);

  // An observation can be a finer update within the next displayed candle.
  await page.locator('#rp-fwd').click();
  const s1 = await state();
  expect(s1!.index).toBe(s0!.index + 1);
  await expect(page.locator('#rp-count')).toHaveText(`${s1!.index + 1} / ${s1!.total}`);
  // The series shows the session so far and nothing past the playhead.
  expect(await page.evaluate(() => (window as any).__oac.app.price.getData().length as number)).toBe(s1!.members[0].state.index + 1);
  expect(s1!.members[0].state.bar.time).toBeLessThanOrEqual(s1!.time);
  expect(errors).toEqual([]);
});

test('a symbol the source cannot serve leaves the shell up and says so', async ({ page }) => {
  // Only uncaught exceptions count here: Chromium reports the 502 itself as
  // a console error, and that line is the request failing, not the page.
  const pageErrors: string[] = [];
  page.on('pageerror', (e) => pageErrors.push(String(e)));
  await openDemo(page);
  const barsBefore = await page.evaluate(() => (window as any).__oac.app.currentBars.length as number);

  // The symbol box is raised by the toolbar's symbol button; Enter loads.
  await page.locator('#shellbar button', { hasText: 'AAPL' }).click();
  const sym = page.getByPlaceholder('Symbol or expression');
  await expect(sym).toBeFocused();
  await sym.fill('FAIL');
  await expect(sym).toHaveAttribute('aria-expanded', 'false');
  await sym.press('Enter');

  // The feed gives a gateway failure one retry before it reports, so the
  // readout arrives after a pause. Either the status line or the chart-state
  // card may carry it, depending on which the page wires.
  const readout = () => page.evaluate(() => {
    const card = document.getElementById('chartstate');
    if (card && !card.hidden && card.dataset.state === 'error') {
      return [document.getElementById('cs-title'), document.getElementById('cs-text')].map((n) => n?.textContent ?? '').join(' ').trim();
    }
    const status = document.getElementById('status')?.textContent ?? '';
    return /^error/i.test(status) ? status : '';
  });
  await expect.poll(readout, { timeout: 10_000, message: 'no error readout for FAIL' }).toMatch(/502|upstream|could not load/i);

  // The shell and the last good chart are still there to try again from.
  expect(await page.locator('#shellbar button').count()).toBeGreaterThan(5);
  expect(await page.evaluate(() => Boolean((window as any).__oac.chart))).toBe(true);
  expect(await page.evaluate(() => (window as any).__oac.app.currentBars.length as number)).toBe(barsBefore);
  expect(pageErrors).toEqual([]);
});

for (const pane of [1, 2]) {
  test(`chart ${pane} history handoff clears old bars before context and preserves same-source refresh`, async ({ page }) => {
    const errors = watchErrors(page);
    await page.route('**/api/history?**', route => route.fulfill({ json: Array.from({ length: 48 }, (_, index) => ({
      time: 1735689600 + index * 300, open: 99, high: 102, low: 98, close: 100, volume: 1000,
    })) }));
    await openDemo(page);
    await page.waitForFunction(() => !(window as unknown as AlertLoadHost).__oac.app.loading);
    if (pane === 2) {
      await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
      await page.waitForFunction(() => !(window as unknown as AlertLoadHost).__oac.app.loading2);
    }
    const same = await page.evaluate(async pane => {
      const app = (window as unknown as AlertLoadHost).__oac.app;
      const chart = pane === 1 ? app.chart : app.chart2;
      chart.setVisibleLogicalRange({ from: 12, to: 34 });
      const before = chart.getVisibleLogicalRange();
      const load = pane === 1 ? app.load() : app.loadSecondary();
      const during = { price: chart.primaryBars().length, volume: (pane === 1 ? app.volume : app.volume2).getData().length };
      await load;
      return { before, during, after: (pane === 1 ? app.chart : app.chart2).getVisibleLogicalRange() };
    }, pane);
    expect.soft(same.during).toEqual({ price: 48, volume: 48 });
    expect(same.after!.from).toBeCloseTo(same.before!.from, 6);
    expect(same.after!.to).toBeCloseTo(same.before!.to, 6);
    const changed = await page.evaluate(async pane => {
      const app = (window as unknown as AlertLoadHost).__oac.app;
      const chart = pane === 1 ? app.chart : app.chart2;
      const volume = pane === 1 ? app.volume : app.volume2;
      const atContext: { price: number; volume: number }[] = [];
      chart.on('data:context', () => atContext.push({ price: chart.primaryBars().length, volume: volume.getData().length }));
      if (pane === 1) (document.getElementById('interval') as HTMLSelectElement).value = '5m';
      else app.p2.interval = '5m';
      await (pane === 1 ? app.load() : app.loadSecondary());
      return atContext;
    }, pane);
    expect(changed).toEqual([{ price: 0, volume: 0 }]);
    expect(errors).toEqual([]);
  });

  test(`chart ${pane} returning to alert timeframe preserves its unclosed bar checkpoint`, async ({ page }, info) => {
    const errors = watchErrors(page);
    await page.route('**/api/history?**', route => {
      const interval = new URL(route.request().url()).searchParams.get('interval');
      const seconds = interval === '1m' ? 60 : 300;
      const start = 1735689600 + (interval === '1m' ? 18000 : 0);
      return route.fulfill({ json: Array.from({ length: 48 }, (_, index) => {
        const close = index === 47 ? 101 : 99;
        return { time: start + index * seconds, open: 99, high: 102, low: 98, close, volume: 1000 };
      }) });
    });
    await openDemo(page);
    await page.waitForFunction(() => !(window as unknown as AlertLoadHost).__oac.app.loading);
    if (pane === 2) {
      await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
      await page.waitForFunction(() => !(window as unknown as AlertLoadHost).__oac.app.loading2);
    }
    const switchFrame = async (interval: string): Promise<void> => {
      await page.evaluate(async ({ pane, interval }) => {
        const app = (window as unknown as AlertLoadHost).__oac.app;
        if (pane === 1) {
          const select = document.getElementById('interval') as HTMLSelectElement;
          if (![...select.options].some(option => option.value === interval)) select.add(new Option(interval, interval));
          select.value = interval;
        }
        else app.p2.interval = interval;
        await (pane === 1 ? app.load() : app.loadSecondary());
      }, { pane, interval });
      expect(await page.evaluate(pane => {
        const app = (window as unknown as AlertLoadHost).__oac.app;
        return (pane === 1 ? app.chart : app.chart2).getDataContext()?.interval;
      }, pane)).toBe(interval);
    };
    await switchFrame('5m');
    const created = await page.evaluate(pane => {
      const app = (window as unknown as AlertLoadHost).__oac.app;
      const chart = pane === 1 ? app.chart : app.chart2;
      const alerts = pane === 1 ? app.alerts : app.alerts2;
      const alert = alerts.add({ title: 'Original frame close', source: { kind: 'price', price: 100 },
        condition: 'crossingUp', policy: 'onBarClose', repeat: 'once' });
      return { id: alert.id, lastClosedTime: alert.lastClosedTime, formingTime: chart.primaryBars().at(-1)!.time };
    }, pane);
    expect(created).toMatchObject({ lastClosedTime: 1735703400, formingTime: 1735703700 });
    await switchFrame('1m');
    expect(await page.evaluate(pane => {
      const app = (window as unknown as AlertLoadHost).__oac.app;
      return (pane === 1 ? app.chart : app.chart2).primaryBars().at(-1)!.time;
    }, pane)).toBe(1735710420);
    await switchFrame('5m');
    const returned = await page.evaluate(pane => {
      const app = (window as unknown as AlertLoadHost).__oac.app;
      return (pane === 1 ? app.alerts : app.alerts2).list()[0];
    }, pane);
    expect(returned).toMatchObject({ id: created.id, state: 'armed', lastClosedTime: created.lastClosedTime });
    const triggered = await page.evaluate(pane => {
      const app = (window as unknown as AlertLoadHost).__oac.app;
      const chart = pane === 1 ? app.chart : app.chart2;
      const fired: unknown[] = [];
      chart.on('alert:triggered', event => fired.push(event));
      const bar = { time: chart.primaryBars().at(-1)!.time + 300, open: 101, high: 102, low: 100, close: 101, volume: 1000 };
      const price = pane === 1 ? app.price : chart.primarySeries()!;
      price.update(bar);
      price.update({ ...bar, close: 102 });
      return fired;
    }, pane);
    expect(triggered).toHaveLength(1);
    expect(triggered[0]).toMatchObject({ alert: { id: created.id }, time: created.formingTime });
    await page.screenshot({ path: info.outputPath(`chart-${pane}-original-frame-alert.png`), animations: 'disabled' });
    expect(errors).toEqual([]);
  });
}

test('a saved price alert stays visible after a timeframe change and reload', async ({ page }, info) => {
  const errors = watchErrors(page);
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.route('**/api/history?**', route => {
    const interval = new URL(route.request().url()).searchParams.get('interval');
    const seconds = interval === '5m' ? 300 : 86400;
    return route.fulfill({ json: Array.from({ length: 48 }, (_, index) => ({
      time: 1735689600 + index * seconds, open: 99, high: 102, low: 98, close: 100, volume: 1000,
    })) });
  });
  await openDemo(page);
  await page.waitForFunction(() => !(window as unknown as AlertDragHost).__oac.app.loading);
  await page.getByRole('button', { name: 'Alerts', exact: true }).click();
  await page.getByRole('button', { name: 'Create alert', exact: true }).click();
  const editor = page.getByRole('dialog', { name: 'Create alert', exact: true });
  await editor.getByLabel('Name', { exact: true }).fill('Daily price watch');
  await editor.getByLabel('Threshold', { exact: true }).fill('110');
  await editor.getByRole('button', { name: 'Save', exact: true }).click();
  await page.getByRole('dialog', { name: 'Alerts', exact: true }).getByRole('button', { name: 'Close', exact: true }).click();
  await page.getByRole('button', { name: '5M', exact: true }).click();
  const ready = () => page.waitForFunction(() => {
    const app = (window as unknown as AlertDragHost).__oac?.app;
    return app?.chart?.getDataContext()?.interval === '5m' && !app.loading && app.alerts?.list().length === 1;
  });
  await ready();
  const visible = () => page.evaluate(() => (window as unknown as AlertDragHost).__oac.app.chart.exportSVG().includes('Daily price watch (1d)'));
  await expect.poll(visible).toBe(true);
  await page.getByRole('button', { name: 'Alerts', exact: true }).click();
  await expect(page.locator('.oac-alerts__status')).toContainText('1d');
  await expect(page.locator('.oac-alerts__status')).toContainText('Switch');
  await page.getByRole('dialog', { name: 'Alerts', exact: true }).getByRole('button', { name: 'Close', exact: true }).click();
  await page.reload();
  await ready();
  await expect.poll(visible).toBe(true);
  await page.screenshot({ path: info.outputPath('reference-alert-other-timeframe.png') });
  await page.getByRole('button', { name: '1D', exact: true }).click();
  await page.waitForFunction(() => {
    const { chart, alerts, loading } = (window as unknown as AlertDragHost).__oac.app;
    return !loading && chart?.getDataContext()?.interval === '1d' && alerts?.list().length === 1
      && alerts.availability(alerts.list()[0].id).available;
  });
  expect(await page.evaluate(() => (window as unknown as AlertDragHost).__oac.app.alerts.list()[0]))
    .toMatchObject({ title: 'Daily price watch', state: 'armed', scope: { interval: '1d' }, source: { price: 110 } });
  expect(errors).toEqual([]);
});

test('an alert line drag previews without saving and persists once when released', async ({ page }, info) => {
  const errors = watchErrors(page);
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.route('**/api/history?**', route => route.fulfill({ json: Array.from({ length: 48 }, (_, index) => ({
    time: 1735689600 + index * 86400, open: 99, high: 102, low: 98, close: 100, volume: 1000,
  })) }));
  await openDemo(page);
  await page.waitForFunction(() => !(window as unknown as AlertDragHost).__oac.app.loading);
  await page.evaluate(() => {
    const { chart } = (window as unknown as AlertDragHost).__oac.app;
    chart.setVisibleLogicalRange({ from: -2, to: 50 });
    chart.panes()[0].priceScale.setFixedRange({ min: 80, max: 140 });
  });
  await page.getByRole('button', { name: 'Alerts', exact: true }).click();
  await page.getByRole('button', { name: 'Create alert', exact: true }).click();
  const editor = page.getByRole('dialog', { name: 'Create alert', exact: true });
  await editor.getByLabel('Name', { exact: true }).fill('Saved drag threshold');
  await editor.getByLabel('Threshold', { exact: true }).fill('110');
  await editor.getByRole('button', { name: 'Save', exact: true }).click();
  await page.getByRole('dialog', { name: 'Alerts', exact: true }).getByRole('button', { name: 'Close', exact: true }).click();
  const savedPrice = () => page.evaluate(() => {
    const layout = JSON.parse(localStorage.getItem('oa-charts:layout') ?? '{}');
    return layout.alerts?.alerts?.find((alert: { title: string }) => alert.title === 'Saved drag threshold')?.source.price;
  });
  await expect.poll(savedPrice).toBe(110);
  const before = await page.evaluate(() => {
    const host = window as unknown as AlertDragHost;
    const record = host.__referenceAlertDrag = { writes: 0, updates: 0 };
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key: string, value: string): void {
      original.call(this, key, value);
      if (this === localStorage && key === 'oa-charts:layout') record.writes++;
    };
    host.__oac.app.chart.on('alert:updated', () => { record.updates++; });
    return localStorage.getItem('oa-charts:layout');
  });
  const geometry = await page.evaluate(() => {
    const { chart } = (window as unknown as AlertDragHost).__oac.app;
    const box = document.getElementById('chart')!.getBoundingClientRect();
    return { x: box.left + box.width * 0.6, y: box.top + chart.priceToCoordinate(110)!, targetY: box.top + chart.priceToCoordinate(120)! };
  });
  const labelY = () => page.evaluate(() => {
    const { chart } = (window as unknown as AlertDragHost).__oac.app;
    const svg = new DOMParser().parseFromString(chart.exportSVG(), 'image/svg+xml');
    return [...svg.querySelectorAll('text')].find(text => text.textContent === 'Saved drag threshold')!.getAttribute('y');
  });
  const originalY = await labelY();
  await page.mouse.move(geometry.x, geometry.y);
  await page.mouse.down();
  await page.mouse.move(geometry.x, geometry.targetY, { steps: 8 });
  await expect.poll(labelY).not.toBe(originalY);
  // Hold beyond the host's 250ms debounce to expose any preview write.
  await page.waitForTimeout(350);
  expect(await page.evaluate(() => localStorage.getItem('oa-charts:layout'))).toBe(before);
  expect(await page.evaluate(() => (window as unknown as AlertDragHost).__referenceAlertDrag)).toEqual({ writes: 0, updates: 0 });
  expect(await page.evaluate(() => (window as unknown as AlertDragHost).__oac.app.alerts.list()[0].source)).toEqual({ kind: 'price', price: 110 });
  await page.screenshot({ path: info.outputPath('reference-alert-drag-preview.png') });
  await page.mouse.up();
  await expect.poll(savedPrice).toBeCloseTo(120, 1);
  expect(await page.evaluate(() => (window as unknown as AlertDragHost).__referenceAlertDrag)).toEqual({ writes: 1, updates: 1 });
  await page.reload();
  await page.waitForFunction(() => Boolean((window as unknown as AlertDragHost).__oac?.app.alerts?.list().length)
    && !(window as unknown as AlertDragHost).__oac.app.loading);
  expect(await page.evaluate(() => (window as unknown as AlertDragHost).__oac.app.alerts.list()[0].source))
    .toMatchObject({ kind: 'price', price: expect.closeTo(120, 1) });
  await page.screenshot({ path: info.outputPath('reference-alert-drag-restored.png') });
  expect(errors).toEqual([]);
});

test('a session mark selects read-only, stays out of the layout, and only the host clears it', async ({ page }, info) => {
  const errors = watchErrors(page);
  await openDemo(page);
  const box = await chartBox(page);
  const at = { x: box.x + box.width * 0.5, y: box.y + box.height * 0.35 };
  await page.mouse.click(at.x, at.y, { button: 'right' });
  const mark = page.locator('#ctxmenu [data-act="mark"]');
  await expect(mark).toBeVisible();
  await expect(mark).toHaveText(/^Mark .+ for this session$/);
  await mark.click();
  const marks = () => page.evaluate(() => (window as any).__oac.draw.drawings()
    .filter((d: { policy?: { persistent?: boolean } }) => d.policy?.persistent === false)
    .map((d: { id: string; points: unknown }) => ({ id: d.id, points: JSON.stringify(d.points) })) as { id: string; points: string }[]);
  const [placed] = await marks();
  expect(placed).toBeDefined();

  // A click on the line selects it; the bar says read-only and offers only a copy.
  const y = await page.evaluate((id) => {
    const { chart, draw } = (window as any).__oac;
    return chart.priceToCoordinate(draw.get(id).points[0].price, 0) as number;
  }, placed.id);
  await page.mouse.click(box.x + box.width * 0.4, box.y + y);
  expect(await selectedId(page)).toBe(placed.id);
  const bar = page.locator('#propbar');
  await expect(bar.locator('.pb-note')).toHaveText('Read-only');
  await expect(bar.locator('[data-act="delete"]')).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('session-mark-selected.png') });

  // Neither a drag nor Delete moves or removes it, and the saved layout never sees it.
  await page.mouse.move(box.x + box.width * 0.4, box.y + y);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.4 + 60, box.y + y + 40, { steps: 6 });
  await page.mouse.up();
  await page.keyboard.press('Delete');
  expect(await marks()).toEqual([placed]);
  expect(await page.evaluate(() => JSON.stringify((window as any).__oac.draw.toJSON()))).not.toContain(`"${placed.id}"`);

  // With the mark selected again, so a drag that cleared the selection could
  // not pass this on its own, the toolbar's Del has nothing to take and says
  // why, and Clear has nothing either. A chart-type switch, which rebuilds
  // the chart from the saved state, then brings the mark back as it was.
  // Measured again: the drag panned the chart, which may have moved the line.
  const yNow = await page.evaluate((id) => {
    const { chart, draw } = (window as any).__oac;
    return chart.priceToCoordinate(draw.get(id).points[0].price, 0) as number;
  }, placed.id);
  await page.mouse.click(box.x + box.width * 0.4, box.y + yNow);
  expect(await selectedId(page)).toBe(placed.id);
  await expect(page.locator('#drawdel')).toBeDisabled();
  await expect(page.locator('#drawdel')).toHaveAttribute('title', 'read-only');
  await expect(page.locator('#drawclear')).toBeDisabled();
  await page.evaluate(() => {
    const select = document.getElementById('ctype') as HTMLSelectElement;
    select.value = 'line';
    select.dispatchEvent(new Event('change'));
  });
  await expect.poll(marks).toEqual([placed]);
  await page.screenshot({ path: info.outputPath('session-mark-after-rebuild.png') });

  // The host's own row clears it.
  await page.mouse.click(at.x, at.y, { button: 'right' });
  const clear = page.locator('#ctxmenu [data-act="unmark"]');
  await expect(clear).toHaveText('Clear session marks (1)');
  await expect(page.locator('#ctxmenu [data-act="delall"]')).toBeHidden();
  await clear.click();
  expect(await marks()).toEqual([]);
  expect(errors).toEqual([]);
});

// ── labels ────────────────────────────────────────────────────────────────
// What each control is called, to a reader and to assistive technology. The
// 2.5.10 label audit found controls named "[object Object]", toggles whose
// name said the opposite of their pressed state, twin names for different
// actions, and codes where words belong; each check below failed before it.

/** Add a drawing of `tool` over recent bars and select it; its id. */
const addSelected = (page: Page, tool: string, extra: Record<string, unknown> = {}) => page.evaluate(([tool, extra]) => {
  const { draw, app } = (window as any).__oac;
  const bars = app.currentBars;
  const a = bars[bars.length - 40], b = bars[bars.length - 10];
  const points = tool === 'text' ? [{ time: a.time, price: a.high }] : [{ time: a.time, price: a.low }, { time: b.time, price: b.high }];
  const d = draw.add({ tool, paneIndex: 0, style: {}, points, ...extra });
  draw.select(d.id);
  return d.id as string;
}, [tool, extra] as const);

test('the properties bar names every control, and lock and hide keep their names while the state flips', async ({ page }) => {
  const errors = watchErrors(page);
  await openDemo(page);
  const bar = page.locator('#propbar');
  await addSelected(page, 'trend-line');
  await expect(bar).toBeVisible();
  await expect(bar.locator('[data-act="duplicate"]')).toHaveAttribute('aria-label', 'Duplicate');
  await expect(bar.locator('[data-act="delete"]')).toHaveAttribute('aria-label', 'Delete');
  await bar.locator('[data-act="duplicate"]').hover();
  await expect(page.locator('#tip')).toHaveText(/^Duplicate(Ctrl|Cmd)\+D$/);
  const names = await bar.locator('[aria-label]').evaluateAll(nodes => nodes.map(n => n.getAttribute('aria-label')));
  expect(names.filter(name => /\[object/.test(name ?? ''))).toEqual([]);

  // Pressed from the keyboard, with no pointer to refresh the name.
  for (const [act, name] of [['lock', 'Lock'], ['visible', 'Hide']] as const) {
    const control = bar.locator(`[data-act="${act}"]`);
    await expect(control).toHaveAttribute('aria-label', name);
    await expect(control).toHaveAttribute('aria-pressed', 'false');
    await control.focus();
    await page.keyboard.press('Enter');
    await expect(control).toHaveAttribute('aria-label', name);
    await expect(control).toHaveAttribute('aria-pressed', 'true');
    await page.keyboard.press('Enter');
    await expect(control).toHaveAttribute('aria-pressed', 'false');
  }

  await addSelected(page, 'text', { text: { value: 'Breakout' } });
  await expect(bar.locator('[data-act="edit-text"]')).toHaveAttribute('aria-label', 'Edit text');
  await addSelected(page, 'horizontal-line', { policy: { editable: false } });
  await expect(bar.locator('.pb-note')).toHaveText('Read-only');
  await expect(bar.locator('[data-act="duplicate"]')).toHaveAttribute('aria-label', 'Duplicate as your own drawing');
  expect(errors).toEqual([]);
});

test('a fill opacity slider is named by its label', async ({ page }) => {
  await openDemo(page);
  await addSelected(page, 'rectangle');
  await page.locator('#propbar [data-path="style.fillColor"]').click();
  await expect(page.getByRole('slider', { name: 'Fill opacity', exact: true })).toBeVisible();
});

test('the sandbox broker names its panel close apart from closing the position', async ({ page }) => {
  await openDemo(page);
  await page.locator('#account').click();
  const panel = page.locator('#acctpanel');
  await expect(panel.getByRole('button', { name: 'Close position', exact: true })).toHaveCount(1);
  await expect(panel.getByRole('button', { name: 'Close panel', exact: true })).toHaveCount(1);
});

test('a bracket prints its P&L with no currency the instrument does not trade in', async ({ page }) => {
  await openDemo(page);
  await page.getByRole('button', { name: /^Place a Buy OCO bracket/ }).click();
  await expect(page.locator('#bk-tp .pnl')).toHaveText(/^[+-][\d,]+$/);
  await expect(page.locator('#bk-sl .pnl')).toHaveText(/^[+-][\d,]+$/);
});

test('the chart menu speaks in sentence case and says what each row does', async ({ page }) => {
  await openDemo(page);
  await addSelected(page, 'trend-line');
  const box = await chartBox(page);
  await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.35, { button: 'right' });
  const menu = page.locator('#ctxmenu');
  await expect(menu).toBeVisible();
  const rows = await menu.locator('button:visible').evaluateAll(nodes => nodes.map(n => n.firstChild?.textContent ?? ''));
  // After the first word, capitals only in acronyms and names.
  for (const row of rows) expect(row.split(' ').slice(1).filter(word => /^[A-Z][a-z]/.test(word)), row).toEqual([]);
  await expect(menu.locator('[data-act="cancelall"]')).toHaveText('Cancel orders and close position');
  await expect(menu.locator('[data-act="volshow"]')).toHaveAttribute('role', 'menuitemcheckbox');
  await expect(menu.locator('[data-act="volshow"]')).toHaveAttribute('aria-checked', 'true');
  await expect(menu.getByRole('menuitem', { name: 'Copy drawing', exact: true })).toHaveAttribute('aria-keyshortcuts', /^(Control|Meta)\+C$/);
  await page.keyboard.press('Escape');
  await expect(page.locator('#cset-ok')).toHaveText('OK');
  await expect(page.locator('#bk-entry [data-act="modify"]')).toHaveText('Show bracket summary');
});

test('the status line and the legend use names, not ids and codes', async ({ page }) => {
  await openDemo(page);
  await page.locator('#rail .rail__group[data-group="lines"]').click();
  const box = await chartBox(page);
  await page.mouse.click(box.x + box.width * 0.30, box.y + box.height * 0.40);
  await page.mouse.click(box.x + box.width * 0.55, box.y + box.height * 0.25);
  await expect(page.locator('#status')).toContainText('Trend Line');
  await expect(page.locator('#status')).not.toContainText('trend-line');
  await page.getByRole('button', { name: '1W', exact: true }).click();
  await page.waitForFunction(() => (window as any).__oac.app.req.interval === '1wk' && !(window as any).__oac.app.loading);
  const params = await page.evaluate(() => (window as any).__oac.app.symbolLegend.options().params as string);
  expect(params).toMatch(/^1W /);
  await expect(page.getByRole('button', { name: '5M', exact: true })).toHaveAttribute('title', '5 minute bars');
});

test('menus and pills expose which option is on, and value buttons carry their value in the name', async ({ page }) => {
  await openDemo(page);
  const pill = page.getByRole('button', { name: '1D', exact: true });
  await expect(pill).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', { name: /AAPL/ }).first()).toBeVisible();
  await page.getByRole('button', { name: /^Chart type/ }).click();
  await expect(page.getByRole('menuitemradio', { name: 'Candles', exact: true })).toHaveAttribute('aria-checked', 'true');
  await page.keyboard.press('Escape');
  const box = await chartBox(page);
  await page.mouse.click(box.x + box.width - 20, box.y + box.height * 0.3, { button: 'right' });
  await expect(page.locator('#axmenu')).toBeVisible();
  await expect(page.locator('#axmenu').getByRole('menuitemradio', { name: 'Linear', exact: true })).toHaveAttribute('aria-checked', 'true');
  await page.keyboard.press('Escape');
  // Each chip's cross names the study it removes.
  const chips = await page.locator('#indlist .chip').evaluateAll(nodes => nodes.map(n => [n.querySelector('b')?.textContent, n.querySelector('button')?.getAttribute('aria-label')]));
  expect(chips.length).toBeGreaterThan(0);
  for (const [name, remove] of chips) expect(remove).toBe(`Remove ${name}`);
});

test('one action keeps one name across the page', async ({ page }) => {
  await openDemo(page);
  await expect(page.getByRole('button', { name: 'Save PNG', exact: true })).toHaveCount(1);
  await page.locator('.tbtn[aria-label="Chart snapshot"]').click();
  await expect(page.locator('#snap-save')).toContainText('Save PNG');
  await page.getByRole('button', { name: /Compare/ }).first().click();
  await expect(page.locator('#cmp-title')).toHaveText('Compare symbols: Chart 1');
  await page.keyboard.press('Escape');
  // Chart 2's disabled trading controls name the chart that trades as the page names it.
  await page.getByRole('button', { name: /Open a second, linked chart/ }).click();
  await page.waitForFunction(() => (window as any).__oac?.app.chart2?.primaryBars().length > 0 && !(window as any).__oac.app.loading2);
  await page.locator('#chart2').focus();
  // The pointer rests on the plot, so no control under it raises a tip of its own.
  const plot = (await page.locator('#chart2').boundingBox())!;
  await page.mouse.move(plot.x + plot.width / 2, plot.y + plot.height / 2);
  for (const [selector, said] of [['.tbtn--buy', 'Trading is available on Chart 1'], ['#account', 'The sandbox broker trades Chart 1']]) {
    await expect(page.locator(selector)).toBeDisabled();
    // A disabled button takes no pointer, so its tip is raised the way the pointer would.
    await page.locator(selector).dispatchEvent('pointerenter');
    await expect(page.locator('#tip.is-on')).toContainText(said);
  }
});

test('the canvas legend controls say what they do under the pointer', async ({ page }) => {
  const errors = watchErrors(page);
  await openDemo(page);
  const where = (action: string) => page.evaluate(action => {
    const { chart } = (window as any).__oac;
    const study = chart.indicators().find((s: any) => s.name === 'RSI');
    const pane = chart.panes()[study.paneIndex].element.getBoundingClientRect();
    const button = (study.legend()._buttons as { id: string; x: number; y: number }[]).find(b => b.id.endsWith(`::${action}`));
    return { row: { x: pane.left + 40, y: pane.top + 15 }, at: button ? { x: pane.left + button.x + 8, y: pane.top + button.y + 8 } : null };
  }, action);
  for (const [action, said] of [['hide', 'Hide RSI'], ['close', 'Remove RSI']] as const) {
    await page.mouse.move((await where(action)).row.x, (await where(action)).row.y);
    let at = (await where(action)).at;
    expect(at, action).not.toBeNull();
    // The controls reveal on hover and can shift as they do; follow them until they hold still.
    for (let tries = 0; tries < 4; tries++) {
      await page.mouse.move(at!.x, at!.y);
      const next = (await where(action)).at!;
      const settled = Math.abs(next.x - at!.x) < 0.5 && Math.abs(next.y - at!.y) < 0.5;
      at = next;
      if (settled) break;
    }
    await expect(page.locator('#tip.is-on')).toHaveText(said);
  }
  expect(errors).toEqual([]);
});

test('the Objects dock names a drawing the way the rail does', async ({ page }) => {
  await openDemo(page);
  await addSelected(page, 'trend-line');
  await page.getByRole('button', { name: 'Chart objects', exact: true }).first().click();
  await expect(page.locator('.oac-objects__name', { hasText: /^Trend Line/ }).first()).toBeVisible();
  await expect(page.locator('.oac-objects__name', { hasText: /^Trend line/ })).toHaveCount(0);
});

test('a paired colour swatch in the settings says which row it belongs to', async ({ page }) => {
  await openDemo(page);
  await page.getByRole('button', { name: /^Chart settings/ }).first().click();
  await expect(page.locator('#csetmodal, #cset-body').first()).toBeVisible();
  // Three rows have an Up swatch; each is named with its row, as the widget's form names them.
  await expect(page.getByRole('button', { name: 'Body Up', exact: true })).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Up', exact: true })).toHaveCount(0);
});
