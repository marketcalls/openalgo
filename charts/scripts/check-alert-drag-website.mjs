/** Exercise the published-page demo through real pointers and rendered pixels. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { chromium, firefox, webkit, expect } from '@playwright/test';

const base = (process.argv[2] ?? 'http://127.0.0.1:4174/openalgo-charts').replace(/\/$/, '');
const output = process.argv[3] ?? 'artifacts';
const engines = { chromium, firefox, webkit };
const selected = (process.env.OAC_WEBSITE_BROWSERS ?? 'chromium,firefox,webkit').split(',').map(name => name.trim()).filter(Boolean);
assert.ok(selected.length > 0 && selected.every(name => name in engines), 'OAC_WEBSITE_BROWSERS must name chromium, firefox or webkit');
await mkdir(output, { recursive: true });
const results = [];
const paint = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));

async function settleGeometry(target) {
  let previous;
  let stable = 0;
  await expect.poll(async () => {
    const box = JSON.stringify(await target.boundingBox());
    stable = box === previous ? stable + 1 : 0;
    previous = box;
    return stable;
  }, { intervals: [50], timeout: 5000 }).toBeGreaterThanOrEqual(2);
}

async function focusAndSettle(target) {
  // WebKit restores the pre-focus scroll position on button blur. Keep focus
  // from moving the page, then measure the actual pointer gesture normally.
  await target.evaluate(node => node.focus({ preventScroll: true }));
  await settleGeometry(target);
}

async function activateControl(target, browser) {
  if (browser === 'webkit') {
    // WebKit can scroll on button blur between press and release. Native
    // keyboard activation avoids that page-navigation race; chart drags below
    // still use physical pointers and assert stable geometry throughout.
    await focusAndSettle(target);
    await target.press('Space');
  } else await target.click();
}

async function saved(values) {
  return values.evaluate(node => Object.fromEntries(['price', 'lower', 'upper', 'study', 'commits']
    .map(key => [key, Number(node.dataset[key])])));
}

async function point(stage, key) {
  const box = await stage.boundingBox();
  const position = await stage.evaluate((node, key) => ({
    x: Number(node.dataset.dragX), y: Number(node.dataset[key + 'Y']), targetY: Number(node.dataset[key + 'TargetY']),
  }), key);
  assert.ok(box && Object.values(position).every(Number.isFinite), 'Chart coordinates must be measured');
  assert.ok(position.x > 0 && position.x < box.width && position.y > 0 && position.y < box.height);
  assert.ok(position.targetY > 0 && position.targetY < box.height);
  return { x: box.x + position.x, y: box.y + position.y, targetY: box.y + position.targetY, localTargetY: position.targetY };
}

async function bluePixels(stage, y) {
  return stage.evaluate((node, y) => {
    const root = node.getBoundingClientRect();
    const x = Number(node.dataset.dragX);
    let count = 0;
    for (const canvas of node.querySelectorAll('canvas')) {
      const box = canvas.getBoundingClientRect();
      if (!box.width || !box.height || root.y + y < box.y || root.y + y >= box.bottom) continue;
      const ratio = canvas.width / box.width;
      const context = canvas.getContext('2d');
      if (!context) continue;
      const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
      const centre = (root.y + y - box.y) * ratio;
      const left = Math.max(0, Math.floor((root.x + x - 35 - box.x) * ratio));
      const right = Math.min(canvas.width, Math.ceil((root.x + x + 35 - box.x) * ratio));
      for (let py = Math.max(0, Math.floor(centre - 3 * ratio)); py < Math.min(canvas.height, centre + 3 * ratio); py++) {
        for (let px = left; px < right; px++) {
          const at = (py * canvas.width + px) * 4;
          const [red, green, blue, alpha] = pixels.subarray(at, at + 4);
          if (alpha > 160 && blue > 190 && blue - red > 70 && green > 80 && green < 220) count++;
        }
      }
    }
    return count;
  }, y);
}

for (const name of selected) {
  const engine = engines[name];
  const browser = await engine.launch();
  try {
    for (const scenario of [
      { name: 'desktop-dark', width: 1440, height: 1000, theme: 'dark' },
      { name: 'narrow-light', width: 390, height: 1000, theme: 'light' },
    ]) {
      const context = await browser.newContext({ viewport: { width: scenario.width, height: scenario.height }, colorScheme: scenario.theme, reducedMotion: 'reduce' });
      const page = await context.newPage();
      const errors = [];
      const assetFailures = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('response', response => {
        if (new URL(response.url()).origin === new URL(base).origin && response.status() >= 400) {
          assetFailures.push({ url: response.url(), status: response.status(), type: response.request().resourceType() });
        }
      });
      const prefix = `alert-drag-${name}-${scenario.name}`;
      const shot = suffix => page.screenshot({ path: join(output, `${prefix}-${suffix}.png`), animations: 'disabled' });
      try {
        await page.addInitScript(theme => localStorage.setItem('oac-theme', theme), scenario.theme);
        const response = await page.goto(`${base}/examples/`);
        assert.equal(response?.status(), 200);
        await expect(page.locator('#alert-threshold-dragging')).toHaveCount(1);
        const demo = page.locator('#alert-drag-demo');
        await expect(demo.locator('[data-alert-drag-ready="true"]')).toHaveCount(1, { timeout: 30000 });
        await demo.scrollIntoViewIfNeeded();
        await expect(demo.locator('.oac-example__err')).toHaveCount(0);
        await expect(page.locator('html')).toHaveClass(new RegExp(`(?:^|\\s)${scenario.theme}(?:\\s|$)`));
        const stage = demo.locator('[data-alert-drag-chart]');
        const values = demo.locator('[data-alert-drag-values]');
        const reset = demo.locator('[data-alert-drag-action="reset"]');
        const pause = demo.locator('[data-alert-drag-action="pause"]');
        await paint(page);
        assert.equal(await demo.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true, 'Demo must fit its container');
        await shot('ready');

        for (const key of ['price', 'lower', 'upper', 'study']) {
          await activateControl(reset, name);
          await expect.poll(() => saved(values)).toEqual({ price: 110, lower: 90, upper: 120, study: 30, commits: 0 });
          await paint(page);
          await focusAndSettle(stage);
          const before = await saved(values);
          const beforeBox = await stage.boundingBox();
          const coordinates = await point(stage, key);
          await page.mouse.move(coordinates.x, coordinates.y);
          await page.mouse.down();
          const inkBefore = await bluePixels(stage, coordinates.localTargetY);
          await page.mouse.move(coordinates.x, coordinates.targetY, { steps: 6 });
          await paint(page);
          assert.deepEqual(await stage.boundingBox(), beforeBox, `${key}: preview must keep the chart geometry stable`);
          assert.deepEqual(await saved(values), before, `${key}: pointer movement must not change saved levels`);
          const inkDuring = await bluePixels(stage, coordinates.localTargetY);
          assert.ok(inkDuring > inkBefore + 8, `${key}: a visible blue threshold must move to the pointer (${inkBefore} -> ${inkDuring})`);
          if (key === 'price') await shot('preview');
          await page.mouse.up();
          await paint(page);
          const after = await saved(values);
          assert.equal(after.commits, 1, `${key}: release commits exactly once`);
          const expected = before[key] + (key === 'study' ? 10 : key === 'upper' ? -5 : 5);
          // Browser pointers quantize CSS coordinates; price alerts then round
          // to the demo's 0.25 tick. Account for both independent rounding steps.
          const unitsPerPixel = Math.abs((expected - before[key]) / (coordinates.targetY - coordinates.y));
          const halfTick = key === 'study' ? 0 : 0.125;
          if (key !== 'study') assert.equal(after[key] * 4, Math.round(after[key] * 4), `${key}: commit must snap to the 0.25 price tick`);
          assert.ok(Math.abs(after[key] - expected) <= unitsPerPixel + halfTick + 1e-6,
            `${key}: ${after[key]} must land within one pointer pixel plus half a tick of ${expected} (${unitsPerPixel} units/px)`);
          for (const other of ['price', 'lower', 'upper', 'study'].filter(item => item !== key)) {
            assert.equal(after[other], before[other], `${key}: release must preserve ${other}`);
          }
          results.push({ browser: name, scenario: scenario.name, source: key, inkBefore, inkDuring, unitsPerPixel, before, after });
        }

        await activateControl(reset, name);
        await expect.poll(() => saved(values)).toEqual({ price: 110, lower: 90, upper: 120, study: 30, commits: 0 });
        await paint(page);
        await focusAndSettle(stage);
        const beforeCancel = await saved(values);
        const cancelPoint = await point(stage, 'price');
        await page.mouse.move(cancelPoint.x, cancelPoint.y);
        await page.mouse.down();
        const inkBeforeCancel = await bluePixels(stage, cancelPoint.localTargetY);
        await page.mouse.move(cancelPoint.x, cancelPoint.targetY, { steps: 6 });
        await paint(page);
        assert.ok(await bluePixels(stage, cancelPoint.localTargetY) > inkBeforeCancel + 8);
        await page.keyboard.press('Escape');
        await page.mouse.up();
        await page.mouse.move(5, 5);
        await paint(page);
        assert.deepEqual(await saved(values), beforeCancel, 'Escape must leave the saved threshold and commit count unchanged');
        assert.ok(await bluePixels(stage, cancelPoint.localTargetY) <= inkBeforeCancel + 8, 'Escape must remove the moved preview pixels');
        await expect(demo.locator('[data-alert-drag-status]')).toContainText('cancelled');
        await shot('cancelled');

        await activateControl(pause, name);
        await expect(pause).toHaveAttribute('aria-pressed', 'true');
        await focusAndSettle(stage);
        const beforePause = await saved(values);
        const pausedPoint = await point(stage, 'price');
        await page.mouse.move(pausedPoint.x, pausedPoint.y);
        await page.mouse.down();
        await page.mouse.move(pausedPoint.x, pausedPoint.targetY, { steps: 6 });
        await page.mouse.up();
        await paint(page);
        assert.deepEqual(await saved(values), beforePause, 'Pause must prohibit threshold edits');
        await expect(demo.locator('[data-alert-drag-status]')).toContainText('paused');
        await shot('paused');
        await activateControl(pause, name);
        await expect(pause).toHaveAttribute('aria-pressed', 'false');
        assert.deepEqual(errors, [], 'No page errors');
        assert.deepEqual(assetFailures, [], 'Same-origin pages and assets must resolve under the website base path');
        console.log(`${name} ${scenario.name}: four threshold drags, preview pixels, single commits, Escape and pause passed.`);
      } catch (error) {
        await shot('failure').catch(() => {});
        throw error;
      } finally { await context.close(); }
    }
  } finally { await browser.close(); }
}
await writeFile(join(output, 'alert-drag-website-results.json'), JSON.stringify({ base, results }, null, 2) + '\n');
