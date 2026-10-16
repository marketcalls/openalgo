import { expect, test, type Page } from '@playwright/test';
import type { Chart, TimeNavigator } from '../../src/index';
import type { Widget } from '../../src/widget/widget';
import type * as Charts from '../../src/index';
import type * as Widgets from '../../src/widget/index';

test.use({ hasTouch: true });

declare global {
  interface Window {
    __navigationPolicy: { chart: Chart; widget: Widget; nav: TimeNavigator; settings(): void };
  }
}

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function initialize(page: Page) {
  await page.evaluate(async () => {
    const baseUrl = '/dist/openalgo-charts.mjs', widgetUrl = '/dist/openalgo-charts.widget.mjs';
    const lib = await import(baseUrl) as typeof Charts, widgets = await import(widgetUrl) as typeof Widgets;
    const widget = widgets.createWidget(document.getElementById('host')!, {
      persist: 'browser-navigation-policy', rail: false, symbol: 'SYNTH', interval: '1m',
      branding: false, animZoom: false, animAutoscale: false,
      timeNavigator: { fadeSeconds: 0, buttons: ['panRightBar', null, 'zoomIn', null, 'panLeftBar', 'resetScale'] },
      mobile: window.innerWidth <= 640 ? 'auto' : 'never',
    });
    // The saved navigation lands once the widget's store (IndexedDB) has answered.
    await widget.ready;
    const chart = widget.chart;
    widget.series.applyOptions({ upColor: '#33aaff', downColor: '#33aaff' });
    widget.series.setData(Array.from({ length: 200 }, (_, index) => {
      const close = 100 + index + 4 * Math.sin(index);
      return { time: 1700000040 + index * 60, open: close - 2, high: close + 2, low: close - 4, close };
    }));
    chart.setVisibleLogicalRange({ from: 100, to: 160 });
    const nav = chart.panes()[0].primitives().find(primitive => primitive instanceof lib.TimeNavigator) as TimeNavigator;
    window.__navigationPolicy = { chart, widget, nav,
      settings: () => { widgets.mountSettingsDialog(widget.context, undefined, { tab: 'axes' }); } };
  });
  await paint(page);
}

async function mount(page: Page, width: number) {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width, height: 820 });
  await page.route('**/user-navigation-policy.html', route => route.fulfill({ contentType: 'text/html', body:
    '<!doctype html><html><head><style>html,body{margin:0;background:#111318}#host{height:800px;width:100%}</style></head><body><div id="host"></div></body></html>' }));
  await page.goto('/user-navigation-policy.html'); await initialize(page);
  return errors;
}

async function reading(page: Page) {
  return page.evaluate(() => {
    const { chart, nav, widget } = window.__navigationPolicy;
    return { range: chart.getVisibleLogicalRange(), spacing: chart.timeScale.barSpacing,
      price: widget.series.priceScale().priceRange(), navigation: chart.navigationOptions(), buttons: nav.options().buttons };
  });
}

async function resetView(page: Page) {
  await page.evaluate(() => {
    const { chart, widget } = window.__navigationPolicy;
    chart.setVisibleLogicalRange({ from: 100, to: 160 }); widget.series.priceScale().setAutoScale(true);
  });
  await paint(page);
}

async function navigatorButton(page: Page, action: string) {
  const box = await page.locator('.oac-chart').boundingBox();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height - 55); await paint(page);
  const point = await page.evaluate(action => {
    const { chart, nav } = window.__navigationPolicy, pane = chart.panes()[0], rect = pane.base.element.getBoundingClientRect();
    for (let y = Math.max(0, rect.height - 130); y < rect.height; y += 2) for (let x = 0; x < chart.timeScale.width; x += 2) {
      if (nav.hitTest(x, y)?.externalId === `${nav.options().id}::${action}`) return { x: rect.left + x + 3, y: rect.top + y + 3 };
    }
    return null;
  }, action);
  expect(point).not.toBeNull();
  await page.mouse.click(point!.x, point!.y); await paint(page);
}

for (const width of [900, 390]) {
  test(`navigator completes fades with a stationary pointer at ${width}px`, async ({ page }, info) => {
    const errors = await mount(page, width);
    await page.evaluate(() => window.__navigationPolicy.nav.setOptions({ fadeSeconds: 1 }));
    await paint(page);
    const box = (await page.locator('.oac-chart').boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height - 55);
    await paint(page);
    await expect.poll(() => page.evaluate(() => window.__navigationPolicy.nav.animating()), { timeout: 4000 }).toBe(false);
    const before = await reading(page);
    await navigatorButton(page, 'zoomIn');
    expect((await reading(page)).spacing).toBeGreaterThan(before.spacing);
    await page.screenshot({ path: info.outputPath(`navigation-idle-reveal-${width}.png`) });
    await page.mouse.move(box.x + 80, box.y + 120);
    await paint(page);
    await expect.poll(() => page.evaluate(() => window.__navigationPolicy.nav.animating()), { timeout: 4000 }).toBe(false);
    expect(await page.evaluate(() => {
      const { chart, nav } = window.__navigationPolicy;
      for (let y = chart.panes()[0].base.element.height - 130; y < chart.panes()[0].base.element.height; y += 2)
        for (let x = 0; x < chart.timeScale.width; x += 2) if (nav.hitTest(x, y)) return true;
      return false;
    })).toBe(false);
    await page.screenshot({ path: info.outputPath(`navigation-idle-hidden-${width}.png`) });
    expect(errors).toEqual([]);
  });

  test(`independent gestures and navigator controls at ${width}px`, async ({ page }, info) => {
    const errors = await mount(page, width), box = (await page.locator('.oac-chart').boundingBox())!;
    for (const panEnabled of [false, true]) for (const zoomEnabled of [false, true]) {
      await page.evaluate(policy => window.__navigationPolicy.chart.setNavigationOptions(policy), { panEnabled, zoomEnabled });
      await resetView(page);
      const start = await reading(page);
      const expected = panEnabled ? (zoomEnabled ? ['panRightBar', null, 'zoomIn', null, 'panLeftBar', 'resetScale']
        : ['panRightBar', null, 'panLeftBar']) : (zoomEnabled ? ['zoomIn', null, 'resetScale'] : []);
      expect(start.buttons).toEqual(expected);
      await page.mouse.move(box.x + 100, box.y + 220); await page.mouse.down();
      await page.mouse.move(box.x + 155, box.y + 250, { steps: 6 }); await page.mouse.up(); await paint(page);
      const dragged = await reading(page);
      expect(dragged.range.from !== start.range.from).toBe(panEnabled);
      expect(dragged.price.min !== start.price.min).toBe(panEnabled);
      await resetView(page); const beforeWheel = await reading(page);
      await page.mouse.move(box.x + 160, box.y + 270); await page.mouse.wheel(0, -100); await paint(page);
      expect((await reading(page)).spacing !== beforeWheel.spacing).toBe(zoomEnabled);
      await resetView(page); const beforeHorizontal = await reading(page);
      await page.mouse.wheel(65, 0); await paint(page);
      expect((await reading(page)).range.from !== beforeHorizontal.range.from).toBe(panEnabled);
      await resetView(page);
      if (panEnabled) {
        const beforeButton = await reading(page); await navigatorButton(page, 'panRightBar');
        expect((await reading(page)).range.from).not.toBe(beforeButton.range.from);
      }
      if (zoomEnabled) {
        const beforeButton = await reading(page); await navigatorButton(page, 'zoomIn');
        expect((await reading(page)).spacing).toBeGreaterThan(beforeButton.spacing);
      }
    }
    const blue = await page.evaluate(() => {
      const canvas = window.__navigationPolicy.chart.panes()[0].base.element;
      const pixels = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
      let count = 0; for (let i = 0; i < pixels.length; i += 4) if (pixels[i] === 51 && pixels[i + 1] === 170 && pixels[i + 2] === 255) count++;
      return count;
    });
    expect(blue).toBeGreaterThan(100);
    await page.screenshot({ path: info.outputPath(`navigation-controls-${width}.png`) });
    expect(errors).toEqual([]);
  });

  test(`settings cancel, save and reload navigation policies at ${width}px`, async ({ page }, info) => {
    const errors = await mount(page, width);
    const edit = async () => {
      await page.evaluate(() => window.__navigationPolicy.settings());
      const dialog = page.locator('.oac-settings');
      for (const name of ['Enable panning', 'Enable zooming']) {
        const input = dialog.getByLabel(name, { exact: true }); await input.focus(); await input.press('Space');
      }
      expect((await reading(page)).navigation).toMatchObject({ panEnabled: false, zoomEnabled: false });
      return dialog;
    };
    let dialog = await edit(); await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
    expect((await reading(page)).navigation).toMatchObject({ panEnabled: true, zoomEnabled: true });
    dialog = await edit(); await page.screenshot({ path: info.outputPath(`navigation-settings-${width}.png`) });
    await dialog.getByRole('button', { name: 'OK', exact: true }).click();
    await expect.poll(() => page.evaluate(() => {
      const saved = window.__navigationPolicy.widget.context.storage.get('state') as { chart?: { navigation?: { panEnabled?: boolean; zoomEnabled?: boolean } } } | null;
      return [saved?.chart?.navigation?.panEnabled, saved?.chart?.navigation?.zoomEnabled];
    })).toEqual([false, false]);
    await page.reload(); await initialize(page);
    const restored = await reading(page); expect(restored.navigation).toMatchObject({ panEnabled: false, zoomEnabled: false });
    expect(restored.buttons).toEqual([]);
    const box = (await page.locator('.oac-chart').boundingBox())!;
    await page.mouse.click(box.x + 160, box.y + 250, { button: 'right' });
    await expect(page.getByRole('menuitem', { name: 'Fit all bars', exact: true })).toHaveAttribute('aria-disabled', 'true');
    await page.keyboard.press('Escape');
    await page.evaluate(() => window.__navigationPolicy.chart.fitContent()); await paint(page);
    expect((await reading(page)).range).not.toEqual(restored.range);
    await page.evaluate(() => window.__navigationPolicy.settings()); dialog = page.locator('.oac-settings');
    await dialog.getByRole('button', { name: 'Restore this tab', exact: true }).click();
    expect((await reading(page)).navigation).toMatchObject({ panEnabled: true, zoomEnabled: true });
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
    expect((await reading(page)).navigation).toMatchObject({ panEnabled: false, zoomEnabled: false });
    await page.screenshot({ path: info.outputPath(`navigation-restored-${width}.png`) });
    expect(errors).toEqual([]);
  });
}
