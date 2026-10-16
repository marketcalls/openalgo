import { test, expect } from '@playwright/test';

// The vector export against the live canvases, in a real browser.
//
// The unit suite proves the export is the paint stream serialised; it cannot
// prove a browser draws that document the way it drew the canvases (an arc
// flag the wrong way round, a baseline keyword Chrome reads differently, a
// clip in the wrong coordinate space all pass a string test). So the SVG is
// rasterised here through an <img> and compared pixel for pixel with a
// composite of the pane canvases at the positions the DOM gives them.
//
// The tolerance is for anti-aliasing: text is hinted differently by the two
// paths and a hairline's coverage rounds differently, so a small share of
// pixels differs by design. A structural fault (a pane one row off, a missing
// series, a wrong clip) differs by far more than the budget allows.

/** Share of pixels allowed to differ by more than `CHANNEL_TOLERANCE`. */
const MAX_DIFFERING = 0.03;
const CHANNEL_TOLERANCE = 24;

const paintedPixels = (): number => {
  const cv = document.querySelector('#c canvas') as HTMLCanvasElement;
  const { data } = cv.getContext('2d')!.getImageData(0, 0, cv.width, cv.height);
  let n = 0;
  for (let i = 0; i < data.length; i += 4) if (data[i] > 20 || data[i + 1] > 20 || data[i + 2] > 30) n++;
  return n;
};

for (const width of [1000, 240]) {
test(`the SVG export rasterises to the live chart and fits legend readings at width ${width}`, async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));

  await page.setViewportSize({ width, height: 700 });
  await page.goto('/');
  await page.waitForFunction(() => (window as any).__ready === true);
  await page.evaluate(async () => {
    const source = '/dist/openalgo-charts.mjs';
    const { PaneLegend } = await import(source);
    const legend = new PaneLegend({ id: 'export-legend', title: 'A long instrument description', actions: [] });
    legend.setValues([{ label: 'O', text: '999999.99', field: 'ohlc' },
      { label: 'C', text: '123456.78', field: 'ohlc', priority: 10 }]);
    (window as any).__api.chart.addPrimitive(legend);
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
  // The first frame lands after `__ready`; wait for the pixels themselves.
  await page.waitForFunction(
    (fn) => new Function('return (' + fn + ')()')() > 2000,
    paintedPixels.toString(),
    { timeout: 5000 },
  );

  const report = await page.evaluate(async ({ tolerance }) => {
    const api = (window as any).__api;
    const chart = api.chart;
    const host = document.getElementById('c') as HTMLElement;
    const hostRect = host.getBoundingClientRect();
    const dpr = window.devicePixelRatio;
    const bw = Math.round(hostRect.width * dpr);
    const bh = Math.round(hostRect.height * dpr);

    const svg: string = chart.exportSVG();

    // Reference: every pane canvas composited where the DOM shows it, under
    // the pane box's own clip (the row that overflows a bordered pane is
    // hidden on screen and must be hidden here too).
    const ref = document.createElement('canvas');
    ref.width = bw; ref.height = bh;
    const rg = ref.getContext('2d')!;
    rg.fillStyle = getComputedStyle(host).backgroundColor;
    rg.fillRect(0, 0, bw, bh);
    for (const cv of Array.from(host.querySelectorAll('canvas'))) {
      const pane = cv.parentElement as HTMLElement;
      const pr = pane.getBoundingClientRect();
      const cr = cv.getBoundingClientRect();
      rg.save();
      rg.beginPath();
      rg.rect((pr.left - hostRect.left) * dpr, (pr.top - hostRect.top) * dpr, pr.width * dpr, pr.height * dpr);
      rg.clip();
      rg.drawImage(cv, Math.round((cr.left - hostRect.left) * dpr), Math.round((cr.top - hostRect.top) * dpr));
      rg.restore();
    }

    // Candidate: the document, decoded by the browser's own SVG renderer.
    const img = new Image();
    const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }));
    const loaded = await new Promise<boolean>((resolve) => {
      img.onload = () => resolve(true);
      img.onerror = () => resolve(false);
      img.src = url;
    });
    URL.revokeObjectURL(url);
    if (!loaded) return { loaded: false, ratio: 1, total: 0, texts: 0, hasPriceLabel: false };
    const out = document.createElement('canvas');
    out.width = bw; out.height = bh;
    const og = out.getContext('2d')!;
    og.drawImage(img, 0, 0, bw, bh);

    const a = rg.getImageData(0, 0, bw, bh).data;
    const b = og.getImageData(0, 0, bw, bh).data;
    let differing = 0;
    for (let i = 0; i < a.length; i += 4) {
      if (
        Math.abs(a[i] - b[i]) > tolerance ||
        Math.abs(a[i + 1] - b[i + 1]) > tolerance ||
        Math.abs(a[i + 2] - b[i + 2]) > tolerance
      ) differing++;
    }
    const total = a.length / 4;

    const bars = api.bars as { close: number }[];
    const lastLabel: string = chart.panes()[0].priceScale.format(bars[bars.length - 1].close);
    return {
      loaded: true,
      ratio: differing / total,
      total,
      texts: (svg.match(/<text\b/g) ?? []).length,
      hasPriceLabel: svg.includes('>' + lastLabel + '</text>'),
      hasClose: svg.includes('>123456.78</text>'),
      hasOpen: svg.includes('>999999.99</text>'),
      oneRoot: (svg.match(/<svg\b/g) ?? []).length === 1 && svg.endsWith('</svg>'),
    };
  }, { tolerance: CHANNEL_TOLERANCE });

  expect(errors).toEqual([]);
  expect(report.loaded, 'the browser decoded the SVG').toBe(true);
  expect(report.oneRoot).toBe(true);
  expect(report.total).toBeGreaterThan(100_000);
  expect(report.ratio, `share of pixels differing by more than ${CHANNEL_TOLERANCE}`).toBeLessThanOrEqual(MAX_DIFFERING);
  // The ladder, the time strip and the tags are text elements, not outlines.
  expect(report.texts).toBeGreaterThan(10);
  expect(report.hasPriceLabel).toBe(true);
  expect(report.hasClose).toBe(true);
  expect(report.hasOpen).toBe(width === 1000);
});
}
