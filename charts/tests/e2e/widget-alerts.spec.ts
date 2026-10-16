import { expect, test, type Page } from '@playwright/test';
import type { Widget } from '../../src/widget/widget';
import type { AlertTriggeredPayload, Bar } from '../../src/index';

declare global {
  interface Window {
    __widgetAlerts: { widget: Widget; fired: AlertTriggeredPayload[]; bars: Bar[]; tick(delta: number, next?: boolean): void };
  }
}

test.afterEach(async ({ page }, info) => {
  if (info.status !== info.expectedStatus) {
    await page.screenshot({ path: info.outputPath('failure.png'), animations: 'disabled' });
  }
});

async function openAlertEditor(page: Page, narrow = false): Promise<void> {
  if (narrow) {
    await page.locator('[data-mobile-action="more"]').click();
    await page.locator('[data-mobile-action="alerts"]').click();
  } else await page.locator('.oac-topbar__alerts').click();
  await page.getByRole('button', { name: 'Create alert', exact: true }).click();
}

for (const key of ['Delete', 'Backspace']) {
  test(`${key} gives drawings priority over hovered alerts and persists alert removal`, async ({ page }, info) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewportSize({ width: 1360, height: 900 });
    await page.goto('/tests/e2e/widget-alerts-fixture.html');
    await page.waitForFunction(() => !!window.__widgetAlerts);
    const ids = await page.evaluate(() => {
      const { widget, bars } = window.__widgetAlerts;
      widget.draw.clear();
      const drawing = widget.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {},
        points: [{ time: bars[80].time, price: 99 }] });
      const alert = widget.alerts.add({ title: 'Keyboard target', source: { kind: 'price', price: 102 } });
      const kept = widget.alerts.add({ title: 'Retained alert', source: { kind: 'price', price: 101 } });
      widget.draw.select(drawing.id);
      return { drawing: drawing.id, alert: alert.id, kept: kept.id };
    });
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    const point = await page.evaluate(() => {
      const { widget } = window.__widgetAlerts;
      const rect = widget.root.querySelector('.oac-chart')!.getBoundingClientRect();
      return { x: Math.round(rect.left + rect.width * 0.65), y: Math.round(rect.top + widget.chart.priceToCoordinate(102)!) };
    });
    await page.mouse.move(point.x, point.y);
    await expect.poll(() => page.evaluate(() => window.__widgetAlerts.widget.alerts.hovered())).toBe(ids.alert);
    await page.keyboard.press(key);
    expect(await page.evaluate(() => window.__widgetAlerts.widget.draw.drawings())).toEqual([]);
    expect(await page.evaluate(() => window.__widgetAlerts.widget.alerts.list().map(item => item.id))).toEqual([ids.alert, ids.kept]);
    await page.screenshot({ path: info.outputPath('drawing-deleted-alert-retained.png'), animations: 'disabled' });

    await page.mouse.move(point.x, point.y + 20);
    await page.mouse.move(point.x, point.y);
    await expect.poll(() => page.evaluate(() => window.__widgetAlerts.widget.alerts.hovered())).toBe(ids.alert);
    await page.keyboard.press(key);
    expect(await page.evaluate(() => window.__widgetAlerts.widget.alerts.list().map(item => item.id))).toEqual([ids.kept]);
    await page.screenshot({ path: info.outputPath('hovered-alert-deleted.png'), animations: 'disabled' });
    // The fixture must not seed a new drawing if pagehide is skipped on reload.
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('oac-alert-preview:bars') ?? '[]').length)).toBe(100);
    await page.reload();
    await page.waitForFunction(() => !!window.__widgetAlerts);
    expect(await page.evaluate(() => window.__widgetAlerts.widget.draw.drawings())).toEqual([]);
    expect(await page.evaluate(() => window.__widgetAlerts.widget.alerts.list().map(item => item.id))).toEqual([ids.kept]);
    expect(errors).toEqual([]);
  });
}

test('Delete removes a dragged alert without moving the pointer off its line', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.goto('/tests/e2e/widget-alerts-fixture.html');
  await page.waitForFunction(() => !!window.__widgetAlerts);
  const id = await page.evaluate(() => {
    const { widget } = window.__widgetAlerts;
    widget.draw.clear();
    return widget.alerts.add({ title: 'Drag then delete', source: { kind: 'price', price: 102 } }).id;
  });
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  const points = await page.evaluate(() => {
    const { widget } = window.__widgetAlerts;
    const rect = widget.root.querySelector('.oac-chart')!.getBoundingClientRect();
    return { x: Math.round(rect.left + rect.width * 0.65),
      from: Math.round(rect.top + widget.chart.priceToCoordinate(102)!),
      to: Math.round(rect.top + widget.chart.priceToCoordinate(99.5)!) };
  });
  await page.mouse.move(points.x, points.from);
  await expect.poll(() => page.evaluate(() => window.__widgetAlerts.widget.alerts.hovered())).toBe(id);
  await page.mouse.down();
  await page.mouse.move(points.x, points.to, { steps: 8 });
  await page.mouse.up();
  await expect.poll(() => page.evaluate(() => window.__widgetAlerts.widget.alerts.list()[0].source))
    .toMatchObject({ kind: 'price', price: expect.closeTo(99.5, 1) });
  await expect.poll(() => page.evaluate(() => window.__widgetAlerts.widget.alerts.hovered())).toBe(id);
  await page.screenshot({ path: info.outputPath('dragged-alert-hovered.png'), animations: 'disabled' });
  await page.keyboard.press('Delete');
  expect(await page.evaluate(() => window.__widgetAlerts.widget.alerts.list())).toEqual([]);
  expect(errors).toEqual([]);
});

for (const viewport of [{ width: 1360, height: 900 }, { width: 390, height: 844 }]) {
  test(`host form metrics keep controls aligned at ${viewport.width}px`, async ({ page }, info) => {
    await page.setViewportSize(viewport);
    await page.goto('/tests/e2e/widget-alerts-fixture.html');
    await page.waitForFunction(() => !!window.__widgetAlerts);
    await page.evaluate(narrow => {
      const { widget } = window.__widgetAlerts;
      widget.setTheme(narrow ? 'light' : 'dark');
      widget.root.style.setProperty('--oac-ctl-h', '32px');
      widget.root.style.setProperty('--oac-radius', '8px');
    }, viewport.width < 720);
    await openAlertEditor(page, viewport.width < 720);
    const editor = page.getByRole('dialog', { name: 'Create alert', exact: true });
    const geometry = await editor.evaluate(dialog => {
      const fields = ['kind', 'title', 'price', 'expiresAt'].map(key => {
        const input = dialog.querySelector<HTMLElement>(`[data-key="${key}"] input, [data-key="${key}"] select`)!;
        const box = input.getBoundingClientRect();
        return { key, left: box.left, right: box.right, height: box.height, radius: getComputedStyle(input).borderRadius };
      });
      const buttons = [...dialog.querySelectorAll<HTMLButtonElement>('button')].map(button => ({
        text: button.textContent, height: button.getBoundingClientRect().height, radius: getComputedStyle(button).borderRadius,
      }));
      const arrows = [...dialog.querySelectorAll('.oac-select')].map(wrapper => {
        const select = wrapper.querySelector('select')!.getBoundingClientRect();
        const chevron = wrapper.querySelector('.oac-chev')!.getBoundingClientRect();
        return chevron.left >= select.left && chevron.right <= select.right
          && chevron.top >= select.top && chevron.bottom <= select.bottom;
      });
      const box = dialog.getBoundingClientRect();
      return { fields, buttons, arrows, fits: box.left >= 0 && box.right <= innerWidth
        && dialog.scrollWidth <= dialog.clientWidth + 1
        && document.documentElement.scrollWidth <= innerWidth };
    });
    for (const field of geometry.fields) {
      expect(field.height, `${field.key} uses the host control height`).toBeCloseTo(32, 1);
      expect(field.radius, `${field.key} uses the host corner radius`).toBe('8px');
      expect(field.left).toBeCloseTo(geometry.fields[0].left, 1);
      expect(field.right).toBeCloseTo(geometry.fields[0].right, 1);
    }
    for (const button of geometry.buttons) {
      expect(button.height, `${button.text} uses the host control height`).toBeCloseTo(32, 1);
      expect(button.radius).toBe('8px');
    }
    expect(geometry.arrows.length).toBeGreaterThan(0);
    expect(geometry.arrows.every(Boolean)).toBe(true);
    expect(geometry.fits).toBe(true);
    await page.screenshot({ path: info.outputPath(`alert-host-metrics-${viewport.width}.png`), animations: 'disabled' });
    await editor.getByRole('button', { name: 'Cancel', exact: true }).click();
  });
}

test.describe('expiry follows the chart timezone', () => {
  test.use({ timezoneId: 'Pacific/Honolulu' });
  for (const sample of [
    { zone: 'Asia/Kolkata', defaultText: '2031-02-28T01:30', instant: '2031-07-01T03:45:00Z' },
    { zone: 'America/New_York', defaultText: '2031-02-28T15:00', instant: '2031-07-01T13:15:00Z' },
  ]) {
    test(`labels and preserves ${sample.zone} expiry through edits and reload`, async ({ page }, info) => {
      await page.clock.setFixedTime(new Date('2030-12-30T20:00:00Z'));
      await page.setViewportSize({ width: 1360, height: 900 });
      await page.goto('/tests/e2e/widget-alerts-fixture.html');
      await page.waitForFunction(() => !!window.__widgetAlerts);
      await page.evaluate(zone => window.__widgetAlerts.widget.chart.setTimezone(zone), sample.zone);
      await openAlertEditor(page);
      const editor = page.getByRole('dialog', { name: 'Create alert', exact: true });
      const expiry = editor.getByLabel(`Expires (${sample.zone})`);
      await expect(expiry).toHaveAttribute('type', 'datetime-local');
      await expect(expiry).toHaveValue(sample.defaultText);
      await editor.getByLabel('Name', { exact: true }).fill('Zoned threshold');
      await expiry.fill('2031-07-01T09:15');
      await page.evaluate(() => window.__widgetAlerts.widget.chart.setTimezone('UTC'));
      await editor.getByLabel('Condition', { exact: true }).selectOption('greaterThan');
      await expect(expiry).toHaveValue('2031-07-01T09:15');
      await page.screenshot({ path: info.outputPath('alert-pinned-expiry-zone.png'), animations: 'disabled' });
      await editor.getByRole('button', { name: 'Save', exact: true }).click();
      const expected = Date.parse(sample.instant) / 1000;
      expect(await page.evaluate(() => window.__widgetAlerts.widget.alerts.list()[0].expiresAt)).toBe(expected);
      const list = page.getByRole('dialog', { name: 'Alerts', exact: true });
      await list.getByRole('button', { name: 'Edit', exact: true }).click();
      const edit = page.getByRole('dialog', { name: 'Edit alert', exact: true });
      await expect(edit.getByLabel('Expires (UTC)')).toHaveValue(sample.instant.slice(0, 16));
      await edit.getByRole('button', { name: 'Save', exact: true }).click();
      await page.reload();
      await page.waitForFunction(() => !!window.__widgetAlerts);
      expect(await page.evaluate(() => window.__widgetAlerts.widget.alerts.list()[0].expiresAt)).toBe(expected);
      await page.evaluate(zone => window.__widgetAlerts.widget.chart.setTimezone(zone), sample.zone);
      await page.locator('.oac-topbar__alerts').click();
      await list.getByRole('button', { name: 'Edit', exact: true }).click();
      await expect(edit.getByLabel(`Expires (${sample.zone})`)).toHaveValue('2031-07-01T09:15');
      await edit.getByRole('button', { name: 'Save', exact: true }).click();
      expect(await page.evaluate(() => window.__widgetAlerts.widget.alerts.list()[0].expiresAt)).toBe(expected);
    });
  }
});

test('creates, triggers, edits and restores a once alert through the widget controls', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.goto('/tests/e2e/widget-alerts-fixture.html');
  await page.waitForFunction(() => !!window.__widgetAlerts);
  await page.locator('.oac-topbar__alerts').click();
  await page.getByRole('button', { name: 'Create alert', exact: true }).click();
  const editor = page.getByRole('dialog', { name: 'Create alert', exact: true });
  await editor.getByLabel('Name', { exact: true }).fill('Desktop threshold');
  await editor.getByLabel('Threshold', { exact: true }).fill('105');
  await editor.getByLabel('Evaluate', { exact: true }).selectOption('onTouch');
  await expect(editor.getByLabel('Enabled', { exact: true })).toBeChecked();
  await expect(editor.getByLabel('Enabled', { exact: true })).not.toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  await expect(editor).toContainText('absent from final history');
  await page.screenshot({ path: info.outputPath('alert-editor-desktop.png'), animations: 'disabled' });
  await editor.getByRole('button', { name: 'Save', exact: true }).click();
  const list = page.getByRole('dialog', { name: 'Alerts', exact: true });
  await expect(list).toContainText('Desktop threshold');
  await list.getByRole('button', { name: 'Close', exact: true }).click();
  await page.getByRole('button', { name: 'Price +5', exact: true }).click();
  expect(await page.evaluate(() => window.__widgetAlerts.fired)).toEqual([]);
  await page.getByRole('button', { name: 'Price +5', exact: true }).click();
  await expect(page.locator('.oac-toast__msg')).toContainText('Desktop threshold');
  await page.locator('.oac-topbar__alerts').click();
  await expect(list).toContainText('Triggered');
  await list.getByRole('button', { name: 'Edit', exact: true }).click();
  await page.getByRole('dialog', { name: 'Edit alert', exact: true }).getByLabel('Name', { exact: true }).fill('Fired threshold');
  await page.getByRole('dialog', { name: 'Edit alert', exact: true }).getByRole('button', { name: 'Save', exact: true }).click();
  await expect(list).toContainText('Triggered');
  await page.reload();
  await page.waitForFunction(() => !!window.__widgetAlerts);
  expect(await page.evaluate(() => window.__widgetAlerts.fired)).toEqual([]);
  await expect(page.locator('.oac-toast__msg')).toHaveCount(0);
  await page.locator('.oac-topbar__alerts').click();
  await expect(list).toContainText('Fired threshold');
  await expect(list).toContainText('Triggered');
  await page.screenshot({ path: info.outputPath('alert-list-desktop.png'), animations: 'disabled' });
  expect(errors).toEqual([]);
});

test('keeps the editor usable on a narrow screen and selects a missing OI plot explicitly', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/tests/e2e/widget-alerts-fixture.html');
  await page.waitForFunction(() => !!window.__widgetAlerts);
  await page.locator('[data-mobile-action="more"]').click();
  await page.locator('[data-mobile-action="alerts"]').click();
  await page.getByRole('button', { name: 'Create alert', exact: true }).click();
  const editor = page.getByRole('dialog', { name: 'Create alert', exact: true });
  await editor.getByLabel('Source', { exact: true }).focus();
  await editor.getByLabel('Source', { exact: true }).selectOption('indicator');
  await expect(editor.getByLabel('Source', { exact: true })).toBeFocused();
  const instanceId = await page.evaluate(() => window.__widgetAlerts.widget.chart.indicators().find(item => item.indicatorId === 'open-interest')!.id);
  await editor.getByLabel('Study', { exact: true }).selectOption(instanceId);
  await expect(editor.getByLabel('Threshold', { exact: true })).toHaveValue('');
  await expect(editor).toContainText('current plot value is unavailable');
  await editor.getByLabel('Threshold', { exact: true }).fill('0');
  await editor.getByLabel('Name', { exact: true }).fill('OI zero reading');
  const bounds = await editor.boundingBox();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  expect(await editor.evaluate(node => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
  await page.screenshot({ path: info.outputPath('alert-editor-narrow.png'), animations: 'disabled' });
  await editor.getByRole('button', { name: 'Save', exact: true }).click();
  const list = page.getByRole('dialog', { name: 'Alerts', exact: true });
  await expect(list).toContainText('OI zero reading');
  await expect(list).toContainText('Plot value is unavailable');
  await page.screenshot({ path: info.outputPath('alert-list-narrow.png'), animations: 'disabled' });
  await list.getByRole('button', { name: 'Delete', exact: true }).click();
  await expect(list).toContainText('No alerts');
  expect(errors).toEqual([]);
});

test('rejects a blank draft after blur and creates a drawing alert from a real context menu', async ({ page }, info) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.goto('/tests/e2e/widget-alerts-fixture.html');
  await page.waitForFunction(() => !!window.__widgetAlerts);
  await page.locator('.oac-topbar__alerts').click();
  await page.getByRole('button', { name: 'Create alert', exact: true }).click();
  const editor = page.getByRole('dialog', { name: 'Create alert', exact: true });
  await editor.getByLabel('Threshold', { exact: true }).fill('');
  await editor.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(editor).toBeVisible();
  await expect(editor.getByLabel('Threshold', { exact: true })).toHaveValue('');
  await expect(editor.locator('.oac-alert-error')).toContainText('finite');
  await editor.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('dialog', { name: 'Alerts', exact: true }).getByRole('button', { name: 'Close', exact: true }).click();
  const point = await page.evaluate(() => {
    const { widget, bars } = window.__widgetAlerts;
    const drawing = widget.draw.drawings()[0];
    widget.draw.update(drawing.id, { points: [{ time: bars[80].time, price: 102 }] });
    const rect = widget.root.querySelector('.oac-chart')!.getBoundingClientRect();
    return { x: rect.left + widget.chart.timeToCoordinate(bars[80].time)!, y: rect.top + widget.chart.priceToCoordinate(102)! };
  });
  await page.mouse.click(point.x, point.y, { button: 'right' });
  await page.getByRole('menuitem', { name: 'Create drawing alert...' }).click();
  await expect(editor.getByLabel('Source', { exact: true })).toHaveValue('drawing');
  await expect(editor.getByLabel('Level', { exact: true })).toHaveValue('line');
  await editor.getByLabel('Name', { exact: true }).fill('Drawing close');
  await page.screenshot({ path: info.outputPath('alert-drawing-editor.png'), animations: 'disabled' });
  await editor.getByRole('button', { name: 'Save', exact: true }).click();
  await page.getByRole('button', { name: 'Price +5', exact: true }).click();
  expect(await page.evaluate(() => window.__widgetAlerts.fired)).toEqual([]);
  await page.getByRole('button', { name: 'Close bar', exact: true }).click();
  await expect(page.locator('.oac-toast__msg')).toContainText('Drawing close');
});
