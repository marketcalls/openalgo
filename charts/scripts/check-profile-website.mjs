/** Browser checks against the built website, including its embedded demo. */
import { strict as assert } from 'node:assert';
import { mkdir, readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { chromium, expect } from '@playwright/test';

const base = (process.argv[2] ?? 'http://127.0.0.1:4174/openalgo-charts').replace(/\/$/, '');
const manifest = JSON.parse(await readFile(new URL('../website/public/screenshots/market-profile-v2.1.1/captures.json', import.meta.url), 'utf8'));
const { version } = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'));
assert.equal(existsSync(new URL('../website/public/screenshots/market-profile/', import.meta.url)), false, 'Remove the legacy screenshot directory');
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
for (const [path, hash] of Object.entries(manifest.sources)) {
  assert.equal(digest(await readFile(new URL(`../${path}`, import.meta.url))), hash, `Regenerate screenshots after changing ${path}`);
}
await mkdir('artifacts', { recursive: true });
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  // The embedded demos open in the palette that matches the site theme. This
  // run checks the dark palettes, so it chooses the dark site the way a reader
  // would; the light default is checked on its own page further down.
  await page.addInitScript(() => localStorage.setItem('oac-theme', 'dark'));
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  for (const file of [...Object.values(manifest.captures).map(capture => capture.file), 'captures.json']) {
    const oldImage = await page.request.get(`${base}/screenshots/market-profile/${file}`);
    assert.equal(oldImage.status(), 404, `Legacy image URL must no longer be published: ${file}`);
  }
  await page.goto(`${base}/docs/market-profile-examples/`);
  await expect(page.getByRole('heading', { level: 1, name: 'Profile demo & themes' })).toBeVisible();
  await expect(page.locator('.oac-profile-gallery .oac-profile-shot')).toHaveCount(5);
  const images = await page.locator('.oac-profile-shot img, .oac-profile-overview img').evaluateAll(nodes => nodes.map(node => node.src));
  assert.equal(images.length, 8);
  for (const src of images) {
    const response = await page.request.get(src);
    assert.equal(response.status(), 200, src);
    const body = await response.body();
    assert.equal(body.subarray(1, 4).toString(), 'PNG', src);
    const name = new URL(src).pathname.split('/').at(-1).replace('.png', '');
    const capture = manifest.captures[name];
    assert.ok(capture, src);
    assert.equal(body.readUInt32BE(16), capture.width, src);
    assert.equal(body.readUInt32BE(20), capture.height, src);
    assert.equal(digest(body), capture.sha256, src);
    assert.equal(new URL(src).searchParams.get('v'), capture.sha256.slice(0, 12), 'Screenshot URLs must change with their pixels');
  }
  const iframe = page.locator('iframe[title="Interactive compact market profile demo"]');
  await iframe.scrollIntoViewIfNeeded();
  const frame = await (await iframe.elementHandle()).contentFrame();
  assert.ok(frame);
  assert.equal(await frame.evaluate(async () => (await import(new URL('../dist/openalgo-charts.mjs', location.href).href)).version()), version, 'Embedded demo must use the current library build');
  await expect(frame.locator('#theme')).toHaveValue('blue');
  await expect(frame.locator('#block')).toHaveValue('compact');
  await expect(frame.locator('#markers')).toBeChecked();
  await frame.locator('#compressed').click();
  await frame.waitForFunction(() => {
    const chart = window.__chart();
    const s = window.__profileResult().sessions[5];
    return window.__mp().hoverAt(chart.timeScale.indexToX(375) + 18,
      chart.panes()[0].priceScale.priceToY(s.poc))?.sessionIndex === 5;
  });
  const rightClick = async () => {
    const point = await frame.evaluate(() => {
      const chart = window.__chart();
      return { x: chart.timeScale.indexToX(375) + 18,
        y: chart.panes()[0].priceScale.priceToY(window.__profileResult().sessions[5].poc) };
    });
    await frame.locator('#chart').click({ button: 'right', position: point });
  };
  const before = await frame.evaluate(() => JSON.stringify(window.__profileResult()));
  await rightClick();
  await frame.getByRole('menuitem', { name: 'Split this day', exact: true }).click();
  for (const theme of ['ivory', 'graphite', 'emerald', 'dark', 'blue']) {
    await frame.locator('#theme').selectOption(theme);
    assert.deepEqual(await frame.evaluate(() => window.__profileResult().sessions.map((_, i) => window.__mp().isSessionSplit(i))),
      [false, false, false, false, false, true]);
  }
  assert.equal(await frame.evaluate(() => JSON.stringify(window.__profileResult())), before);
  await rightClick();
  await frame.getByRole('menuitem', { name: 'Unsplit this day', exact: true }).click();
  assert.equal(await frame.evaluate(() => window.__mp().isSessionSplit(5)), false);
  await page.screenshot({ path: 'artifacts/website-profile-demo.png' });

  await page.locator('#five-themes').scrollIntoViewIfNeeded();
  await page.screenshot({ path: 'artifacts/website-profile-themes.png' });
  await page.goto(`${base}/docs/market-profile/`);
  await expect(page.getByRole('heading', { level: 1, name: 'Market Profile (TPO)' })).toBeVisible();
  await expect(page.locator('.oac-profile-gallery .oac-profile-shot')).toHaveCount(5);
  await expect(page.locator('.oac-profile-overview img')).toHaveCount(1);
  await expect(page.locator('.oac-example__loading')).toHaveCount(0);
  await expect(page.locator('.oac-example__err')).toHaveCount(0);
  await expect(page.locator('.oac-example__chart')).toHaveCount(3);
  for (const chart of await page.locator('.oac-example__chart').all()) {
    await expect(chart.locator('canvas').first()).toBeVisible();
  }
  const sources = await page.locator('.oac-example__code').allTextContents();
  assert.match(sources[0], /blockDisplay: 'compact'/);
  assert.match(sources[1], /blockDisplay: 'compact'/);
  assert.match(sources[2], /blockDisplay: 'blocks'/, 'Keep the deliberate heat-block comparison');
  await page.screenshot({ path: 'artifacts/website-market-profile-guide.png', fullPage: true });
  await page.goto(`${base}/examples/`);
  await expect(page.getByRole('heading', { name: /^Compact market profiles/ })).toBeVisible();
  await expect(page.locator('.oac-profile-gallery .oac-profile-shot')).toHaveCount(5);
  await page.goto(`${base}/docs/release-notes/`);
  await expect(page.getByRole('heading', { name: new RegExp(`^${version.replaceAll('.', '\\.')}`) })).toBeVisible();
  await page.goto(`${base}/`);
  await expect(page.getByRole('link', { name: 'Explore the profile demo' })).toHaveCount(0);
  await expect(page.locator('img[src*="screenshots/market-profile"]')).toHaveCount(0);
  await expect(page.locator('.oac-profile-demo')).toHaveCount(0);
  await page.screenshot({ path: 'artifacts/website-profile-home.png', fullPage: true });
  const api = await page.request.get(`${base}/api/classes/profile.MarketProfile.html`);
  assert.equal(api.status(), 200);
  assert.match(await api.text(), /setSessionSplit/);
  assert.match(await api.text(), /isSessionSplit/);
  await page.goto(`${base}/docs/profiles-and-orderflow/`);
  const standaloneLinks = await page.locator('a[href*="/demos/"]').evaluateAll(nodes => nodes.map(node => node.href));
  assert.ok(standaloneLinks.length >= 2, 'Orderflow guide must link to its standalone demos');
  for (const href of standaloneLinks) {
    assert.ok(!href.includes('/openalgo-charts/openalgo-charts/'), `Standalone links must apply the website base path once: ${href}`);
    assert.equal((await page.request.get(new URL(href, base).href)).status(), 200, href);
  }
  const orderflowEmbed = page.locator('iframe[title="Interactive footprint chart with profile, cluster ladder and heatmap styles"]');
  await orderflowEmbed.scrollIntoViewIfNeeded();
  const orderflow = await (await orderflowEmbed.elementHandle()).contentFrame();
  assert.ok(orderflow);
  await orderflow.waitForFunction(() => typeof window.__footprint === 'function');
  assert.equal(await orderflow.evaluate(async () => (await import(new URL('../dist/openalgo-charts.mjs', location.href).href)).version()), version);
  await expect(orderflow.locator('#chart canvas').first()).toBeVisible();
  await expect(orderflow.locator('#theme')).toHaveValue('midnight');
  await expect(orderflow.locator('#play')).toHaveText('Resume');
  await expect(orderflow.locator('#group')).toHaveValue('2');
  await expect(orderflow.locator('#table')).not.toBeChecked();
  await expect(orderflow.locator('#units')).toHaveValue('raw');
  await expect(orderflow.locator('#lot-size')).toHaveValue('65');
  assert.deepEqual(await orderflow.evaluate(() => window.__footprint().options().tableRows), []);
  const rawData = await orderflow.evaluate(() => JSON.stringify({ data: window.__orderflowData(), stats: window.__footprint().stats() }));
  for (const style of ['profile', 'ladder', 'heatmap']) await orderflow.locator('#style').selectOption(style);
  for (const theme of ['midnight', 'graphite', 'classic', 'ocean', 'ivory']) await orderflow.locator('#theme').selectOption(theme);
  for (const mode of ['contrast', 'side', 'delta', 'dominant', 'imbalance', 'volume']) await orderflow.locator('#text').selectOption(mode);
  await orderflow.locator('#style').selectOption('profile');
  await orderflow.locator('#theme').selectOption('midnight');
  await orderflow.locator('#text').selectOption('contrast');
  await page.screenshot({ path: 'artifacts/website-orderflow-embed.png' });
  await orderflow.locator('#table').check();
  const tableRows = ['delta', 'minDelta', 'maxDelta', 'cvd', 'askVolume', 'bidVolume', 'volume'];
  assert.deepEqual(await orderflow.evaluate(() => window.__footprint().options().tableRows), tableRows);
  await expect(orderflow.locator('input[name="table-row"]:checked')).toHaveCount(7);
  const range = await orderflow.evaluate(() => window.__chart().timeScale.visibleRange());
  await orderflow.locator('#units').selectOption('lots');
  assert.equal(await orderflow.evaluate(() => window.__footprint().options().volumeDivisor), 65);
  await expect(orderflow.locator('#volume-label')).toContainText('LOTS');
  await expect(orderflow.locator('#s-vol')).toHaveText(await orderflow.evaluate(() => String(window.__footprint().stats().at(-1).volume / 65)));
  assert.equal(await orderflow.evaluate(() => JSON.stringify({ data: window.__orderflowData(), stats: window.__footprint().stats() })), rawData, 'Table, styles and lots must preserve raw executions and analytics');
  assert.deepEqual(await orderflow.evaluate(() => window.__chart().timeScale.visibleRange()), range, 'Changing quantity units must preserve the viewport');
  await orderflow.locator('footer').scrollIntoViewIfNeeded();
  await page.screenshot({ path: 'artifacts/website-orderflow-table-lots.png' });
  await orderflow.locator('#units').selectOption('raw');
  assert.equal(await orderflow.evaluate(() => window.__footprint().options().volumeDivisor), 1);
  await orderflow.locator('#table').uncheck();
  assert.deepEqual(await orderflow.evaluate(() => window.__footprint().options().tableRows), []);
  await orderflow.locator('#table').check();
  assert.deepEqual(await orderflow.evaluate(() => window.__footprint().options().tableRows), tableRows, 'Toggling the table must remember its selected metrics');
  for (const width of [390, 768]) {
    await page.setViewportSize({ width, height: 1000 });
    await orderflowEmbed.scrollIntoViewIfNeeded();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `Orderflow docs at ${width}px must not overflow horizontally`);
    await expect(orderflow.locator('#chart canvas').first()).toBeVisible();
  }
  for (const route of ['/docs/market-profile/', '/docs/market-profile-examples/', '/examples/']) {
    await page.goto(`${base}${route}`);
    for (const width of [320, 390, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      const shots = page.locator('.oac-profile-shot img');
      for (const shot of await shots.all()) {
        await shot.scrollIntoViewIfNeeded();
        await expect(shot).toBeVisible();
        await shot.evaluate(node => node.decode());
        const metrics = await shot.evaluate(node => ({ width: node.getBoundingClientRect().width, sourceWidth: node.naturalWidth }));
        assert.equal(metrics.sourceWidth, 800);
        // Captures use 16 CSS pixel letters at DPR 2. Check the actual rendered
        // font size, including responsive card and thumbnail scaling.
        assert.ok(32 * metrics.width / metrics.sourceWidth >= 12.7, `${route} at ${width}px must keep readable letters`);
      }
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${route} at ${width}px must not overflow horizontally`);
      if (route === '/docs/market-profile-examples/' && (width === 390 || width === 1440)) {
        await shots.nth(1).scrollIntoViewIfNeeded();
        await page.screenshot({ path: `artifacts/website-profile-gallery-${width}.png` });
      }
    }
  }
  // With no saved choice the site opens light, and both embedded demos open in
  // their light Ivory palettes instead of a dark panel on a white page.
  const light = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  light.on('pageerror', error => errors.push(error.message));
  await light.goto(`${base}/docs/market-profile-examples/`);
  await expect(light.locator('html')).toHaveClass(/(?:^|\s)light(?:\s|$)/);
  await expect(light.getByRole('link', { name: /^Open full-size demo/ })).toHaveAttribute('href', /[?&]theme=ivory(?:&|$)/);
  const lightProfile = light.locator('iframe[title="Interactive compact market profile demo"]');
  await lightProfile.scrollIntoViewIfNeeded();
  const lightProfileFrame = await (await lightProfile.elementHandle()).contentFrame();
  assert.ok(lightProfileFrame);
  await expect(lightProfileFrame.locator('#theme')).toHaveValue('ivory');
  await light.goto(`${base}/docs/profiles-and-orderflow/`);
  await expect(light.getByRole('link', { name: /^Open full-size order-flow demo/ })).toHaveAttribute('href', /[?&]theme=ivory&paused=1$/);
  const lightOrderflow = light.locator('iframe[title="Interactive footprint chart with profile, cluster ladder and heatmap styles"]');
  await lightOrderflow.scrollIntoViewIfNeeded();
  const lightOrderflowFrame = await (await lightOrderflow.elementHandle()).contentFrame();
  assert.ok(lightOrderflowFrame);
  await expect(lightOrderflowFrame.locator('#theme')).toHaveValue('ivory');
  await expect(lightOrderflowFrame.locator('#play')).toHaveText('Resume');
  await light.screenshot({ path: 'artifacts/website-orderflow-embed-light.png' });
  await light.close();
  assert.deepEqual(errors, []);
  console.log('Website checks passed: compact guide examples, embedded split/unsplit, five themes, unchanged analytics, eight fingerprinted screenshots, removed legacy URLs, orderflow styles/text/themes, optional seven-row table, lots divided by 65 with raw data preserved, current runtime, release/API references, mobile layout and light-default demo palettes.');
} finally {
  await browser.close();
}
