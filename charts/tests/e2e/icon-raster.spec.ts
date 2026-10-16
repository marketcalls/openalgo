import { expect, test, type Page } from '@playwright/test';
import type { Widget } from '../../src/widget/widget';

/**
 * The icon sets, judged as pixels.
 *
 * `tests/draw-icons.test.ts` holds the path data to its grid and rejects two
 * glyphs that are the same drawing written differently. It cannot see two
 * drawings that differ on paper and still rasterise to the same shape at the
 * size a rail shows them: lock and unlock differed by one short stroke, which
 * a round cap filled in, and overlapped by more than 99 percent at 16px.
 *
 * So every glyph is rasterised here at the size its tier is drawn for, by each
 * engine's own SVG renderer, and each pair within a tier is compared as a
 * mask: the share of inked pixels the two have in common (intersection over
 * union). The same pass measures how dark each glyph's line reads, so the two
 * tiers can be held to one weight.
 *
 * Both tiers are judged twice: as the markup builders draw them, accents
 * filled, and as the bare path data, which is all a host that wraps the
 * registry itself draws. The marks that tell siblings apart have to survive
 * the second: a horizontal ray whose origin dot lived only in its accent was
 * the horizontal line at 0.86 overlap for such a host.
 */

interface Glyph { id: string; svg: string; px: number }
type Tier = 'tools' | 'chrome';
type Rendering = 'markup' | 'path';
interface Measured {
  /** Each pair's overlap, and the count of pixels inked in one and not the other. */
  pairs: { a: string; b: string; iou: number; diff: number }[];
  /** Mean alpha over each glyph's inked pixels, averaged over the tier: the line's apparent weight. */
  weight: number;
  n: number;
  /**
   * The glyphs that inked no pixel. A blank glyph overlaps nothing, so it
   * passes every overlap ceiling while showing an empty button; the chrome
   * marks drawn as strokes of no length (an i's dot, a grip) are the ones
   * an engine could drop.
   */
  blank: string[];
}

declare global {
  interface Window {
    __iconFixture: {
      icons: Record<Tier | 'toolsPath' | 'chromePath' | 'layouts', Glyph[]>;
      widget: Widget;
      lineId: string;
      mountIndicatorSettings: (ctx: Widget['context'], anchor?: HTMLElement, opts?: { instanceId?: string; tab?: 'inputs' | 'style' }) => unknown;
      showSheet: () => number;
    };
  }
}

/** Past this overlap two buttons in one rail are the same button. */
const CEILING = 0.85;

/**
 * One control in two states, drawn alike on purpose: the second state is the
 * first with a mark added. Nothing else may pass the ceiling.
 */
const STATE_PAIRS = new Set(['star~star-filled', 'eye~eye-off', 'link~unlink', 'pin~pin-filled']);

/** Every pair among one family's ids. */
const allPairs = (ids: readonly string[]): [string, string][] =>
  ids.flatMap((a, i) => ids.slice(i + 1).map((b) => [a, b] as [string, string]));

/**
 * Siblings that sit next to each other in one flyout or menu and were
 * measured too close, held to a tighter ceiling than the rest: same family,
 * told apart by their ends, their direction or their marks. The horizontal
 * pair, the three bubbles and trash beside paste were 0.72 to 0.86. The
 * construction families were redrawn to their tools in 2.5.9 and are held
 * here too: four pitchforks that share one head and differ in where the
 * median starts, and the harmonics, which share one zigzag and differ in
 * their ratios. The supersonic pair were 0.80 before. The speed resistance
 * fan sits under the Gann box and square in its flyout, and drawn in a whole
 * box it was the closest pair of the tier, at 0.71.
 */
const SIBLINGS: Record<Tier, [string, string][]> = {
  tools: [
    ['long-position', 'short-position'], ['risk-reward-long', 'risk-reward-short'],
    ['long-position', 'risk-reward-long'], ['short-position', 'risk-reward-short'],
    ['path', 'polyline'], ['cursor', 'cross-line'],
    ['trend-line', 'ray'], ['trend-line', 'extended-line'], ['trend-line', 'info-line'], ['trend-line', 'arrow'],
    ['ray', 'extended-line'], ['ray', 'info-line'], ['extended-line', 'info-line'],
    ['horizontal-line', 'horizontal-ray'], ['callout', 'balloon'], ['callout', 'comment'], ['balloon', 'comment'],
    ...allPairs(['pitchfork', 'schiff-pitchfork', 'modified-schiff-pitchfork', 'inside-pitchfork']),
    ...allPairs(['xabcd-pattern', 'gartley', 'bat', 'butterfly', 'crab', 'shark', 'cypher']),
    ['supersonic', 'golden-supersonic'], ['sonic', 'supersonic'], ['golden-sonic', 'golden-supersonic'],
    ['fib-speed-resistance-fan', 'fib-speed-fan'], ['fib-speed-resistance-fan', 'gann-box'],
    ['fib-speed-resistance-fan', 'gann-square'], ['fib-wedge', 'fib-speed-resistance-arcs'],
    ['fib-wedge', 'fib-fan'], ['fib-circles', 'circle'],
  ],
  chrome: [
    ['lock', 'unlock'], ['cursor', 'plus'], ['trash', 'paste'],
    // The families 2.5.10 added, each the members of one menu or bar: the
    // replay controls, the corner controls of a grid, the market session,
    // the scale modes, the three levels, the layout menu, the trading
    // actions, the line styles, the link channels, the capture menu and the
    // text styles. The chart types share one menu, so all of them are held.
    ...allPairs(['replay', 'play', 'pause', 'stop', 'step-forward', 'step-back']),
    ['fullscreen', 'fullscreen-exit'], ['maximize', 'restore'], ['maximize', 'fullscreen'], ['restore', 'fullscreen-exit'],
    ...allPairs(['market-open', 'market-pre', 'market-post', 'market-closed', 'market-holiday']),
    ...allPairs(['scale-auto', 'scale-log', 'scale-percent']),
    ...allPairs(['info', 'warning', 'error']),
    ...allPairs(['folder', 'save', 'save-as', 'autosave', 'rename', 'recent', 'template']),
    ...allPairs(['buy', 'sell', 'close-position', 'reverse', 'bracket', 'dom-ladder']),
    ...allPairs(['minus', 'line-dashed', 'line-dotted', 'line-mixed']),
    ...allPairs(['link', 'link-group', 'drawing-sync', 'crosshair', 'time-range', 'palette']),
    ['grid', 'layout'], ['camera', 'capture-grid'], ['download', 'capture-grid'], ['grid', 'capture-grid'],
    ...allPairs(['chevron-up', 'chevron-down', 'chevron-left', 'chevron-right']),
    ...allPairs(['text', 'bold', 'italic']),
    ['clock', 'recent'], ['refresh', 'recent'], ['refresh', 'autosave'], ['more', 'grip'], ['sun', 'moon'],
    ...allPairs(['candlestick', 'hollow-candle', 'volume-candle', 'heikin-ashi', 'bar', 'high-low', 'line',
      'line-markers', 'step', 'area', 'hlc-area', 'baseline', 'column', 'histogram', 'point-figure', 'kagi',
      'renko', 'range-bars', 'line-break'].map((t) => `chart-${t}`)),
  ],
};
const SIBLING_CEILING = 0.7;

/**
 * How far apart the two tiers' line weights may read. Each tier's stroke is
 * set so its line is about 1.3px at the size it is drawn for (20px tools,
 * 16px chrome), so a lock under the tools reads as the same set, only
 * smaller. Through 2.6.2 the two tiers drew a 2px line on whole units and
 * this spec held their solid-pixel share instead; at a finer line nearly
 * every pixel is anti-aliased, so what is held now is that the two weigh the
 * same.
 */
const WEIGHT_GAP = 0.08;

/** The computed stroke widths the widget's stylesheet gives each tier: the tier constants. */
const TOOL_PX = '1.6px';
const CHROME_PX = '1.3px';

async function mount(page: Page, theme: 'dark' | 'light' = 'dark'): Promise<string[]> {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1180, height: 760 });
  await page.goto(`/tests/e2e/icon-raster-fixture.html?theme=${theme}`);
  await page.waitForFunction(() => !!window.__iconFixture && window.__iconFixture.lineId !== '');
  return errors;
}

/** Rasterise one tier, drawn one way, in the page and compare every pair. */
function measure(page: Page, tier: Tier, rendering: Rendering = 'markup'): Promise<Measured> {
  return rasterise(page, rendering === 'markup' ? tier : `${tier}Path`);
}

/** Rasterise one list of the fixture's glyphs and compare every pair in it. */
function rasterise(page: Page, which: 'tools' | 'chrome' | 'toolsPath' | 'chromePath' | 'layouts'): Promise<Measured> {
  return page.evaluate(async (which) => {
    const list = window.__iconFixture.icons[which];
    const rows: { id: string; mask: Uint8Array; lit: number; ink: number }[] = [];
    for (const g of list) {
      // Black on transparent, so alpha alone is the ink.
      const img = new Image();
      img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(g.svg.replace(/currentColor/g, '#000'));
      await img.decode();
      const c = document.createElement('canvas');
      c.width = g.px;
      c.height = g.px;
      const ctx = c.getContext('2d')!;
      ctx.drawImage(img, 0, 0, g.px, g.px);
      const data = ctx.getImageData(0, 0, g.px, g.px).data;
      const mask = new Uint8Array(g.px * g.px);
      let lit = 0;
      let ink = 0;
      for (let i = 0; i < mask.length; i++) {
        const a = data[i * 4 + 3] / 255;
        mask[i] = a > 0.3 ? 1 : 0;
        if (a > 0.05) { lit++; ink += a; }
      }
      rows.push({ id: g.id, mask, lit, ink });
    }
    const pairs: { a: string; b: string; iou: number; diff: number }[] = [];
    for (let i = 0; i < rows.length; i++) {
      for (let j = i + 1; j < rows.length; j++) {
        let inter = 0;
        let union = 0;
        const A = rows[i].mask;
        const B = rows[j].mask;
        for (let k = 0; k < A.length; k++) { inter += A[k] & B[k]; union += A[k] | B[k]; }
        pairs.push({ a: rows[i].id, b: rows[j].id, iou: union === 0 ? 0 : inter / union, diff: union - inter });
      }
    }
    return {
      pairs, n: rows.length,
      // Ink per inked pixel: how dark the line reads, whatever its length.
      weight: rows.reduce((s, r) => s + (r.lit === 0 ? 0 : r.ink / r.lit), 0) / rows.length,
      blank: rows.filter((r) => r.lit === 0).map((r) => r.id),
    };
  }, which);
}

const key = (a: string, b: string): string => `${a}~${b}`;

for (const [tier, rendering] of [['tools', 'markup'], ['chrome', 'markup'], ['tools', 'path'], ['chrome', 'path']] as const) {
  test(`no two ${tier} glyphs rasterise to the same shape, drawn as ${rendering === 'path' ? 'bare path data' : 'markup'}`, async ({ page }, info) => {
    const errors = await mount(page);
    const m = await measure(page, tier, rendering);
    expect(m.n).toBeGreaterThan(20);
    expect(m.blank, 'glyphs that ink no pixel').toEqual([]);
    const close = m.pairs
      .filter((p) => p.iou >= CEILING && !STATE_PAIRS.has(key(p.a, p.b)) && !STATE_PAIRS.has(key(p.b, p.a)))
      .map((p) => `${key(p.a, p.b)} ${p.iou.toFixed(2)}`);
    await info.attach(`${tier}-${rendering}-closest.txt`, {
      body: [...m.pairs].sort((p, q) => q.iou - p.iou).slice(0, 20).map((p) => `${key(p.a, p.b)} ${p.iou.toFixed(3)}`).join('\n'),
      contentType: 'text/plain',
    });
    expect(close, `pairs at IoU ${CEILING} or more`).toEqual([]);

    const byKey = new Map(m.pairs.map((p) => [key(p.a, p.b), p.iou] as const));
    const siblings = SIBLINGS[tier].map(([a, b]) => {
      const iou = byKey.get(key(a, b)) ?? byKey.get(key(b, a));
      expect(iou, `${key(a, b)} was not measured`).toBeDefined();
      return { pair: key(a, b), iou: iou! };
    });
    const tooClose = siblings.filter((s) => s.iou >= SIBLING_CEILING).map((s) => `${s.pair} ${s.iou.toFixed(2)}`);
    expect(tooClose, `siblings at IoU ${SIBLING_CEILING} or more`).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test('both tiers draw one line weight at the size they are drawn for', async ({ page }, info) => {
  await mount(page);
  const tools = await measure(page, 'tools');
  const chrome = await measure(page, 'chrome');
  await info.attach('weights.txt', { body: `tools ${tools.weight.toFixed(3)} chrome ${chrome.weight.toFixed(3)}`, contentType: 'text/plain' });
  console.log('WEIGHTS', tools.weight.toFixed(3), chrome.weight.toFixed(3));
  expect(tools.blank).toEqual([]);
  expect(chrome.blank).toEqual([]);
  expect(Math.abs(tools.weight - chrome.weight)).toBeLessThan(WEIGHT_GAP);
});

test('every two layout tiles differ by a divider, and weigh what the chrome set weighs', async ({ page }, info) => {
  // The tiles share their frame by design, so their overlap is high whatever
  // they show: a picker tells them apart by the dividers they do not share.
  // Each pair has to differ by at least a short divider, and the tiles sit
  // in a menu beside chrome glyphs, so they draw the same line.
  const errors = await mount(page);
  const m = await rasterise(page, 'layouts');
  const chrome = await measure(page, 'chrome');
  expect(m.n).toBeGreaterThan(10);
  expect(m.blank, 'tiles that ink no pixel').toEqual([]);
  const nearest = [...m.pairs].sort((p, q) => p.diff - q.diff);
  await info.attach('layouts-nearest.txt', {
    body: nearest.slice(0, 10).map((p) => `${key(p.a, p.b)} ${p.diff}px ${p.iou.toFixed(3)}`).join('\n') + `\nweight ${m.weight.toFixed(3)}`,
    contentType: 'text/plain',
  });
  expect(nearest.filter((p) => p.diff < 6).map((p) => `${key(p.a, p.b)} ${p.diff}px`)).toEqual([]);
  console.log('LAYOUT', nearest[0] ? nearest[0].diff : -1, m.weight.toFixed(3), chrome.weight.toFixed(3));
  expect(Math.abs(m.weight - chrome.weight)).toBeLessThan(WEIGHT_GAP);
  expect(errors).toEqual([]);
});

test('the chrome set and the layout tiles, as a sheet on both themes', async ({ page }, info) => {
  // Not an assertion on the drawing: a picture of the whole set in each
  // engine, to look at, beside the glyphs in place below.
  for (const theme of ['dark', 'light'] as const) {
    const errors = await mount(page, theme);
    const n = await page.evaluate(() => window.__iconFixture.showSheet());
    expect(n).toBeGreaterThan(100);
    await page.locator('#sheet').screenshot({ path: info.outputPath(`chrome-sheet-${theme}.png`) });
    expect(errors).toEqual([]);
  }
});

test('the widget shows the glyphs as the tier ships them, in the rail, a flyout and menus', async ({ page }, info) => {
  for (const theme of ['dark', 'light'] as const) {
    const errors = await mount(page, theme);
    // The rail draws tools from the sprite; an accent must travel with its
    // symbol, filled, or the rail shows a ray without its origin.
    const accents = await page.evaluate(() => ({
      ray: document.querySelectorAll('#oac-rail-sprite symbol#oac-icon-ray path[fill="currentColor"]').length,
      trend: document.querySelectorAll('#oac-rail-sprite symbol#oac-icon-trend-line path[fill="currentColor"]').length,
    }));
    expect(accents).toEqual({ ray: 1, trend: 1 });
    // The widget's own stylesheet sets each tier's width; it has to match the
    // tier, or the rail draws a weight the set was not drawn for.
    const widths = await page.evaluate(() => [...document.querySelectorAll('.oac-widget .oac-glyph--chrome > svg')]
      .map((svg) => getComputedStyle(svg).strokeWidth));
    expect(widths.length).toBeGreaterThan(3);
    expect(new Set(widths)).toEqual(new Set([CHROME_PX]));
    const toolWidths = await page.evaluate(() => [...document.querySelectorAll('.oac-widget .oac-glyph--tool > svg')]
      .map((svg) => `${getComputedStyle(svg).strokeWidth} ${svg.getBoundingClientRect().width}`));
    expect(toolWidths.length).toBeGreaterThan(3);
    expect(new Set(toolWidths)).toEqual(new Set([`${TOOL_PX} 20`]));

    const rail = page.locator('.oac-rail');
    await rail.screenshot({ path: info.outputPath(`rail-${theme}.png`) });
    await page.locator('.oac-topbar').screenshot({ path: info.outputPath(`topbar-${theme}.png`) });

    // The flyouts that hold the redrawn siblings: the line family, path and
    // polyline, the two positions, the pitchforks, the Fibonacci
    // constructions, the harmonics and the geometric studies.
    for (const group of ['lines', 'shapes', 'forecast', 'channels', 'fib', 'patterns', 'geometry']) {
      const button = page.locator(`.oac-rail [data-group="${group}"]`);
      await expect(button).toHaveCount(1);
      await button.click({ button: 'right' });
      const fly = page.locator('.oac-fly');
      await expect(fly).toBeVisible();
      const box = (await fly.boundingBox())!;
      const railBox = (await rail.boundingBox())!;
      await page.screenshot({ path: info.outputPath(`flyout-${group}-${theme}.png`),
        clip: { x: 0, y: Math.max(0, box.y - 8), width: box.x + box.width + 8, height: box.height + 16 } });
      expect(box.x).toBeGreaterThanOrEqual(railBox.x + railBox.width - 1);
      await page.keyboard.press('Escape');
      await expect(fly).toHaveCount(0);
    }

    // The drawing menu carries most of the chrome tier: copy, duplicate,
    // lock, eye, front, back and trash.
    const at = await page.evaluate(() => {
      const { widget, lineId } = window.__iconFixture;
      const [a, b] = widget.draw.screenPoints(lineId);
      const rect = widget.root.querySelector('.oac-chart')!.getBoundingClientRect();
      return { x: rect.left + (a.x + b.x) / 2, y: rect.top + (a.y + b.y) / 2 };
    });
    await page.mouse.click(at.x, at.y, { button: 'right' });
    const menu = page.getByRole('menu');
    await expect(menu.getByRole('menuitem', { name: /Duplicate/ })).toBeVisible();
    await menu.screenshot({ path: info.outputPath(`drawing-menu-${theme}.png`) });
    await page.keyboard.press('Escape');

    // The chart-type menu: a glyph beside every type, each the registry's
    // chart-<id> at its native size and line, and none blank; the type
    // button and the theme button carry theirs too.
    await page.locator('.oac-topbar__type').click();
    const typeMenu = page.getByRole('menu', { name: 'Chart type' });
    await expect(typeMenu).toBeVisible();
    const rows = await typeMenu.locator('.oac-menu__row').evaluateAll((els) => els.map((row) => {
      const svg = row.querySelector('.oac-glyph--chrome > svg');
      const box = svg?.getBoundingClientRect();
      return { label: row.textContent, d: svg?.querySelector('path')?.getAttribute('d') ?? '',
        size: box === undefined ? '' : `${box.width}x${box.height}`, stroke: svg === null ? '' : getComputedStyle(svg!).strokeWidth };
    }));
    expect(rows.length).toBeGreaterThan(8);
    for (const row of rows) expect(row, row.label ?? '').toMatchObject({ size: '16x16', stroke: CHROME_PX, d: expect.stringMatching(/^M/) });
    expect(new Set(rows.map((row) => row.d)).size).toBe(rows.length);
    await typeMenu.screenshot({ path: info.outputPath(`chart-type-menu-${theme}.png`) });
    await page.keyboard.press('Escape');
    for (const button of ['.oac-topbar__type', '.oac-topbar__theme']) {
      const box = await page.locator(`${button} .oac-glyph--chrome > svg`).boundingBox();
      expect(box, button).toMatchObject({ width: 16, height: 16 });
    }

    // Every settings tab carries a registry glyph at the same width as the
    // rest of the chrome; the price tab and the style brush moved into the
    // registry from widget files, where no width or grid check saw them.
    const tabGlyphs = async (name: string): Promise<void> => {
      const tabs = page.locator('.oac-tabs').last();
      await expect(tabs).toBeVisible();
      const strokes = await tabs.locator('.oac-glyph--chrome > svg').evaluateAll((svgs) => svgs.map((s) => getComputedStyle(s).strokeWidth));
      expect(strokes.length).toBeGreaterThan(1);
      expect(strokes.length, 'a glyph on every tab').toBe(await tabs.locator('[role="tab"]').count());
      expect(new Set(strokes)).toEqual(new Set([CHROME_PX]));
      await tabs.screenshot({ path: info.outputPath(`${name}-tabs-${theme}.png`) });
      await page.keyboard.press('Escape');
      await expect(tabs).toHaveCount(0);
    };
    expect(await page.evaluate(() => window.__iconFixture.widget.openSettings())).toBe(true);
    await tabGlyphs('settings');
    await page.evaluate(() => {
      const { widget, mountIndicatorSettings } = window.__iconFixture;
      const inst = widget.chart.addIndicator('sma', { length: 5 });
      mountIndicatorSettings(widget.context, undefined, { instanceId: inst.id, tab: 'style' });
    });
    await tabGlyphs('indicator');
    expect(errors).toEqual([]);
  }
});
