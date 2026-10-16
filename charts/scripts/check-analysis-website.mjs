/** Exercise the same public example before deployment and on the published site. */
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { chromium, firefox, webkit, expect } from '@playwright/test';

const base = (process.argv[2] ?? 'http://127.0.0.1:4174/openalgo-charts').replace(/\/$/, '');
const output = process.env.OAC_ARTIFACT_DIR ?? 'artifacts';
await mkdir(output, { recursive: true });
const engines = { chromium, firefox, webkit };
for (const name of (process.env.OAC_WEBSITE_BROWSERS ?? 'chromium,firefox,webkit').split(',')) {
  const browser = await engines[name].launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base + '/examples/');
    const demo = page.locator('.oac-linked-analysis');
    await expect(demo.getByRole('button', { name: 'Anchor VWAP', exact: true })).toBeVisible();
    await expect(demo.locator('.oac-example__err')).toHaveCount(0);
    await expect(demo.locator('.oac-widget')).toHaveCount(2);
    await demo.scrollIntoViewIfNeeded();
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const ink = async () => demo.locator('.oac-widget').evaluateAll(widgets => widgets.map(widget => {
      let total = 0;
      for (const canvas of widget.querySelectorAll('canvas')) {
        const pixels = canvas.getContext('2d')?.getImageData(0, 0, canvas.width, canvas.height).data;
        for (let i = 0; pixels && i < pixels.length; i += 4) total += pixels[i] + pixels[i + 1] + pixels[i + 2];
      }
      return total;
    }));
    const before = await ink();
    await demo.getByRole('button', { name: 'Undo', exact: true }).click();
    await expect.poll(ink).not.toEqual(before);
    const after = await ink();
    expect(after[0]).not.toBe(before[0]);
    expect(after[1]).not.toBe(before[1]);
    const events = page.locator('.oac-timeline-events');
    await events.scrollIntoViewIfNeeded();
    const eventPoint = await events.locator('.oac-widget').evaluate(widget => {
      for (const canvas of widget.querySelectorAll('canvas')) {
        const pixels = canvas.getContext('2d')?.getImageData(0, 0, canvas.width, canvas.height).data;
        const rect = canvas.getBoundingClientRect();
        const ratio = canvas.width / rect.width;
        const hits = [];
        for (let y = Math.max(0, canvas.height - Math.ceil(60 * ratio)); y < canvas.height; y++) {
          for (let x = 0; pixels && x < canvas.width; x++) {
            const i = (y * canvas.width + x) * 4;
            if (pixels[i] === 240 && pixels[i + 1] === 160 && pixels[i + 2] === 32 && pixels[i + 3] > 0) hits.push({ x, y });
          }
        }
        if (hits.length) return {
          x: rect.left + hits.reduce((sum, point) => sum + point.x, 0) / hits.length / ratio,
          y: rect.top + hits.reduce((sum, point) => sum + point.y, 0) / hits.length / ratio,
        };
      }
      return null;
    });
    expect(eventPoint).not.toBeNull();
    await page.mouse.click(eventPoint.x, eventPoint.y);
    await expect(events.locator('.oac-timeline-events__detail')).toContainText('Sample results');
    await expect(events.getByRole('button', { name: 'Sample investor call', exact: true })).toBeVisible();
    await events.getByRole('button', { name: 'Sample investor call', exact: true }).click();
    await expect(events.locator('.oac-timeline-events__detail')).toContainText('Investor Q&A');
    await events.screenshot({ path: join(output, `events-253-${name}.png`) });
    await demo.scrollIntoViewIfNeeded();
    await demo.screenshot({ path: join(output, `analysis-253-${name}.png`) });
    await page.setViewportSize({ width: 390, height: 844 });
    await demo.scrollIntoViewIfNeeded();
    const overflow = await demo.evaluate(el => el.scrollWidth > el.clientWidth + 1);
    expect(overflow).toBe(false);
    const clippedCharts = await demo.evaluate(el => {
      const stage = el.querySelector('.oac-example__chart').getBoundingClientRect();
      return [...el.querySelectorAll('.oac-widget')].some(widget => {
        const box = widget.getBoundingClientRect();
        return box.top < stage.top || box.bottom > stage.bottom + 1 || box.height < 100;
      });
    });
    expect(clippedCharts).toBe(false);
    await demo.screenshot({ path: join(output, `analysis-253-${name}-narrow.png`) });
    expect(errors).toEqual([]);
    console.log(`${name}: linked studies, undo, event details and narrow layout passed`);
  } finally { await browser.close(); }
}
