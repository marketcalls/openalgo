import { strict as assert } from 'node:assert';
import { mkdir } from 'node:fs/promises';
import { chromium, expect } from '@playwright/test';
import { parseCandles, aggregateCandles } from '../website/lib/market-data/btc-usd.mjs';

const base = (process.argv[2] ?? 'http://127.0.0.1:3000/openalgo-charts').replace(/\/$/, '');
await mkdir('artifacts', { recursive: true });
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
  const errors = [];
  const requests = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => { if (response.url().includes('/v2/candles/')) requests.push(response.url()); });
  await page.addInitScript(() => {
    window.__marketTimers = new Set();
    const setTimer = window.setTimeout.bind(window);
    const clearTimer = window.clearTimeout.bind(window);
    window.setTimeout = (callback, delay, ...args) => {
      let id;
      id = setTimer(() => { window.__marketTimers.delete(id); callback(...args); }, delay);
      if (delay === 15000) window.__marketTimers.add(id);
      return id;
    };
    window.clearTimeout = id => { window.__marketTimers.delete(id); return clearTimer(id); };
  });
  const firstResponse = page.waitForResponse(response => response.url().endsWith('/candles/btcusd/1hr'));
  await page.goto(`${base}/`);
  const response = await firstResponse;
  assert.equal(response.status(), 200, 'The real market endpoint must be reachable');
  const initialBars = parseCandles(await response.json());
  const chart = page.getByRole('region', { name: 'Live BTC/USD chart' });
  const status = chart.locator('.oac-market-status');
  await expect(status).toHaveAttribute('data-state', 'connected');
  const quote = price => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(price);
  await expect(chart.locator('.oac-btc-price')).toHaveText(quote(initialBars.at(-1).close));
  await expect(chart.locator('input[aria-label="Symbol: BTC/USD"]')).toHaveJSProperty('readOnly', true);
  assert.ok(!/Sample data|\bDEMO\b/.test(await chart.innerText()));
  await expect(chart.locator('canvas').first()).toBeVisible();

  for (const [interval, label, endpoint] of [['15m', '15m', '15m'], ['4h', '4h', '1hr'], ['1d', 'D', '1day'], ['1h', '1h', '1hr']]) {
    const next = page.waitForResponse(response => response.url().endsWith('/candles/btcusd/' + endpoint));
    await chart.locator('.oac-widget button').filter({ hasText: new RegExp('^' + label + '$') }).click();
    const result = await next;
    assert.equal(result.status(), 200);
    const parsed = parseCandles(await result.json());
    const expected = interval === '4h' ? aggregateCandles(parsed, 14400) : parsed;
    await expect(status).toHaveAttribute('data-state', 'connected');
    await expect(chart.locator('.oac-btc-price')).toHaveText(quote(expected.at(-1).close));
    console.log(interval + ': live response confirmed, ' + expected.length + ' source candles');
  }

  const initialSync = await chart.locator('.oac-btc-source').innerText();
  await expect(chart.locator('.oac-btc-source')).not.toHaveText(initialSync, { timeout: 20000 });
  assert.equal(await page.evaluate(() => window.__marketTimers.size), 1, 'Exactly one market refresh timer');
  const knownQuote = await chart.locator('.oac-btc-price').innerText();
  await page.route('https://api.gemini.com/**', route => route.abort('connectionfailed'));
  await expect(status).toHaveAttribute('data-state', 'stale', { timeout: 20000 });
  await expect(chart.locator('.oac-btc-price')).toHaveText(knownQuote);
  await expect(chart.getByText('Connection interrupted. Showing the last received candles.')).toBeVisible();
  await page.unroute('https://api.gemini.com/**');
  await chart.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(status).toHaveAttribute('data-state', 'connected', { timeout: 15000 });
  await chart.scrollIntoViewIfNeeded();
  await page.screenshot({ path: 'artifacts/homepage-real-btc.png' });

  await page.locator('.nextra-nav-container').getByRole('link', { name: 'Documentation', exact: true }).click();
  await expect(chart).toHaveCount(0);
  assert.equal(await page.evaluate(() => window.__marketTimers.size), 0, 'Leaving the page cancels market polling');
  assert.deepEqual(errors, [], 'No browser exceptions');

  const offline = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await offline.route('https://api.gemini.com/**', route => route.abort('connectionfailed'));
  await offline.goto(`${base}/`);
  const offlineChart = offline.getByRole('region', { name: 'Live BTC/USD chart' });
  await expect(offlineChart.locator('.oac-market-status')).toHaveAttribute('data-state', 'error');
  await expect(offlineChart.getByText('BTC/USD data is unavailable.')).toBeVisible();
  await expect(offlineChart.locator('.oac-btc-price')).toHaveCount(0);
  await offline.unroute('https://api.gemini.com/**');
  await offlineChart.getByRole('button', { name: 'Retry connection' }).click();
  await expect(offlineChart.locator('.oac-market-status')).toHaveAttribute('data-state', 'connected', { timeout: 15000 });
  assert.equal(await offline.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'Mobile viewport does not overflow');
  await offlineChart.scrollIntoViewIfNeeded();
  await offline.screenshot({ path: 'artifacts/homepage-real-btc-mobile.png' });
  console.log('BTC/USD browser verification passed: real history, four timeframes, polling, stale/error recovery, symbol lock, cleanup, mobile. Requests: ' + requests.length);
} finally {
  await browser.close();
}
