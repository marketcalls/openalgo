import { expect, test, type Page } from '@playwright/test';
import type { Widget } from '../../src/widget/widget';
import type { AccountManager, FakeBroker, OrderEngine } from '../../src/trade/index';

declare global {
  interface Window {
    __account: { widget: Widget; broker: FakeBroker; accounts: AccountManager; engine: OrderEngine; tick(seconds: number): void };
  }
}

test.afterEach(async ({ page }, info) => {
  if (info.status !== info.expectedStatus) {
    await page.screenshot({ path: info.outputPath('failure.png'), animations: 'disabled' });
  }
});

async function open(page: Page, query = ''): Promise<string[]> {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1360, height: 820 });
  await page.goto(`/tests/e2e/widget-account-fixture.html${query}`);
  await page.waitForFunction(() => !!window.__account);
  return errors;
}

/** The status line and the account summary inside it, fully on screen and not overlapping the time zone. */
async function layout(page: Page) {
  return page.evaluate(() => {
    const line = document.querySelector('.oac-statusline')!.getBoundingClientRect();
    const account = document.querySelector('.oac-statusline .oac-account')!.getBoundingClientRect();
    const tz = document.querySelector('.oac-statusline__tz')!.getBoundingClientRect();
    return { line: { top: line.top, bottom: line.bottom, right: line.right }, account: { left: account.left, right: account.right, top: account.top, bottom: account.bottom }, tzLeft: tz.left, width: innerWidth };
  });
}

test('shows the selected sandbox account in the status line and follows the ledger', async ({ page }, info) => {
  const errors = await open(page);
  const summary = page.locator('.oac-statusline .oac-account');
  await expect(summary).toHaveAttribute('data-status', 'ready');
  await expect(summary.locator('.oac-account__name')).toHaveText('Sandbox equity');
  await expect(summary.locator('.oac-account__tag')).toHaveText('Analyzer');
  await expect(summary.locator('.oac-account__equity b')).toHaveText('₹5,00,000.00');
  await expect(summary.locator('.oac-account__available b')).toHaveText('₹5,00,000.00');
  const box = await layout(page);
  expect(box.account.top).toBeGreaterThanOrEqual(box.line.top);
  expect(box.account.bottom).toBeLessThanOrEqual(box.line.bottom + 0.5);
  expect(box.account.right).toBeLessThanOrEqual(box.tzLeft + 0.5);
  expect(box.account.left).toBeGreaterThan(0);

  const placed = await page.evaluate(() => window.__account.engine.placeOrder({ symbol: 'ACCT', side: 'BUY', type: 'MARKET', qty: 100, clientToken: 'e2e-1' }));
  expect(placed.ok).toBe(true);
  await expect(summary.locator('.oac-account__used b')).not.toHaveText('₹0.00');
  const used = await summary.locator('.oac-account__used b').textContent();
  expect(used).toMatch(/^₹[\d,]+\.\d\d$/);
  await page.screenshot({ path: info.outputPath('account-ready.png'), animations: 'disabled' });
  await summary.screenshot({ path: info.outputPath('account-summary.png'), animations: 'disabled' });
  expect(errors).toEqual([]);
});

test('switches account from its menu, which lists only the sandbox ledger', async ({ page }, info) => {
  const errors = await open(page);
  const summary = page.locator('.oac-statusline .oac-account');
  await expect(summary).toHaveAttribute('data-status', 'ready');
  await summary.locator('.oac-account__pick').click();
  const menu = page.locator('.oac-menu[aria-label="Accounts"]');
  await expect(menu).toBeVisible();
  await expect(menu.locator('.oac-menu__row')).toHaveCount(2);
  await expect(menu).not.toContainText('Live trading');
  const bounds = await menu.boundingBox();
  const viewport = page.viewportSize()!;
  expect(bounds!.y).toBeGreaterThanOrEqual(0);
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(viewport.height);
  await page.screenshot({ path: info.outputPath('account-menu.png'), animations: 'disabled' });
  await menu.locator('.oac-menu__row', { hasText: 'Sandbox derivatives' }).click();
  await expect(summary.locator('.oac-account__name')).toHaveText('Sandbox derivatives');
  await expect(summary.locator('.oac-account__equity b')).toHaveText('₹15,00,000.00');
  expect(await page.evaluate(() => window.__account.accounts.selectedAccount())).toBe('SBX-FO');
  // An order after the switch goes to the account now shown.
  await page.evaluate(() => window.__account.engine.placeOrder({ symbol: 'ACCT', side: 'SELL', type: 'MARKET', qty: 10, clientToken: 'e2e-2' }));
  expect(await page.evaluate(() => window.__account.broker.accountPositions('SBX-FO').map(p => p.netQty))).toEqual([-10]);
  expect(await page.evaluate(() => window.__account.broker.accountPositions('SBX-EQ'))).toEqual([]);
  expect(errors).toEqual([]);
});

test('keeps the last figures, marked stale, when the connection drops', async ({ page }, info) => {
  const errors = await open(page);
  const summary = page.locator('.oac-statusline .oac-account');
  await expect(summary).toHaveAttribute('data-status', 'ready');
  await page.evaluate(() => window.__account.broker.disconnect());
  await expect(summary).toHaveAttribute('data-status', 'stale');
  await expect(summary.locator('.oac-account__state')).toHaveText('Stale');
  await expect(summary.locator('.oac-account__equity b')).toHaveText('₹5,00,000.00');
  await summary.screenshot({ path: info.outputPath('account-stale.png'), animations: 'disabled' });
  await page.evaluate(async () => { window.__account.broker.reconnect(); window.__account.tick(5); await window.__account.accounts.reconnect(); });
  await expect(summary).toHaveAttribute('data-status', 'ready');
  await expect(summary.locator('.oac-account__state')).toBeHidden();
  expect(errors).toEqual([]);
});

test('stays reachable in a narrow status line, keeping the account and its ledger in view', async ({ page }, info) => {
  const errors = await open(page);
  await page.setViewportSize({ width: 760, height: 700 });
  const summary = page.locator('.oac-statusline .oac-account');
  await expect(summary).toHaveAttribute('data-status', 'ready');
  // Put a bar under the pointer so the status line carries its full reading.
  const chart = await page.locator('.oac-chart').boundingBox();
  await page.mouse.move(chart!.x + chart!.width * 0.6, chart!.y + chart!.height * 0.5);
  await expect(page.locator('.oac-statusline__o')).toBeVisible();
  const pick = summary.locator('.oac-account__pick');
  await expect(pick).toBeVisible();
  await expect(summary.locator('.oac-account__tag')).toBeVisible();
  const line = (await page.locator('.oac-statusline').boundingBox())!;
  for (const box of [await pick.boundingBox(), await summary.locator('.oac-account__tag').boundingBox()]) {
    expect(box!.x).toBeGreaterThanOrEqual(line.x);
    expect(box!.x + box!.width).toBeLessThanOrEqual(line.x + line.width + 0.5);
  }
  // Nothing in the row overlaps: each item starts where the one before it ends.
  const overlaps = await page.evaluate(() => {
    const items = [...document.querySelectorAll('.oac-statusline > *, .oac-statusline .oac-account > *')]
      .filter(node => (node as HTMLElement).offsetParent !== null && node.getBoundingClientRect().width > 0)
      .map(node => ({ name: node.className, rect: node.getBoundingClientRect() }));
    const hits: string[] = [];
    for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) {
      const a = items[i].rect;
      const b = items[j].rect;
      const nested = items[i].name.includes('oac-account') && !items[i].name.includes('__') || items[j].name.includes('oac-account') && !items[j].name.includes('__');
      if (!nested && a.left < b.right - 0.5 && b.left < a.right - 0.5) hits.push(`${items[i].name} / ${items[j].name}`);
    }
    return hits;
  });
  expect(overlaps).toEqual([]);
  await expect(summary.locator('.oac-account__used')).toBeHidden();
  await expect(pick).toHaveAttribute('title', /Equity ₹5,00,000\.00/);
  await page.locator('.oac-statusline').screenshot({ path: info.outputPath('account-narrow.png'), animations: 'disabled' });
  expect(errors).toEqual([]);
});

test('renders disabled, with the reason, when the provider declares no accounts', async ({ page }, info) => {
  const errors = await open(page, '?accounts=none&theme=light');
  const summary = page.locator('.oac-statusline .oac-account');
  await expect(summary).toHaveAttribute('aria-disabled', 'true');
  await expect(summary).toHaveAttribute('data-status', 'unsupported');
  await expect(summary.locator('.oac-account__state')).toHaveText('Account data is not declared by this provider');
  await expect(summary.locator('.oac-account__pick')).toBeDisabled();
  await expect(summary.locator('.oac-account__equity')).toBeHidden();
  const result = await page.evaluate(() => window.__account.engine.placeOrder({ symbol: 'ACCT', side: 'BUY', type: 'MARKET', qty: 1 }));
  expect(result).toMatchObject({ ok: false, intent: 'BLOCKED', reason: 'Account data is not declared by this provider' });
  await page.screenshot({ path: info.outputPath('account-unsupported-light.png'), animations: 'disabled' });
  await summary.screenshot({ path: info.outputPath('account-unsupported-summary.png'), animations: 'disabled' });
  expect(errors).toEqual([]);
});
