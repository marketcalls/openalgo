/** Verify the table sizing demo on a built or deployed website. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { chromium, firefox, webkit, expect } from '@playwright/test';

const base = (process.argv[2] ?? 'http://127.0.0.1:4174/openalgo-charts').replace(/\/$/, '');
const output = process.argv[3] ?? 'artifacts';
const origin = new URL(base).origin;
const engines = { chromium, firefox, webkit };
const selected = (process.env.OAC_WEBSITE_BROWSERS ?? 'chromium,firefox,webkit')
  .split(',').map(name => name.trim()).filter(Boolean);
assert.ok(selected.length > 0 && selected.every(name => Object.hasOwn(engines, name)),
  'OAC_WEBSITE_BROWSERS must name chromium, firefox or webkit');
await mkdir(output, { recursive: true });
const results = [];
const paint = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
// The demo colours its table for the chart's palette, and the chart follows the
// site theme, so each scenario names the exact colours it must find painted.
// `ink` classifies a thresholded pixel as belonging to that colour's glyphs.
const PALETTES = {
  dark: { backdrop: '#17202e', backdropRgb: [23, 32, 46], border: '#40506a', text: '#e2e8f0', up: '#4ade80', neutral: '#fbbf24' },
  light: { backdrop: '#f8fafc', backdropRgb: [248, 250, 252], border: '#cbd5e1', text: '#1e293b', up: '#15803d', neutral: '#b45309' },
};

async function activateControl(target, browser) {
  if (browser !== 'webkit') return target.click();
  // Keep WebKit's button focus from scrolling the page between press and
  // release. Space still exercises the button's native activation behavior.
  await target.evaluate(node => node.focus({ preventScroll: true }));
  let previous;
  let stable = 0;
  await expect.poll(async () => {
    const box = JSON.stringify(await target.boundingBox());
    stable = box === previous ? stable + 1 : 0;
    previous = box;
    return stable;
  }, { intervals: [50], timeout: 5000 }).toBeGreaterThanOrEqual(2);
  await target.press('Space');
}

async function observeCanvas(page, palette) {
  await page.addInitScript(palette => {
    const frames = new WeakMap();
    window.__tableWebsiteFrames = frames;
    const labels = new Set(['Metric', 'Reading', 'Moving averages', 'Up', 'Momentum', 'Neutral']);
    const prototype = CanvasRenderingContext2D.prototype;
    const fillRect = prototype.fillRect;
    const strokeRect = prototype.strokeRect;
    const fillText = prototype.fillText;
    const bounds = (context, x, y, width, height) => {
      const transform = context.getTransform();
      return {
        x: transform.a * x + transform.c * y + transform.e,
        y: transform.b * x + transform.d * y + transform.f,
        width: transform.a * width, height: transform.d * height,
      };
    };
    // The demo's backdrop starts a table frame. All original canvas methods
    // still run; the assertions below read their resulting bitmap pixels.
    prototype.fillRect = function (x, y, width, height) {
      if (this.fillStyle === palette.backdrop) {
        frames.set(this.canvas, { bounds: bounds(this, x, y, width, height), cells: [], texts: [] });
      }
      return fillRect.call(this, x, y, width, height);
    };
    prototype.strokeRect = function (x, y, width, height) {
      const frame = frames.get(this.canvas);
      if (frame && this.strokeStyle === palette.border) frame.cells.push(bounds(this, x, y, width, height));
      return strokeRect.call(this, x, y, width, height);
    };
    prototype.fillText = function (text, x, y, ...rest) {
      const frame = frames.get(this.canvas);
      if (frame && labels.has(text)) {
        const matrix = this.getTransform();
        frame.texts.push({
          text, x, y, font: this.font, color: this.fillStyle,
          align: this.textAlign, baseline: this.textBaseline,
          transform: [matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f],
          cell: frame.cells.at(-1),
        });
      }
      return fillText.call(this, text, x, y, ...rest);
    };
  }, palette);
}

async function snapshot(demo, palette) {
  return demo.evaluate((node, palette) => {
    const canvas = [...node.querySelectorAll('canvas')].find(item => window.__tableWebsiteFrames.get(item)?.texts.length === 6);
    if (!canvas) return null;
    const frame = window.__tableWebsiteFrames.get(canvas);
    const context = canvas.getContext('2d');
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    const ratio = canvas.width / canvas.getBoundingClientRect().width;
    const reference = document.createElement('canvas');
    reference.width = canvas.width;
    reference.height = canvas.height;
    const control = reference.getContext('2d');
    const isInk = (data, at, color) => {
      const [red, green, blue, alpha] = data.subarray(at, at + 4);
      if (alpha < 150) return false;
      if (color === '#4ade80') return green > 145 && green - red > 55 && green - blue > 35;
      if (color === '#fbbf24') return red > 150 && green > 115 && blue < 100 && red - green < 110;
      if (color === '#15803d') return green > 90 && red < 110 && green - red > 45 && green - blue > 30;
      if (color === '#b45309') return red > 130 && red - green > 50 && green - blue > 30;
      if (color === '#1e293b') return red < 120 && green < 130 && blue < 145 && Math.max(red, green, blue) - Math.min(red, green, blue) < 45;
      return red > 135 && green > 145 && blue > 150 && Math.max(red, green, blue) - Math.min(red, green, blue) < 40;
    };
    const mask = (data, box, color) => {
      const ink = new Set();
      for (let y = Math.max(0, Math.ceil(box.y)); y < Math.min(canvas.height, Math.floor(box.y + box.height)); y++) {
        for (let x = Math.max(0, Math.ceil(box.x)); x < Math.min(canvas.width, Math.floor(box.x + box.width)); x++) {
          const index = y * canvas.width + x;
          if (isInk(data, index * 4, color)) ink.add(index);
        }
      }
      return ink;
    };
    const coverage = (source, target) => {
      let matched = 0;
      for (const index of source) {
        const x = index % canvas.width;
        const y = Math.floor(index / canvas.width);
        let found = false;
        for (let dy = -1; dy <= 1 && !found; dy++) {
          for (let dx = -1; dx <= 1; dx++) {
            if (x + dx >= 0 && x + dx < canvas.width && y + dy >= 0 && y + dy < canvas.height
              && target.has(index + dy * canvas.width + dx)) {
              found = true;
              break;
            }
          }
        }
        if (found) matched++;
      }
      return source.size ? matched / source.size : 0;
    };
    const texts = frame.texts.map(text => {
      control.resetTransform();
      control.fillStyle = palette.backdrop;
      control.fillRect(0, 0, canvas.width, canvas.height);
      control.setTransform(...text.transform);
      control.font = text.font;
      control.fillStyle = text.color;
      control.textAlign = text.align;
      control.textBaseline = text.baseline;
      control.fillText(text.text, text.x, text.y);
      const expected = control.getImageData(0, 0, canvas.width, canvas.height).data;
      const actualMask = mask(pixels, text.cell, text.color);
      const fullMask = mask(expected, { x: 0, y: 0, width: canvas.width, height: canvas.height }, text.color);
      // Native canvases can rasterize a glyph edge one bitmap pixel apart.
      // Compare both silhouettes locally instead of requiring identical counts
      // after thresholding antialiased colors. Missing text still loses coverage.
      return {
        text: text.text, font: text.font, color: text.color, cell: text.cell,
        ink: actualMask.size, fullInk: fullMask.size,
        referenceCoverage: coverage(fullMask, actualMask), paintedCoverage: coverage(actualMask, fullMask),
        neutralInk: text.color === palette.text ? null : mask(pixels, text.cell, palette.text).size,
      };
    });
    // Read the backdrop inside the header border, independently of the
    // recorded fill width, to prove that the changed layout was painted.
    const scanY = Math.floor(frame.bounds.y + 2 * ratio);
    let left = -1, right = -1;
    for (let x = 0; x < canvas.width; x++) {
      const at = (scanY * canvas.width + x) * 4;
      const [red, green, blue] = palette.backdropRgb;
      if (pixels[at] === red && pixels[at + 1] === green && pixels[at + 2] === blue && pixels[at + 3] === 255) {
        if (left < 0) left = x;
        right = x;
      }
    }
    return {
      ratio, width: frame.bounds.width / ratio, paintedWidth: left < 0 ? 0 : (right - left + 1) / ratio,
      insideCanvas: frame.bounds.x >= 0 && frame.bounds.y >= 0
        && frame.bounds.x + frame.bounds.width <= canvas.width && frame.bounds.y + frame.bounds.height <= canvas.height,
      cells: frame.cells.length, texts,
      colors: Object.fromEntries(frame.texts.map(text => [text.text, text.color])),
    };
  }, palette);
}

function checkPixels(state, mode, palette) {
  assert.ok(state && state.cells === 6 && state.texts.length === 6, `${mode}: all six cells must render`);
  assert.deepEqual(state.colors, {
    Metric: palette.text, Reading: palette.text, 'Moving averages': palette.text,
    Up: palette.up, Momentum: palette.text, Neutral: palette.neutral,
  }, `${mode}: every label must use the colours of the active palette`);
  assert.ok(state.insideCanvas, `${mode}: the table must fit inside the visible chart`);
  assert.ok(state.paintedWidth > 0 && Math.abs(state.paintedWidth - state.width) <= 4,
    `${mode}: visible backdrop pixels must follow the table width`);
  for (const label of state.texts) {
    assert.ok(label.ink > 0 && label.fullInk > 0, `${mode}: ${label.text} must paint visible glyphs`);
    if (mode === 'auto' || label.text === 'Up' || label.text === 'Neutral') {
      assert.ok(label.referenceCoverage >= 0.98 && label.paintedCoverage >= 0.98,
        `${mode}: ${label.text} must retain its glyph shape within one bitmap pixel `
        + `(reference coverage ${label.referenceCoverage}, painted coverage ${label.paintedCoverage})`);
    }
    if (label.neutralInk !== null) {
      assert.equal(label.neutralInk, 0, `${mode}: the neighboring label must not overlap ${label.text}`);
    }
  }
  if (mode === 'fixed') {
    const long = state.texts.find(label => label.text === 'Moving averages');
    assert.ok(long.ink < long.fullInk, 'Fixed columns must visibly clip the long label inside its own cell');
  }
}

try {
  for (const name of selected) {
    const browser = await engines[name].launch();
    try {
      for (const scenario of [
        { name: 'desktop-dark', width: 1440, height: 1000, theme: 'dark' },
        { name: 'narrow-light', width: 390, height: 1000, theme: 'light' },
      ]) {
        const context = await browser.newContext({
          viewport: { width: scenario.width, height: scenario.height }, colorScheme: scenario.theme, reducedMotion: 'reduce',
        });
        const page = await context.newPage();
        const errors = [];
        const assetFailures = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('response', response => {
          if (new URL(response.url()).origin === origin && response.status() >= 400) {
            assetFailures.push({ url: response.url(), status: response.status(), type: response.request().resourceType() });
          }
        });
        page.on('requestfailed', request => {
          if (new URL(request.url()).origin === origin) {
            assetFailures.push({ url: request.url(), failure: request.failure()?.errorText, type: request.resourceType() });
          }
        });
        const prefix = `table-sizing-${name}-${scenario.name}`;
        const palette = PALETTES[scenario.theme];
        const shot = suffix => page.screenshot({ path: join(output, `${prefix}-${suffix}.png`), animations: 'disabled' });
        try {
          await observeCanvas(page, palette);
          await page.addInitScript(theme => localStorage.setItem('oac-theme', theme), scenario.theme);
          const response = await page.goto(`${base}/examples/#tables-that-fit-their-text`);
          assert.equal(response?.status(), 200, 'The examples page must load');
          await expect(page.locator('#tables-that-fit-their-text')).toHaveCount(1);
          await expect(page.locator('html')).toHaveClass(new RegExp(`(?:^|\\s)${scenario.theme}(?:\\s|$)`));
          const demo = page.locator('#table-sizing-demo');
          const host = demo.locator('[data-table-sizing-mode]');
          const toggle = demo.locator('button[data-table-sizing-toggle]');
          const status = demo.locator('[data-table-sizing-status]');
          await expect(host).toHaveAttribute('data-table-sizing-mode', 'auto', { timeout: 30000 });
          await expect(demo.locator('.oac-example__loading')).toHaveCount(0);
          await expect(demo.locator('.oac-example__err')).toHaveCount(0);
          await demo.scrollIntoViewIfNeeded();
          await page.mouse.move(5, 5);
          await paint(page);
          await expect.poll(() => demo.evaluate(node => [...node.querySelectorAll('canvas')]
            .some(canvas => window.__tableWebsiteFrames.get(canvas)?.texts.length === 6)), { timeout: 10000 }).toBe(true);
          assert.equal(await demo.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true,
            'The demo must fit its container without horizontal scrolling');
          await expect(toggle).toHaveText('Use fixed columns');
          await expect(status).toHaveText('Automatic widths fit each column.');
          const automatic = await snapshot(demo, palette);
          checkPixels(automatic, 'auto', palette);
          await shot('automatic');

          await activateControl(toggle, name);
          await expect(host).toHaveAttribute('data-table-sizing-mode', 'fixed');
          await expect(toggle).toHaveText('Fit columns to text');
          await expect(status).toHaveText('Fixed 64 px columns clip long text.');
          await paint(page);
          const fixed = await snapshot(demo, palette);
          checkPixels(fixed, 'fixed', palette);
          assert.equal(fixed.width, 128, 'Fixed mode must retain two declared 64 px columns');
          assert.ok(automatic.width > fixed.width + 1 && automatic.paintedWidth > fixed.paintedWidth + 1,
            'The native toggle must change both table geometry and its visible width');
          await shot('fixed');

          await activateControl(toggle, name);
          await expect(host).toHaveAttribute('data-table-sizing-mode', 'auto');
          await expect(toggle).toHaveText('Use fixed columns');
          await expect(status).toHaveText('Automatic widths fit each column.');
          await paint(page);
          const restored = await snapshot(demo, palette);
          checkPixels(restored, 'auto', palette);
          assert.equal(restored.width, automatic.width, 'Returning to automatic mode must restore the column widths');
          assert.equal(restored.paintedWidth, automatic.paintedWidth, 'Returning to automatic mode must restore the painted width');
          await shot('restored');
          assert.deepEqual(errors, [], 'The table demo page must not raise browser errors');
          assert.deepEqual(assetFailures, [], 'Same-origin pages and assets must resolve under the website base path');
          results.push({ browser: name, scenario: scenario.name, automatic, fixed, restored, errors, assetFailures });
          console.log(`${name} ${scenario.name}: native sizing toggle, canvas widths, complete automatic labels and clipped fixed labels passed.`);
        } catch (error) {
          results.push({ browser: name, scenario: scenario.name, error: String(error), errors, assetFailures });
          await shot('failure').catch(() => {});
          throw new Error(`${prefix}: ${error.message}`, { cause: error });
        } finally { await context.close(); }
      }
    } finally { await browser.close(); }
  }
} finally {
  await writeFile(join(output, 'table-website-results.json'), JSON.stringify({ base, results }, null, 2) + '\n');
}
