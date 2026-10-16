import { STOCK_BARS_SOURCE } from './synthetic-market';

/**
 * The runnable account examples, kept as plain strings so the library's own
 * tests can run exactly the code a reader sees and clicks through.
 */

/** Examples page: a sandbox broker with native position commands and a dropped connection. */
export const SANDBOX_BROKER_EXAMPLE = `${STOCK_BARS_SOURCE}
el.style.display = 'flex';
el.style.flexDirection = 'column';
const controls = document.createElement('div');
controls.style.cssText = 'display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:6px 8px;font:12px sans-serif';
controls.addEventListener('pointerdown', event => event.stopPropagation());
const host = document.createElement('div');
host.style.cssText = 'flex:1;min-height:0';
el.append(controls, host);

const broker = new lib.FakeBroker({ accounts: [
  { id: 'SBX-CASH', name: 'Sandbox cash', mode: 'analyzer', currency: 'INR', balance: 500000 },
  { id: 'SBX-MARGIN', name: 'Sandbox margin', mode: 'analyzer', currency: 'INR', balance: 1500000, leverage: 5, maxLeverage: 5 },
  { id: 'LIVE', name: 'Live', mode: 'live', currency: 'INR', balance: 9000000 },
] });
const accounts = new lib.AccountManager({ feed: broker, mode: 'analyzer' });
const engine = new lib.OrderEngine({
  feed: broker, mode: 'analyzer', armed: true, constraints: { tickSize: 0.05 },
  selectedAccount: accounts,
});
// The broker's order stream settles every order and command.
broker.onOrderUpdate((order, info) => engine.onBrokerOrder({ ...order, clientToken: info.clientToken }));

// After a reconnect the broker's own history is the word on every write this
// page sent. One whose answer was lost finds its outcome there by the token the
// broker echoes; one the complete history never mentions did not arrive, so its
// token is released. Without this, a close left unresolved by the drop would
// refuse every later close.
const sent = [];
async function reconcile() {
  engine.beginReconcile();
  const tokens = new Set();
  const ids = new Set();
  for (const accountId of new Set(sent.map(id => engine.orderAccount(id)).filter(Boolean))) {
    for (const row of await broker.getOrderHistory({ accountId })) {
      tokens.add(row.clientToken);
      ids.add(row.order.id);
      engine.onBrokerOrder({ ...row.order, clientToken: row.clientToken });
    }
  }
  engine.onReconnect(ids);
  for (const id of sent) if (!tokens.has(id)) engine.releaseAmbiguous(id);
}

const bars = stockBars(1700000000, 160, 300, 100, 41);
const widget = lib.createWidget(host, {
  symbol: 'NOVA', exchange: 'DEMO', interval: '5m', intervals: ['5m'], persist: false, locale: 'en-IN', account: accounts,
});
widget.series.setData(bars);
broker.setMark('NOVA', bars[bars.length - 1].close);
accounts.refresh();

const log = document.createElement('span');
log.style.opacity = '0.8';
const action = (label, run) => {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = label;
  button.style.cssText = 'padding:4px 9px;border:1px solid #667085;border-radius:4px;background:transparent;color:inherit;font:12px sans-serif;cursor:pointer';
  button.onclick = async () => {
    const result = await run();
    if (result.clientId) sent.push(result.clientId);
    log.textContent = result.ok ? label + ': ' + (engine.brokerStatus(result.clientId) || result.intent) : label + ' refused: ' + result.reason;
  };
  controls.appendChild(button);
};
action('Buy 50', () => engine.placeOrder({ symbol: 'NOVA', side: 'BUY', type: 'MARKET', qty: 50, duration: 'DAY' }));
action('Close 20', () => engine.closePosition({ symbol: 'NOVA', qty: 20 }));
action('Reverse', () => engine.reversePosition({ symbol: 'NOVA' }));
action('Close all', () => engine.closePosition({ symbol: 'NOVA' }));
action('Drop connection', async () => { broker.disconnect(); return { ok: true, intent: 'figures are stale' }; });
action('Reconnect', async () => {
  broker.reconnect();
  await reconcile();
  const result = await accounts.reconnect();
  return { ...result, intent: 'reconnected' };
});
controls.appendChild(log);
return widget;`;

/** Docs page: the account summary in the widget's status line. Nothing is sent until the reader asks. */
export const ACCOUNT_SUMMARY_EXAMPLE = `el.style.display = 'flex';
el.style.flexDirection = 'column';
const controls = document.createElement('div');
controls.style.cssText = 'display:flex;align-items:center;gap:6px;padding:6px 8px;font:12px sans-serif';
controls.addEventListener('pointerdown', event => event.stopPropagation());
const host = document.createElement('div');
host.style.cssText = 'flex:1;min-height:0';
el.append(controls, host);

const broker = new lib.FakeBroker({ accounts: [
  { id: 'SBX-CASH', name: 'Sandbox cash', mode: 'analyzer', currency: 'INR', balance: 500000 },
  { id: 'SBX-MARGIN', name: 'Sandbox margin', mode: 'analyzer', currency: 'INR', balance: 1500000, leverage: 5, maxLeverage: 5 },
  { id: 'LIVE', name: 'Live', mode: 'live', currency: 'INR', balance: 9000000 },
] });
const accounts = new lib.AccountManager({ feed: broker, mode: 'analyzer' });
const engine = new lib.OrderEngine({ feed: broker, mode: 'analyzer', armed: true,
  constraints: { tickSize: 0.05 }, selectedAccount: accounts });
broker.onOrderUpdate((order, info) => engine.onBrokerOrder({ ...order, clientToken: info.clientToken }));

const bars = lib.generateBars(1700000000, 160, 300);
const widget = lib.createWidget(host, { symbol: 'NOVA', exchange: 'DEMO', interval: '5m', intervals: ['5m'],
  persist: false, locale: 'en-IN', account: accounts });
widget.series.setData(bars);
broker.setMark('NOVA', bars[bars.length - 1].close);
accounts.refresh();

// The only order this page sends is the one the reader clicks for.
const buy = document.createElement('button');
buy.type = 'button';
buy.textContent = 'Buy 40';
buy.style.cssText = 'padding:4px 9px;border:1px solid #667085;border-radius:4px;background:transparent;color:inherit;font:12px sans-serif;cursor:pointer';
const log = document.createElement('span');
log.style.opacity = '0.8';
buy.onclick = async () => {
  const result = await engine.placeOrder({ symbol: 'NOVA', side: 'BUY', type: 'MARKET', qty: 40 });
  log.textContent = result.ok ? 'Buy 40: ' + (engine.brokerStatus(result.clientId) || result.intent) : 'Buy 40 refused: ' + result.reason;
};
controls.append(buy, log);
return widget;`;
