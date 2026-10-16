import { expect, test, type Page } from '@playwright/test';
import type { Chart } from '../../src/index';

declare const process: { env: Record<string, string | undefined> };

type HostWindow = { __oac: { app: {
  chart: Chart; chart2: Chart | null; loading: boolean; loading2: boolean; focusPane: number;
  render(): void; renderToolbar(): void;
} } };

test.use({ hasTouch: true, screenshot: 'only-on-failure', trace: 'retain-on-failure' });

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function mount(page: Page, width: number) {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width, height: 820 });
  await page.goto(`http://127.0.0.1:${process.env.OAC_E2E_DEMO_PORT || '8124'}/examples/yfinance/index.html?test=1`);
  await page.waitForFunction(() => {
    const app = (window as unknown as HostWindow).__oac?.app;
    return app?.chart?.primaryBars().length > 30 && !app.loading;
  });
  await paint(page);
  return errors;
}

async function controls(page: Page, selectedDisabled: boolean, primaryDisabled = selectedDisabled) {
  for (const id of ['toolbar-fit', 'mobile-zoom-in', 'mobile-zoom-out', 'mobile-fit', 'fit']) {
    const button = page.locator(`#${id}`), disabled = id === 'fit' ? primaryDisabled : selectedDisabled;
    if (disabled) await expect(button).toBeDisabled();
    else await expect(button).toBeEnabled();
    await expect(button).toHaveAttribute('aria-disabled', String(disabled));
  }
}

async function select(page: Page, pane: 1 | 2) {
  await page.locator(pane === 1 ? '#chart' : '#chart2').focus();
  await expect.poll(() => page.evaluate(() => (window as unknown as HostWindow).__oac.app.focusPane)).toBe(pane);
}

async function view(page: Page, pane: 1 | 2 = 1) {
  return page.evaluate(pane => {
    const app = (window as unknown as HostWindow).__oac.app;
    return (pane === 1 ? app.chart : app.chart2!).getVisibleLogicalRange();
  }, pane);
}

async function showNavigation(page: Page, width: number) {
  await page.locator('#toolbar-fit').scrollIntoViewIfNeeded();
  if (width === 390) await page.locator('#mobile-fit').scrollIntoViewIfNeeded();
  await page.mouse.move(width - 2, 400);
  await paint(page);
}

for (const width of [1100, 390]) {
  test(`reference navigation controls follow policy, selection and restore at ${width}px`, async ({ page }, info) => {
    const errors = await mount(page, width);
    await controls(page, false);
    await page.evaluate(() => (window as unknown as HostWindow).__oac.app.chart.setNavigationOptions({ zoomEnabled: false }));
    await controls(page, true);
    await expect(page.locator('#toolbar-fit')).toBeVisible();
    expect(await page.locator('#toolbar-fit').evaluate(button => getComputedStyle(button).opacity)).toBe('0.45');
    await showNavigation(page, width);
    await page.screenshot({ path: info.outputPath(`reference-navigation-disabled-${width}.png`) });

    const beforeProgrammatic = await view(page);
    await page.evaluate(() => (window as unknown as HostWindow).__oac.app.chart.setVisibleLogicalRange({ from: 10, to: 25 }));
    expect(await view(page)).not.toEqual(beforeProgrammatic);
    const blocked = await view(page);
    // Dispatch bypasses native disabled-button suppression and checks the retained action guard too.
    await page.locator('#toolbar-fit').dispatchEvent('click');
    await page.locator('#fit').dispatchEvent('click');
    await page.locator('#mobile-fit').dispatchEvent('click');
    await page.locator('#mobile-zoom-in').dispatchEvent('click');
    await page.locator('#mobile-zoom-out').dispatchEvent('click');
    expect(await view(page)).toEqual(blocked);
    const restored = await page.evaluate(() => (window as unknown as HostWindow).__oac.app.chart.restoreState({
      version: 1, navigation: { zoomEnabled: true },
    }));
    expect(restored.applied).toBe(true); await controls(page, false);
    await page.locator('#toolbar-fit').click(); await paint(page);
    expect(await view(page)).not.toEqual(blocked);

    await page.evaluate(async () => {
      const path = '/examples/yfinance/src/split.js'; await (await import(path)).openSplit();
    });
    await page.waitForFunction(() => {
      const app = (window as unknown as HostWindow).__oac.app;
      return (app.chart2?.primaryBars().length ?? 0) > 30 && !app.loading2;
    });
    await page.evaluate(() => {
      const app = (window as unknown as HostWindow).__oac.app;
      app.chart.setNavigationOptions({ zoomEnabled: false }); app.chart2!.setNavigationOptions({ zoomEnabled: true });
    });
    await select(page, 2); await controls(page, false, true);
    await page.evaluate(() => (window as unknown as HostWindow).__oac.app.chart2!.restoreState({ version: 1,
      navigation: { zoomEnabled: false } }));
    await controls(page, true, true);
    await showNavigation(page, width);
    await page.screenshot({ path: info.outputPath(`reference-navigation-secondary-${width}.png`) });
    await page.evaluate(() => (window as unknown as HostWindow).__oac.app.chart.setNavigationOptions({ zoomEnabled: true }));
    await controls(page, true, false);
    await select(page, 1); await controls(page, false, false);

    await page.evaluate(() => {
      const app = (window as unknown as HostWindow).__oac.app;
      app.chart.setNavigationOptions({ zoomEnabled: false });
      const old = app.chart;
      app.render(); app.renderToolbar();
      if (old === app.chart || !old.isDestroyed) throw new Error('Expected a replacement chart');
      old.emit('objects:change', undefined); old.emit('state:restore:end', undefined);
    });
    await controls(page, true, true);
    await page.evaluate(() => (window as unknown as HostWindow).__oac.app.chart.restoreState({ version: 1,
      navigation: { zoomEnabled: true } }));
    await controls(page, false, false); await paint(page);
    await showNavigation(page, width);
    await page.screenshot({ path: info.outputPath(`reference-navigation-restored-${width}.png`) });
    await page.evaluate(() => (window as unknown as HostWindow).__oac.app.chart.destroy());
    await controls(page, true, true);
    expect(errors).toEqual([]);
  });
}
