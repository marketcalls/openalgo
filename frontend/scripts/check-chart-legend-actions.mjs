/**
 * Real-page acceptance extension for Charts scripts/check-openalgo-compat.mjs.
 * Pass --consumer-checks <this file> against an isolated frontend worktree.
 * The parent runner mocks trading traffic; this extension mocks Historify reads.
 * Widget observation is injected into the served module only, never app source.
 */
import assert from 'node:assert/strict';
import { resolve } from 'node:path';

export async function checkTradingWorkspace({ page, check, expect, report, reload, output }) {
  const artifact = suffix => resolve((output ?? 'chart-legend.json').replace(/\.json$/, '') + suffix);
  const paint = () => page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
  const writes = () => report.requests.filter(r => /\/(placeorder|placesmartorder|modifyorder|cancelorder|cancelallorder|closeposition)$/.test(r.path)).length;
  const initialWrites = writes();
  const theme = async (mode, appMode = 'live') => {
    await page.evaluate(async ({ mode, appMode }) => {
      const { useThemeStore } = await import('/src/stores/themeStore.ts');
      useThemeStore.getState().setAppMode('live');
      useThemeStore.getState().setMode(mode);
      useThemeStore.getState().setAppMode(appMode);
    }, { mode, appMode });
    await paint();
  };
  const setup = async host => {
    await page.waitForFunction(host => {
      const owner = host === 'trading'
        ? window.__compatTerminals.find(t => !t.destroyed && t.chart)
        : window.__historifyWidgets?.at(-1);
      return owner?.chart.primaryBars().length > 30;
    }, host);
    await page.evaluate(host => {
      const owner = host === 'trading'
        ? window.__compatTerminals.find(t => !t.destroyed && t.chart)
        : window.__historifyWidgets.at(-1);
      const chart = owner.chart;
      const study = chart.addIndicator('macd');
      const count = chart.primaryBars().length;
      chart.setVisibleLogicalRange({ from: Math.max(0, count - 100), to: count + 5 });
      window.__legendCheck = { owner, chart, study, hover: null, host };
      chart.on('hover', e => { window.__legendCheck.hover = e.id; });
    }, host);
    await paint();
  };
  const geometry = () => page.evaluate(() => {
    const { chart, study, hover } = window.__legendCheck;
    const legend = study.legend();
    const pane = chart.panes()[study.paneIndex].element.getBoundingClientRect();
    const options = legend.options();
    return {
      row: { x: pane.left + 40, y: pane.top + (options.top ?? 6) + (options.row ?? 0) * 18 + 8 },
      buttons: legend._buttons.map(b => ({ id: b.id, x: pane.left + b.x + 8, y: pane.top + b.y + 8 })),
      values: legend._values.map(v => v.text), hover,
    };
  });
  const exercise = async (host, label, width) => {
    await page.setViewportSize({ width, height: 1000 });
    await paint();
    await setup(host);
    const row = (await geometry()).row;
    await page.mouse.move(row.x, row.y);
    await paint();
    const before = await geometry();
    const gear = before.buttons.find(b => b.id.endsWith('::settings'));
    assert(gear, 'Selected indicator exposes Settings');
    await page.mouse.move(gear.x, gear.y);
    await paint();
    const after = await geometry();
    (report.legendActions ??= []).push({ host, label, width, before, after });
    assert.notDeepEqual(after.values, before.values, 'Moving across bars changes the readings');
    for (const offset of [-4, 0, 4, 0]) {
      await page.mouse.move(gear.x + offset, gear.y);
      await paint();
      const actual = await geometry();
      assert.deepEqual(actual.buttons, before.buttons, 'Readings must not move any control');
      assert.equal(actual.hover, gear.id, 'Stationary pointer retains the settings hit target');
    }
    await page.screenshot({ path: artifact(`-${host}-${label}-${width}.png`), fullPage: true });
    await page.mouse.click(gear.x, gear.y);
    const dialog = host === 'historify' ? page.locator('.oac-indset')
      : page.getByRole('presentation').filter({ hasText: 'MACD', has: page.getByRole('button', { name: 'Close', exact: true }) });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText(/MACD/i);
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();
    const hide = before.buttons.find(b => b.id.endsWith('::hide'));
    await page.mouse.move(hide.x, hide.y);
    await paint();
    await page.mouse.click(hide.x, hide.y);
    assert.equal(await page.evaluate(() => window.__legendCheck.study.visible()), false);
    await paint();
    assert.deepEqual((await geometry()).buttons, before.buttons);
    await page.mouse.click(hide.x, hide.y);
    assert.equal(await page.evaluate(() => window.__legendCheck.study.visible()), true);
    const close = before.buttons.find(b => b.id.endsWith('::close'));
    await page.mouse.move(close.x, close.y);
    await paint();
    await page.mouse.click(close.x, close.y);
    assert.equal(await page.evaluate(() => window.__legendCheck.chart.indicators().some(i => i.id === window.__legendCheck.study.id)), false);
  };

  await page.getByRole('button', { name: /^Chart layout:/ }).click();
  await page.getByTitle('Single', { exact: true }).click();
  await page.waitForFunction(() => window.__compatTerminals.filter(t => !t.destroyed && t.chart).length === 1);
  for (const [mode, appMode, width] of [['dark', 'live', 1440], ['light', 'live', 480], ['dark', 'analyzer', 1440]]) {
    await check(`trading stationary legend and settings, visibility, removal: ${appMode} ${mode} ${width}`, async () => {
      await theme(mode, appMode);
      await exercise('trading', `${appMode}-${mode}`, width);
    });
  }
  await theme('dark');
  await page.setViewportSize({ width: 1440, height: 1000 });

  // Observe only the real widget created by the application. Routing the Vite
  // module keeps this hook out of the production bundle and saved layouts.
  await page.route('**/src/components/chart/OpenAlgoChart.tsx*', async route => {
    const response = await route.fetch();
    const source = await response.text();
    const target = /widgetRef\.current\s*=\s*widget;/;
    assert(target.test(source), 'Widget observation point still exists');
    await route.fulfill({ response, body: source.replace(target,
      '$& (window.__historifyWidgets ??= []).push(widget);') });
  });
  const rows = Array.from({ length: 240 }, (_, i) => ({
    timestamp: Date.parse('2026-09-08T03:45:00Z') / 1000 + i * 300,
    open: 100 + Math.sin(i / 7) * 5, high: 107, low: 93,
    close: 101 + Math.sin(i / 7) * 5, volume: 1000 + i * 10,
  }));
  const catalog = [{ symbol: 'BHEL', exchange: 'NSE', interval: '1m', name: 'Bharat Heavy Electricals',
    lotsize: 1, tick_size: 0.05, first_timestamp: rows[0].timestamp,
    last_timestamp: rows.at(-1).timestamp, record_count: rows.length }];
  const historyRequests = [];
  await page.route('**/historify/api/**', async route => {
    const req = route.request();
    const url = new URL(req.url());
    historyRequests.push({ path: url.pathname, method: req.method() });
    const data = url.pathname.endsWith('/data') ? rows : catalog;
    await route.fulfill({ json: { status: 'success', data } });
  });
  await page.goto(new URL('/historify/charts/BHEL?exchange=NSE&interval=5m', page.url()).href);
  await page.waitForFunction(() => window.__historifyWidgets?.at(-1)?.chart.primaryBars().length > 30);
  for (const [mode, width] of [['dark', 1440], ['light', 480]]) {
    await check(`Historify stationary legend and selected settings, visibility, removal: ${mode} ${width}`, async () => {
      await theme(mode);
      await exercise('historify', mode, width);
    });
  }
  await check('Historify saved studies restore and remain read-only', async () => {
    await setup('historify');
    await page.evaluate(() => window.__legendCheck.study.setSettings({ fastPeriod: 8 }));
    await expect.poll(() => page.evaluate(() => JSON.stringify(
      window.__legendCheck.owner.context.storage.get('state')).includes('"fastPeriod":8'))).toBe(true);
    await page.evaluate(() => window.__legendCheck.owner.context.storage.flush());
    await reload();
    await page.waitForFunction(() => window.__historifyWidgets?.at(-1)?.chart.primaryBars().length > 30);
    await expect.poll(() => page.evaluate(() => window.__historifyWidgets.at(-1).chart.indicators().some(i => i.indicatorId === 'macd' && i.settings().fastPeriod === 8))).toBe(true);
    assert(historyRequests.length > 0 && historyRequests.every(r => r.method === 'GET'));
    assert.equal(writes(), initialWrites, 'Chart controls must never send an order write');
    report.historifyRequests = historyRequests;
  });
}
