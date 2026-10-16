/** Exercise the published website's drawing playground through its visible UI. */
import { strict as assert } from 'node:assert';
import { mkdir } from 'node:fs/promises';
import { chromium, expect } from '@playwright/test';

const base = (process.argv[2] ?? 'http://127.0.0.1:4174/openalgo-charts').replace(/\/$/, '');
await mkdir('artifacts', { recursive: true });
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`${base}/docs/drawing-tools/`);
  const demo = page.locator('.oac-drawing-demo');
  const status = demo.getByRole('status');
  const plot = demo.locator('.oac-draw-playground__plot');
  await expect(demo.getByRole('group', { name: 'Drawing tools' })).toBeVisible();
  await expect(status).toContainText('3 drawings');
  await expect(plot.locator('canvas').first()).toBeVisible();
  await expect(demo.getByRole('button', { name: 'Undo', exact: true })).toBeDisabled();

  // Two chart clicks must commit a real drawing and select it automatically.
  await demo.getByRole('button', { name: 'Trend line', exact: true }).click();
  await expect(status).toContainText('Trend Line');
  await plot.scrollIntoViewIfNeeded();
  const bounds = await plot.boundingBox();
  assert.ok(bounds && bounds.width > 200 && bounds.height > 200);
  await plot.click({ position: { x: bounds.width * 0.22, y: bounds.height * 0.25 } });
  await plot.click({ position: { x: bounds.width * 0.48, y: bounds.height * 0.42 } });
  await expect(status).toContainText('4 drawings');
  await expect(status).toContainText('Selected: Trend Line');
  await expect(demo.getByRole('button', { name: 'Cursor', exact: true })).toHaveAttribute('aria-pressed', 'true');

  await demo.getByRole('button', { name: 'Delete', exact: true }).click();
  await expect(status).toContainText('3 drawings');
  await demo.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(status).toContainText('4 drawings');
  await demo.getByRole('button', { name: 'Redo', exact: true }).click();
  await expect(status).toContainText('3 drawings');

  // A named seed drawing can be selected without pixel hunting, then removed by key.
  await demo.getByLabel('Select a drawing').selectOption('demo-zone');
  await expect(status).toContainText('Selected: Supply zone');
  await plot.focus();
  await page.keyboard.press('Delete');
  await expect(status).toContainText('2 drawings');
  await page.keyboard.press('Control+z');
  await expect(status).toContainText('3 drawings');
  await demo.getByRole('button', { name: 'Rectangle', exact: true }).click();
  await page.keyboard.press('Escape');
  await expect(demo.getByRole('button', { name: 'Cursor', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await demo.getByRole('button', { name: 'Reset demo', exact: true }).click();
  await expect(status).toContainText('3 drawings');
  await expect(demo.getByRole('button', { name: 'Undo', exact: true })).toBeDisabled();

  const catalogue = demo.getByLabel('All drawing tools');
  await expect(catalogue.locator('option')).toHaveCount(88);
  await catalogue.selectOption('pitchfork');
  await expect(status).toContainText('Pitchfork');
  for (const [x, y] of [[.2, .55], [.4, .25], [.6, .65]]) {
    await plot.click({ position: { x: bounds.width * x, y: bounds.height * y } });
  }
  await expect(status).toContainText('4 drawings');
  await demo.getByRole('button', { name: 'Reset demo', exact: true }).click();

  await demo.getByText('View the running example source', { exact: true }).click();
  await expect(demo.getByRole('region', { name: 'Drawing playground source' })).toContainText('new lib.DrawingController');
  await demo.getByText('View the running example source', { exact: true }).click();
  await demo.screenshot({ path: 'artifacts/website-drawing-tools.png' });

  // Theme changes recreate the example; controls must remain functional afterward.
  const oldPlot = await plot.elementHandle();
  const nextTheme = await page.evaluate(() => document.documentElement.classList.contains('dark') ? 'Light' : 'Dark');
  await page.locator('button[title="Change theme"]').first().click();
  await page.getByRole('option', { name: nextTheme, exact: true }).click();
  await expect.poll(() => oldPlot.evaluate(node => node.isConnected)).toBe(false);
  await expect(status).toContainText('3 drawings');
  await demo.getByLabel('Select a drawing').selectOption('demo-zone');
  await demo.getByRole('button', { name: 'Delete', exact: true }).click();
  await expect(status).toContainText('2 drawings');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(status).toContainText('3 drawings');
  await plot.scrollIntoViewIfNeeded();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
    'Drawing guide must not overflow horizontally on mobile');
  await expect(demo.getByRole('button', { name: 'Brush', exact: true })).toBeVisible();
  await expect(plot).toBeVisible();
  await demo.screenshot({ path: 'artifacts/website-drawing-tools-mobile.png' });

  await page.goto(`${base}/examples/`);
  await expect(page.locator('.oac-drawing-demo').getByRole('status')).toContainText('3 drawings');

  await page.goto(`${base}/demos/drawings/index.html`);
  await page.waitForFunction(() => window.drawingGallery);
  await expect(page.locator('#tool option')).toHaveCount(87);
  await page.selectOption('#tool', 'gartley');
  await expect(page.locator('#status')).toContainText('Gartley');
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Drawing gallery fits a phone');
  assert.equal(await page.evaluate(() => window.drawingGallery.widget.draw.drawings()[0].tool), 'gartley');
  await page.screenshot({ path: 'artifacts/website-drawing-gallery-mobile.png' });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('button', { name: 'Show sample', exact: true }).click();
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.screenshot({ path: 'artifacts/website-drawing-gallery.png' });
  assert.deepEqual(errors, []);
  console.log('Drawing playground passed: real placement, selection, delete, undo/redo, local shortcuts, reset, source, theme recreation, mobile layout, and examples integration.');
} finally {
  await browser.close();
}
