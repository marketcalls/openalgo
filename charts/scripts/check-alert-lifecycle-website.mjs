/** Check finished-alert visibility against records, events and actual canvas pixels. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { chromium, firefox, webkit, expect } from '@playwright/test';

const base = (process.argv[2] ?? 'http://127.0.0.1:4174/openalgo-charts').replace(/\/$/, '');
const output = process.argv[3] ?? 'artifacts/alert-lifecycle';
const origin = new URL(base).origin;
const engines = { chromium, firefox, webkit };
const selected = (process.env.OAC_WEBSITE_BROWSERS ?? 'chromium,firefox,webkit').split(',').map(name => name.trim());
assert.ok(selected.length > 0 && selected.every(name => Object.hasOwn(engines, name)));
await mkdir(output, { recursive: true });
const results = [];

async function ink(demo, color) {
  return demo.locator('canvas').evaluateAll((canvases, color) => {
    let found = 0;
    for (const canvas of canvases) {
      const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i] === color[0] && pixels[i + 1] === color[1] && pixels[i + 2] === color[2] && pixels[i + 3] > 200) found++;
      }
    }
    return found;
  }, color);
}

for (const name of selected) {
  const browser = await engines[name].launch();
  try {
    for (const scenario of [
      { label: 'desktop-dark', width: 1440, height: 1000, theme: 'dark' },
      { label: 'narrow-light', width: 390, height: 1000, theme: 'light' },
    ]) {
      const context = await browser.newContext({ viewport: { width: scenario.width, height: scenario.height },
        colorScheme: scenario.theme, reducedMotion: 'reduce', serviceWorkers: 'block' });
      try {
        await context.route('**/*', route => {
          const url = new URL(route.request().url());
          return url.origin === origin || !['http:', 'https:'].includes(url.protocol) ? route.continue() : route.abort();
        });
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('response', response => {
          if (new URL(response.url()).origin === origin && response.status() >= 400) errors.push(`${response.status()} ${response.url()}`);
        });
        await page.addInitScript(theme => localStorage.setItem('oac-theme', theme), scenario.theme);
        const response = await page.goto(`${base}/examples/#finished-alert-lines`);
        assert.equal(response.status(), 200);
        const demo = page.locator('#alert-lifecycle-demo');
        await expect(demo.locator('[data-alert-lifecycle-ready]')).toHaveAttribute('data-alert-lifecycle-ready', 'true');
        await demo.scrollIntoViewIfNeeded();
        const state = demo.locator('[data-alert-lifecycle-state]');
        const click = async action => {
          const button = demo.locator(`[data-alert-lifecycle-action="${action}"]`);
          // Native keyboard activation avoids a focus-scroll race in WebKit.
          await button.evaluate(node => node.focus({ preventScroll: true }));
          await button.press('Space');
        };
        const screenshot = label => page.screenshot({ path: join(output, `${name}-${scenario.label}-${label}.png`), animations: 'disabled' });
        await expect(state).toHaveAttribute('data-records', '4');
        await expect(state).toHaveAttribute('data-state', 'armed');
        await expect.poll(() => ink(demo, [217, 119, 6])).toBe(0);
        await click('trigger');
        await expect(state).toHaveAttribute('data-state', 'triggered');
        await expect(state).toHaveAttribute('data-deliveries', '2');
        await expect.poll(() => ink(demo, [34, 197, 94])).toBe(0);
        await expect.poll(() => ink(demo, [59, 130, 246])).toBeGreaterThan(100);
        await screenshot('hidden');
        await click('restore');
        await click('trigger');
        await expect(state).toHaveAttribute('data-records', '4');
        await expect(state).toHaveAttribute('data-deliveries', '2');
        await expect.poll(() => ink(demo, [34, 197, 94])).toBe(0);
        await click('policy');
        await expect(state).toHaveAttribute('data-policy', 'show');
        await expect.poll(() => ink(demo, [34, 197, 94])).toBeGreaterThan(100);
        await expect.poll(() => ink(demo, [217, 119, 6])).toBeGreaterThan(100);
        await screenshot('shown');
        await click('policy');
        await expect.poll(() => ink(demo, [34, 197, 94])).toBe(0);
        await expect.poll(() => ink(demo, [217, 119, 6])).toBe(0);
        await click('rearm');
        await expect(state).toHaveAttribute('data-state', 'armed');
        await expect(state).toHaveAttribute('data-deliveries', '2');
        await screenshot('rearmed');
        const geometry = await demo.evaluate(node => {
          const badge = node.querySelector('.oac-example__badge').getBoundingClientRect();
          const controls = [...node.querySelectorAll('[data-alert-lifecycle-action]')];
          return { fits: document.documentElement.scrollWidth <= innerWidth,
            overlap: controls.some(control => {
              const box = control.getBoundingClientRect();
              return box.left < badge.right && box.right > badge.left && box.top < badge.bottom && box.bottom > badge.top;
            }) };
        });
        assert.deepEqual(geometry, { fits: true, overlap: false });
        await click('reset');
        await expect(state).toHaveAttribute('data-deliveries', '0');
        assert.deepEqual(errors, []);
        results.push({ browser: name, scenario: scenario.label, records: 4, deliveriesAfterRestore: 2, errors });
        console.log(`${name} ${scenario.label}: hide/show pixels, retained records, restore without redelivery, rearm and layout passed.`);
      } finally { await context.close(); }
    }
  } finally { await browser.close(); }
}
await writeFile(join(output, 'results.json'), JSON.stringify(results, null, 2) + '\n');
