/** Verify the example data, marketing chart, responsive theme and regenerated API reference. */
import { strict as assert } from 'node:assert';
import { mkdir, readdir, readFile } from 'node:fs/promises';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium, expect } from '@playwright/test';

const base = (process.argv[2] ?? 'http://127.0.0.1:4174/openalgo-charts').replace(/\/$/, '');
const { version } = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'));

// Every chart a reader sees is drawn from prices that move like a traded
// instrument: a seeded random walk with wicks and volume (stockBars in
// website/components/synthetic-market.ts), and any study output or drawing on
// it is computed from those bars. Sine waves, straight ramps and sawtooths in
// the bar index made the examples look like test fixtures, so the sources are
// read before any page is: this part needs no build.
const SYNTHETIC = [
  ['a sine or cosine of the index', /Math\.(?:sin|cos)\(/],
  ['a straight ramp in the bar index', /\b(?:open|high|low|close|value)\s*:\s*[\d.]+\s*[+-]\s*(?:i|index)\s*[*/]/],
  ['a sawtooth in the bar index', /\+\s*\(?\s*(?:i|index)\s*%\s*\d+(?!\d)\s*\)?(?!\s*[=!<>])/],
];
const repo = fileURLToPath(new URL('..', import.meta.url));
async function sourceFiles(dir) {
  const out = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...await sourceFiles(path));
    else if (/\.(?:mdx|md|tsx|ts)$/.test(entry.name)) out.push(path);
  }
  return out;
}
// The site's own pages and components; website/lib holds the synced bundles.
const files = [...await sourceFiles(join(repo, 'website/pages')), ...await sourceFiles(join(repo, 'website/components'))];
assert.ok(files.length > 50, `expected the website sources, found ${files.length} files`);
const synthetic = [];
for (const file of files) {
  (await readFile(file, 'utf8')).split(/\r?\n/).forEach((line, i) => {
    for (const [what, pattern] of SYNTHETIC) {
      if (pattern.test(line)) synthetic.push(`${relative(repo, file).replaceAll('\\', '/')}:${i + 1} ${what}: ${line.trim()}`);
    }
  });
}
assert.deepEqual(synthetic, [], 'Website examples must draw prices and study outputs from stockBars, not a formula of the bar index');

await mkdir('artifacts', { recursive: true });
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, colorScheme: 'dark' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`${base}/`);
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  // A first visit opens in light even on a system that prefers dark; only a
  // choice the reader saves on the site changes it.
  await expect(page.locator('html')).toHaveClass(/(?:^|\s)light(?:\s|$)/);
  await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', '#fcfcfc');
  await expect(page.locator('img[src*="screenshots/market-profile"]')).toHaveCount(0);
  await expect(page.locator('.oac-profile-demo')).toHaveCount(0);
  await expect(page.locator('.oac-example__code')).toHaveCount(0);
  const widget = page.locator('.oac-widget').first();
  await expect(widget.locator('canvas').first()).toBeVisible();
  await expect(widget.locator('.oac-rail')).toBeVisible();
  const trend = widget.getByRole('button', { name: 'Trend Line', exact: true });
  await trend.click();
  await expect(trend).toHaveAttribute('aria-pressed', 'true');
  await page.keyboard.press('Escape');
  await expect(trend).toHaveAttribute('aria-pressed', 'false');
  await widget.getByRole('button', { name: 'Indicators', exact: true }).click();
  const picker = page.getByRole('dialog');
  await expect(picker).toBeVisible();
  await expect(picker.getByRole('option').first()).toBeVisible();
  await picker.getByRole('button', { name: 'Close', exact: true }).click();
  await widget.getByRole('button', { name: 'Chart settings', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click();
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.evaluate(() => scrollTo({ top: 0, behavior: 'instant' }));
  await page.waitForFunction(() => scrollY === 0);
  await page.screenshot({ path: 'artifacts/website-premium-home.png', fullPage: true });

  for (const route of ['/', '/docs/getting-started/', '/examples/']) {
    await page.goto(`${base}${route}`);
    for (const width of [320, 390, 768, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${route} must fit ${width}px viewport`);
    }
  }
  await page.evaluate(() => localStorage.setItem('oac-theme', 'light'));
  await page.goto(`${base}/docs/getting-started/`);
  await expect(page.locator('html')).toHaveClass(/light/);
  await page.screenshot({ path: 'artifacts/website-premium-docs-light.png' });
  await page.evaluate(() => localStorage.setItem('oac-theme', 'dark'));
  await page.reload();
  await expect(page.locator('html')).toHaveClass(/dark/);
  await page.screenshot({ path: 'artifacts/website-premium-docs-dark.png' });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(`${base}/`);
  await expect(widget.locator('canvas').first()).toBeVisible();
  const activeAnimations = await page.evaluate(() => document.getAnimations().filter(animation => animation.playState === 'running').length);
  assert.equal(activeAnimations, 0, 'Reduced motion must disable intro animations');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: 'artifacts/website-premium-home-mobile.png', fullPage: true });

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${base}/api/`);
  await expect(page.getByRole('heading', { level: 1 })).toContainText(`v${version}`);
  const css = page.locator('link[rel="stylesheet"][href*="custom.css"]');
  assert.equal(await css.count(), 1);
  const cssHref = await css.evaluate(node => node.href);
  assert.match(cssHref, /cache=/);
  assert.equal((await page.request.get(cssHref)).status(), 200);
  await expect(page.locator('#tsd-toolbar-links').getByRole('link', { name: 'Live demos', exact: true })).toHaveAttribute('href', '/openalgo-charts/examples/');
  for (const href of await page.locator('.oac-api-links a, .tsd-typography table a').evaluateAll(nodes => nodes.map(node => node.href))) {
    assert.equal((await page.request.get(href)).status(), 200, href);
  }
  await page.screenshot({ path: 'artifacts/website-premium-api.png' });
  await page.locator('label[for="tsd-search-field"]').click();
  await page.locator('#tsd-search-field').fill('setSessionSplit');
  await expect(page.locator('#tsd-search .results a').first()).toContainText('setSessionSplit');
  await page.locator('#tsd-search .results a').first().click();
  await expect(page.getByRole('heading', { level: 1 })).toContainText('MarketProfile');
  const apiBody = await page.locator('body').innerText();
  assert.match(apiBody, /setSessionSplit/);
  assert.match(apiBody, /isSessionSplit/);
  await page.goto(`${base}/api/interfaces/profile.MarketProfilePrimitiveOptions.html`);
  const options = await page.locator('body').innerText();
  assert.match(options, /showSessionOpen/);
  assert.match(options, /showLastPrice/);
  // Keyed on the page's scroll width, not on typedoc's class names, which a
  // typedoc upgrade renames. The pages are the index and the ones with the
  // longest type and member names, which do not break without help.
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 });
    for (const route of ['/api/', '/api/classes/index.Chart.html', '/api/interfaces/profile.MarketProfilePrimitiveOptions.html',
      '/api/classes/workspace.DrawingTemplateConflictError.html', '/api/modules/workspace.html']) {
      await page.goto(`${base}${route}`);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `API page ${route} must fit ${width}px viewport`);
    }
  }
  await page.goto(`${base}/api/`);
  await page.getByRole('link', { name: 'Menu', exact: true }).click();
  await expect(page.locator('html')).toHaveClass(/has-menu/);
  await page.screenshot({ path: 'artifacts/website-premium-api-mobile.png' });
  assert.deepEqual(errors, []);
  console.log('Site design checks passed: interactive homepage tools and dialogs, responsive pages, dark/light docs, reduced motion, current versioned API, working API search and mobile navigation.');
} finally {
  await browser.close();
}
