import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { createWidget, mountAccountSummary, type Widget, type WidgetOptions } from '../src/widget/index';
import { AccountManager, type AccountState, type AccountStateSource } from '../src/trade/account';
import { FakeBroker, type FakeAccountSeed } from '../src/trade/fake-broker';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);
const widgets: Widget[] = [];
afterEach(() => { for (const widget of widgets.splice(0)) widget.destroy(); });

const SEEDS: FakeAccountSeed[] = [
  { id: 'SBX-1', name: 'Sandbox one', mode: 'analyzer', currency: 'INR', balance: 100_000 },
  { id: 'SBX-2', name: 'Sandbox two', mode: 'analyzer', currency: 'INR', balance: 250_000 },
  { id: 'LIVE-1', name: 'Live', mode: 'live', currency: 'INR', balance: 9_000_000 },
];

function make(options: WidgetOptions = {}) {
  const document = fakeWidgetDocument();
  const widget = createWidget(fakeContainer(document) as unknown as HTMLElement, {
    document: document as unknown as Document, mobile: 'never', symbol: 'SYN', exchange: 'NSE', locale: 'en-US',
    raf: { schedule: callback => { callback(); return 1; }, cancel: () => {} }, ...options,
  });
  widgets.push(widget);
  return widget;
}
const root = (widget: Widget) => widget.root as unknown as FakeElement;
const summary = (widget: Widget) => root(widget).querySelector('.oac-account');

describe('widget account summary', () => {
  it('renders nothing when the host supplies no account source', () => {
    expect(summary(make())).toBeNull();
  });

  it('renders disabled, with the reason visible, when the provider declares no accounts', () => {
    const widget = make({ account: new AccountManager({ feed: new FakeBroker(), mode: 'analyzer' }) });
    const el = summary(widget)!;
    expect(el).not.toBeNull();
    expect(el.getAttribute('aria-disabled')).toBe('true');
    expect(el.classList.contains('is-disabled')).toBe(true);
    expect(el.textContent).toContain('Account data is not declared by this provider');
    const pick = el.querySelector('.oac-account__pick')!;
    expect(pick.disabled).toBe(true);
    // Not "Account: Account" while none is chosen.
    expect(pick.getAttribute('aria-label')).toBe('Account');
    // Inside the status line, beside the timezone rather than on the canvas.
    expect(root(widget).querySelector('.oac-statusline .oac-account')).toBe(el);
  });

  it('shows the selected account figures and follows the provider as they change', async () => {
    const broker = new FakeBroker({ accounts: SEEDS, now: () => 1 });
    const accounts = new AccountManager({ feed: broker, mode: 'analyzer' });
    const widget = make({ account: accounts });
    expect(summary(widget)!.dataset.status).toBe('idle');
    await accounts.refresh();
    const el = summary(widget)!;
    expect(el.dataset.status).toBe('ready');
    expect(el.getAttribute('aria-disabled')).toBeNull();
    expect(el.querySelector('.oac-account__name')!.textContent).toBe('Sandbox one');
    expect(el.querySelector('.oac-account__tag')!.textContent).toBe('Analyzer');
    expect(el.querySelector('.oac-account__equity b')!.textContent).toBe('₹100,000.00');
    expect(el.querySelector('.oac-account__available b')!.textContent).toBe('₹100,000.00');
    broker.setMark('SYN', 100);
    await broker.place({ symbol: 'SYN', side: 'BUY', type: 'MARKET', qty: 10, mode: 'analyzer', account: 'SBX-1' });
    expect(el.querySelector('.oac-account__used b')!.textContent).toBe('₹1,000.00');
    expect(el.querySelector('.oac-account__available b')!.textContent).toBe('₹99,000.00');
    broker.disconnect();
    expect(el.dataset.status).toBe('stale');
    expect(el.querySelector('.oac-account__state')!.textContent).toContain('Stale');
  });

  it('switches account from its menu, listing only accounts in the widget mode', async () => {
    const accounts = new AccountManager({ feed: new FakeBroker({ accounts: SEEDS, now: () => 1 }), mode: 'analyzer' });
    await accounts.refresh();
    const widget = make({ account: accounts });
    const select = vi.spyOn(accounts, 'select');
    (summary(widget)!.querySelector('.oac-account__pick') as FakeElement).click();
    const rows = root(widget).querySelectorAll('.oac-menu .oac-menu__row');
    expect(rows.map(row => row.textContent)).toEqual(['Sandbox oneSBX-1', 'Sandbox twoSBX-2']);
    expect(rows[0].getAttribute('aria-checked')).toBe('true');
    rows[1].click();
    expect(select).toHaveBeenCalledWith('SBX-2');
    await select.mock.results[0].value;
    expect(summary(widget)!.querySelector('.oac-account__name')!.textContent).toBe('Sandbox two');
    expect(summary(widget)!.querySelector('.oac-account__equity b')!.textContent).toBe('₹250,000.00');
  });

  it('reports a failed switch and releases its subscription on destroy', async () => {
    let state: AccountState = { status: 'ready', mode: 'live', accounts: [{ id: 'A', mode: 'live' }, { id: 'B', mode: 'live' }], selectedId: 'A',
      snapshot: { accountId: 'A', mode: 'live', asOf: 1, equity: 5, currency: 'XYZ-not-a-code' }, generation: 1 };
    const unsubscribe = vi.fn();
    const source: AccountStateSource = {
      getState: () => state,
      subscribe: () => unsubscribe,
      select: async () => ({ ok: false, reason: 'The provider refused the switch' }),
    };
    const widget = make({ account: source });
    const el = summary(widget)!;
    // An unknown currency code falls back to plain figures rather than failing the row.
    expect(el.querySelector('.oac-account__equity b')!.textContent).toBe('5.00');
    expect(el.querySelector('.oac-account__tag')).toBeNull();
    (el.querySelector('.oac-account__pick') as FakeElement).click();
    root(widget).querySelectorAll('.oac-menu .oac-menu__row')[1].click();
    await Promise.resolve(); await Promise.resolve();
    expect(root(widget).textContent).toContain('Could not switch account: The provider refused the switch');
    state = { ...state, status: 'error', reason: 'Snapshot failed', snapshot: null };
    widget.destroy();
    expect(unsubscribe).toHaveBeenCalledTimes(1);
  });

  it('is left out with the status line, and can be mounted by a host on its own', async () => {
    const accounts = new AccountManager({ feed: new FakeBroker({ accounts: SEEDS, now: () => 1 }), mode: 'analyzer' });
    const widget = make({ account: accounts, statusline: false });
    expect(summary(widget)).toBeNull();
    const host = (widget.root as unknown as FakeElement).ownerDocument!.createElement('div') as FakeElement;
    const handle = mountAccountSummary(widget.context, host as unknown as HTMLElement, { source: accounts });
    await accounts.refresh();
    expect(host.querySelector('.oac-account__name')!.textContent).toBe('Sandbox one');
    handle.destroy();
    expect(host.querySelector('.oac-account')).toBeNull();
  });
});
