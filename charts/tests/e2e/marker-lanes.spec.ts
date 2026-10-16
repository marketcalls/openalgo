import { test, expect, type Page } from '@playwright/test';

// Signal labels on neighbouring bars, in a real browser.
//
// A label plate is wider than a bar, so on a whipsaw the labels of
// neighbouring bars were painted over each other and the earlier ones lost
// most of their plate. Each mark here has its own fill colour, so the pixels
// of that colour are what is left visible of its plate: every plate in the
// whipsaw has to keep the extent of a label standing alone, clear of its
// neighbours' plates.
//
// Against the baseline build (when dist-baseline/ exists) the same scene may
// differ only inside the whipsaw: a label that collided with nothing, and every
// candle, has to come out pixel for pixel as it was.

const W = 900;
const H = 480;

interface Scene { counts: Record<string, number>; boxes: Record<string, [number, number, number, number]> }

/** Paint the scene with one bundle, keep its pixels in the page under `name`, and leave it on screen. */
async function render(page: Page, bundle: string, theme: 'dark' | 'light', name: string): Promise<Scene> {
  return page.evaluate(async ({ bundle, w, h, theme, name }) => {
    const win = window as any;
    win.__sceneChart?.destroy();
    document.getElementById('scene')?.remove();
    const lib = await import(bundle) as any;
    let state = 17;
    const random = (): number => { state = (state * 1664525 + 1013904223) >>> 0; return state / 4294967296; };
    // A seeded random walk with a quiet stretch where a crossover whipsaws.
    const bars: any[] = [];
    let close = 1480;
    for (let i = 0; i < 150; i++) {
      const quiet = i >= 88 && i <= 122;
      const vol = quiet ? 0.0012 : 0.006;
      const open = close;
      close = Math.round(open * (1 + (random() - 0.5) * 2 * vol + (quiet ? 0 : 0.0008)) * 100) / 100;
      const high = Math.round((Math.max(open, close) * (1 + random() * vol * 0.7)) * 100) / 100;
      const low = Math.round((Math.min(open, close) * (1 - random() * vol * 0.7)) * 100) / 100;
      bars.push({ time: 1_789_776_000 + i * 300, open, high, low, close, volume: 2000 + Math.round(random() * 3000) });
    }
    const host = document.createElement('div');
    host.id = 'scene';
    host.style.cssText = `position:fixed;left:0;top:0;width:${w}px;height:${h}px;z-index:9999`;
    document.body.appendChild(host);
    const chart = lib.createChart(host, { priceAxisWidth: 64, branding: false, theme: theme === 'light' ? lib.lightTheme : lib.darkTheme });
    win.__sceneChart = chart;
    chart.applySize(w, h);
    const series = chart.addSeries('candlestick');
    series.setData(bars);
    chart.setVisibleLogicalRange({ from: -2, to: 152 });
    const markers: any[] = [];
    const colours: Record<string, string> = {};
    const add = (i: number, buy: boolean, key: string, rgb: string): void => {
      colours[key] = rgb;
      markers.push(buy
        ? { time: bars[i].time, position: 'belowBar', shape: 'labelUp', size: 'small', color: rgb, text: 'Buy' }
        : { time: bars[i].time, position: 'aboveBar', shape: 'labelDown', size: 'small', color: rgb, text: 'Sell' });
    };
    add(20, false, 'lone-sell', 'rgb(214, 40, 90)');
    add(40, true, 'lone-buy', 'rgb(30, 120, 214)');
    for (let i = 92; i <= 117; i++) {
      const k = i - 92;
      add(i, i % 2 === 0, `w${i}`, i % 2 === 0 ? `rgb(20, ${60 + k * 5}, 230)` : `rgb(236, ${30 + k * 5}, 40)`);
    }
    series.createMarkers().setMarkers(markers);
    await new Promise<void>(r => requestAnimationFrame(() => requestAnimationFrame(() => r())));
    // The pane canvas the marks are painted on is the largest one.
    const canvas = Array.from(host.querySelectorAll('canvas')).sort((a, b) => b.width * b.height - a.width * a.height)[0] as HTMLCanvasElement;
    const data = canvas.getContext('2d', { willReadFrequently: true })!.getImageData(0, 0, canvas.width, canvas.height).data;
    (win.__scenes ??= {})[name] = { data, width: canvas.width, height: canvas.height };
    const want = new Map<number, string>();
    for (const [key, rgb] of Object.entries(colours)) {
      const [r, g, b] = rgb.match(/\d+/g)!.map(Number);
      want.set((r << 16) | (g << 8) | b, key);
    }
    const counts: Record<string, number> = {};
    const boxes: Record<string, [number, number, number, number]> = {};
    for (let y = 0; y < canvas.height; y++) {
      for (let x = 0; x < canvas.width; x++) {
        const o = (y * canvas.width + x) * 4;
        const key = want.get((data[o] << 16) | (data[o + 1] << 8) | data[o + 2]);
        if (key === undefined) continue;
        counts[key] = (counts[key] ?? 0) + 1;
        const box = boxes[key] ?? (boxes[key] = [x, y, x, y]);
        box[0] = Math.min(box[0], x); box[1] = Math.min(box[1], y); box[2] = Math.max(box[2], x); box[3] = Math.max(box[3], y);
      }
    }
    return { counts, boxes };
  }, { bundle, w: W, h: H, theme, name });
}

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await page.setViewportSize({ width: W + 40, height: H + 40 });
});

test('labels on a whipsaw keep their whole plates, in the dark and the light theme', async ({ page }, info) => {
  for (const theme of ['dark', 'light'] as const) {
    const scene = await render(page, '/dist/openalgo-charts.mjs', theme, theme);
    const sell = scene.counts['lone-sell'], buy = scene.counts['lone-buy'];
    expect(sell).toBeGreaterThan(150);
    expect(buy).toBeGreaterThan(120);
    // A plate a neighbour covers loses its full extent on the side it is
    // covered from, or, covered at a corner, shares that corner with the
    // neighbour's extent. Pixel counts alone cannot say it: a plate at a
    // fractional position has antialiased edge rows and columns, and how many
    // depends on the platform's font, so its exact-colour count runs as much
    // as a fifth below the lone plate's with nothing over it.
    const size = (key: string): [number, number] => { const b = scene.boxes[key]; return [b[2] - b[0] + 1, b[3] - b[1] + 1]; };
    const short: string[] = [];
    for (let i = 92; i <= 117; i++) {
      const key = `w${i}`;
      const seen = scene.counts[key] ?? 0;
      const lone = i % 2 === 0 ? 'lone-buy' : 'lone-sell';
      const whole = scene.counts[lone];
      if (seen < whole * 0.75) { short.push(`${key}: ${seen} of ${whole}`); continue; }
      const [w, h] = size(key), [lw, lh] = size(lone);
      if (w < lw - 2 || h < lh - 2) short.push(`${key}: ${w} by ${h} of ${lw} by ${lh}`);
      const [l, t, r, b] = scene.boxes[key];
      for (let j = 92; j <= 117; j++) {
        const o = scene.boxes[`w${j}`];
        if (j !== i && o !== undefined && o[0] <= r && o[2] >= l && o[1] <= b && o[3] >= t) short.push(`${key}: meets w${j}`);
      }
    }
    await page.locator('#scene').screenshot({ path: info.outputPath(`marker-lanes-${theme}.png`) });
    expect(short, `${theme}: plates partly covered by a neighbour`).toEqual([]);
  }
});

test('against the baseline build, only the labels that collided move', async ({ page, request }, info) => {
  const probe = await request.get('/dist-baseline/openalgo-charts.mjs');
  test.skip(!probe.ok(), 'no dist-baseline/: run node scripts/build-baseline.mjs');
  const next = await render(page, '/dist/openalgo-charts.mjs', 'dark', 'next');
  const base = await render(page, '/dist-baseline/openalgo-charts.mjs', 'dark', 'base');
  await page.locator('#scene').screenshot({ path: info.outputPath('marker-lanes-baseline.png') });
  // The whipsaw's region: every box its plates cover in either build, and a
  // pixel more for the anti-aliased plate edges.
  let [l, t, r, b] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const scene of [next, base]) {
    for (const [key, box] of Object.entries(scene.boxes)) {
      if (!key.startsWith('w')) continue;
      l = Math.min(l, box[0]); t = Math.min(t, box[1]); r = Math.max(r, box[2]); b = Math.max(b, box[3]);
    }
  }
  const region = [l - 2, t - 2, r + 2, b + 2];
  const diff = await page.evaluate(([l, t, r, b]) => {
    const { next, base } = (window as any).__scenes;
    if (next.width !== base.width || next.height !== base.height) return { size: false, inside: 0, outside: -1 };
    let inside = 0, outside = 0;
    for (let y = 0; y < next.height; y++) {
      for (let x = 0; x < next.width; x++) {
        const o = (y * next.width + x) * 4;
        if (next.data[o] === base.data[o] && next.data[o + 1] === base.data[o + 1] && next.data[o + 2] === base.data[o + 2]) continue;
        if (x >= l && x <= r && y >= t && y <= b) inside++;
        else outside++;
      }
    }
    return { size: true, inside, outside };
  }, region);
  await info.attach('difference', { body: JSON.stringify({ ...diff, region }), contentType: 'application/json' });
  expect(diff.size).toBe(true);
  expect(diff.outside, 'pixels changed away from the labels that collided').toBe(0);
  // The two lone labels come out as they were.
  for (const key of ['lone-sell', 'lone-buy']) {
    expect(next.boxes[key]).toEqual(base.boxes[key]);
    expect(next.counts[key]).toBe(base.counts[key]);
  }
});
