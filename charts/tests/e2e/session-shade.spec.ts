import { test, expect, type Page, type TestInfo } from '@playwright/test';

/**
 * Session shading in real browser pixels. Unit tests prove which rects the
 * shade asks for; this proves what lands on the canvas: the pre-open and
 * post-close columns change, nothing else does, the tint is the phase's own,
 * and taking the shade off gives back the exact pixels of a chart that never
 * had one.
 */

async function ready(page: Page, theme: string): Promise<void> {
  await page.setViewportSize({ width: 1200, height: 640 });
  await page.goto(`/tests/e2e/session-shade-fixture.html?theme=${theme}`);
  await page.waitForFunction(() => (window as any).__ready);
}

interface Run { phase: string; left: number; right: number; changed: number; area: number; dr: number; db: number }
interface Comparison { changed: number; stray: number; strayBox: number[] | null; runs: Run[] }

/**
 * Paint the chart without the shade, run `act`, paint it again, and compare
 * the two flattened captures in the page: how many device pixels changed,
 * how many of those fall outside a pre-open or post-close column of the
 * price plot, and per run of bars how much of its column changed and which
 * way the colour moved.
 */
async function compare(page: Page, act: string, arg?: unknown, fromFirst = false): Promise<Comparison> {
  return page.evaluate(async ({ act, arg, fromFirst }) => {
    const probe = (window as any).__probe, frame = (window as any).__frame;
    const { chart, bars } = probe;
    const grab = async (): Promise<Uint8ClampedArray> => {
      await frame();
      const c = chart.takeScreenshot() as HTMLCanvasElement;
      return c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
    };
    // The first capture of the page is kept, so a later call can compare
    // against the chart as it was before anything was attached.
    const w = window as any;
    const before = fromFirst ? w.__first : await grab();
    w.__first ??= before;
    probe[act](arg);
    const after = await grab();
    const shot = chart.takeScreenshot() as HTMLCanvasElement, width = shot.width, height = shot.height;
    const dpr = devicePixelRatio, half = chart.timeScale.barSpacing / 2, plot = chart.plotRect(0);
    const box = { left: plot.left * dpr, top: plot.top * dpr, right: (plot.left + plot.width) * dpr, bottom: (plot.top + plot.height) * dpr };
    const runs: Run[] = probe.runs().map((run: { phase: string; from: number; to: number }) => ({
      phase: run.phase,
      left: (chart.timeToCoordinate(bars[run.from].time) - half) * dpr,
      right: (chart.timeToCoordinate(bars[run.to].time) + half) * dpr,
      changed: 0, area: 0, dr: 0, db: 0,
    }));
    let changed = 0, stray = 0, strayBox: number[] | null = null;
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const i = (y * width + x) * 4;
        const moved = before[i] !== after[i] || before[i + 1] !== after[i + 1] || before[i + 2] !== after[i + 2] || before[i + 3] !== after[i + 3];
        const inPlot = x >= box.left && x < box.right && y >= box.top && y < box.bottom;
        // Inside a column by more than a pixel, so an edge shared by two runs belongs to neither.
        const run = inPlot ? runs.find(r => x > r.left + 1 && x < r.right - 1) : undefined;
        const edge = inPlot && runs.some(r => Math.abs(x - r.left) <= 1 || Math.abs(x - r.right) <= 1);
        if (run) {
          run.area++;
          if (moved) { run.changed++; run.dr += after[i] - before[i]; run.db += after[i + 2] - before[i + 2]; }
        }
        if (!moved) continue;
        changed++;
        if (edge || (run && run.phase !== 'regular')) continue;
        stray++;
        strayBox = strayBox ? [Math.min(strayBox[0], x), Math.min(strayBox[1], y), Math.max(strayBox[2], x), Math.max(strayBox[3], y)] : [x, y, x, y];
      }
    }
    return { changed, stray, strayBox, runs };
  }, { act, arg, fromFirst });
}

async function shadesOnlyExtendedHours(page: Page, info: TestInfo, theme: string, tag: string): Promise<void> {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await ready(page, theme);
  await info.attach(`${tag} without shading`, { body: await page.screenshot(), contentType: 'image/png' });

  const on = await compare(page, 'attach');
  await page.screenshot({ path: info.outputPath(`session-shade-${tag}.png`) });
  await info.attach(`${tag} with shading`, { body: await page.screenshot(), contentType: 'image/png' });
  expect(on.runs.map(run => run.phase)).toEqual(['pre', 'regular', 'post', 'pre', 'regular', 'post']);
  expect(on.strayBox).toBeNull();
  expect(on.stray).toBe(0);
  expect(on.changed).toBeGreaterThan(20000);
  for (const run of on.runs) {
    // Most of a shaded column is background, which the wash changes; the
    // candles are drawn over it and keep their own colour. A regular
    // column does not change at all.
    if (run.phase === 'regular') expect(run.changed).toBe(0);
    else expect(run.changed / run.area).toBeGreaterThan(0.6);
  }
  // The pre-open wash leans blue and the post-close one amber, in either theme.
  const lean = (run: Run): number => (run.db - run.dr) / run.changed;
  const pre = on.runs.filter(run => run.phase === 'pre'), post = on.runs.filter(run => run.phase === 'post');
  for (const run of pre) expect(lean(run)).toBeGreaterThan(0);
  for (const run of post) expect(lean(run)).toBeLessThan(0);

  // Off again is exactly the chart that never had it.
  const off = await compare(page, 'detach', undefined, true);
  expect(off.changed).toBe(0);
  expect(errors).toEqual([]);
}

for (const theme of ['dark', 'light']) {
  test(`shades pre-open and post-close columns and nothing else, ${theme} theme`, async ({ page }, info) => {
    await shadesOnlyExtendedHours(page, info, theme, theme);
  });
}

// 1.25 puts bar midpoints between device pixels, and the wash must still stay
// inside its columns; the unit tests hold the shared edges to one column.
for (const ratio of [1.25, 2]) {
  test.describe(`at a pixel ratio of ${ratio}`, () => {
    test.use({ deviceScaleFactor: ratio });
    for (const theme of ['dark', 'light']) {
      test(`shades the same columns in device pixels, ${theme} theme`, async ({ page }, info) => {
        await shadesOnlyExtendedHours(page, info, theme, `${theme}-dpr${ratio}`);
      });
    }
  });
}

test('follows the chart calendar and the colours a host picks', async ({ page }, info) => {
  await ready(page, 'dark');
  // A null colour leaves that phase unshaded: only post-close columns change.
  const postOnly = await compare(page, 'attach', { preColor: null, postColor: 'rgba(214,40,190,0.35)' });
  await info.attach('post-close only', { body: await page.screenshot(), contentType: 'image/png' });
  expect(postOnly.stray).toBe(0);
  for (const run of postOnly.runs) {
    if (run.phase === 'post') expect(run.changed / run.area).toBeGreaterThan(0.6);
    else expect(run.changed).toBe(0);
  }
  // Dropping the chart's hours drops the shading that reads them.
  const noHours = await compare(page, 'dropHours', undefined, true);
  expect(noHours.changed).toBe(0);
});
