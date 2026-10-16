/** Check shared branding in the built documentation and standalone examples. */
import { strict as assert } from 'node:assert';
import { mkdir, readdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { chromium, expect } from '@playwright/test';

const site = (process.argv[2] ?? 'http://127.0.0.1:4196/openalgo-charts').replace(/\/$/, '');
const examples = (process.argv[3] ?? 'http://127.0.0.1:4198').replace(/\/$/, '');
const output = resolve(process.argv[4] ?? 'artifacts/branding-examples');
await mkdir(output, { recursive: true });
const routes = ['/', '/examples/'];
for (const name of await readdir(new URL('../website/pages/docs/', import.meta.url))) {
  if (name.endsWith('.mdx')) routes.push(`/docs/${name.slice(0, -4)}/`);
}
const pages = (await readdir(new URL('../examples/', import.meta.url)))
  .filter(name => name.endsWith('.html') && name !== 'index.html').map(name => `/examples/${name}`);
pages.push('/examples/market-profile/index.html', '/examples/orderflow/index.html');
const result = { website: [], examples: [] };
const browser = await chromium.launch();
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2 });
  await context.addInitScript(() => {
    window.__paintedBrands = new Set();
    const moveTo = CanvasRenderingContext2D.prototype.moveTo;
    CanvasRenderingContext2D.prototype.moveTo = function (x, y) {
      // Identify the built-in vector path without changing the renderer or its pixels.
      if (x === 367.5 && y === 255.5) window.__paintedBrands.add(this.canvas);
      return moveTo.call(this, x, y);
    };
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  for (const route of routes) {
    await page.goto(site + route);
    await expect(page.locator('.oac-example__loading')).toHaveCount(0);
    await expect(page.locator('.oac-example__err')).toHaveCount(0);
    const stages = page.locator('.oac-example__chart, .oac-card__chart');
    for (const stage of await stages.all()) {
      await stage.scrollIntoViewIfNeeded();
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const hasCanvas = await stage.locator('canvas').count();
      if (hasCanvas === 0) continue;
      const manual = await stage.evaluate(node => node.closest('.oac-example')?.textContent.includes('LogoWatermark: a colored badge'));
      if (!manual) await expect.poll(() => stage.evaluate(node => [...window.__paintedBrands].some(canvas => node.contains(canvas)))).toBe(true);
    }
    const brands = await page.evaluate(() => [...window.__paintedBrands].filter(canvas => canvas.isConnected).length);
    result.website.push({ route, stages: await stages.count(), brands });
    assert.deepEqual(errors, [], route);
  }

  await page.goto(site + '/docs/branding-and-watermarks/');
  const demo = page.locator('.oac-example').first();
  await expect(demo.locator('canvas').first()).toBeVisible();
  await demo.getByRole('button', { name: 'Chart settings', exact: true }).first().click();
  await page.getByRole('tab', { name: 'Appearance', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: 'Show watermark', exact: true })).not.toBeChecked();
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await demo.getByRole('button', { name: 'Toggle watermark', exact: true }).click();
  await demo.getByRole('button', { name: 'Automatic or custom text', exact: true }).click();
  await demo.screenshot({ path: resolve(output, 'website-branding-desktop.png') });
  await demo.getByRole('button', { name: 'Width: desktop', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 900 });
  await demo.getByRole('button', { name: 'More', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Chart by OpenAlgo', exact: true }).last()).toBeVisible();
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  await demo.screenshot({ path: resolve(output, 'website-branding-mobile.png') });
  await demo.getByRole('button', { name: 'Logo: on', exact: true }).click();
  await demo.getByRole('button', { name: 'More', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Chart by OpenAlgo', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  await demo.getByRole('button', { name: 'Logo: off', exact: true }).click();

  for (const route of pages) {
    await page.setViewportSize({ width: 1200, height: 800 });
    await page.goto(examples + route);
    await expect.poll(() => page.evaluate(() => [...window.__paintedBrands].filter(canvas => canvas.isConnected).length)).toBeGreaterThan(0);
    const brands = await page.evaluate(() => [...window.__paintedBrands].filter(canvas => canvas.isConnected).length);
    result.examples.push({ route, brands });
    assert.deepEqual(errors, [], route);
  }
  await page.goto(examples + '/examples/orderflow/index.html');
  await expect.poll(() => page.evaluate(() => window.__paintedBrands.size)).toBeGreaterThan(0);
  await page.screenshot({ path: resolve(output, 'orderflow-branding.png') });
  await page.goto(examples + '/examples/market-profile/index.html');
  await expect.poll(() => page.evaluate(() => window.__paintedBrands.size)).toBeGreaterThan(0);
  await page.screenshot({ path: resolve(output, 'market-profile-branding.png') });

  // The website embeds must load the same candidate bytes as the standalone examples.
  for (const name of ['openalgo-charts.mjs', 'openalgo-charts.profile.mjs']) {
    const response = await page.request.get(`${site}/demos/dist/${name}`);
    assert.equal(response.status(), 200);
    assert.deepEqual(await response.body(), await readFile(new URL(`../dist/${name}`, import.meta.url)));
  }
  assert.deepEqual(errors, []);
  await writeFile(resolve(output, 'report.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(`PASS ${result.website.length} website routes and ${result.examples.length} standalone examples`);
} finally {
  await browser.close();
}
