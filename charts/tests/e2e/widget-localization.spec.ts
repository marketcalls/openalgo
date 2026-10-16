import { expect, test } from '@playwright/test';

test('translated desktop controls, late dialogs and keyboard dismissal remain usable', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1100, height: 700 });
  await page.goto('/tests/e2e/widget-localization-fixture.html');
  await expect(page.getByRole('toolbar', { name: 'Herramientas del grafico' })).toBeVisible();
  await expect(page.getByRole('radio', { name: 'Intervalo 5m', exact: true })).toHaveText('5m');
  await expect(page.locator('.oac-sym__input')).toHaveValue('OBJECTS');
  await page.getByRole('button', { name: 'Configuracion del grafico', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Configuracion del grafico', exact: true });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('tab', { name: 'Apariencia' }).click();
  await expect(dialog.getByRole('button', { name: 'Cancelar', exact: true })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Aceptar', exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('translated-settings.png') });
  await dialog.getByRole('button', { name: 'Cerrar', exact: true }).focus();
  await page.keyboard.press('Enter');
  await expect(dialog).toBeHidden();
  await page.getByRole('button', { name: 'Cambiar al tema claro', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Cambiar al tema oscuro', exact: true })).toHaveAttribute('data-theme', 'light');
  await page.getByRole('button', { name: 'Objetos', exact: true }).click();
  await expect(page.getByRole('searchbox', { name: 'Buscar objetos' })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.evaluate(() => (window as any).fixture.widget.context.toast('Chart settings'));
  await expect(page.locator('.oac-toast__msg')).toHaveText('Chart settings');
  await expect(page.getByRole('button', { name: 'Descartar' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('translated mobile settings fit the viewport and retain their close action', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/tests/e2e/widget-localization-fixture.html?mobile');
  await expect(page.getByRole('navigation', { name: 'Controles del grafico' })).toBeVisible();
  await page.locator('[data-mobile-action="more"]').click();
  await expect(page.locator('.oac-mobile-sheet')).toHaveAttribute('aria-label', 'Mas opciones');
  await page.locator('.oac-mobile-sheet').getByRole('button', { name: 'Configuracion del grafico' }).click();
  const dialog = page.getByRole('dialog', { name: 'Configuracion del grafico' });
  await expect(dialog).toBeVisible();
  const close = dialog.getByRole('button', { name: 'Cerrar', exact: true });
  const box = await close.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  expect(box!.y + box!.height).toBeLessThanOrEqual(844);
  await page.screenshot({ path: info.outputPath('translated-mobile-settings.png') });
  await close.click();
  await expect(dialog).toBeHidden();
  expect(errors).toEqual([]);
});

test('order menus recheck changed account capabilities and replay before invoking the host', async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 700 });
  await page.goto('/tests/e2e/widget-localization-fixture.html');
  await expect(page.getByRole('toolbar', { name: 'Herramientas del grafico' })).toBeVisible();
  await page.evaluate(() => (window as any).fixture.openMenu());
  await expect(page.locator('[data-act="order-buy-market"]')).toHaveCount(0);
  const buy = page.locator('[data-act="order-buy-limit"]');
  await expect(buy).toBeVisible();
  await page.evaluate(() => (window as any).fixture.setCapabilities({ place: false }));
  await buy.click();
  await expect(page.locator('.oac-statusline__msg')).toContainText('Order entry is unavailable');
  expect(await page.evaluate(() => (window as any).fixture.orders)).toEqual([]);
  await page.evaluate(() => (window as any).fixture.openMenu());
  await expect(page.locator('[data-act="trading-unavailable"]')).toHaveAttribute('aria-disabled', 'true');
  await expect(page.locator('[data-act="trading-unavailable"]')).toContainText('Order entry is unavailable');
  await page.keyboard.press('Escape');
  await page.evaluate(() => {
    const fixture = (window as any).fixture;
    fixture.setCapabilities({ orderTypes: ['LIMIT'] });
    fixture.openMenu();
    fixture.setLocked(true);
  });
  await buy.click();
  await expect(page.locator('.oac-statusline__msg')).toContainText('locked by the host');
  expect(await page.evaluate(() => (window as any).fixture.orders)).toEqual([]);
  await page.evaluate(() => {
    const fixture = (window as any).fixture;
    fixture.setLocked(false);
    fixture.openMenu();
    fixture.startReplay();
  });
  await buy.click();
  await expect(page.locator('.oac-statusline__msg')).toContainText('locked during replay');
  expect(await page.evaluate(() => (window as any).fixture.orders)).toEqual([]);
});
