import { expect, test, type Page } from '@playwright/test';
import type { Chart, IndicatorApi, IndicatorSettings } from '../../src/index';
import type { WidgetContext } from '../../src/widget/context';
import type * as Charts from '../../src/index';
import type * as Widgets from '../../src/widget/index';

test.use({ hasTouch: true, screenshot: 'only-on-failure', trace: 'retain-on-failure' });
type Surface = 'widget' | 'demo';
type DemoWindow = Window & { __oac: { app: { chart: Chart; loading: boolean;
  inspection1: { context: WidgetContext }; alertUi: { context: WidgetContext } } } };
declare global { interface Window { __typedInputs: {
  chart: Chart; study: IndicatorApi; patches: IndicatorSettings[]; open(): void;
  initialSymbol: string; symbol(): string; events: unknown[];
} } }

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function mount(page: Page, surface: Surface, width: number, exchangeKey = 'venue') {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width, height: 900 });
  if (surface === 'widget') {
    await page.route('**/native-typed-inputs.html', route => route.fulfill({ contentType: 'text/html', body:
      '<!doctype html><html><head><style>html,body{margin:0;background:#111318}#host{height:880px;width:100%}</style></head><body><div id="host"></div></body></html>' }));
    await page.goto('/native-typed-inputs.html');
  } else {
    await page.goto(`http://127.0.0.1:${process.env.OAC_E2E_DEMO_PORT || '8124'}/examples/yfinance/index.html?test=1`);
    await page.waitForFunction(() => Boolean((window as DemoWindow).__oac?.app.chart) && !(window as DemoWindow).__oac.app.loading);
  }
  await page.evaluate(async ({ kind, exchangeKey }) => {
    const baseUrl = '/dist/openalgo-charts.mjs', widgetUrl = '/dist/openalgo-charts.widget.mjs';
    const lib = await import(baseUrl) as typeof Charts, widgets = await import(widgetUrl) as typeof Widgets;
    const search = async () => [{ symbol: 'SAME', exchange: 'X1', name: 'First venue' },
      { symbol: 'SAME', exchange: 'X2', name: 'Second venue' }];
    let chart: Chart, open: (id: string) => void, symbol: () => string;
    if (kind === 'widget') {
      const widget = widgets.createWidget(document.getElementById('host')!, {
        persist: false, rail: false, symbol: 'PRIMARY', interval: '1m', symbolSearch: search,
        branding: false, timeNavigator: false, animZoom: false, animAutoscale: false,
        mobile: window.innerWidth <= 640 ? 'auto' : 'never',
      });
      chart = widget.chart; symbol = () => widget.context.symbol().symbol;
      open = id => { widgets.mountIndicatorSettings(widget.context, undefined, { instanceId: id }); };
    } else {
      const app = (window as DemoWindow).__oac.app;
      chart = app.chart; symbol = () => chart.getDataContext()?.symbol ?? '';
      Object.defineProperty(app.inspection1.context, 'symbolSearch', { configurable: true, value: search });
      const url = '/examples/yfinance/src/indicators.js';
      const host = await import(url) as { openSettings(id: string): void };
      open = id => host.openSettings(id);
    }
    for (const study of [...chart.indicators()]) study.remove();
    lib.registerIndicator({ id: 'browser-typed-inputs', name: 'Typed input study', placement: 'pane',
      inputs: [
        { key: 'instrument', type: 'symbol', label: 'Instrument', default: 'AAA', exchangeKey },
        { key: 'hours', type: 'session', label: 'Session', default: '0900-1700:23456' },
        { key: 'note', type: 'multiline', label: 'Notes', default: 'first\nsecond' },
        { key: 'level', type: 'price', label: 'Price', default: 12.345678901234567, min: 0, max: 100, step: 0.001, pick: true },
        { key: 'when', type: 'timestamp', label: 'Instant', default: 1700000000.125, pick: true },
        { key: 'wall', type: 'time', label: 'Wall time', default: '2026-09-25 09:30' },
      ], plots: [{ key: 'value', title: 'Value', type: 'line', style: { color: '#33aaff', lineWidth: 3 } },
        { key: 'second', title: 'Reference', type: 'line', style: { color: '#ffcc44' } }],
      calc: (bars, settings) => ({ value: bars.map(() => settings.level as number), second: bars.map(() => 50) }),
    });
    chart.primarySeries()!.setData(Array.from({ length: 48 }, (_, index) => ({
      time: 1700000000.125 + index * 60, open: 200 + index, high: 203 + index, low: 199 + index, close: 201 + index,
    })));
    const study = chart.addIndicator('browser-typed-inputs', {}, { priceScaleId: 'overlay:typed' });
    chart.setPaneWeight(0, 1); chart.setPaneWeight(study.paneIndex, 1);
    chart.setVisibleLogicalRange({ from: -1, to: 49 });
    const patches: IndicatorSettings[] = [], write = study.setSettings.bind(study);
    study.setSettings = patch => { patches.push({ ...patch }); write(patch); };
    const events: unknown[] = [];
    for (const event of ['click', 'pick:start', 'pick:end']) chart.on(event, payload => events.push({ event, payload }));
    window.__typedInputs = { chart, study, patches, open: () => open(window.__typedInputs.study.id), initialSymbol: symbol(), symbol, events };
    window.__typedInputs.open();
  }, { kind: surface, exchangeKey });
  await paint(page); return errors;
}

function controls(page: Page, surface: Surface) {
  const dialog = page.locator(surface === 'widget' ? '.oac-indset' : '#setmodal');
  return { dialog,
    field: (key: string) => surface === 'widget' ? dialog.locator(`[id$="-${key}"]`).filter({ visible: true }) : dialog.locator(`[data-key="${key}"]`),
    accept: surface === 'widget' ? dialog.getByRole('button', { name: 'OK', exact: true }) : dialog.locator('#set-ok'),
    cancel: surface === 'widget' ? dialog.getByRole('button', { name: 'Cancel', exact: true }) : dialog.locator('#set-x'),
    defaults: surface === 'widget' ? dialog.getByRole('button', { name: 'Defaults', exact: true }) : dialog.locator('#set-reset'),
  };
}
async function settings(page: Page) { return page.evaluate(() => window.__typedInputs.study.settings()); }
async function open(page: Page) { await page.evaluate(() => window.__typedInputs.open()); await paint(page); }
async function fits(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  expect(await page.evaluate(() => Math.max(0, ...[...document.querySelectorAll('#set-body .set-row')]
    .map(row => row.getBoundingClientRect().height)))).toBeLessThan(160);
}
async function chartPoint(page: Page, paneIndex: number, price = 37.125) {
  return page.evaluate(({ index, value }) => {
    const { chart, study } = window.__typedInputs, pane = chart.panes()[index];
    const rect = pane.base.element.getBoundingClientRect(), scale = study.series('value')!.priceScale();
    const x = chart.timeToCoordinate(1700000000.125 + 24 * 60)!;
    return { x: rect.left + x, y: rect.top + (index === study.paneIndex ? scale.priceToY(value) : 100) };
  }, { index: paneIndex, value: price });
}

for (const surface of ['widget', 'demo'] as const) for (const width of [1100, 390]) {
  test(`${surface} typed drafts and exact saved values at ${width}px`, async ({ page }, info) => {
    const errors = await mount(page, surface, width), c = controls(page, surface);
    await expect(c.field('level')).toHaveValue('12.345678901234567');
    await expect(c.dialog).toContainText('UTC seconds');
    await c.field('level').fill(''); await c.field('level').press('Tab'); await c.accept.click();
    await expect(c.dialog).toBeVisible(); await expect(c.field('level')).toHaveAttribute('aria-invalid', 'true');
    expect((await settings(page)).level).toBe(12.345678901234567);
    await c.field('level').fill('1e'); await c.field('level').press('Tab');
    await c.field('hours').fill('0960-1700'); await c.field('hours').press('Tab'); await c.accept.click();
    await expect(c.field('level')).toHaveValue('1e'); await expect(c.field('hours')).toHaveAttribute('aria-invalid', 'true');
    await fits(page); await page.screenshot({ path: info.outputPath(`${surface}-${width}-invalid.png`) });
    await c.field('level').fill('33.125'); await c.field('level').press('Tab');
    await c.field('hours').fill('2200-0200:23456'); await c.field('hours').press('Tab');
    await c.field('note').fill(' <b>literal</b>\nnext\n'); await c.field('note').press('Tab');
    await c.field('when').fill('1700000000.375'); await c.field('when').press('Tab');
    await c.accept.click(); await expect(c.dialog).toBeHidden();
    const expected = await settings(page);
    expect(expected).toMatchObject({ level: 33.125, hours: '2200-0200:23456', note: ' <b>literal</b>\nnext\n', when: 1700000000.375, wall: '2026-09-25 09:30' });
    expect(await page.evaluate(() => {
      const values = window.__typedInputs.study.values().value;
      return values[values.length - 1];
    })).toBe(33.125);
    expect(await page.evaluate(() => {
      const state = window.__typedInputs, saved = JSON.parse(JSON.stringify(state.chart.getState()));
      const applied = state.chart.restoreState(saved).applied;
      state.study = state.chart.indicators().find(study => study.indicatorId === 'browser-typed-inputs')!;
      return applied;
    })).toBe(true);
    expect(await settings(page)).toEqual(expected); await open(page);
    await expect(c.field('when')).toHaveValue('1700000000.375'); await expect(c.field('note')).toHaveValue(' <b>literal</b>\nnext\n');
    await page.screenshot({ path: info.outputPath(`${surface}-${width}-restored.png`) });
    await c.cancel.click(); expect(errors).toEqual([]);
  });

  test(`${surface} symbol pairs, hidden exchange rollback and defaults at ${width}px`, async ({ page }, info) => {
    const errors = await mount(page, surface, width), c = controls(page, surface);
    await c.field('instrument').fill('sam');
    const result = page.getByRole('option', { name: 'X2:SAME Second venue' });
    await expect(result).toBeVisible(); await fits(page);
    await page.screenshot({ path: info.outputPath(`${surface}-${width}-symbol.png`) });
    await result.click(); await expect(c.field('instrument')).toHaveValue('SAME');
    const patches = await page.evaluate(() => window.__typedInputs.patches);
    if (surface === 'widget') expect(patches).toEqual([{ instrument: 'SAME', venue: 'X2' }]);
    else expect(patches).toEqual([]);
    await c.cancel.click(); await expect(c.dialog).toBeHidden();
    expect(await settings(page)).toMatchObject({ instrument: 'AAA', venue: '' });
    await open(page); await c.field('instrument').fill('sam'); await result.click();
    await c.defaults.click();
    expect(await settings(page)).toMatchObject({ instrument: 'AAA', venue: '' });
    if (surface === 'widget') await c.accept.click();
    await open(page); await c.field('instrument').fill('sam'); await result.click(); await c.accept.click();
    expect(await settings(page)).toMatchObject({ instrument: 'SAME', venue: 'X2' });
    expect(await page.evaluate(() => { const state = window.__typedInputs; return state.symbol() === state.initialSymbol; })).toBe(true);
    expect(errors).toEqual([]);
  });

  test(`${surface} targeted picks suspend and resume settings at ${width}px`, async ({ page }, info) => {
    const errors = await mount(page, surface, width), c = controls(page, surface);
    const pricePick = c.dialog.locator('[data-input-action="level"]');
    await page.evaluate(() => window.__typedInputs.study.setPlotPriceScales({ second: 'left' }));
    await expect(pricePick).toBeDisabled(); await expect(pricePick).toHaveAttribute('title', /explicit pane/);
    await page.evaluate(() => {
      const { study } = window.__typedInputs;
      study.setPlotPriceScales({ second: 'overlay:typed' });
      study.series('value')!.priceScale().setPriceRange({ min: 0, max: 100 });
      study.series('value')!.priceScale().setAutoScale(false);
    });
    await expect(pricePick).toBeEnabled(); await pricePick.click();
    await expect(c.dialog).toBeHidden(); await expect(page.locator('.oac-input-pick')).toBeVisible();
    await page.screenshot({ path: info.outputPath(`${surface}-${width}-picking.png`) });
    const wrong = await chartPoint(page, 0); await page.touchscreen.tap(wrong.x, wrong.y);
    await expect(c.dialog).toBeHidden();
    await page.keyboard.press('Escape'); await expect(c.dialog).toBeVisible(); await expect(pricePick).toBeFocused();
    await pricePick.click();
    const paneIndex = await page.evaluate(() => window.__typedInputs.study.paneIndex);
    const point = await chartPoint(page, paneIndex); await page.touchscreen.tap(point.x, point.y);
    await info.attach('pick-state.json', { contentType: 'application/json', body: JSON.stringify(await page.evaluate(point => ({
      point, events: window.__typedInputs.events, hit: document.elementFromPoint(point.x, point.y)?.outerHTML.slice(0, 200),
      panes: window.__typedInputs.chart.panes().map(pane => ({ rect: pane.base.element.getBoundingClientRect().toJSON() })),
      range: window.__typedInputs.study.series('value')!.priceScale().priceRange(),
    }), point), null, 2) });
    await expect(c.dialog).toBeVisible(); await expect(page.locator('.oac-input-pick')).toHaveCount(0);
    const picked = Number(await c.field('level').inputValue()); expect(picked).toBeCloseTo(37.125, 0);
    await c.dialog.locator('[data-input-action="when"]').click();
    const timePoint = await chartPoint(page, 0); await page.touchscreen.tap(timePoint.x, timePoint.y);
    await expect(c.dialog).toBeVisible();
    expect(Number(await c.field('when').inputValue())).toBe(1700000000.125 + 24 * 60);
    await fits(page); await page.screenshot({ path: info.outputPath(`${surface}-${width}-picked.png`) });
    await c.accept.click(); expect((await settings(page)).level).toBe(picked);
    await open(page); await pricePick.click(); await page.evaluate(() => window.__typedInputs.study.remove());
    await expect(c.dialog).toBeHidden(); await expect(page.locator('.oac-input-pick')).toHaveCount(0);
    await page.evaluate(() => {
      const state = window.__typedInputs; state.study = state.chart.addIndicator('browser-typed-inputs'); state.open();
    });
    await expect(c.dialog).toBeVisible(); await page.evaluate(() => window.__typedInputs.chart.destroy());
    await expect(c.dialog).toBeHidden(); expect(errors).toEqual([]);
  });
}

for (const surface of ['widget', 'demo'] as const) {
  test(`${surface} preserves an own __proto__ exchange through picker, Defaults and Cancel`, async ({ page }, info) => {
    const errors = await mount(page, surface, 390, '__proto__'), c = controls(page, surface);
    const pair = () => page.evaluate(() => {
      const state = window.__typedInputs.study.settings();
      return { instrument: state.instrument, venue: Object.getOwnPropertyDescriptor(state, '__proto__')?.value,
        ordinaryPrototype: Object.getPrototypeOf(state) === Object.prototype };
    });
    const select = async () => {
      await c.field('instrument').fill('sam');
      await page.getByRole('option', { name: 'X2:SAME Second venue' }).click();
      await expect(c.field('instrument')).toHaveValue('SAME');
    };
    expect(await pair()).toEqual({ instrument: 'AAA', venue: '', ordinaryPrototype: true });
    await select();
    if (surface === 'widget') expect(await pair()).toEqual({ instrument: 'SAME', venue: 'X2', ordinaryPrototype: true });
    else expect(await pair()).toEqual({ instrument: 'AAA', venue: '', ordinaryPrototype: true });
    await c.cancel.click(); await expect(c.dialog).toBeHidden();
    expect(await pair()).toEqual({ instrument: 'AAA', venue: '', ordinaryPrototype: true });

    await open(page); await select(); await c.accept.click();
    expect(await pair()).toEqual({ instrument: 'SAME', venue: 'X2', ordinaryPrototype: true });
    await open(page);
    await fits(page);
    await page.screenshot({ path: info.outputPath(`${surface}-own-exchange-selected.png`) });
    await c.defaults.click();
    expect(await pair()).toEqual({ instrument: 'AAA', venue: '', ordinaryPrototype: true });
    if (surface === 'widget') await c.accept.click();
    await open(page); await select(); await c.cancel.click();
    expect(await pair()).toEqual({ instrument: 'AAA', venue: '', ordinaryPrototype: true });
    expect(await page.evaluate(() => { const state = window.__typedInputs; return state.symbol() === state.initialSymbol; })).toBe(true);
    expect(errors).toEqual([]);
  });
}
