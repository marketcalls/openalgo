/** Exercise Objects through the built documentation and examples pages. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { chromium, expect } from '@playwright/test';

const base = (process.argv[2] ?? 'http://127.0.0.1:4174/openalgo-charts').replace(/\/$/, '');
const output = process.argv[3] ?? 'artifacts';
await mkdir(output, { recursive: true });
const browser = await chromium.launch();

async function checkBounds(widget, panel) {
  const host = await widget.boundingBox();
  const bounds = await panel.boundingBox();
  const done = await panel.getByRole('button', { name: 'Close', exact: true }).boundingBox();
  assert.ok(host && bounds && done);
  assert.ok(bounds.x >= host.x - 1 && bounds.x + bounds.width <= host.x + host.width + 1,
    'Objects panel must fit the chart width');
  assert.ok(bounds.y >= host.y - 1 && bounds.y + bounds.height <= host.y + host.height + 1,
    'Objects panel must fit the chart height');
  assert.ok(done.y >= bounds.y && done.y + done.height <= bounds.y + bounds.height,
    'Done must remain reachable without scrolling the panel');
  assert.equal(await panel.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true,
    'Objects controls must not overflow horizontally');
}

try {
  for (const route of ['docs/objects', 'examples']) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const response = await page.goto(`${base}/${route}/`);
    assert.equal(response?.status(), 200);
    const demo = page.locator('.oac-example').filter({
      has: page.getByRole('button', { name: 'Open Objects', exact: true }),
    });
    const widget = demo.locator('.oac-widget');
    const panel = widget.locator('.oac-panel-dock');
    const shot = name => join(output, `objects-${route.replace('/', '-')}-${name}.png`);
    const open = async () => {
      await demo.getByRole('button', { name: 'Open Objects', exact: true }).click();
      await expect(panel.getByRole('searchbox')).toBeFocused();
    };
    const close = async () => {
      await panel.getByRole('button', { name: 'Close', exact: true }).click();
      await expect(panel).toBeHidden();
    };
    await expect(widget.locator('canvas').first()).toBeVisible();
    await open();
    await expect(panel.locator('.oac-objects__row')).toHaveCount(5);
    const primary = panel.locator('[data-object-id="source:primary"]');
    await expect(primary).toContainText('OBJECTS SIM');
    await expect(primary.locator('[data-action="remove"]')).toHaveCount(0);
    const profile = panel.locator('[data-object-id="custom:session-profile"]');
    await expect(profile.locator('button')).toHaveCount(2);
    await profile.getByRole('button', { name: 'Hide Session profile', exact: true }).click();
    await expect(profile).toContainText('Hidden');
    await profile.getByRole('button', { name: 'Show Session profile', exact: true }).click();

    await panel.getByRole('searchbox').fill('pane 2');
    await expect(panel.locator('.oac-objects__row')).toHaveCount(1);
    await expect(panel.locator('[data-object-id^="indicator:"]')).toHaveCount(1);
    await panel.getByRole('searchbox').fill('not on this chart');
    await expect(panel.getByText('No objects match your search.', { exact: true })).toBeVisible();
    await panel.getByRole('searchbox').fill('trend');
    const line = panel.locator('[data-object-id^="drawing:"]').filter({
      has: page.getByText('Trend Line', { exact: true }),
    });
    await line.getByRole('button', { name: 'Select Trend Line', exact: true }).click();
    await expect(line.getByRole('button', { name: 'Select Trend Line', exact: true }))
      .toHaveAttribute('aria-pressed', 'true');
    await line.getByRole('button', { name: 'Hide Trend Line', exact: true }).click();
    await expect(line).toContainText('Hidden');
    await line.getByRole('button', { name: 'Show Trend Line', exact: true }).click();
    await line.getByRole('button', { name: 'Lock Trend Line', exact: true }).click();
    await expect(line.getByRole('button', { name: 'Unlock Trend Line', exact: true })).toBeVisible();
    await line.getByRole('button', { name: 'Delete Trend Line', exact: true }).click();
    await expect(line).toHaveCount(0);
    await close();
    await demo.getByRole('button', { name: 'Undo drawing action', exact: true }).click();
    await open();
    await expect(line).toHaveCount(1);
    await checkBounds(widget, panel);
    await page.screenshot({ path: shot('wide-panel') });

    const future = panel.locator('[data-object-id^="drawing:"]').filter({
      has: page.getByText('Rectangle', { exact: true }),
    });
    await future.getByRole('button', { name: 'Focus Rectangle', exact: true }).click();
    await close();
    await page.screenshot({ path: shot('future-focus') });

    await open();
    const study = panel.locator('[data-object-id^="indicator:"]');
    await study.locator('[data-action="visibility"]').click();
    await expect(study).toContainText('Hidden');
    await close();
    await demo.getByRole('button', { name: 'Save layout', exact: true }).click();
    await open();
    await study.locator('[data-action="visibility"]').click();
    await expect(study).toContainText('Visible');
    await close();
    await demo.getByRole('button', { name: 'Restore layout', exact: true }).click();
    await open();
    await expect(study).toContainText('Hidden');
    await close();

    await demo.getByRole('button', { name: 'Width: fit', exact: true }).click();
    await expect.poll(async () => (await widget.boundingBox())?.width).toBeLessThanOrEqual(350);
    await open();
    await checkBounds(widget, panel);
    await page.screenshot({ path: shot('compact-panel') });
    await close();
    await page.setViewportSize({ width: 390, height: 844 });
    await demo.scrollIntoViewIfNeeded();
    await open();
    await checkBounds(widget, panel);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true,
      'The mobile documentation page must not overflow horizontally');
    const chartBounds = await widget.boundingBox();
    const captionBounds = await demo.locator('.oac-example__caption').boundingBox();
    assert.ok(chartBounds && captionBounds && chartBounds.y + chartBounds.height <= captionBounds.y + 1,
      'The mobile chart must not overlap its caption');
    await page.screenshot({ path: shot('mobile-panel') });
    await profile.getByRole('button', { name: 'Remove Session profile', exact: true }).click();
    await expect(profile).toHaveCount(0);
    await close();
    assert.deepEqual(errors, [], `No browser errors on ${route}`);
    await page.close();
    console.log(`Objects website ${route}: drawing actions and undo, future focus, provider capabilities, protected source, saved indicator visibility and compact layouts passed.`);
  }
} finally { await browser.close(); }
