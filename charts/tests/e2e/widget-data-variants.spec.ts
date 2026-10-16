import { test, expect, type Page } from '@playwright/test';
import { VERSION } from '../../src/version';

// A data variant in a real browser: the widget asks the provider for the
// extended series, draws its extra bars, names it on the status line, and
// says plainly when the provider does not serve it rather than drawing the
// regular series under the extended name.

async function mount(page: Page): Promise<string[]> {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 960, height: 640 });
  await page.goto('/tests/e2e/widget-data-variants-fixture.html');
  await page.waitForFunction(version => (window as any).fixture?.version === version, VERSION);
  return errors;
}
const count = (page: Page): Promise<number> => page.evaluate(() => (window as any).fixture.widget.series.getData().length);
const requests = (page: Page): Promise<{ interval: string; variant: unknown }[]> => page.evaluate(() => (window as any).fixture.requests);

test('extended hours load as their own series, and an undeclared variant is reported', async ({ page }, info) => {
  const errors = await mount(page);
  await expect.poll(() => count(page)).toBe(40);
  const label = page.locator('.oac-statusline__variant');
  await expect(label).toBeHidden();
  await page.screenshot({ path: info.outputPath('widget-regular.png') });

  await page.evaluate(() => (window as any).fixture.widget.setDataVariant({ session: 'extended' }));
  await expect.poll(() => count(page)).toBe(60);
  await expect(label).toBeVisible();
  await expect(label).toHaveText('Extended hours');
  expect((await requests(page)).map(request => request.variant)).toEqual([null, { session: 'extended' }]);
  expect(await page.evaluate(() => (window as any).fixture.widget.chart.getDataContext().variant)).toEqual({ session: 'extended' });
  await page.screenshot({ path: info.outputPath('widget-extended.png') });

  // Daily bars have no extended hours at this provider: nothing is fetched,
  // the chart is empty and the overlay says what is missing, with no retry.
  await page.evaluate(() => (window as any).fixture.widget.setInterval('1d'));
  const status = page.locator('.oac-data-status');
  await expect(status).toBeVisible();
  await expect(status).toContainText('Not available from this source: Extended hours');
  await expect(status.getByRole('button')).toHaveCount(0);
  expect(await count(page)).toBe(0);
  expect(await requests(page)).toHaveLength(2);
  await page.screenshot({ path: info.outputPath('widget-variant-unsupported.png') });

  await page.evaluate(() => (window as any).fixture.widget.setDataVariant(undefined));
  await expect.poll(() => count(page)).toBe(40);
  await expect(status).toBeHidden();
  await expect(label).toBeHidden();
  const sent = await requests(page);
  expect(sent[sent.length - 1]).toEqual({ interval: '1d', variant: null });
  expect(errors).toEqual([]);
});

test('a layout saved on regular hours restores as regular hours, and an extended-hours alert waits for its series', async ({ page }, info) => {
  const errors = await mount(page);
  await expect.poll(() => count(page)).toBe(40);
  const saved = await page.evaluate(() => {
    const { widget } = (window as any).fixture;
    widget.chart.setVisibleLogicalRange({ from: 5, to: 25 });
    return widget.getState();
  });
  expect(saved).not.toHaveProperty('variant');
  await page.evaluate(() => (window as any).fixture.widget.setDataVariant({ session: 'extended' }));
  await expect.poll(() => count(page)).toBe(60);
  const label = page.locator('.oac-statusline__variant');
  await expect(label).toHaveText('Extended hours');

  // The saved state names no variant, so it is the regular series again,
  // whatever the widget showed, and the view taken on regular bars is not
  // laid over the extended ones on the way.
  const report = await page.evaluate(state => (window as any).fixture.widget.restoreState(state), saved);
  expect(report.applied).toBe(true);
  await expect.poll(() => count(page)).toBe(40);
  await expect(label).toBeHidden();
  expect(await page.evaluate(() => (window as any).fixture.widget.variant())).toBeUndefined();
  const sent = await requests(page);
  expect(sent[sent.length - 1]).toEqual({ interval: '1m', variant: null });
  const view = await page.evaluate(() => (window as any).fixture.widget.chart.getVisibleLogicalRange());
  expect(view).not.toEqual({ from: 5, to: 25 });
  await page.screenshot({ path: info.outputPath('widget-restored-regular.png') });

  // An alert set on extended hours waits for them: on regular hours it stays
  // in view, paused, labelled with where it evaluates, and says why.
  await page.evaluate(() => (window as any).fixture.widget.setDataVariant({ session: 'extended' }));
  await expect.poll(() => count(page)).toBe(60);
  const id = await page.evaluate(() => (window as any).fixture.widget.alerts.add({
    source: { kind: 'price', price: 104 }, condition: 'crossingUp', title: 'Extended level' }).id);
  await page.screenshot({ path: info.outputPath('widget-extended-alert.png') });
  await page.evaluate(() => (window as any).fixture.widget.setDataVariant(undefined));
  await expect.poll(() => count(page)).toBe(40);
  expect(await page.evaluate(() => (window as any).fixture.widget.chart.exportSVG().includes('Extended level (1m, extended)'))).toBe(true);
  expect(await page.evaluate(alert => (window as any).fixture.widget.alerts.availability(alert), id))
    .toMatchObject({ available: false, reason: expect.stringContaining('data variant') });
  await page.screenshot({ path: info.outputPath('widget-regular-with-extended-alert.png') });
  expect(errors).toEqual([]);
});
