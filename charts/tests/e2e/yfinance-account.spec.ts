import { test, expect } from '@playwright/test';

const PAGE = '/examples/yfinance/index.html?test=1';
const PROBE = '/api/history?symbol=AAPL&interval=1d&period=1mo';
let serverUp: boolean | null = null;

test.beforeEach(async ({ request, page }) => {
  if (serverUp === null) serverUp = await request.get(PROBE).then(response => response.ok(), () => false);
  test.skip(!serverUp, 'The reference fixture server is unavailable');
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto(PAGE);
  await page.waitForFunction(() => Boolean((window as any).__oac?.app?.currentBars?.length));
});

test.afterEach(async ({ page }, info) => {
  if (info.status !== info.expectedStatus) await page.screenshot({ path: info.outputPath('failure.png'), animations: 'disabled' });
});

test('the sandbox broker previews, places, closes part, reverses and closes through the provider', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.locator('#account').click();
  const panel = page.locator('#acctpanel');
  await expect(panel).toBeVisible();
  const summary = panel.locator('.oac-account');
  await expect(summary).toHaveAttribute('data-status', 'ready');
  await expect(summary.locator('.oac-account__name')).toHaveText('Sandbox cash');
  await expect(summary.locator('.oac-account__tag')).toHaveText('Analyzer');
  await expect(panel.locator('.acct-position')).toHaveText('No open position in AAPL');
  await expect(panel.locator('#acct-close')).toBeDisabled();

  // Nothing can be placed until this exact ticket has been previewed.
  const place = panel.locator('#acct-place');
  await expect(place).toBeDisabled();
  await panel.locator('#acct-preview').click();
  await expect(panel.locator('.acct-preview')).toContainText('Margin');
  await expect(place).toBeEnabled();
  await panel.getByRole('spinbutton', { name: 'Quantity', exact: true }).fill('12');
  await expect(place).toBeDisabled();
  await panel.locator('#acct-preview').click();
  await expect(place).toBeEnabled();
  await page.screenshot({ path: info.outputPath('account-preview.png'), animations: 'disabled' });
  await place.click();
  await expect(panel.locator('.acct-position')).toContainText('Long 12 @');
  await expect(panel.locator('.acct-msg')).toContainText('filled');
  await expect(summary.locator('.oac-account__used b')).not.toHaveText('0.00');

  await panel.getByRole('spinbutton', { name: 'Quantity to close', exact: true }).fill('5');
  await panel.locator('#acct-close-part').click();
  await expect(panel.locator('.acct-position')).toContainText('Long 7 @');
  await panel.locator('#acct-reverse').click();
  await expect(panel.locator('.acct-position')).toContainText('Short 7 @');
  await expect(panel.locator('.acct-fills li')).toHaveCount(3);
  await expect(panel.locator('.acct-fills li').first()).toContainText('SELL 14');
  await page.screenshot({ path: info.outputPath('account-reversed.png'), animations: 'disabled' });
  // A dropped connection and a reconnect settle the engine from the provider's
  // history, so the commands still work afterwards.
  await panel.locator('#acct-connection').click();
  await expect(summary).toHaveAttribute('data-status', 'stale');
  await expect(panel.locator('#acct-close')).toBeDisabled();
  await panel.locator('#acct-connection').click();
  await expect(panel.locator('.acct-msg')).toHaveText('Reconnected to the simulated provider');
  await expect(summary).toHaveAttribute('data-status', 'ready');
  await expect(panel.locator('.acct-position')).toContainText('Short 7 @');
  await page.screenshot({ path: info.outputPath('account-reconnected.png'), animations: 'disabled' });
  await panel.locator('#acct-close').click();
  await expect(panel.locator('.acct-position')).toHaveText('No open position in AAPL');
  // The page's own simulated orders are separate and untouched.
  expect(await page.evaluate(() => (window as any).__oac.app.position)).toBeNull();
  expect(errors).toEqual([]);
});

test('the sandbox broker refuses a duration it cannot take and switches account without carrying figures over', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.locator('#account').click();
  const panel = page.locator('#acctpanel');
  const summary = panel.locator('.oac-account');
  await expect(summary).toHaveAttribute('data-status', 'ready');
  // A GTD ticket with no expiry is refused before anything is sent.
  await panel.getByRole('group', { name: 'Duration' }).getByRole('button', { name: 'GTD', exact: true }).click();
  await expect(panel.getByLabel('Expiry')).toBeVisible();
  await panel.locator('#acct-preview').click();
  await expect(panel.locator('.acct-preview')).toHaveText('A GTD order needs an expiry');
  await expect(panel.locator('#acct-place')).toBeDisabled();
  await panel.getByRole('group', { name: 'Duration' }).getByRole('button', { name: 'IOC', exact: true }).click();

  await summary.locator('.oac-account__pick').click();
  const menu = page.locator('.oac-menu[aria-label="Accounts"]');
  await expect(menu.locator('.oac-menu__row')).toHaveCount(2);
  await expect(menu).not.toContainText('Live');
  await page.screenshot({ path: info.outputPath('account-menu.png'), animations: 'disabled' });
  await menu.locator('.oac-menu__row', { hasText: 'Sandbox margin' }).click();
  await expect(summary.locator('.oac-account__name')).toHaveText('Sandbox margin');
  await expect(summary.locator('.oac-account__equity b')).toHaveText('250,000.00');

  await panel.locator('#acct-connection').click();
  await expect(summary).toHaveAttribute('data-status', 'stale');
  await expect(summary.locator('.oac-account__state')).toHaveText('Stale');
  await page.screenshot({ path: info.outputPath('account-stale.png'), animations: 'disabled' });
  await panel.locator('#acct-connection').click();
  await expect(summary).toHaveAttribute('data-status', 'ready');
  await expect(panel.locator('.acct-msg')).toHaveText('Reconnected to the simulated provider');
  await page.getByRole('button', { name: 'Light theme', exact: true }).click();
  await expect(panel).toBeVisible();
  await page.screenshot({ path: info.outputPath('account-light.png'), animations: 'disabled' });
  await page.keyboard.press('Escape');
  await expect(panel).toBeHidden();
  expect(errors).toEqual([]);
});

test('a bracket placed from the panel keeps its legs live across two drops and reconnects', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.locator('#account').click();
  const panel = page.locator('#acctpanel');
  const summary = panel.locator('.oac-account');
  await expect(summary).toHaveAttribute('data-status', 'ready');
  await panel.locator('#acct-bracket').click();
  await expect(panel.locator('.acct-msg')).toHaveText('Bracket placed: stop and target are linked by the provider');
  await expect(panel.locator('.acct-position')).toContainText('Long 10 @');

  // The engine the panel drives, read through the same module instance.
  const rows = () => page.evaluate(async () => {
    const path = '/examples/yfinance/src/account.js';
    const { engine } = (await import(path)).accountDesk();
    const legs = engine.bracketLegs('c1') ?? {};
    const row = (id: string | undefined) => id === undefined ? null : [engine.state(id), engine.intentState(id), engine.brokerStatus(id)];
    return { kind: engine.orderKind('c1'), entry: row('c1'), stop: row(legs.stopLoss), target: row(legs.takeProfit) };
  });
  expect(await rows()).toEqual({
    kind: 'bracket', entry: ['filled', 'SETTLED', 'filled'],
    stop: ['working', 'ACKNOWLEDGED', 'working'], target: ['working', 'ACKNOWLEDGED', 'working'],
  });
  for (let cycle = 0; cycle < 2; cycle++) {
    await panel.locator('#acct-connection').click();
    await expect(summary).toHaveAttribute('data-status', 'stale');
    await panel.locator('#acct-connection').click();
    await expect(panel.locator('.acct-msg')).toHaveText('Reconnected to the simulated provider');
    await expect(summary).toHaveAttribute('data-status', 'ready');
    expect(await rows()).toEqual({
      kind: 'bracket', entry: ['filled', 'SETTLED', 'filled'],
      stop: ['working', 'ACKNOWLEDGED', 'working'], target: ['working', 'ACKNOWLEDGED', 'working'],
    });
  }
  await expect(panel.locator('.acct-position')).toContainText('Long 10 @');
  await page.screenshot({ path: info.outputPath('account-bracket-reconnected.png'), animations: 'disabled' });
  expect(errors).toEqual([]);
});
