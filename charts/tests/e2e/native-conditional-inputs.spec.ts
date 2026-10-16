import { expect, test, type Page } from '@playwright/test';
import type { Chart, IndicatorApi, IndicatorInput } from '../../src/index';
import type * as Charts from '../../src/index';
import type * as Widgets from '../../src/widget/index';

// Conditional study inputs in real engines: rows a setting shows, rows a
// setting enables, neighbours on one row, the tab order around hidden rows,
// the live announcement, and drafts, Cancel and Defaults, in the widget's
// generated dialog and in the reference host's own form.
test.use({ screenshot: 'only-on-failure', trace: 'retain-on-failure' });
type Surface = 'widget' | 'demo';
type DemoWindow = Window & { __oac: { app: { chart: Chart; loading: boolean } } };
declare global { interface Window { __conditional: { chart: Chart; study: IndicatorApi; open(): void } } }

const INPUTS: IndicatorInput[] = [
  { key: 'length', type: 'number', label: 'Length', default: 14, min: 1, max: 200, inline: 'len' },
  { key: 'source', type: 'source', label: 'Source', default: 'close', inline: 'len' },
  { key: 'mode', type: 'select', label: 'Mode', default: 'line',
    options: [{ label: 'Line', value: 'line' }, { label: 'Bands', value: 'bands' }] },
  { key: 'width', type: 'number', label: 'Band width', default: 2, min: 0.5, max: 5, step: 0.5,
    visibleWhen: { key: 'mode', is: 'bands' } },
  { key: 'level', type: 'price', label: 'Anchor price', default: 10, min: 0, max: 1000,
    visibleWhen: { key: 'mode', is: 'bands' } },
  { key: 'smoothing', type: 'select', label: 'Smoothing', default: 'none', group: 'Smoothing',
    options: [{ label: 'None', value: 'none' }, { label: 'Moving average', value: 'sma' }] },
  { key: 'smoothLength', type: 'number', label: 'Smoothing length', default: 5, min: 1, max: 50, group: 'Smoothing',
    activeWhen: { key: 'smoothing', isNot: 'none' } },
  { key: 'showSignal', type: 'boolean', label: 'Signal', default: false, group: 'Signal', inline: 'signal' },
  { key: 'signalLength', type: 'number', label: 'Length', default: 9, min: 1, max: 50, group: 'Signal', inline: 'signal',
    activeWhen: { key: 'showSignal', is: true } },
  { key: 'signalColor', type: 'color', label: 'Colour', default: '#f59e0b', group: 'Signal', inline: 'signal',
    activeWhen: { key: 'showSignal', is: true } },
];

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function mount(page: Page, surface: Surface, width: number) {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width, height: 900 });
  if (surface === 'widget') {
    await page.route('**/native-conditional-inputs.html', route => route.fulfill({ contentType: 'text/html', body:
      '<!doctype html><html><head><style>html,body{margin:0;background:#111318}#host{height:880px;width:100%}</style></head><body><div id="host"></div></body></html>' }));
    await page.goto('/native-conditional-inputs.html');
  } else {
    await page.goto(`http://127.0.0.1:${process.env.OAC_E2E_DEMO_PORT || '8124'}/examples/yfinance/index.html?test=1`);
    await page.waitForFunction(() => Boolean((window as DemoWindow).__oac?.app.chart) && !(window as DemoWindow).__oac.app.loading);
  }
  await page.evaluate(async ({ kind, inputs }) => {
    const baseUrl = '/dist/openalgo-charts.mjs', widgetUrl = '/dist/openalgo-charts.widget.mjs';
    const lib = await import(baseUrl) as typeof Charts, widgets = await import(widgetUrl) as typeof Widgets;
    let chart: Chart, open: (id: string) => void;
    if (kind === 'widget') {
      const widget = widgets.createWidget(document.getElementById('host')!, {
        persist: false, rail: false, symbol: 'PRIMARY', interval: '1m',
        branding: false, timeNavigator: false, animZoom: false, animAutoscale: false,
        mobile: window.innerWidth <= 640 ? 'auto' : 'never',
      });
      chart = widget.chart;
      open = id => { widgets.mountIndicatorSettings(widget.context, undefined, { instanceId: id }); };
    } else {
      chart = (window as DemoWindow).__oac.app.chart;
      const url = '/examples/yfinance/src/indicators.js';
      const host = await import(url) as { openSettings(id: string): void };
      open = id => host.openSettings(id);
    }
    for (const study of [...chart.indicators()]) study.remove();
    lib.registerIndicator({ id: 'browser-conditional-inputs', name: 'Conditional study', placement: 'pane',
      inputs, plots: [{ key: 'value', title: 'Value', type: 'line', style: { color: '#33aaff', lineWidth: 2 } }],
      calc: (bars, settings) => ({ value: bars.map(bar => bar.close * (settings.mode === 'bands' ? settings.width as number : 1)) }),
    });
    chart.primarySeries()!.setData(Array.from({ length: 48 }, (_, index) => ({
      time: 1700000000 + index * 60, open: 200 + index, high: 203 + index, low: 199 + index, close: 201 + index,
    })));
    const study = chart.addIndicator('browser-conditional-inputs');
    window.__conditional = { chart, study, open: () => open(window.__conditional.study.id) };
    window.__conditional.open();
  }, { kind: surface, inputs: INPUTS });
  await paint(page); return errors;
}

function controls(page: Page, surface: Surface) {
  const dialog = page.locator(surface === 'widget' ? '.oac-indset' : '#setmodal');
  return { dialog,
    field: (key: string) => surface === 'widget' ? dialog.locator(`[id$="-${key}"]`) : dialog.locator(`[data-key="${key}"]`),
    swatch: (key: string) => surface === 'widget' ? dialog.locator(`[id$="-${key}-trigger"]`) : dialog.locator(`[id$="_${key}-trigger"]`),
    live: dialog.locator('[role="status"][aria-live="polite"]'),
    accept: surface === 'widget' ? dialog.getByRole('button', { name: 'OK', exact: true }) : dialog.locator('#set-ok'),
    cancel: surface === 'widget' ? dialog.getByRole('button', { name: 'Cancel', exact: true }) : dialog.locator('#set-x'),
    defaults: surface === 'widget' ? dialog.getByRole('button', { name: 'Defaults', exact: true }) : dialog.locator('#set-reset'),
  };
}
async function settings(page: Page) { return page.evaluate(() => window.__conditional.study.settings()); }
async function open(page: Page) { await page.evaluate(() => window.__conditional.open()); await paint(page); }
async function fits(page: Page, surface: Surface) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  // Every shown control sits inside the dialog's width: an inline row wraps its
  // members inside itself rather than pushing one past the edge.
  expect(await page.evaluate(selector => {
    const dialog = document.querySelector(selector)!.getBoundingClientRect();
    return [...document.querySelectorAll(`${selector} input, ${selector} select, ${selector} button`)]
      .map(node => node.getBoundingClientRect()).filter(rect => rect.width > 0)
      .every(rect => rect.left >= dialog.left - 1 && rect.right <= dialog.right + 1);
  }, surface === 'widget' ? '.oac-indset' : '#setmodal .set-card')).toBe(true);
}
/**
 * How many passes over the rules one committed edit makes, counted from the
 * title every pass writes on a field. Setting an attribute queues a mutation
 * record even when the value is unchanged, so each pass counts once.
 */
async function passes(page: Page, surface: Surface) {
  const c = controls(page, surface);
  await c.field('smoothLength').evaluate(node => {
    const w = window as unknown as { __passes: number; __observer?: MutationObserver };
    w.__observer?.disconnect(); w.__passes = 0;
    w.__observer = new MutationObserver(records => { w.__passes += records.length; });
    w.__observer.observe(node, { attributes: true, attributeFilter: ['title'] });
  });
  await c.field('smoothing').selectOption('sma');
  await c.field('smoothing').selectOption('none');
  return page.evaluate(() => (window as unknown as { __passes: number }).__passes);
}

/** Ids of the fields keyboard focus visits, pressing Tab from `start`. */
async function tabOrder(page: Page, start: ReturnType<Page['locator']>, presses: number) {
  await start.focus();
  const seen: string[] = [];
  for (let i = 0; i < presses; i++) {
    await page.keyboard.press('Tab');
    seen.push(await page.evaluate(() => document.activeElement?.id ?? ''));
  }
  return seen;
}

for (const surface of ['widget', 'demo'] as const) {
  test(`${surface} re-reads the rules once per edit however often the dialog opens, and commits numbers alike`, async ({ page }, info) => {
    const errors = await mount(page, surface, 1100), c = controls(page, surface);
    const first = await passes(page, surface);
    expect(first).toBeGreaterThan(0);
    for (let i = 0; i < 3; i++) { await c.cancel.click(); await expect(c.dialog).toBeHidden(); await open(page); }
    expect(await passes(page, surface)).toBe(first);

    // A number counts as its commit leaves it: a blank box is no edit, and a
    // value past its bound is clamped, in the widget and the reference host alike.
    await c.field('mode').selectOption('bands');
    await c.field('width').fill(''); await c.field('width').press('Tab');
    await expect(c.field('width')).toHaveValue('2');
    await expect(c.field('width')).toBeVisible();
    await c.field('width').fill('9'); await c.field('width').press('Tab');
    await expect(c.field('width')).toHaveValue('5');
    await page.screenshot({ path: info.outputPath(`${surface}-committed.png`) });
    await c.cancel.click();
    expect(errors).toEqual([]);
  });
}

for (const surface of ['widget', 'demo'] as const) for (const width of [1100, 390]) {
  test(`${surface} shows, hides and announces conditional rows at ${width}px`, async ({ page }, info) => {
    const errors = await mount(page, surface, width), c = controls(page, surface);
    await expect(c.field('mode')).toBeVisible();
    await expect(c.field('width')).toBeHidden();
    await expect(c.field('level')).toBeHidden();
    await expect(c.field('smoothLength')).toBeDisabled();
    await expect(c.field('smoothLength')).toHaveAttribute('title', 'Depends on Smoothing');
    await expect(c.field('signalLength')).toBeDisabled();
    await expect(c.swatch('signalColor')).toBeDisabled();
    // Hidden rows are out of the tab order, not merely out of sight.
    const skipped = await tabOrder(page, c.field('mode'), 4);
    expect(skipped.some(id => /(?:-|_)(?:width|level)$/.test(id))).toBe(false);
    await fits(page, surface);
    await page.screenshot({ path: info.outputPath(`${surface}-${width}-closed.png`) });

    await c.field('mode').selectOption('bands');
    await expect(c.field('width')).toBeVisible();
    await expect(c.field('level')).toBeVisible();
    await expect(c.live).toHaveText('Shown: Band width, Anchor price');
    const reached = await tabOrder(page, c.field('mode'), 2);
    expect(reached.some(id => /(?:-|_)width$/.test(id))).toBe(true);
    await c.field('smoothing').selectOption('sma');
    await expect(c.field('smoothLength')).toBeEnabled();
    await expect(c.live).toHaveText('Available: Smoothing length');
    await c.field('showSignal').check();
    await expect(c.field('signalLength')).toBeEnabled();
    await expect(c.swatch('signalColor')).toBeEnabled();
    await fits(page, surface);
    await page.screenshot({ path: info.outputPath(`${surface}-${width}-open.png`) });

    // A draft survives its row being hidden and shown again.
    await c.field('width').fill('3.5'); await c.field('width').press('Tab');
    await c.field('mode').selectOption('line');
    await expect(c.field('width')).toBeHidden();
    await expect(c.live).toHaveText('Hidden: Band width, Anchor price');
    await c.field('mode').selectOption('bands');
    await expect(c.field('width')).toHaveValue('3.5');

    await c.cancel.click(); await expect(c.dialog).toBeHidden();
    expect(await settings(page)).toMatchObject({ mode: 'line', width: 2, smoothing: 'none', showSignal: false });
    await open(page);
    await expect(c.field('width')).toBeHidden();
    await expect(c.field('smoothLength')).toBeDisabled();
    await c.cancel.click();
    expect(errors).toEqual([]);
  });

  test(`${surface} inline rows, a hidden invalid draft and defaults at ${width}px`, async ({ page }, info) => {
    const errors = await mount(page, surface, width), c = controls(page, surface);
    const length = await c.field('length').boundingBox(), source = await c.field('source').boundingBox();
    const mode = await c.field('mode').boundingBox();
    // One row: the pair sits above the next row, not stacked as two rows.
    expect(length!.y + length!.height).toBeLessThanOrEqual(mode!.y + 1);
    expect(source!.y + source!.height).toBeLessThanOrEqual(mode!.y + 1);
    if (width > 640) expect(Math.abs((length!.y + length!.height / 2) - (source!.y + source!.height / 2))).toBeLessThan(4);

    await c.field('mode').selectOption('bands');
    await c.field('level').fill('-1'); await c.field('level').press('Tab');
    await c.accept.click();
    await expect(c.dialog).toBeVisible();
    await expect(c.field('level')).toHaveAttribute('aria-invalid', 'true');
    await page.screenshot({ path: info.outputPath(`${surface}-${width}-invalid.png`) });
    await c.field('mode').selectOption('line');
    await c.accept.click(); await expect(c.dialog).toBeHidden();
    expect(await settings(page)).toMatchObject({ mode: 'line', level: 10 });

    await open(page);
    await c.field('mode').selectOption('bands');
    await c.field('width').fill('4'); await c.field('width').press('Tab');
    await c.field('smoothing').selectOption('sma');
    await c.accept.click(); await expect(c.dialog).toBeHidden();
    expect(await settings(page)).toMatchObject({ mode: 'bands', width: 4, smoothing: 'sma' });
    await open(page);
    await expect(c.field('width')).toHaveValue('4');
    await c.defaults.click();
    expect(await settings(page)).toMatchObject({ mode: 'line', width: 2, smoothing: 'none', level: 10 });
    if (surface === 'widget') {
      await expect(c.field('width')).toBeHidden();
      await expect(c.field('smoothLength')).toBeDisabled();
      await c.accept.click();
    }
    await open(page);
    await expect(c.field('width')).toBeHidden();
    await fits(page, surface);
    await page.screenshot({ path: info.outputPath(`${surface}-${width}-defaults.png`) });
    await c.cancel.click();
    expect(errors).toEqual([]);
  });
}
