/** Custom interval acceptance against the actual trading and stored-history routes. */
import assert from 'node:assert/strict';
import { resolve } from 'node:path';

const DAY = 86400, IST = 19800;
const NOW = Date.parse('2026-09-10T06:32:00Z') / 1000;
const daily = [], minutes = [];
for (let day = Date.parse('2023-01-02') / 1000, i = 0; day < NOW; day += DAY, i++) {
  const weekday = new Date(day * 1000).getUTCDay();
  if (weekday === 0 || weekday === 6) continue;
  const price = 100 + Math.sin(i / 11) * 4 + i * 0.01;
  daily.push({ time: day - IST, open: price, high: price + 3, low: price - 2, close: price + 1, volume: 37500 });
  if (day < NOW - 7 * DAY) continue;
  for (let time = day + 13500, n = 0; time < Math.min(day + 36000, NOW); time += 60, n++) {
    const close = price + Math.sin(n / 15);
    minutes.push({ time, open: close - 0.1, high: close + 0.2, low: close - 0.2, close, volume: 100 });
  }
}
function aggregate(interval) {
  if (interval === 'D') return daily;
  if (interval === '1m') return minutes;
  const match = /^(\d+)([mh])$/.exec(interval);
  const groups = new Map();
  for (const bar of match ? minutes : daily) {
    const date = new Date((bar.time + IST) * 1000);
    let time;
    if (match) {
      const seconds = +match[1] * (match[2] === 'h' ? 3600 : 60);
      const open = Math.floor((bar.time + IST) / DAY) * DAY + 13500;
      time = open + Math.floor((bar.time - open) / seconds) * seconds;
    } else if (interval === 'W') {
      time = (Math.floor((bar.time + IST) / DAY) - (date.getUTCDay() + 6) % 7) * DAY - IST;
    } else {
      const count = interval === 'Q' ? 3 : interval === 'Y' ? 12 : Number(interval.replace('M', '')) || 1;
      const month = Math.floor((date.getUTCFullYear() * 12 + date.getUTCMonth()) / count) * count;
      time = Date.UTC(Math.floor(month / 12), month % 12, 1) / 1000 - IST;
    }
    const old = groups.get(time);
    if (old) { old.high = Math.max(old.high, bar.high); old.low = Math.min(old.low, bar.low); old.close = bar.close; old.volume += bar.volume; }
    else groups.set(time, { ...bar, time });
  }
  return [...groups.values()];
}
export async function checkTradingWorkspace({ page, check, expect, report, reload, screenshot }) {
  const evidence = report.customTimeframes = { wires: [], ema: [], screenshots: [] };
  const shot = async label => {
    if (!screenshot) return;
    const path = resolve(screenshot.replace(/\.png$/, `-${label}.png`));
    await page.screenshot({ path, fullPage: true, animations: 'disabled' }); evidence.screenshots.push(path);
  };
  await page.route('**/*', async route => {
    const url = new URL(route.request().url()), path = url.pathname;
    let data;
    if (path === '/admin/api/timings') data = ['NSE', 'BSE', 'NFO'].map(exchange => ({ exchange, start_offset: 33300000, end_offset: 55800000 }));
    else if (path === '/api/v1/market/holidays') data = [];
    else if (path === '/api/v1/intervals') data = { minutes: ['1m', '5m'], hours: ['1h'], days: ['D'] };
    else if (path === '/historify/api/catalog/metadata' || path === '/historify/api/catalog') data = ['1m', 'D'].map(interval => ({ symbol: 'BHEL', exchange: 'NSE', interval, name: 'Bharat Heavy Electricals', record_count: 1000, first_timestamp: (interval === 'D' ? daily : minutes)[0].time, last_timestamp: (interval === 'D' ? daily : minutes).at(-1).time }));
    else if (path === '/api/v1/history' || path === '/historify/api/data') {
      const body = path === '/api/v1/history' ? route.request().postDataJSON() : Object.fromEntries(url.searchParams);
      const from = Date.parse(body.start_date) / 1000 - DAY, to = Date.parse(body.end_date) / 1000 + 2 * DAY;
      evidence.wires.push({ path, interval: body.interval, from, to });
      const calendarWire = path === '/historify/api/data' && !/^[0-9]+[mh]$/.test(body.interval) && body.interval !== 'D';
      data = aggregate(body.interval).filter(bar => (!Number.isFinite(from) || bar.time >= from) && (!Number.isFinite(to) || bar.time < to)).map(bar => ({ ...bar, timestamp: bar.time + (calendarWire ? IST : 0), oi: 0 }));
    } else return route.fallback();
    return route.fulfill({ json: { status: 'success', data } });
  });
  const live = () => page.evaluate(() => window.__compatTerminals.filter(t => !t.destroyed && t.chart).map(t => ({ interval: t.interval, count: t.price.getData().length })));
  const ready = code => page.waitForFunction(code => {
    const t = window.__compatTerminals.filter(t => !t.destroyed && t.chart)[0];
    return t && !t.dataUnavailable() && t.chart.getDataContext()?.interval === t.interval && t.price.getData().length > 1 && (!code || t.interval === code);
  }, code);
  const add = async (unit, count, button) => {
    await (button ?? page.getByRole('button', { name: /^Interval / }).first()).click();
    await page.getByRole('button', { name: 'Add custom interval', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Add custom interval', exact: true });
    await dialog.getByLabel('Type', { exact: true }).selectOption(unit);
    await dialog.getByLabel('Interval', { exact: true }).fill(count);
    await dialog.getByRole('button', { name: 'Add', exact: true }).click();
  };
  await page.evaluate(() => {
    for (const key of Object.keys(localStorage)) if (key.startsWith('oa-trading-') || key === 'openalgo-chart-timeframes') localStorage.removeItem(key);
  });
  await reload(); await ready();
  const dark = page.getByRole('button', { name: 'Switch to dark mode', exact: true });
  if (await dark.count()) await dark.click();
  await check('custom trading intervals derive 7m from minute candles and persist favorites', async () => {
    await add('minutes', '7'); await ready('7m');
    const bars = await page.evaluate(() => window.__compatTerminals.find(t => !t.destroyed && t.chart).price.getData());
    assert.deepEqual(bars[0], aggregate('7m').find(bar => bar.time === bars[0].time));
    await page.getByRole('button', { name: 'Interval 7m', exact: true }).click();
    const pick = page.getByRole('button', { name: '7 minutes', exact: true });
    await pick.scrollIntoViewIfNeeded();
    await page.evaluate(() => Promise.all(document.getAnimations().map(animation => animation.finished.catch(() => {}))));
    const before = await pick.boundingBox();
    await pick.hover(); assert.deepEqual(await pick.boundingBox(), before);
    await page.getByRole('button', { name: 'Add 7 minutes to favorites', exact: true }).click();
    await shot('trading-picker-dark'); await page.keyboard.press('Escape');
    await reload(); await ready('7m');
    await expect(page.getByRole('button', { name: 'Favorite interval 7m', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Interval 7m', exact: true }).click();
    await page.getByRole('button', { name: 'Remove 7 minutes', exact: true }).click();
    assert.equal((await live())[0].interval, '7m');
    await page.keyboard.press('Escape');
  });
  await check('custom trading hours and calendar periods use compatible native sources', async () => {
    for (const [unit, count, code] of [['hours', '2', '2h'], ['weeks', '1', 'W'], ['months', '1', 'M'], ['quarters', '1', 'Q']]) {
      await add(unit, count); await ready(code);
    }
    assert(evidence.wires.some(w => w.interval === '1h'));
    assert(evidence.wires.some(w => w.interval === 'D'));
    assert(!evidence.wires.some(w => ['7m', '2h', 'W', 'M', 'Q'].includes(w.interval)));
  });
  const ema = async host => {
    await page.evaluate(host => {
      const entry = host === 'trading'
        ? (() => { const t = window.__compatTerminals.find(t => !t.destroyed && t.chart); return { chart: t.chart, provider: t.timeframes.provider }; })()
        : window.__compatCharts.findLast(e => !e.chart.isDestroyed && e.chart.primaryBars().length > 10);
      if (!entry) throw Error('Chart/provider observer is missing');
      window.__customEntry = entry;
      for (const study of [...entry.chart.indicators()]) study.remove();
      window.__customEma = entry.chart.addIndicator('ema', { length: 200, timeframe: 'D', color: '#ff00ff', 'ma:color': '#ff00ff', 'ma:width': 3 });
    }, host);
    await page.waitForFunction(() => window.__customEma.dataStatus()?.state === 'ready');
    const result = await page.evaluate(async () => {
      const { chart, provider } = window.__customEntry, bars = chart.primaryBars(), engine = window.__compatEngine;
      const snapshot = await provider.requestSnapshot({ ...chart.getDataContext(), interval: 'D', from: bars[0].time, to: bars.at(-1).time + 1, warmupBars: 200 });
      const descriptor = engine.getIndicator('ema');
      const expected = descriptor.calc(snapshot.bars, { ...engine.indicatorDefaults(descriptor), length: 200, timeframe: '' }, {}).ma;
      const actual = window.__customEma.values().ma;
      let matches = 0;
      for (let i = 0; i < bars.length; i++) {
        let at = -1;
        for (let j = 0; j < snapshot.bars.length; j++) if (snapshot.confirmed[j] && snapshot.availableAt[j] != null && snapshot.availableAt[j] <= bars[i].time) at = j;
        if (at >= 0 && expected[at] != null && actual[i] != null && Math.abs(expected[at] - actual[i]) < 1e-8) matches++;
      }
      return { bars: bars.length, daily: snapshot.bars.length, matches };
    });
    assert(result.daily >= 200); assert(result.bars > 10); assert.equal(result.matches, result.bars);
    await expect.poll(() => page.evaluate(() => {
      const { ctx, element } = window.__customEntry.chart.panes()[0].base;
      const pixels = ctx.getImageData(0, 0, element.width, element.height).data;
      let count = 0;
      for (let i = 0; i < pixels.length; i += 4) if (pixels[i] > 210 && pixels[i + 1] < 70 && pixels[i + 2] > 210) count++;
      return count;
    })).toBeGreaterThan(100);
    evidence.ema.push({ host, ...result }); await shot(`${host}-daily-ema-200`);
  };
  await check('trading daily EMA 200 uses independent confirmed history on 5m', async () => {
    await page.evaluate(() => window.__compatTerminals.find(t => !t.destroyed && t.chart).setInterval('5m')); await ready('5m');
    await ema('trading');
  });
  await check('mobile interval dialog fits and refuses seconds without a seconds source', async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('button', { name: 'Interval 5m', exact: true }).click();
    await page.getByRole('button', { name: 'Add custom interval', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Add custom interval' });
    await dialog.getByLabel('Type', { exact: true }).selectOption('seconds'); await dialog.getByLabel('Interval', { exact: true }).fill('5');
    await expect(dialog.getByRole('button', { name: 'Add', exact: true })).toBeDisabled();
    const box = await dialog.boundingBox(); assert(box.x >= 0 && box.x + box.width <= 390);
    await shot('trading-mobile-custom'); await dialog.getByRole('button', { name: 'Cancel' }).click();
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  await check('trading custom favorites stay shared while selection remains pane-owned', async () => {
    await page.getByRole('button', { name: /^Chart layout:/ }).click();
    await page.getByTitle('2 columns', { exact: true }).click();
    await page.waitForFunction(() => window.__compatTerminals.filter(t => !t.destroyed && t.chart && !t.dataUnavailable()).length === 2);
    await page.evaluate(() => window.__compatTerminals.filter(t => !t.destroyed && t.chart)[0].container.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true })));
    const before = (await live())[1].interval;
    await add('minutes', '11'); await ready('11m');
    assert.equal((await live())[1].interval, before);
    await page.getByRole('button', { name: 'Interval 11m', exact: true }).click();
    await page.getByRole('button', { name: 'Add 11 minutes to favorites', exact: true }).click(); await page.keyboard.press('Escape');
    await page.evaluate(() => window.__compatTerminals.filter(t => !t.destroyed && t.chart)[1].container.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true })));
    await expect(page.getByRole('button', { name: 'Favorite interval 11m', exact: true })).toBeVisible();
    assert.equal((await live())[1].interval, before);
    const light = page.getByRole('button', { name: 'Switch to light mode', exact: true });
    if (await light.count()) await light.click();
    await shot('trading-two-panes-light');
  });
  await check('custom interval controls render in analyzer mode', async () => {
    await page.route('**/auth/analyzer-mode', route => route.fulfill({ json: { status: 'success', data: { analyze_mode: true } } }));
    await page.evaluate(async () => {
      const { useThemeStore } = await import('/src/stores/themeStore.ts');
      useThemeStore.getState().setAppMode('analyzer');
    });
    await expect(page.locator('html')).toHaveClass(/analyzer/);
    await page.getByRole('button', { name: /^Interval / }).first().click();
    await expect(page.getByRole('button', { name: 'Add custom interval', exact: true })).toBeVisible();
    await shot('trading-analyzer-picker'); await page.keyboard.press('Escape');
    await page.unroute('**/auth/analyzer-mode');
    await page.evaluate(async () => {
      const { useThemeStore } = await import('/src/stores/themeStore.ts');
      useThemeStore.getState().setAppMode('live');
    });
  });
  await reload(new URL('/historify/charts/BHEL?exchange=NSE&interval=5m', page.url()).href);
  const storedReady = code => page.waitForFunction(code => window.__compatCharts?.some(e => !e.chart.isDestroyed && e.chart.getDataContext()?.interval === code && e.chart.primaryBars().length > 10), code);
  await storedReady('5m');
  await expect(page.getByRole('button', { name: 'Favorite interval 11m', exact: true })).toBeVisible();
  await check('Historify displays daily EMA 200 on 5m from its stored daily history', async () => { await ema('historify'); });
  await check('Historify shares custom favorites, supports removal, and restores its interval', async () => {
    await add('minutes', '7'); await storedReady('7m');
    await page.getByRole('button', { name: 'Interval 7m', exact: true }).click();
    await page.getByRole('button', { name: 'Add 7 minutes to favorites', exact: true }).click();
    await shot('historify-picker'); await page.keyboard.press('Escape');
    await reload(); await storedReady('7m');
    await expect(page.getByRole('button', { name: 'Favorite interval 7m', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Interval 7m', exact: true }).click();
    await page.getByRole('button', { name: 'Remove 7 minutes', exact: true }).click();
    await page.keyboard.press('Escape'); await storedReady('7m');
  });
  await check('Historify multiple panes share favorites without changing the other interval', async () => {
    await page.getByRole('button', { name: 'Chart layout', exact: true }).click();
    await page.getByTitle('2 columns', { exact: true }).click();
    await page.getByRole('button', { name: 'Select symbol', exact: true }).click();
    await page.getByPlaceholder('Search downloaded symbols').fill('BHEL');
    await page.getByRole('option').filter({ hasText: 'BHEL' }).click();
    await page.waitForFunction(() => new Set(window.__compatCharts.filter(e => !e.chart.isDestroyed && e.chart.primaryBars().length > 0).map(e => e.chart)).size === 2);
    const second = page.getByRole('button', { name: /^Interval / }).nth(1);
    const before = await second.getAttribute('aria-label');
    await add('minutes', '13'); await storedReady('13m');
    await expect(second).toHaveAttribute('aria-label', before);
    await page.getByRole('button', { name: 'Interval 13m', exact: true }).click();
    await page.getByRole('button', { name: 'Add 13 minutes to favorites', exact: true }).click(); await page.keyboard.press('Escape');
    await expect(page.getByRole('button', { name: 'Favorite interval 13m', exact: true })).toHaveCount(2);
    const bounds = await page.getByRole('application').evaluateAll(nodes =>
      nodes.map(root => {
        const rect = root.getBoundingClientRect();
        return { left: rect.left, right: rect.right, width: rect.width, viewport: innerWidth };
      }));
    expect(bounds).toHaveLength(2);
    for (const rect of bounds) {
      expect(rect.left).toBeGreaterThanOrEqual(0);
      expect(rect.right).toBeLessThanOrEqual(rect.viewport);
      expect(rect.width).toBeGreaterThan(300);
    }
    await shot('historify-two-panes');
  });
}
