/** Reproducible close-ups of the real synthetic-data profile demo. */
import { strict as assert } from 'node:assert';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const demoUrl = process.argv[2] ?? 'http://127.0.0.1:4173/examples/market-profile/index.html';
const output = fileURLToPath(new URL('../website/public/screenshots/market-profile-v2.1.1/', import.meta.url));
await mkdir(output, { recursive: true });
const captures = {};
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2 });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const paint = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const capture = async (name, options = {}) => {
    const bytes = await page.screenshot({ path: `${output}/${name}.png`, ...options });
    captures[name] = { file: `${name}.png`, sha256: digest(bytes), width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
  };
  const setSplit = async (split) => {
    if (await page.evaluate(() => window.__mp().isSessionSplit(5)) === split) return;
    await paint();
    const point = await page.evaluate(() => {
      const chart = window.__chart();
      const session = window.__profileResult().sessions[5];
      return { x: chart.timeScale.indexToX(375) + 30,
        y: chart.panes()[0].priceScale.priceToY(session.poc) };
    });
    await page.locator('#chart').click({ button: 'right', position: point });
    await page.getByRole('menuitem', { name: split ? 'Split this day' : 'Unsplit this day', exact: true }).click();
    await page.mouse.move(0, 0);
  };
  const url = new URL(demoUrl);
  url.searchParams.set('theme', 'dark');
  await page.goto(url.href);
  await page.waitForFunction(() => typeof window.__mp === 'function');
  await page.locator('#theme').selectOption('blue');
  await page.locator('#compressed').click();
  await paint();
  assert.equal(await page.evaluate(() => window.__mp().options().blockDisplay), 'compact');
  assert.equal(await page.locator('#density').inputValue(), '5');
  assert.deepEqual(await page.evaluate(() => window.__profileResult().sessions.map((_, i) => window.__mp().isSessionSplit(i))), Array(6).fill(false));
  await page.mouse.move(0, 0);
  await capture('compressed-overview');
  await page.setViewportSize({ width: 400, height: 1100 });
  await paint();
  // Fit a full day vertically and give every period room. Crop only the chart;
  // the surrounding gallery supplies theme names and links to the live controls.
  const chartTop = await page.locator('#chart').evaluate(node => node.getBoundingClientRect().top);
  await page.locator('#chart').evaluate(node => { node.style.flex = 'none'; node.style.height = '660px'; });
  await page.setViewportSize({ width: 400, height: Math.ceil(chartTop + 660) });
  const clip = { x: 0, y: Math.ceil(chartTop), width: 400, height: 660 };
  await paint();
  await page.locator('#density').fill('18');
  await page.locator('#density').dispatchEvent('input');
  await paint();
  const before = await page.evaluate(() => JSON.stringify(window.__profileResult()));
  await page.evaluate(() => {
    const chart = window.__chart();
    const scale = chart.panes()[0].priceScale;
    const session = window.__profileResult().sessions.at(-1);
    const span = scale.height * 2 / 18;
    const centre = (session.high + session.low) / 2;
    scale.setPriceRange({ min: centre - span / 2, max: centre + span / 2 });
    chart.timeScale.setVisibleLogicalRange({ from: 375, to: 455 });
    window.__mp().setOptions({ font: 16, letterWidth: 12, volumeProfileWidth: 90, showSessionLabel: true });
  });
  await setSplit(true);
  for (const theme of ['dark', 'blue', 'graphite', 'emerald', 'ivory']) {
    await page.locator('#theme').selectOption(theme);
    await paint();
    assert.equal(await page.evaluate(() => window.__mp().isSessionSplit(5)), true, `${theme} must preserve the split session`);
    const rowHeight = await page.evaluate(() => {
      const scale = window.__chart().panes()[0].priceScale;
      const poc = window.__profileResult().sessions[5].poc;
      return Math.abs(scale.priceToY(poc + 2) - scale.priceToY(poc));
    });
    assert.ok(Math.abs(rowHeight - 18) < 0.01, `${theme} must match the documented 18px row height`);
    await capture(theme, { clip });
    console.log(`Captured ${theme}: 800 x 1320, DPR 2, 18px rows, 16px letters, newest session split`);
  }
  await page.locator('#theme').selectOption('graphite');
  for (const split of [false, true]) {
    await setSplit(split);
    await paint();
    await capture(`${split ? 'split' : 'packed'}-detail`, { clip });
  }
  assert.equal(await page.evaluate(() => JSON.stringify(window.__profileResult())), before, 'Close-up captures must preserve the original price rows and analytics');
  assert.deepEqual(errors, []);
  const sources = {};
  for (const path of ['examples/market-profile/index.html', 'examples/market-profile/themes.js', 'src/profile/market-profile-primitive.ts', 'src/profile/market-profile.ts', 'src/profile/compact-text.ts', 'src/primitives/watermark.ts', 'src/primitives/openalgo-glyph.ts']) {
    sources[path] = digest(await readFile(new URL(`../${path}`, import.meta.url)));
  }
  await writeFile(`${output}/captures.json`, JSON.stringify({
    sources,
    settings: { deviceScaleFactor: 2, blockDisplay: 'compact', overviewRowHeight: 5, closeupRowHeight: 18, closeupFont: 16 },
    captures,
  }, null, 2) + '\n');
} finally {
  await browser.close();
}
