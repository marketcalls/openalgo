import { afterEach, describe, expect, it } from 'vitest';
import { ACCOUNT_SUMMARY_EXAMPLE, SANDBOX_BROKER_EXAMPLE } from '../website/components/account-examples';
import { AccountManager, FakeBroker, OrderEngine, type FakeBrokerOptions } from '../src/trade/index';
import { generateBars } from '../src/index';

/** Just enough of an element for the examples' own controls. */
class FakeNode {
  public readonly children: FakeNode[] = [];
  public readonly style: Record<string, string> = { cssText: '' };
  public textContent = '';
  public type = '';
  public onclick: (() => Promise<void>) | null = null;
  public constructor(public readonly tag: string) {}
  public append(...nodes: FakeNode[]): void { this.children.push(...nodes); }
  public appendChild(node: FakeNode): FakeNode { this.children.push(node); return node; }
  public addEventListener(): void {}
  public all(): FakeNode[] { return [this, ...this.children.flatMap(child => child.all())]; }
}

const realDocument = (globalThis as { document?: unknown }).document;
afterEach(() => { (globalThis as { document?: unknown }).document = realDocument; });
const settle = async () => { for (let i = 0; i < 5; i++) await new Promise(done => setTimeout(done, 0)); };

/** Run an example the way the docs page does, with the real trade classes and a stand-in widget. */
async function run(code: string) {
  const brokers: FakeBroker[] = [];
  class Recorded extends FakeBroker {
    public constructor(options?: FakeBrokerOptions) { super(options); brokers.push(this); }
  }
  const lib = {
    FakeBroker: Recorded, AccountManager, OrderEngine, generateBars,
    createWidget: () => ({ series: { setData: () => {} }, destroy: () => {} }),
  };
  (globalThis as { document?: unknown }).document = { createElement: (tag: string) => new FakeNode(tag) };
  const el = new FakeNode('div');
  new Function('el', 'lib', code)(el, lib);
  await settle();
  const nodes = el.all();
  const click = async (label: string) => {
    const button = nodes.find(node => node.tag === 'button' && node.textContent === label);
    if (button?.onclick == null) throw new Error(`no button ${label}`);
    await button.onclick();
    await settle();
    return nodes.find(node => node.tag === 'span')!.textContent;
  };
  return { broker: brokers[0], click, buttons: nodes.filter(node => node.tag === 'button').map(node => node.textContent) };
}

describe('website sandbox broker example', () => {
  it('drops and restores the connection without leaving a command stuck', async () => {
    const { broker, click } = await run(SANDBOX_BROKER_EXAMPLE);
    expect(await click('Buy 50')).toBe('Buy 50: filled');
    await click('Drop connection');
    // Nothing left while the connection was down, so the close is refused outright, not held.
    expect(await click('Close 20')).toBe('Close 20 refused: FakeBroker: disconnected; nothing was sent');
    expect(await click('Reconnect')).toBe('Reconnect: reconnected');
    expect(await click('Close 20')).toBe('Close 20: filled');
    expect(broker.accountPositions('SBX-CASH')).toMatchObject([{ symbol: 'NOVA', netQty: 30 }]);
  });

  it('settles a close whose answer the drop lost, and releases one that never arrived, on reconnect', async () => {
    const { broker, click } = await run(SANDBOX_BROKER_EXAMPLE);
    await click('Buy 50');
    // The broker applies this close and the answer is lost with the connection.
    broker.muteOrderUpdates(true);
    broker.failNext('close', 'lost-response');
    expect(await click('Close 20')).toMatch(/may have reached the broker/);
    broker.muteOrderUpdates(false);
    await click('Drop connection');
    await click('Reconnect');
    expect(broker.accountPositions('SBX-CASH')).toMatchObject([{ symbol: 'NOVA', netQty: 30 }]);
    // This reverse is lost before the broker applies it.
    broker.failNext('reverse', 'timeout');
    expect(await click('Reverse')).toMatch(/may have reached the broker/);
    expect(await click('Close all')).toMatch(/unresolved/);
    await click('Drop connection');
    await click('Reconnect');
    expect(await click('Reverse')).toBe('Reverse: filled');
    expect(broker.accountPositions('SBX-CASH')).toMatchObject([{ symbol: 'NOVA', netQty: -30 }]);
    expect(await click('Close all')).toBe('Close all: filled');
    expect(broker.accountPositions('SBX-CASH')).toEqual([]);
  });
});

describe('website account summary example', () => {
  it('sends no order until the reader asks for one', async () => {
    const { broker, click, buttons } = await run(ACCOUNT_SUMMARY_EXAMPLE);
    // Loaded and settled: the accounts are listed and nothing has been sent.
    expect(broker.orders()).toEqual([]);
    expect(broker.accountPositions('SBX-CASH')).toEqual([]);
    expect(buttons).toEqual(['Buy 40']);
    expect(await click('Buy 40')).toBe('Buy 40: filled');
    expect(broker.accountPositions('SBX-CASH')).toMatchObject([{ symbol: 'NOVA', netQty: 40 }]);
  });
});
