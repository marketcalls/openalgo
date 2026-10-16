import { expect, test, type Page } from '@playwright/test';
import type { Chart } from '../../src/index';
import type * as Charts from '../../src/index';

/**
 * The chart at device pixel ratios other than 1, and across a change of ratio.
 *
 * Pane boundaries land on whole device pixels at every ratio. The rule between
 * panes takes one of two forms: at a whole-number ratio it is the pane's 1 px
 * top border with the canvases under it, the layout of every earlier release;
 * at a fractional ratio it is one device pixel laid over the lower pane's
 * first row, with the canvases starting at the pane's top.
 *
 * What each engine allows:
 * - Chromium changes the device scale of a live page through the DevTools
 *   protocol. The change is made the way a zoom makes it, with the CSS
 *   viewport shrinking as the scale grows: a scale-only override changes
 *   `devicePixelRatio` without any resize, resolution-query change or
 *   ResizeObserver notification in Chromium's emulation, so no page code can
 *   see it at all. A zoom-shaped change fires the window's `resize` first and
 *   the resolution query's `change` after it, so each of the chart's two
 *   signals is checked with the other taken away.
 * - Firefox and WebKit take a device scale per browser context, fixed for its
 *   life, and Playwright has no protocol to change it, so both are checked
 *   at fixed scales from the first frame.
 * - Every engine renders a headless screenshot one to one at a whole scale.
 *   Only Firefox does at 1.25 and 1.5; Chromium and WebKit resample the page
 *   there (a canvas line on a whole device row lands on two rows even in the
 *   top pane), so the pixel-level separator check runs in every engine at 1
 *   and 2 and in Firefox between them, and the geometry checks run everywhere.
 * - Firefox and Chromium report a canvas's device-pixel box; WebKit does not,
 *   and keeps `media x ratio`. Both reporting engines give the unscaled box
 *   under an emulated scale, which the chart refuses, so that path is checked
 *   at a ratio of 1 with a box half a pixel in.
 */

declare global {
  interface Window { __dpx: { chart: Chart }; __queries: string[] }
}

const CONTAINER = { left: 20, top: 20, width: 560, height: 344 };

async function paint(page: Page): Promise<void> {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

/**
 * A price pane over two study panes at 1 : 0.32 : 0.32, in a box whose height
 * splits into fractions of a device pixel at every ratio checked here. Grid
 * lines are off so a pixel column crosses nothing but background and rules.
 */
async function mount(page: Page, box: { left: number; width: number } = CONTAINER): Promise<void> {
  const css = `left:${box.left}px;top:${CONTAINER.top}px;width:${box.width}px;height:${CONTAINER.height}px`;
  await page.route('**/device-pixels.html', route => route.fulfill({
    contentType: 'text/html',
    body: `<!doctype html><html><head><style>html,body{margin:0;background:#101010}#c{position:absolute;${css}}</style></head><body><div id="c"></div></body></html>`,
  }));
  await page.goto('/device-pixels.html');
  await page.evaluate(async () => {
    const { createChart, darkTheme } = await import('/dist/openalgo-charts.mjs') as typeof Charts;
    const chart = createChart(document.getElementById('c')!, {
      theme: darkTheme, branding: false, timeNavigator: false, animZoom: false, animAutoscale: false,
    });
    const bars = Array.from({ length: 120 }, (_, i) => {
      const close = 100 + Math.sin(i / 7) * 6;
      return { time: 1_700_000_000 + i * 300, open: close - 1, high: close + 2, low: close - 2, close, volume: 100 + i };
    });
    chart.addSeries('candlestick').setData(bars);
    chart.addSeries('line', { paneIndex: 1 }).setData(bars.map(b => ({ time: b.time, value: 50 + Math.sin(b.time / 3000) * 10 })));
    chart.addSeries('line', { paneIndex: 2 }).setData(bars.map(b => ({ time: b.time, value: b.volume })));
    chart.setPaneWeight(1, 0.32);
    chart.setPaneWeight(2, 0.32);
    chart.setGridOptions({ vertLines: false, horzLines: false });
    window.__dpx = { chart };
  });
  await paint(page);
}

interface PaneGeometry {
  top: number; height: number; border: number;
  rule: { shown: boolean; height: number } | null;
  canvases: { offset: number; width: number; height: number; mediaWidth: number; mediaHeight: number }[];
}

/** Pane boxes relative to the chart's container, their border and rule, and their canvases. */
const geometry = (page: Page) => page.evaluate(() => {
  const container = document.getElementById('c')!.getBoundingClientRect();
  return {
    dpr: devicePixelRatio,
    panes: window.__dpx.chart.panes().map(pane => {
      const box = pane.element.getBoundingClientRect();
      const rule = pane.element.querySelector<HTMLElement>(':scope > div');
      return {
        top: box.top - container.top,
        height: box.height,
        border: parseFloat(getComputedStyle(pane.element).borderTopWidth),
        rule: rule === null ? null : { shown: getComputedStyle(rule).display !== 'none', height: rule.getBoundingClientRect().height },
        canvases: [pane.base, pane.top].map(layer => ({
          offset: layer.element.getBoundingClientRect().top - box.top,
          width: layer.element.width, height: layer.element.height, mediaWidth: layer.mediaWidth, mediaHeight: layer.mediaHeight,
        })),
      };
    }) as PaneGeometry[],
  };
});

/** Layout positions come back in the engine's layout units, a 64th of a CSS pixel at worst. */
const onDevicePixel = (css: number, dpr: number): boolean => Math.abs(css * dpr - Math.round(css * dpr)) < 0.05;

function expectOnDevicePixels(g: { dpr: number; panes: PaneGeometry[] }): void {
  const { dpr, panes } = g;
  const whole = Number.isInteger(dpr);
  expect(panes).toHaveLength(3);
  panes.forEach((pane, i) => {
    expect(onDevicePixel(pane.top, dpr), `pane ${i} top ${pane.top} at ${dpr}`).toBe(true);
    expect(onDevicePixel(pane.height, dpr), `pane ${i} height ${pane.height} at ${dpr}`).toBe(true);
    // The rule's form: the 1 px border at a whole ratio, the box laid over the pane between them.
    const border = i > 0 && whole;
    expect(pane.border, `pane ${i} border at ${dpr}`).toBeCloseTo(border ? 1 : 0, 2);
    expect(pane.rule, `pane ${i} rule`).not.toBeNull();
    expect(pane.rule!.shown, `pane ${i} rule shown at ${dpr}`).toBe(i > 0 && !whole);
    if (i > 0 && !whole) expect(pane.rule!.height * dpr, `pane ${i} rule height`).toBeCloseTo(Math.max(1, Math.floor(dpr)), 1);
    for (const canvas of pane.canvases) {
      // Under the border, or at the pane's own top; on a device pixel either way.
      expect(canvas.offset, `pane ${i} canvas offset at ${dpr}`).toBeCloseTo(border ? 1 : 0, 2);
      // The store covers the box one to one: whole device pixels, not a stretched estimate.
      expect(canvas.width, `pane ${i} store width`).toBe(Math.round(canvas.mediaWidth * dpr));
      expect(canvas.height, `pane ${i} store height`).toBe(Math.round(canvas.mediaHeight * dpr));
      expect(Math.abs(canvas.mediaHeight * dpr - canvas.height), `pane ${i} media height`).toBeLessThan(0.05);
    }
  });
}

const hexRgb = (hex: string): [number, number, number] =>
  [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16)) as [number, number, number];

/**
 * Read the screenshot at three columns across the plot, clear of the legend
 * text and the price axis, and check each separator is whole rows of its
 * colour, `max(1, floor(dpr))` rows at a fractional ratio and `dpr` rows (the
 * 1 px border) at a whole one, between rows of plain pane background.
 */
async function expectCrispSeparators(page: Page, g: { dpr: number; panes: PaneGeometry[] }, shot: Buffer): Promise<void> {
  const { dpr } = g;
  const rows = Number.isInteger(dpr) ? dpr : Math.max(1, Math.floor(dpr));
  const theme = await page.evaluate(() => ({ background: window.__dpx.chart.theme().background, rule: window.__dpx.chart.theme().paneSeparator }));
  const probes = g.panes.slice(1).flatMap(pane => {
    const y = Math.round((CONTAINER.top + pane.top) * dpr);
    return [y - 1, ...Array.from({ length: rows }, (_, k) => y + k), y + rows];
  });
  const columns = await page.evaluate(async ([encoded, ys, ratio]) => {
    const bitmap = await createImageBitmap(new Blob([Uint8Array.from(atob(encoded), c => c.charCodeAt(0))], { type: 'image/png' }));
    const canvas = document.createElement('canvas');
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const g2 = canvas.getContext('2d')!;
    g2.drawImage(bitmap, 0, 0);
    return [200, 300, 400].map(xCss => {
      const x = Math.round(xCss * ratio);
      return ys.map(y => Array.from(g2.getImageData(x, y, 1, 1).data.slice(0, 3)));
    });
  }, [shot.toString('base64'), probes, dpr] as const);
  const [bg, rule] = [hexRgb(theme.background), hexRgb(theme.rule)];
  const near = (px: number[], rgb: number[]) => px.every((v, k) => Math.abs(v - rgb[k]) <= 2);
  const per = rows + 2;
  for (const column of columns) {
    for (let s = 0; s < 2; s++) {
      const run = column.slice(s * per, s * per + per);
      expect(near(run[0], bg), `row above separator ${s + 1} at ${dpr}: ${run[0]}`).toBe(true);
      for (let k = 1; k <= rows; k++) expect(near(run[k], rule), `separator ${s + 1} row ${k} at ${dpr}: ${run[k]}`).toBe(true);
      expect(near(run[rows + 1], bg), `row below separator ${s + 1} at ${dpr}: ${run[rows + 1]}`).toBe(true);
    }
  }
}

for (const scale of [1, 1.25, 1.5, 2]) {
  test.describe(`at a device scale of ${scale}`, () => {
    // Viewport times scale is whole, so a device-scale screenshot is the page one to one.
    test.use({ viewport: { width: 720, height: 480 }, deviceScaleFactor: scale });

    test('puts every pane boundary and separator on whole device pixels, and sizes each canvas to its box', async ({ page }, testInfo) => {
      await mount(page);
      const g = await geometry(page);
      expect(g.dpr).toBe(scale);
      expectOnDevicePixels(g);
      await page.screenshot({ scale: 'device', path: testInfo.outputPath(`chart-${scale}.png`) });
    });

    test('draws each separator as whole rows of its colour between plain pane backgrounds', async ({ page, browserName }, testInfo) => {
      test.skip(!Number.isInteger(scale) && browserName !== 'firefox',
        'Headless Chromium and WebKit resample the page at a fractional scale, so only Firefox shows it pixel for pixel');
      await mount(page);
      const g = await geometry(page);
      const shot = await page.screenshot({ scale: 'device', path: testInfo.outputPath(`separators-${scale}.png`) });
      await testInfo.attach(`separators-${scale}`, { path: testInfo.outputPath(`separators-${scale}.png`), contentType: 'image/png' });
      await expectCrispSeparators(page, g, shot);
    });
  });
}

test.describe('a device scale changed while the chart is showing', () => {
  test.use({ viewport: { width: 900, height: 600 }, deviceScaleFactor: 1 });

  /**
   * Change the scale zoom-shaped through the DevTools protocol, 1.5 then 2
   * then 1.25 then 1, and after each change check the canvases followed.
   * `check` runs the change-specific assertions.
   */
  async function changeScales(page: Page, check: (scale: number) => Promise<void>): Promise<void> {
    await mount(page);
    expectOnDevicePixels(await geometry(page));
    const cdp = await page.context().newCDPSession(page);
    for (const scale of [1.5, 2, 1.25, 1]) {
      await cdp.send('Emulation.setDeviceMetricsOverride', {
        width: Math.round(900 / scale), height: Math.round(600 / scale), deviceScaleFactor: scale, mobile: false,
      });
      await page.waitForFunction(ratio => devicePixelRatio === ratio, scale);
      await expect.poll(() => page.evaluate(() => window.__dpx.chart.panes()[0].base.pixelRatio), { message: `canvases at ${scale}` }).toBe(scale);
      await paint(page);
      const g = await geometry(page);
      expect(g.dpr).toBe(scale);
      expectOnDevicePixels(g);
      expect(g.panes[0].canvases[0].width).toBe(Math.round(CONTAINER.width * scale));
      await check(scale);
    }
    await cdp.send('Emulation.clearDeviceMetricsOverride');
  }

  test('re-sizes every canvas and keeps the separators on device pixels, each time', async ({ page, browserName }, testInfo) => {
    test.skip(browserName !== 'chromium', 'Only Chromium lets Playwright change the device scale of a live page; Firefox and WebKit are checked at fixed scales above');
    // Every query the page asks for, so the test sees the chart make the one for each new ratio.
    await page.addInitScript(() => {
      window.__queries = [];
      const match = window.matchMedia.bind(window);
      window.matchMedia = (query: string) => { window.__queries.push(query); return match(query); };
    });
    await changeScales(page, async scale => {
      await expect.poll(() => page.evaluate(() => window.__queries), { message: `the query for ${scale}` }).toContain(`(resolution: ${scale}dppx)`);
      // One to one at a whole scale, so the rule's rows can be read off the screen.
      if (!Number.isInteger(scale)) return;
      const shot = await page.screenshot({ scale: 'device', path: testInfo.outputPath(`live-${scale}.png`) });
      await expectCrispSeparators(page, await geometry(page), shot);
    });
  });

  test('follows the ratio through the resolution query alone', async ({ page, browserName }) => {
    test.skip(browserName !== 'chromium', 'Only Chromium lets Playwright change the device scale of a live page');
    // No window resize reaches the page's listeners: only the query can tell the chart.
    await page.addInitScript(() => {
      const add = window.addEventListener.bind(window);
      window.addEventListener = ((type: string, ...rest: unknown[]) => {
        if (type !== 'resize') (add as (...args: unknown[]) => void)(type, ...rest);
      }) as typeof window.addEventListener;
    });
    await changeScales(page, async () => {});
  });

  test('follows the ratio through the window resize alone', async ({ page, browserName }) => {
    test.skip(browserName !== 'chromium', 'Only Chromium lets Playwright change the device scale of a live page');
    // A browser whose query list takes no change listener.
    await page.addInitScript(() => {
      const match = window.matchMedia.bind(window);
      window.matchMedia = (query: string) => {
        const list = match(query);
        return { matches: list.matches, media: list.media } as MediaQueryList;
      };
    });
    await changeScales(page, async () => {});
  });
});

test.describe('the device-pixel box the browser reports', () => {
  test.use({ viewport: { width: 900, height: 600 }, deviceScaleFactor: 1 });

  /** Each canvas's store, and the device-pixel box the browser reports for the first one. */
  const stores = (page: Page) => page.evaluate(() => new Promise<{ device: number; media: number; stores: number[][] }>(resolve => {
    const canvas = window.__dpx.chart.panes()[0].base.element;
    const observer = new ResizeObserver(entries => {
      observer.disconnect();
      resolve({
        device: entries[0].devicePixelContentBoxSize[0].inlineSize,
        media: window.__dpx.chart.panes()[0].base.mediaWidth,
        stores: window.__dpx.chart.panes().map(p => [p.base.element.width, p.top.element.width]),
      });
    });
    observer.observe(canvas, { box: 'device-pixel-content-box' });
  }));

  test('sizes a canvas that starts half a pixel in to the pixels its box covers, and keeps it there', async ({ page, browserName }) => {
    test.skip(browserName === 'webkit', 'WebKit reports no device-pixel content box, so the chart keeps media times ratio there');
    await mount(page, { left: 20.5, width: 560.5 });
    const reported = await stores(page);
    // The case is real: the box snaps to a pixel fewer than media times ratio rounds to.
    expect(reported.media).toBe(560.5);
    expect(reported.device).not.toBe(Math.round(reported.media));
    const all = (width: number): number[][] => [[width, width], [width, width], [width, width]];
    await expect.poll(async () => (await stores(page)).stores).toEqual(all(reported.device));
    // Painted at that size, not left cleared by the change.
    const painted = await page.evaluate(() => {
      const canvas = window.__dpx.chart.panes()[0].base.element;
      const data = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
      let opaque = 0;
      for (let i = 3; i < data.length; i += 4) if (data[i] === 255) opaque++;
      return opaque / (canvas.width * canvas.height);
    });
    expect(painted).toBeGreaterThan(0.9);
    // A tenth of a pixel wider covers the same device pixels in Chromium, so
    // the browser reports nothing; the store stays on the box, and back again.
    for (const width of [560.6, 560.5]) {
      await page.evaluate(w => { document.getElementById('c')!.style.width = `${w}px`; }, width);
      await paint(page);
      const now = await stores(page);
      if (browserName === 'chromium') expect(now.device, `device box at ${width}`).toBe(reported.device);
      expect(now.stores, `stores at ${width}`).toEqual(all(now.device));
    }
  });

  test('paints each pane once for a one-pixel step, the report of the new box changing nothing', async ({ page, browserName }) => {
    test.skip(browserName === 'webkit', 'WebKit reports no device-pixel content box, so no report can ask for a second paint there');
    await mount(page);
    await paint(page);
    // A step in width moves every pane's box; one in height moves the boundaries.
    for (const [side, size] of [['width', CONTAINER.width + 1], ['height', CONTAINER.height + 1]] as const) {
      const result = await page.evaluate(([prop, px]) => new Promise<{ paints: number[]; stores: number[][]; media: number[][] }>(resolve => {
        const { chart } = window.__dpx;
        const paints = chart.panes().map(() => 0);
        const own = chart.panes().map(pane => pane.paintBase);
        chart.panes().forEach((pane, i) => {
          pane.paintBase = (...args: Parameters<typeof pane.paintBase>) => { paints[i]++; own[i].apply(pane, args); };
        });
        document.getElementById('c')!.style[prop] = `${px}px`;
        // Three frames: the resize, the box reports the browser sends before
        // painting it, and one more for any frame a report asked for.
        requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(() => {
          chart.panes().forEach((pane, i) => { pane.paintBase = own[i]; });
          resolve({
            paints,
            stores: chart.panes().map(p => [p.base.element.width, p.base.element.height]),
            media: chart.panes().map(p => [p.base.mediaWidth, p.base.mediaHeight]),
          });
        })));
      }), [side, size] as const);
      expect(result.paints, `paints after a step in ${side}`).toEqual([1, 1, 1]);
      expect(result.stores, `stores after a step in ${side}`).toEqual(result.media.map(([w, h]) => [Math.round(w), Math.round(h)]));
    }
  });
});
