import { test, expect, type Page } from '@playwright/test';

// The reference host's own chrome in both of its palettes. The rail's lower
// block (magnet, keep tool, lock, visibility, trash, undo, redo) and its
// active and danger tints were written as the dark palette's literal
// colours, so the light theme kept a dark strip at the bottom of the rail.
// And the replay transport printed the chart's name twice: once as the
// owner label and once as the scope toggle beside it.

const PAGE = '/examples/yfinance/index.html?test=1';
const PROBE = '/api/history?symbol=AAPL&interval=1d&period=1mo';
let serverUp: boolean | null = null;

test.beforeEach(async ({ request, page }) => {
  if (serverUp === null) serverUp = await request.get(PROBE).then(response => response.ok(), () => false);
  test.skip(!serverUp, 'The reference fixture server is unavailable');
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.goto(PAGE);
  await page.waitForFunction(() => Boolean((window as any).__oac?.app?.currentBars?.length));
});

async function setTheme(page: Page, name: 'dark' | 'light'): Promise<void> {
  await page.evaluate(async theme => {
    const path = '/examples/yfinance/src/ui.js';
    (await import(path)).setTheme(theme, { silent: true });
  }, name);
  await expect(page.locator('html')).toHaveAttribute('data-theme', name);
}

/** A custom property resolved to the colour the browser paints, via a probe element. */
async function token(page: Page, name: string, property: 'backgroundColor' | 'color' | 'borderTopColor'): Promise<string> {
  return page.evaluate(([n, p]) => {
    const probe = document.createElement('div');
    const css = p === 'backgroundColor' ? 'background-color' : p === 'color' ? 'color' : 'border-top-color';
    probe.style.setProperty(css, `var(${n})`);
    document.body.appendChild(probe);
    const value = getComputedStyle(probe)[p as 'color'];
    probe.remove();
    return value;
  }, [name, property] as const);
}

const style = (page: Page, selector: string, property: 'backgroundColor' | 'color' | 'borderTopColor') =>
  page.locator(selector).first().evaluate((node, p) => getComputedStyle(node)[p as 'color'], property);

test('the rail and its lower block share one surface in the light and the dark theme', async ({ page }, info) => {
  for (const theme of ['light', 'dark', 'light'] as const) {
    await setTheme(page, theme);
    const rail = await style(page, '#rail', 'backgroundColor');
    expect(await style(page, '#rail .rail__ctl', 'backgroundColor')).toBe(rail);
    expect(rail).toBe(await token(page, '--panel-2', 'backgroundColor'));
    await page.screenshot({ path: info.outputPath(`rail-${theme}.png`) });
  }
});

test('the active tool, the checked flyout row and the danger hover take the theme tokens', async ({ page }, info) => {
  await setTheme(page, 'light');
  const lines = page.locator('#rail .rail__group[data-group="lines"]');
  await lines.click();
  await expect(lines).toHaveAttribute('aria-pressed', 'true');
  // Polled: the button eases its tint over a tenth of a second.
  const onBg = await token(page, '--on-bg', 'backgroundColor');
  await expect.poll(() => style(page, '#rail .rail__group[data-group="lines"]', 'backgroundColor')).toBe(onBg);
  await expect.poll(() => style(page, '#rail .rail__group[data-group="lines"]', 'borderTopColor')).toBe(await token(page, '--on-bd', 'borderTopColor'));

  // The group's flyout marks the tool in use as its checked row.
  await lines.hover();
  await lines.locator('.rail__chev').click();
  const checked = page.locator('.fly__row[aria-checked="true"]').first();
  await expect(checked).toBeVisible();
  await expect.poll(() => checked.evaluate(node => getComputedStyle(node).backgroundColor)).toBe(onBg);
  await page.screenshot({ path: info.outputPath('rail-flyout-light.png') });
  await page.keyboard.press('Escape');

  // With nothing selected the trash is off; a selected drawing turns it on.
  await page.evaluate(() => {
    const oac = (window as any).__oac;
    const bars = oac.app.currentBars;
    const a = bars[bars.length - 30], b = bars[bars.length - 5];
    const drawing = oac.draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [{ time: a.time, price: a.close }, { time: b.time, price: b.close }] });
    oac.draw.select([drawing.id]);
  });
  await expect(page.locator('#rail .rail__btn--danger:not(.is-off)').first()).toBeVisible();
  await page.locator('#rail .rail__btn--danger:not(.is-off)').first().hover();
  await expect.poll(() => style(page, '#rail .rail__btn--danger:not(.is-off)', 'color')).toBe(await token(page, '--danger-tx', 'color'));
});

test('the replay bar names the chart once and the scope toggle names the scope', async ({ page }, info) => {
  await page.locator('#chart').focus();
  await page.getByRole('button', { name: 'Replay this session bar by bar', exact: true }).click();
  // The pick prompt has no owner label, so its toggle still names the chart.
  await expect(page.locator('#rp-pick-scope')).toHaveText('Chart 1');
  await page.evaluate(async () => {
    const path = '/examples/yfinance/src/replay.js'; await (await import(path)).startReplayAt(20);
  });
  await expect(page.locator('#replaybar')).toBeVisible();
  const owner = page.locator('#rp-owner'), scope = page.locator('#rp-scope');
  await expect(owner).toHaveText('Chart 1');
  await expect(scope).toHaveText('This chart');
  await expect(scope).toHaveAttribute('aria-label', 'Replay scope: This chart');
  // Named for the scope in force; no pressed state says it a second time, or the opposite.
  await expect(scope).not.toHaveAttribute('aria-pressed', /.*/);
  expect(await owner.textContent()).not.toBe(await scope.textContent());
  for (const theme of ['light', 'dark'] as const) {
    await setTheme(page, theme);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await page.locator('#replaybar').screenshot({ path: info.outputPath(`replay-bar-${theme}.png`) });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.locator('#replaybar').evaluate(node => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
  await page.locator('#replaybar').screenshot({ path: info.outputPath('replay-bar-narrow.png') });
});

test('picking a replay start on all charts veils what a still open bar of a longer interval formed', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  // Chart 1 shows days; chart 2 shows weekly Renko bricks, which the chart forms from weekly bars.
  await page.evaluate(async () => {
    const app = (window as any).__oac.app, path = '/examples/yfinance/src/split.js';
    Object.assign(app.p2, { symbol: 'AAPL', interval: '1wk', period: '5y', chartType: 't:renko' });
    await (await import(path)).openSplit();
  });
  await page.waitForFunction(() => { const app = (window as any).__oac.app; return !app.loading2 && app.chart2?.primaryBars().length > 0; });
  const found = await page.evaluate(async () => {
    const app = (window as any).__oac.app;
    const replayPath = '/examples/yfinance/src/replay.js', distPath = '/dist/openalgo-charts.mjs';
    const replay = await import(replayPath), { ReplayShade } = await import(distPath);
    // The cut each veil is given, read through its public setter.
    const cuts = new Map<unknown, number | null>(), set = ReplayShade.prototype.setOptions;
    ReplayShade.prototype.setOptions = function (patch: { index?: number | null }) {
      if ('index' in patch) cuts.set(this, patch.index ?? null);
      return set.call(this, patch);
    };
    const daily = app.chart.primarySeries().getData(), weekly = app.chart2.primarySeries().getData(), bricks = app.chart2.primaryBars();
    const endOfDay = replay.replayBarEndTime('1d', app.chart.timezone()), endOfWeek = replay.replayBarEndTime('1wk', app.chart2.timezone());
    // A day inside a week whose bar, still open at that day's close, formed bricks.
    for (let pick = daily.length - 30; pick > daily.length / 2; pick--) {
      const close = endOfDay(daily[pick]);
      const week = weekly.findIndex((bar: { time: number }) => endOfWeek(bar) > close);
      if (week < 1 || weekly[week].time >= close) continue;
      const first = bricks.findIndex((brick: { time: number }) => brick.time >= weekly[week].time);
      const next = weekly[week + 1]?.time ?? Infinity;
      if (first < 0 || bricks[first].time >= next) continue;
      app.focusPane = 1;
      replay.enterReplay(); replay.setReplayScope('all'); replay.movePick(pick, app.chart);
      const shade = app.chart2.panes()[app.chart2.primaryPaneIndex()].primitives().find((primitive: unknown) => cuts.has(primitive));
      return { cut: cuts.get(shade), firstOfOpenWeek: first, picking: app.replayPicking, scope: app.replayScope };
    }
    return null;
  });
  expect(found).not.toBeNull();
  expect(found).toMatchObject({ picking: true, scope: 'all' });
  // Every brick the open week formed is behind the veil: its close is still to come.
  expect(found!.cut).toBe(found!.firstOfOpenWeek - 1);
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.screenshot({ path: info.outputPath('replay-pick-weekly-renko.png') });
  expect(errors).toEqual([]);
});
