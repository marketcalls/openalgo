/** Check the built website's chart bundles, plot panning and time-axis drags. */
import { strict as assert } from 'node:assert';
import { createHash } from 'node:crypto';
import { mkdir, readFile, readdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { chromium, expect } from '@playwright/test';

const base = (process.argv[2] ?? 'http://127.0.0.1:4174/openalgo-charts').replace(/\/$/, '');
const origin = new URL(base).origin;
const root = new URL('../', import.meta.url);
const artifacts = new URL('artifacts/navigation-website/', root);
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const esmFiles = async path => (await readdir(new URL(path, root))).filter(name => name.endsWith('.mjs')).sort();
const builtFiles = await esmFiles('dist/');
const siteFiles = await esmFiles('website/lib/oac/');
assert.ok(builtFiles.length > 0, 'Build the library before checking the website');
assert.deepEqual(siteFiles, builtFiles, 'The website must contain every current ESM bundle and no stale extras');

const bundleHashes = new Map();
for (const name of builtFiles) {
  const hash = digest(await readFile(new URL(`dist/${name}`, root)));
  bundleHashes.set(name, hash);
  assert.equal(digest(await readFile(new URL(`website/lib/oac/${name}`, root))), hash,
    `Rebuild the website: its ${name} differs from dist`);
}
const demoFiles = ['openalgo-charts.mjs', 'openalgo-charts.profile.mjs'];
for (const name of demoFiles) {
  assert.equal(digest(await readFile(new URL(`website/public/demos/dist/${name}`, root))), bundleHashes.get(name),
    `Rebuild the website: the embedded demos have a stale ${name}`);
}
await mkdir(artifacts, { recursive: true });

const browser = await chromium.launch();
try {
  const context = await browser.newContext({
    viewport: { width: 1600, height: 1100 }, deviceScaleFactor: 2,
    colorScheme: 'dark', serviceWorkers: 'block',
  });
  const blocked = new Set();
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin === origin || !['http:', 'https:'].includes(url.protocol)) return route.continue();
    blocked.add(url.origin);
    return route.abort();
  });
  // The candle probe below matches the dark palette's up and down colours, so
  // choose the dark site the way a reader would; the site itself opens light.
  await context.addInitScript(() => localStorage.setItem('oac-theme', 'dark'));
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));

  // Record what the browser actually paints without changing the library or its data.
  // A full-canvas background fill starts each frame; retain only that frame's candles.
  await page.addInitScript(() => {
    window.__navigationCanvasRects = new WeakMap();
    const fillRect = CanvasRenderingContext2D.prototype.fillRect;
    CanvasRenderingContext2D.prototype.fillRect = function (x, y, width, height) {
      if (x === 0 && y === 0 && width >= this.canvas.width && height >= this.canvas.height) {
        window.__navigationCanvasRects.set(this.canvas, []);
      }
      if (this.fillStyle === '#26a69a' || this.fillStyle === '#ef5350') {
        const rects = window.__navigationCanvasRects.get(this.canvas) ?? [];
        if (rects.length < 4096) rects.push({ x, y, width, height, color: this.fillStyle });
        window.__navigationCanvasRects.set(this.canvas, rects);
      }
      return fillRect.call(this, x, y, width, height);
    };
  });

  for (const name of demoFiles) {
    const response = await page.request.get(`${base}/demos/dist/${name}`);
    assert.equal(response.status(), 200, `The preview must serve ${name}`);
    assert.equal(digest(await response.body()), bundleHashes.get(name),
      `The preview serves stale ${name} bytes even though the source copy is current`);
  }

  const settle = async () => {
    await page.mouse.move(8, 8);
    // Keep the pointer and its crosshair away from the captured chart.
    await page.waitForTimeout(300);
  };
  const capture = async (chart, name) => {
    await settle();
    const bytes = await chart.screenshot({ path: fileURLToPath(new URL(`${name}.png`, artifacts)) });
    return digest(bytes);
  };
  const dragAxis = async (chart, direction) => {
    await chart.scrollIntoViewIfNeeded();
    const box = await chart.boundingBox();
    assert.ok(box && box.width > 180 && box.height > 80, 'The chart must have a usable time axis');
    // Locator bounding boxes include the iframe's position in the parent viewport.
    // Native mouse events exercise the same pointer capture path as a real drag.
    const distance = Math.min(160, (box.width - 100) * 0.38);
    const x = box.x + (box.width - 74) / 2;
    const y = box.y + box.height - 8;
    await page.mouse.move(x, y);
    await page.mouse.down();
    try {
      await page.mouse.move(x + direction * distance, y, { steps: 16 });
    } finally {
      await page.mouse.up();
    }
  };
  const dragPlot = async chart => {
    await chart.scrollIntoViewIfNeeded();
    const box = await chart.boundingBox();
    assert.ok(box && box.width > 180 && box.height > 160, 'The chart must have a usable plot');
    const x = box.x + box.width * 0.35;
    const y = box.y + box.height * 0.35;
    const dx = Math.min(84, box.width * 0.15);
    const dy = Math.min(56, box.height * 0.18);
    await page.mouse.move(x, y);
    await page.mouse.down();
    try {
      await expect(chart.locator('canvas').first()).toHaveCSS('cursor', 'grabbing');
      await page.mouse.move(x + dx, y + dy, { steps: 16 });
    } finally {
      await page.mouse.up();
    }
    await expect(chart.locator('canvas').first()).not.toHaveCSS('cursor', 'grabbing');
    return { dx, dy };
  };
  const clickReset = async (chart, axisWidth) => {
    await chart.scrollIntoViewIfNeeded();
    const box = await chart.boundingBox();
    assert.ok(box, 'The reset button must have chart geometry');
    const x = box.x + (box.width - axisWidth) / 2;
    const y = box.y + box.height - 22 - 10 - 26 / 2;
    await page.mouse.move(x, y);
    await page.waitForTimeout(200);
    await page.mouse.click(x, y);
  };
  const view = frame => frame.evaluate(() => {
    const chart = window.__chart();
    const scale = chart.panes()[0].priceScale;
    return {
      time: chart.getVisibleLogicalRange(), price: scale.priceRange(), autoScale: scale.autoScale,
    };
  });

  const results = [];
  const panResults = [];
  for (const demo of [
    { name: 'market-profile', route: '/docs/market-profile-examples/', title: 'Interactive compact market profile demo' },
    { name: 'orderflow', route: '/docs/profiles-and-orderflow/', title: 'Interactive footprint chart with profile, cluster ladder and heatmap styles' },
  ]) {
    const response = await page.goto(`${base}${demo.route}`);
    assert.equal(response.status(), 200, demo.route);
    const embed = page.locator(`iframe[title="${demo.title}"]`);
    await embed.scrollIntoViewIfNeeded();
    const handle = await embed.elementHandle();
    const frame = await handle.contentFrame();
    assert.ok(frame, `${demo.name} iframe must load`);
    await frame.waitForFunction(() => typeof window.__chart === 'function' && window.__chart().timeScale.width > 0);
    const chart = frame.locator('#chart');
    await expect(chart.locator('canvas').first()).toBeVisible();
    if (demo.name === 'orderflow') await expect(frame.locator('#play')).toHaveText('Resume');
    await settle();
    const original = await frame.evaluate(() => {
      const chart = window.__chart();
      return {
        viewport: chart.getVisibleLogicalRange(), navigation: chart.navigationOptions(),
        scales: chart.panes().map(pane => pane.scales().map(scale => ({
          range: scale.priceRange(), autoScale: scale.autoScale,
        }))),
      };
    });
    try {
      assert.equal(original.navigation.mousePan, 'both', `${demo.name}: the untouched mouse pan default must be both`);
      const panBefore = await view(frame);
      const panBeforeHash = await capture(chart, `${demo.name}-pan-before`);
      await dragPlot(chart);
      const panAfterHash = await capture(chart, `${demo.name}-pan-both`);
      const panAfter = await view(frame);
      assert.notDeepEqual(panAfter.time, panBefore.time, `${demo.name}: a default plot drag must move time`);
      assert.notDeepEqual(panAfter.price, panBefore.price, `${demo.name}: a default plot drag must move price`);
      assert.equal(panAfter.autoScale, false, `${demo.name}: default panning must leave the price range manual`);
      assert.notEqual(panAfterHash, panBeforeHash, `${demo.name}: default panning must change visible pixels`);

      await frame.evaluate(() => window.__chart().setNavigationOptions({ mousePan: 'horizontal' }));
      const horizontalBefore = await view(frame);
      await dragPlot(chart);
      const horizontalHash = await capture(chart, `${demo.name}-pan-horizontal`);
      const horizontalAfter = await view(frame);
      assert.notDeepEqual(horizontalAfter.time, horizontalBefore.time, `${demo.name}: horizontal mode must still move time`);
      // The first drag made this range manual, so changing visible bars cannot
      // legitimately remeasure it and hide an unwanted vertical pan.
      assert.deepEqual(horizontalAfter.price, horizontalBefore.price, `${demo.name}: horizontal mode must preserve price`);
      assert.equal(horizontalAfter.autoScale, horizontalBefore.autoScale, `${demo.name}: horizontal mode must preserve autoscale`);
      assert.notEqual(horizontalHash, panAfterHash, `${demo.name}: horizontal panning must change visible pixels`);

      await clickReset(chart, 74);
      await expect.poll(async () => (await view(frame)).autoScale).toBe(true);
      const resetHash = await capture(chart, `${demo.name}-pan-reset`);
      const reset = await view(frame);
      assert.notDeepEqual(reset.price, horizontalAfter.price, `${demo.name}: the reset button must restore the price view`);
      assert.notEqual(resetHash, horizontalHash, `${demo.name}: reset must change visible pixels`);
      panResults.push({ chart: demo.name, defaultMode: original.navigation.mousePan, before: panBefore,
        both: panAfter, horizontal: horizontalAfter, reset });

      await frame.evaluate(() => {
        const chart = window.__chart();
        const spacing = chart.timeScale.barSpacing;
        // A demo fitted at the zoom limit cannot expand. Keep it in the range
        // where both directions have visible room, then restore its original view.
        if (spacing < 4 || spacing > 30) {
          chart.timeScale.setBarSpacing(12);
          chart.invalidate(mask => mask.invalidateGlobal(3));
        }
      });
      const before = await frame.evaluate(() => window.__chart().timeScale.barSpacing);
      assert.ok(Number.isFinite(before) && before > 0, `${demo.name} initial spacing`);
      const beforeHash = await capture(chart, `${demo.name}-before`);
      await dragAxis(chart, -1);
      const left = await frame.evaluate(() => window.__chart().timeScale.barSpacing);
      assert.ok(left > before, `${demo.name}: dragging left must expand spacing (${before} to ${left})`);
      const leftHash = await capture(chart, `${demo.name}-left`);
      assert.notEqual(leftHash, beforeHash, `${demo.name}: left drag must change visible pixels`);
      await dragAxis(chart, 1);
      const right = await frame.evaluate(() => window.__chart().timeScale.barSpacing);
      assert.ok(right < left, `${demo.name}: dragging right must compress spacing (${left} to ${right})`);
      const rightHash = await capture(chart, `${demo.name}-right`);
      assert.notEqual(rightHash, leftHash, `${demo.name}: right drag must change visible pixels`);
      results.push({ chart: demo.name, spacing: { before, left, right } });
    } finally {
      await frame.evaluate(state => {
        const chart = window.__chart();
        chart.setNavigationOptions(state.navigation);
        chart.setVisibleLogicalRange(state.viewport);
        chart.panes().forEach((pane, i) => pane.scales().forEach((scale, j) => {
          scale.setPriceRange(state.scales[i][j].range);
          scale.setAutoScale(state.scales[i][j].autoScale);
        }));
        chart.invalidate(mask => mask.invalidateGlobal(3));
      }, original);
    }
  }

  assert.equal((await page.goto(`${base}/examples/`)).status(), 200, 'The gallery must load');
  const card = page.locator('.oac-card').filter({ has: page.getByRole('heading', { name: 'Chart type', exact: true }) });
  await card.scrollIntoViewIfNeeded();
  await card.getByRole('button', { name: 'Candles', exact: true }).click();
  const gallery = card.locator('.oac-card__chart');
  await expect(gallery.locator('canvas').first()).toBeVisible();
  const candlePaint = async () => gallery.locator('canvas').first().evaluate(canvas => {
    const dpr = canvas.width / canvas.getBoundingClientRect().width;
    const plotRight = canvas.width - 56 * dpr;
    const plotBottom = canvas.height - 22 * dpr;
    const rects = (window.__navigationCanvasRects.get(canvas) ?? []).filter(rect =>
      rect.x >= 0 && rect.x + rect.width < plotRight && rect.y >= 0 &&
      rect.y + rect.height < plotBottom && rect.width > 0 && rect.width < 80 * dpr);
    // Candle colours plus plot bounds exclude the background, grid and axis tags.
    // Wicks remain narrower than bodies, so the maximum is the painted body width.
    return { count: rects.length, width: Math.max(0, ...rects.map(rect => rect.width)), rects, dpr };
  });
  await expect.poll(async () => (await candlePaint()).count).toBeGreaterThan(20);
  const beforeHash = await capture(gallery, 'gallery-candles-before');
  const before = await candlePaint();
  await dragAxis(gallery, -1);
  const leftHash = await capture(gallery, 'gallery-candles-left');
  const left = await candlePaint();
  assert.notEqual(leftHash, beforeHash, 'Gallery candles must visibly change after a left drag');
  assert.ok(left.count > 20 && left.width > before.width,
    `Gallery left drag must paint wider candles (${before.width} to ${left.width} device px)`);
  await dragAxis(gallery, 1);
  const rightHash = await capture(gallery, 'gallery-candles-right');
  const right = await candlePaint();
  assert.notEqual(rightHash, leftHash, 'Gallery candles must visibly change after a right drag');
  assert.ok(right.count > 20 && right.width < left.width,
    `Gallery right drag must paint narrower candles (${left.width} to ${right.width} device px)`);
  results.push({ chart: 'gallery-candles', paintedWidth: { before: before.width, left: left.width, right: right.width } });

  await capture(gallery, 'gallery-candles-pan-before');
  const panBefore = await candlePaint();
  const { dx, dy } = await dragPlot(gallery);
  await capture(gallery, 'gallery-candles-pan-both');
  const panAfter = await candlePaint();
  const shifted = panBefore.rects.filter(beforeRect => panAfter.rects.some(afterRect =>
    beforeRect.color === afterRect.color && beforeRect.width === afterRect.width &&
    Math.abs(beforeRect.height - afterRect.height) <= 1 &&
    Math.abs(afterRect.x - beforeRect.x - dx * panBefore.dpr) <= 2 &&
    Math.abs(afterRect.y - beforeRect.y - dy * panBefore.dpr) <= 2));
  assert.ok(shifted.length > 20,
    `Gallery default panning must translate candles in both directions (${shifted.length} matched painted rectangles)`);
  await clickReset(gallery, 56);
  await capture(gallery, 'gallery-candles-pan-reset');
  const reset = await candlePaint();
  assert.equal(reset.width, before.width, 'Gallery reset must restore the original fitted candle width');
  panResults.push({ chart: 'gallery-candles', matchedPaintedRectangles: shifted.length,
    movement: { x: dx * panBefore.dpr, y: dy * panBefore.dpr } });

  await page.goto(`${base}/docs/mobile/`);
  const navigation = page.locator('.oac-example').filter({
    has: page.locator(':scope > .oac-example__caption').filter({ hasText: 'Start at 360 px to use the mobile header and Draw sheet.' }),
  });
  await navigation.scrollIntoViewIfNeeded();
  const widget = navigation.locator('.oac-widget');
  await expect(widget).toHaveClass(/is-mobile/);
  const retainedCanvas = await widget.locator('canvas').first().elementHandle();
  await navigation.getByRole('button', { name: 'Width: 360 px', exact: true }).click();
  await expect(widget).not.toHaveClass(/is-mobile/);
  assert(await retainedCanvas.evaluate(canvas => canvas.isConnected), 'Width changes retain the same chart');
  await navigation.getByRole('button', { name: 'Width: 760 px', exact: true }).click();
  await expect(widget).toHaveClass(/is-mobile/);
  await widget.locator('[data-mobile-action=draw]').click();
  await expect(widget.locator('.oac-mobile__tool')).toHaveCount(3);
  await widget.locator('[data-mobile-action=close]').click();
  await navigation.getByRole('button', { name: 'Reset view', exact: true }).click();
  const navigationBefore = await capture(widget, 'mobile-navigation-before');
  await navigation.getByRole('button', { name: 'Show extrema', exact: true }).click();
  await page.waitForTimeout(900);
  const navigationAfter = await capture(widget, 'mobile-navigation-extrema');
  assert.notEqual(navigationAfter, navigationBefore, 'The extrema reveal paints a new chart view');
  await navigation.getByRole('button', { name: 'Animation: on', exact: true }).click();
  await expect(widget.locator('canvas').first()).toBeVisible();
  await navigation.getByRole('button', { name: 'Reset view', exact: true }).click();
  results.push({ chart: 'mobile-navigation-example', retainedCanvas: true, permittedTools: 3, extremaVisible: true });

  assert.deepEqual(errors, [], 'The checked website pages must have no browser exceptions');
  console.log(JSON.stringify({
    checkedBundles: siteFiles.length, embeddedBundles: demoFiles.length,
    nativeAxisDrags: results, nativePlotPans: panResults, blockedExternalOrigins: [...blocked],
    screenshots: fileURLToPath(artifacts),
  }, null, 2));
} finally {
  await browser.close();
}
