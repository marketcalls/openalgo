import { test, expect, type Page } from '@playwright/test';
import { VERSION } from '../../src/version';

async function mount(page: Page, compact = false): Promise<string[]> {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize(compact ? { width: 320, height: 240 } : { width: 960, height: 640 });
  await page.goto(`/tests/e2e/widget-data-loading-fixture.html${compact ? '?compact' : ''}`);
  await page.waitForFunction(version => (window as any).fixture?.version === version, VERSION);
  if (compact) expect((await page.locator('.oac-chart').boundingBox())!.height).toBeGreaterThan(180);
  return errors;
}
const count = (page: Page): Promise<number> => page.evaluate(() => (window as any).fixture.widget.series.getData().length);

test('loading, retry, recovery and a compact study status remain usable', async ({ page }, info) => {
  const errors = await mount(page, true);
  const status = page.locator('.oac-data-status');
  await expect(status).toHaveAttribute('role', 'status');
  await expect(status).toContainText('Loading AAA 1m');
  await page.evaluate(() => (window as any).fixture.fail(0));
  const retry = page.getByRole('button', { name: 'Retry chart data' });
  await expect(retry).toBeVisible();
  const bounds = await retry.boundingBox();
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(320);
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(240);
  await page.screenshot({ path: info.outputPath('widget-error.png') });
  await retry.focus();
  await page.keyboard.press('Enter');
  await expect.poll(() => page.evaluate(() => (window as any).fixture.history.length)).toBe(2);
  await page.evaluate(() => (window as any).fixture.ready(1));
  await expect.poll(() => count(page)).toBe(40);
  await expect(status).toBeHidden();
  await page.evaluate(() => (window as any).fixture.addStudy());
  await expect(status).toContainText('External value: Unsupported');
  await page.screenshot({ path: info.outputPath('widget-unsupported.png') });
  await page.evaluate(() => (window as any).fixture.support(true));
  await page.getByRole('button', { name: 'Retry External value' }).click();
  await expect(status).toContainText('External value: Loading');
  await page.evaluate(() => {
    const fixture = (window as any).fixture;
    fixture.studies[0].resolve([{ time: fixture.bars()[0].time, values: { v: 10 } }]);
  });
  await expect(status).toBeHidden();
  await page.evaluate(() => (window as any).fixture.recover());
  await expect(status).toContainText('Refreshing');
  await page.evaluate(() => (window as any).fixture.fail(2));
  await expect(status).toContainText('History is stale');
  await retry.click();
  await page.evaluate(() => (window as any).fixture.ready(3));
  // Resynced history is a new source revision, so the external study asks again.
  await expect(status).toContainText('External value: Loading');
  expect(await page.evaluate(() => (window as any).fixture.studies.length)).toBe(2);
  await page.evaluate(() => {
    const fixture = (window as any).fixture;
    fixture.studies[1].resolve([{ time: fixture.bars()[0].time, values: { v: 11 } }]);
  });
  await expect(status).toBeHidden();
  expect(errors).toEqual([]);
});

test('context races, older-history anchors and replay keep the correct bars on screen', async ({ page }, info) => {
  const errors = await mount(page);
  await page.evaluate(() => {
    const fixture = (window as any).fixture;
    fixture.widget.setSymbol('BBB');
    fixture.ready(1, 30, 40, 200);
    fixture.ready(0, 30, 40, 100);
  });
  await expect.poll(() => count(page)).toBe(40);
  expect(await page.evaluate(() => (window as any).fixture.widget.series.getData()[0].close)).toBeGreaterThan(190);
  expect(await page.evaluate(() => (window as any).fixture.history[0].request.signal.aborted)).toBe(true);
  const anchor = await page.evaluate(() => {
    const widget = (window as any).fixture.widget;
    widget.chart.setVisibleLogicalRange({ from: 5, to: 15 });
    return widget.series.getData()[5].time;
  });
  // A keyboard pan reaches Chart's actual history callback.
  await page.locator('.oac-chart').click({ position: { x: 300, y: 200 } });
  await page.keyboard.press('ArrowLeft');
  await expect.poll(() => page.evaluate(() => (window as any).fixture.pages.length)).toBe(1);
  const beforePage = await page.evaluate(() => (window as any).fixture.widget.chart.getVisibleLogicalRange());
  await page.evaluate(() => {
    const fixture = (window as any).fixture;
    fixture.pages[0].resolve({ bars: fixture.bars(10, 20, 200), hasMore: false });
  });
  await expect.poll(() => count(page)).toBe(60);
  const afterPage = await page.evaluate(() => (window as any).fixture.widget.chart.getVisibleLogicalRange());
  expect(afterPage.from - beforePage.from).toBeCloseTo(20, 5);
  expect(await page.evaluate(() => (window as any).fixture.widget.series.getData()[25].time)).toBe(anchor);
  await page.screenshot({ path: info.outputPath('widget-history.png') });
  await page.evaluate(() => {
    const fixture = (window as any).fixture;
    fixture.widget.dataController.setPaused(true);
    fixture.widget.series.setData(fixture.widget.series.getData().slice(0, 25));
    fixture.live(70, 211);
  });
  await expect.poll(() => count(page)).toBe(25);
  expect(await page.evaluate(() => (window as any).fixture.widget.dataController.bars().length)).toBe(61);
  await page.evaluate(() => (window as any).fixture.widget.dataController.setPaused(false));
  await expect.poll(() => count(page)).toBe(61);
  await page.evaluate(() => (window as any).fixture.widget.destroy());
  await expect(page.locator('.oac-widget')).toHaveCount(0);
  expect(await page.evaluate(() => (window as any).fixture.streams.every((stream: any) => stream.stopped))).toBe(true);
  expect(errors).toEqual([]);
});
