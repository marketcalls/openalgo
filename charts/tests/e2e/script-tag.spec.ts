import { test, expect, type Page } from '@playwright/test';

// The script-tag build in all three engines: a plain page loads the nine
// classic scripts (no modules, no bundler, no import map) and draws with them.
// Each tier file adds itself to the base's `OpenAlgoCharts` global and
// registers into the base's registries, and the widget's first-use parts are
// bundled into its script, so nothing on the page is fetched as a module.
// scripts/check-exports.mjs holds the global's keys to the declarations.

const FIXTURE = '/tests/e2e/script-tag-fixture.html';
const TIERS = ['trade', 'transform', 'profile', 'indicators', 'draw', 'webgl', 'workspace', 'widget'];

async function open(page: Page): Promise<{ errors: string[]; modules: string[] }> {
  const errors: string[] = [];
  const modules: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('request', (r) => { if (new URL(r.url()).pathname.endsWith('.mjs')) modules.push(r.url()); });
  await page.setViewportSize({ width: 1280, height: 600 });
  await page.goto(FIXTURE);
  // The classic scripts have all run by the load event: a missing or refused
  // tier file has already thrown, so say so rather than wait out the timeout.
  expect(errors).toEqual([]);
  await page.waitForFunction(() => (window as any).__ready === true && (window as any).__loaded > 0);
  return { errors, modules };
}

/** Pixels near one colour across the plain chart's canvases. */
function pixelsNear(page: Page, rgb: [number, number, number]): Promise<number> {
  return page.evaluate(([r, g, b]) => {
    let n = 0;
    for (const canvas of document.querySelectorAll<HTMLCanvasElement>('#chart canvas')) {
      const ctx = canvas.getContext('2d');
      if (!ctx || canvas.width === 0 || canvas.height === 0) continue;
      const d = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      for (let i = 0; i < d.length; i += 4) {
        if (d[i + 3] > 200 && Math.abs(d[i] - r) < 40 && Math.abs(d[i + 1] - g) < 40 && Math.abs(d[i + 2] - b) < 40) n++;
      }
    }
    return n;
  }, rgb);
}

test('every tier file joins the page\'s base global and registers into its registries', async ({ page }) => {
  const { errors, modules } = await open(page);
  const seen = await page.evaluate((tiers) => {
    const g = (window as any).OpenAlgoCharts;
    const ids = new Set(g.registeredIndicators().map((d: { id: string }) => d.id));
    return {
      tiers: tiers.filter((t) => typeof g[t] === 'object' && Object.keys(g[t]).length > 0),
      indicators: g.indicators.BUILTIN_INDICATORS.every((d: { id: string }) => ids.has(d.id)),
      tools: g.draw.registeredDrawingTools().length === g.draw.BUILTIN_DRAWING_TOOLS.length,
      chartTypes: ['point-figure', 'kagi'].every((t) => g.registeredChartTypes().includes(t)),
      backends: g.registeredRenderBackends().includes('webgl2'),
      sharedError: g.trade.TradingCapabilityError === g.TradingCapabilityError,
    };
  }, TIERS);
  expect(seen).toEqual({ tiers: TIERS, indicators: true, tools: true, chartTypes: true, backends: true, sharedError: true });
  expect(modules).toEqual([]);
  expect(errors).toEqual([]);
});

test('a plain chart draws a study from the indicator tier and a drawing from the draw tier', async ({ page }, info) => {
  const { errors } = await open(page);
  const state = await page.evaluate(() => {
    const { chart, rsi, draw } = (window as any).__page;
    return {
      panes: chart.panes().length,
      readings: rsi.values().rsi.filter((v: number | null) => Number.isFinite(v)).length,
      drawings: draw.drawings().map((d: { tool: string }) => d.tool),
    };
  });
  expect(state.panes).toBe(2);
  expect(state.readings).toBeGreaterThan(150);
  expect(state.drawings).toEqual(['trend-line']);
  // The study's line and the drawing reached the canvas, not only the model.
  expect(await pixelsNear(page, [0, 229, 255])).toBeGreaterThan(200);
  expect(await pixelsNear(page, [255, 0, 255])).toBeGreaterThan(200);
  await info.attach('script-tag chart, study, drawing and widget', { body: await page.screenshot(), contentType: 'image/png' });
  expect(errors).toEqual([]);
});

test('the widget renders and opens a first-use part it carries in its own file', async ({ page }, info) => {
  const { errors, modules } = await open(page);
  await expect(page.locator('#terminal .oac-widget')).toBeVisible();
  const box = await page.locator('#terminal .oac-widget .oac-chart').boundingBox();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await page.keyboard.press('Shift+Slash');
  await expect(page.locator('.oac-keys-dialog')).toBeVisible();
  await info.attach('script-tag widget shortcuts panel', { body: await page.screenshot(), contentType: 'image/png' });
  expect(modules).toEqual([]);
  expect(errors).toEqual([]);
});
