import { expect, test, type Page } from '@playwright/test';
import type { Chart, IndicatorApi, IndicatorSettings } from '../../src/index';
import type * as Charts from '../../src/index';
import type * as Widgets from '../../src/widget/index';

// A study whose anchor is a time and a price that belong together, in the
// packaged widget and in the reference host: one pick sets both, a handle on
// the chart drags both, and the host's Undo takes a drag back.
test.use({ screenshot: 'only-on-failure', trace: 'retain-on-failure' });
type Surface = 'widget' | 'demo';
type Draw = { add(drawing: object): { id: string }; get(id: string): unknown; historySteps(): { undo: number[]; redo: number[] } };
type DemoWindow = Window & { __oac: { app: { chart: Chart; draw: Draw; loading: boolean } } };
declare global { interface Window { __points: {
  chart: Chart; draw: Draw; study: IndicatorApi; patches: IndicatorSettings[]; open(): void;
  history?: { destroy(): void };
} } }

const T0 = 1700000000;

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function mount(page: Page, surface: Surface, width: number) {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width, height: 860 });
  if (surface === 'widget') {
    await page.route('**/native-input-points.html', route => route.fulfill({ contentType: 'text/html', body:
      '<!doctype html><html><head><style>html,body{margin:0;background:#111318}#host{height:840px;width:100%}</style></head><body><div id="host"></div></body></html>' }));
    await page.goto('/native-input-points.html');
  } else {
    await page.goto(`http://127.0.0.1:${process.env.OAC_E2E_DEMO_PORT || '8124'}/examples/yfinance/index.html?test=1`);
    await page.waitForFunction(() => Boolean((window as DemoWindow).__oac?.app.chart) && !(window as DemoWindow).__oac.app.loading);
  }
  await page.evaluate(async ({ kind, t0 }) => {
    const lib = await import('/dist/openalgo-charts.mjs' as string) as typeof Charts;
    const widgets = await import('/dist/openalgo-charts.widget.mjs' as string) as typeof Widgets;
    let chart: Chart, draw: Draw, open: (id: string) => void, history: { destroy(): void } | undefined;
    if (kind === 'widget') {
      const widget = widgets.createWidget(document.getElementById('host')!, {
        persist: false, rail: window.innerWidth > 640, symbol: 'PRIMARY', interval: '1m',
        branding: false, timeNavigator: false, animZoom: false, animAutoscale: false,
        mobile: window.innerWidth <= 640 ? 'auto' : 'never',
      });
      chart = widget.chart;
      draw = widget.draw as unknown as Draw;
      history = widget.history;
      open = id => { widgets.mountIndicatorSettings(widget.context, undefined, { instanceId: id }); };
    } else {
      chart = (window as DemoWindow).__oac.app.chart;
      draw = (window as DemoWindow).__oac.app.draw;
      const host = await import('/examples/yfinance/src/indicators.js' as string) as { openSettings(id: string): void };
      open = id => host.openSettings(id);
    }
    for (const study of [...chart.indicators()]) study.remove({ force: true });
    lib.registerIndicator({ id: 'browser-input-points', name: 'Anchored path', placement: 'onchart',
      inputs: [
        { key: 'at', type: 'timestamp', label: 'Anchor time', default: t0 + 12 * 60, pick: true },
        { key: 'level', type: 'price', label: 'Anchor price', default: 206, pick: true, timeKey: 'at', anchor: true },
      ],
      plots: [{ key: 'path', title: 'Path', type: 'line', style: { color: '#f59e0b', lineWidth: 2 } }],
      calc: (bars, settings) => ({ path: bars.map(bar => bar.time >= (settings.at as number)
        ? (settings.level as number) + ((bar.time - (settings.at as number)) / 60) * 0.25 : NaN) }),
    });
    chart.primarySeries()!.setData(Array.from({ length: 48 }, (_, index) => ({
      time: t0 + index * 60, open: 200 + index * 0.5, high: 203 + index * 0.5, low: 199 + index * 0.5, close: 201 + index * 0.5,
    })));
    const study = chart.addIndicator('browser-input-points');
    chart.setVisibleLogicalRange({ from: -1, to: 49 });
    chart.panes()[0].priceScale.setFixedRange({ min: 190, max: 240 });
    const patches: IndicatorSettings[] = [], write = study.setSettings.bind(study);
    study.setSettings = (patch, options) => { patches.push({ ...patch }); return write(patch, options); };
    window.__points = { chart, draw, study, patches, history, open: () => open(window.__points.study.id) };
  }, { kind: surface, t0: T0 });
  await paint(page);
  return errors;
}

function dialog(page: Page, surface: Surface) {
  const root = page.locator(surface === 'widget' ? '.oac-indset' : '#setmodal');
  return { root,
    field: (key: string) => surface === 'widget' ? root.locator(`[id$="-${key}"]`).filter({ visible: true }) : root.locator(`[data-key="${key}"]`),
    accept: surface === 'widget' ? root.getByRole('button', { name: 'OK', exact: true }) : root.locator('#set-ok'),
  };
}

const settings = (page: Page) => page.evaluate(() => window.__points.study.settings());

/** Page px of a time and price on the price pane. */
async function at(page: Page, time: number, price: number) {
  return page.evaluate(({ time, price }) => {
    const { chart } = window.__points;
    const box = chart.panes()[0].base.element.getBoundingClientRect(), rect = chart.plotRect(0)!;
    return { x: box.left + chart.timeToCoordinate(time)!, y: box.top + rect.top + chart.panes()[0].priceScale.priceToY(price) };
  }, { time, price });
}

for (const surface of ['widget', 'demo'] as const) for (const width of [1100, 390]) {
  test(`${surface} picks a paired time and price from one click at ${width}px`, async ({ page }, info) => {
    const errors = await mount(page, surface, width), c = dialog(page, surface);
    await page.evaluate(() => window.__points.open());
    const trigger = c.root.locator('[data-input-action="level"]');
    await expect(trigger).toHaveText('Pick point on chart');
    await trigger.click();
    await expect(c.root).toBeHidden();
    await expect(page.locator('.oac-input-pick')).toContainText('Pick Anchor time and Anchor price on the chart');
    await page.screenshot({ path: info.outputPath(`${surface}-${width}-point-picking.png`) });
    const target = await at(page, T0 + 30 * 60, 222);
    await page.mouse.click(target.x + 2, target.y);
    await expect(c.root).toBeVisible();
    expect(Number(await c.field('at').inputValue())).toBe(T0 + 30 * 60);
    const picked = Number(await c.field('level').inputValue());
    expect(picked).toBeCloseTo(222, 0);
    await page.screenshot({ path: info.outputPath(`${surface}-${width}-point-picked.png`) });
    await c.accept.click();
    await expect(c.root).toBeHidden();
    expect(await settings(page)).toMatchObject({ at: T0 + 30 * 60, level: picked });
    // The widget commits the pick as it lands and the reference host on
    // Apply; either way both halves travel in one patch.
    const patches = await page.evaluate(() => window.__points.patches);
    expect(patches.some(patch => patch.at === T0 + 30 * 60 && patch.level === picked)).toBe(true);
    expect(patches.every(patch => ('at' in patch) === ('level' in patch))).toBe(true);
    expect(errors).toEqual([]);
  });

  test(`${surface} drags the anchor on the chart and undoes the drag at ${width}px`, async ({ page }, info) => {
    const errors = await mount(page, surface, width);
    const from = await at(page, T0 + 12 * 60, 206);
    await page.mouse.move(from.x, from.y);
    await paint(page);
    await page.screenshot({ path: info.outputPath(`${surface}-${width}-anchor-hover.png`) });
    const to = await at(page, T0 + 24 * 60, 226);
    await page.mouse.down();
    await page.mouse.move((from.x + to.x) / 2, (from.y + to.y) / 2, { steps: 6 });
    await page.mouse.move(to.x + 2, to.y, { steps: 6 });
    await paint(page);
    // Nothing is written while the anchor is in hand.
    expect(await page.evaluate(() => window.__points.patches)).toEqual([]);
    await page.screenshot({ path: info.outputPath(`${surface}-${width}-anchor-dragging.png`) });
    await page.mouse.up();
    await paint(page);
    const moved = await settings(page);
    expect(moved.at).toBe(T0 + 24 * 60);
    expect(moved.level as number).toBeCloseTo(226, 0);
    expect(await page.evaluate(() => window.__points.patches)).toEqual([{ at: T0 + 24 * 60, level: moved.level }]);
    // The reference host's phone bar offers Undo for it, as it does for a drawing.
    if (surface === 'demo' && width < 640) await expect(page.locator('#mobile-undo')).toBeEnabled();
    await page.screenshot({ path: info.outputPath(`${surface}-${width}-anchor-dropped.png`) });

    // Escape drops a second drag without writing anything.
    const again = await at(page, T0 + 24 * 60, moved.level as number);
    await page.mouse.move(again.x, again.y);
    await page.mouse.down();
    await page.mouse.move(again.x - 80, again.y + 40, { steps: 6 });
    await page.keyboard.press('Escape');
    await page.mouse.up();
    await paint(page);
    expect(await settings(page)).toMatchObject({ at: moved.at, level: moved.level });

    // The host's Undo control takes the drag back, both halves at once: the
    // rail's button, the phone bar's on a phone, and the key where there is neither.
    const control = (name: 'Undo' | 'Redo') => surface === 'demo'
      ? page.locator(width < 640 ? `#mobile-${name.toLowerCase()}` : `#rail button[aria-label="${name}"]`)
      : width < 640 ? null : page.locator(`.oac-rail button[aria-label="${name}"]`);
    const undo = control('Undo'), redo = control('Redo');
    if (undo === null) await page.keyboard.press('Control+z');
    else await undo.click();
    await paint(page);
    expect(await settings(page)).toMatchObject({ at: T0 + 12 * 60, level: 206 });
    if (redo === null) await page.keyboard.press('Control+Shift+z');
    else await redo.click();
    await paint(page);
    expect(await settings(page)).toMatchObject({ at: moved.at, level: moved.level });
    await page.screenshot({ path: info.outputPath(`${surface}-${width}-anchor-redone.png`) });
    expect(errors).toEqual([]);
  });
}

for (const surface of ['widget', 'demo'] as const) {
  test(`${surface} walks a line, a drag and a pick back one step each with the rail's Undo`, async ({ page }, info) => {
    const errors = await mount(page, surface, 1100), c = dialog(page, surface);
    const line = await page.evaluate(t0 => window.__points.draw.add({
      tool: 'horizontal-line', paneIndex: 0, style: { color: '#38bdf8' }, points: [{ time: t0 + 6 * 60, price: 196 }],
    }).id, T0);
    const from = await at(page, T0 + 12 * 60, 206), to = await at(page, T0 + 24 * 60, 226);
    await page.mouse.move(from.x, from.y);
    await page.mouse.down();
    await page.mouse.move(to.x + 2, to.y, { steps: 8 });
    await page.mouse.up();
    await paint(page);
    const dragged = await settings(page);
    expect(dragged.at).toBe(T0 + 24 * 60);

    await page.evaluate(() => window.__points.open());
    await c.root.locator('[data-input-action="level"]').click();
    const pick = await at(page, T0 + 36 * 60, 232);
    await page.mouse.click(pick.x + 2, pick.y);
    await expect(c.root).toBeVisible();
    await c.accept.click();
    await expect(c.root).toBeHidden();
    await paint(page);
    const picked = await settings(page);
    expect(picked.at).toBe(T0 + 36 * 60);
    // One owner: the drawing history holds the line and nothing of the study.
    expect((await page.evaluate(() => window.__points.draw.historySteps())).undo).toHaveLength(1);
    await page.screenshot({ path: info.outputPath(`${surface}-timeline-picked.png`) });

    const rail = surface === 'demo' ? '#rail' : '.oac-rail';
    const undo = page.locator(`${rail} button[aria-label="Undo"]`), redo = page.locator(`${rail} button[aria-label="Redo"]`);
    const hasLine = () => page.evaluate(id => window.__points.draw.get(id) !== undefined, line);
    await undo.click();
    await paint(page);
    expect(await settings(page)).toMatchObject({ at: dragged.at, level: dragged.level });
    expect(await hasLine()).toBe(true);
    await undo.click();
    await paint(page);
    expect(await settings(page)).toMatchObject({ at: T0 + 12 * 60, level: 206 });
    expect(await hasLine()).toBe(true);
    await page.screenshot({ path: info.outputPath(`${surface}-timeline-undone-twice.png`) });
    await undo.click();
    await paint(page);
    expect(await hasLine()).toBe(false);
    for (let i = 0; i < 3; i++) { await redo.click(); await paint(page); }
    expect(await hasLine()).toBe(true);
    expect(await settings(page)).toMatchObject({ at: picked.at, level: picked.level });
    await page.screenshot({ path: info.outputPath(`${surface}-timeline-redone.png`) });
    expect(errors).toEqual([]);
  });
}

// The verifier's case: a drag, then Pick point on chart in the settings dialog,
// with no chart-wide history, so the rail walks the drawing controller's own.
// The first Undo takes the pick back and leaves the line drawn before both.
test('widget takes a pick back first when the rail walks the drawing history alone, and never the line before it', async ({ page }, info) => {
  const errors = await mount(page, 'widget', 1100), c = dialog(page, 'widget');
  await page.evaluate(() => window.__points.history!.destroy());
  const line = await page.evaluate(t0 => window.__points.draw.add({
    tool: 'horizontal-line', paneIndex: 0, style: { color: '#38bdf8' }, points: [{ time: t0 + 6 * 60, price: 196 }],
  }).id, T0);
  const from = await at(page, T0 + 12 * 60, 206), to = await at(page, T0 + 24 * 60, 226);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(to.x + 2, to.y, { steps: 8 });
  await page.mouse.up();
  await paint(page);
  const dragged = await settings(page);
  expect(dragged.at).toBe(T0 + 24 * 60);

  await page.evaluate(() => window.__points.open());
  await c.root.locator('[data-input-action="level"]').click();
  const pick = await at(page, T0 + 36 * 60, 232);
  await page.mouse.click(pick.x + 2, pick.y);
  await expect(c.root).toBeVisible();
  await c.accept.click();
  await expect(c.root).toBeHidden();
  await paint(page);
  const picked = await settings(page);
  expect(picked.at).toBe(T0 + 36 * 60);
  await page.screenshot({ path: info.outputPath('drawing-history-picked.png') });

  const undo = page.locator('.oac-rail button[aria-label="Undo"]'), redo = page.locator('.oac-rail button[aria-label="Redo"]');
  const hasLine = () => page.evaluate(id => window.__points.draw.get(id) !== undefined, line);
  await undo.click();
  await paint(page);
  expect(await hasLine()).toBe(true);
  expect(await settings(page)).toMatchObject({ at: dragged.at, level: dragged.level });
  await page.screenshot({ path: info.outputPath('drawing-history-pick-undone.png') });
  await undo.click();
  await paint(page);
  expect(await hasLine()).toBe(true);
  expect(await settings(page)).toMatchObject({ at: T0 + 12 * 60, level: 206 });
  await undo.click();
  await paint(page);
  expect(await hasLine()).toBe(false);
  for (let i = 0; i < 3; i++) { await redo.click(); await paint(page); }
  expect(await hasLine()).toBe(true);
  expect(await settings(page)).toMatchObject({ at: picked.at, level: picked.level });
  await page.screenshot({ path: info.outputPath('drawing-history-redone.png') });
  expect(errors).toEqual([]);
});
