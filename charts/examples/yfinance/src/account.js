// The sandbox broker panel. The rest of this demo simulates its own orders on
// the page; this panel drives the trade tier against a simulated provider
// instead (FakeBroker, analyzer mode), which is the contract a real broker
// adapter implements: account selection and figures, order preview,
// durations and leverage, and the provider's own close, partial close,
// reverse and brackets. Nothing here sends an order the user did not ask for:
// placing needs a preview of that exact ticket first, and each position
// command is approved only by the click that asked for it.
import { AccountManager, FakeBroker, OrderEngine } from '/dist/openalgo-charts.trade.mjs';
import { mountAccountSummary } from '/dist/openalgo-charts.widget.mjs';
import { el, fmt } from './ui.js';

let app;
let desk = null;
let panel = null;

/** Two sandbox accounts, and a live one the analyzer view must never list. */
export const SANDBOX_ACCOUNTS = [
  { id: 'SBX-CASH', name: 'Sandbox cash', mode: 'analyzer', balance: 100000 },
  { id: 'SBX-MARGIN', name: 'Sandbox margin', mode: 'analyzer', balance: 250000, leverage: 2, maxLeverage: 5 },
  { id: 'LIVE-MAIN', name: 'Live', mode: 'live', balance: 1000000 },
];
export const TICKET_DURATIONS = ['DAY', 'IOC', 'GTC', 'GTD'];

/** What a Place click approves: the ticket as previewed, not whatever the form says later. */
export const fingerprint = (req) => JSON.stringify([req.symbol, req.side, req.type, req.qty, req.price ?? null,
  req.duration ?? null, req.expiresAt ?? null, req.leverage ?? null]);

/** The broker, the account view and the engine, wired so the broker's order stream is the authority. */
export function createDesk(options = {}) {
  const broker = new FakeBroker({ accounts: SANDBOX_ACCOUNTS, now: options.now });
  const accounts = new AccountManager({ feed: broker, mode: 'analyzer' });
  let approvedOrder = null;
  let approvedCommand = null;
  const engine = new OrderEngine({
    feed: broker, mode: 'analyzer', constraints: { tickSize: 0.01 },
    selectedAccount: accounts,
    gate: (req) => { const ok = approvedOrder !== null && approvedOrder === fingerprint(req); approvedOrder = null; return ok; },
    confirmCommand: (command) => { const ok = approvedCommand === command.kind; approvedCommand = null; return ok; },
    clock: options.now,
  });
  broker.onOrderUpdate((order, info) => engine.onBrokerOrder({ ...order, clientToken: info.clientToken }));

  // Every write the panel sent whose outcome may still need the broker's word.
  let sent = [];
  // Every account the panel has written to. It is never pruned: a settled
  // write can leave live orders behind (a filled bracket entry's legs), and
  // an account whose history is not read leaves them absent from the book.
  const written = new Set();
  /**
   * Restore the connection, then settle every write from the broker's own
   * history before reading the account again. A write whose answer was lost
   * finds its outcome there by the token the broker echoes; one the complete
   * history never mentions did not arrive, so its token is released. Without
   * this, a close left unresolved by the drop would refuse every later close.
   */
  async function reconnect() {
    broker.reconnect();
    engine.beginReconcile();
    const tokens = new Set();
    const ids = new Set();
    for (const accountId of written) {
      for (const row of await broker.getOrderHistory({ accountId })) {
        tokens.add(row.clientToken);
        ids.add(row.order.id);
        engine.onBrokerOrder({ ...row.order, clientToken: row.clientToken });
      }
    }
    engine.onReconnect(ids);
    for (const id of sent) if (!tokens.has(id)) engine.releaseAmbiguous(id);
    // A settled write needs nothing more from a later reconnect. Its account
    // stays in `written`, for the orders it may have left live.
    sent = sent.filter((id) => !['SETTLED', 'BLOCKED', undefined].includes(engine.intentState(id)));
    return accounts.reconnect();
  }
  return {
    broker, accounts, engine, reconnect,
    approveOrder: (req) => { approvedOrder = fingerprint(req); },
    approveCommand: (kind) => { approvedCommand = kind; },
    /** Remember a write the panel sent, and its account, so a reconnect can account for both. */
    track: (result) => {
      const account = result.clientId === undefined ? undefined : engine.orderAccount(result.clientId);
      if (account !== undefined) { sent.push(result.clientId); written.add(account); }
      return result;
    },
  };
}

/** The order the ticket describes. Only a limit order carries a price, only GTD an expiry. */
export function ticketRequest(ticket, symbol) {
  const req = { symbol, side: ticket.side, type: ticket.type, qty: ticket.qty, duration: ticket.duration };
  if (ticket.type === 'LIMIT') req.price = ticket.price;
  if (ticket.duration === 'GTD') req.expiresAt = ticket.expiresAt;
  if (ticket.leverage !== undefined) req.leverage = ticket.leverage;
  return req;
}

export function initAccount(a) {
  app = a;
  app.openAccount = openAccountPanel;
}

/** The desk, built on first use so a page that never opens it pays nothing. */
export function accountDesk() {
  if (desk === null) {
    desk = createDesk();
    void desk.accounts.refresh();
  }
  return desk;
}

const lastClose = () => (app.currentBars.length ? app.currentBars[app.currentBars.length - 1].close : undefined);
const symbolNow = () => (app.req?.symbol || '').toUpperCase();

function node(tag, className, text) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text !== undefined) n.textContent = text;
  return n;
}
function button(label, onClick, className = 'oac-btn') {
  const b = node('button', className, label);
  b.type = 'button';
  b.addEventListener('click', onClick);
  return b;
}
function numberInput(label, value, step = 'any') {
  const input = node('input', 'acct-num');
  input.type = 'number';
  input.step = step;
  input.value = value === undefined ? '' : String(value);
  input.setAttribute('aria-label', label);
  return input;
}
function field(label, control) {
  const wrap = node('label', 'acct-field');
  wrap.append(node('span', 'acct-field__label', label), control);
  return wrap;
}
function segment(label, values, current, onPick) {
  const group = node('div', 'acct-seg');
  group.setAttribute('role', 'group');
  group.setAttribute('aria-label', label);
  const buttons = values.map(([value, text]) => {
    const b = button(text, () => { onPick(value); sync(value); });
    b.dataset.value = value;
    group.appendChild(b);
    return b;
  });
  const sync = (value) => { for (const b of buttons) b.setAttribute('aria-pressed', String(b.dataset.value === value)); };
  sync(current);
  return group;
}

/** Open the panel under `anchor`, in the chart's overlay layer so the widget styles and menus apply. */
export function openAccountPanel(anchor) {
  const context = app.inspection1?.context;
  if (!context) return false;
  if (panel) { panel.close(); return true; }
  const { broker, accounts, engine, approveOrder, approveCommand, track, reconnect } = accountDesk();
  const price = lastClose();
  const symbol = symbolNow();
  const ticket = {
    side: 'BUY', type: 'MARKET', qty: 10, price: price === undefined ? undefined : Number(price.toFixed(2)),
    duration: 'DAY', expiresAt: undefined, leverage: undefined,
  };
  let previewed = null;
  let alive = true;

  const root = node('div', 'oac-panel acct-panel');
  root.id = 'acctpanel';
  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-label', 'Sandbox broker');
  const head = node('div', 'acct-head');
  head.append(node('span', 'acct-title', 'Sandbox broker'), button('×', () => close(), 'acct-x'));
  head.lastChild.setAttribute('aria-label', 'Close panel');
  const summaryHost = node('div', 'acct-summary');
  const note = node('p', 'acct-note', `Analyzer mode against a simulated provider. ${symbol} fills at the last close shown.`);
  const message = node('p', 'acct-msg');
  message.setAttribute('role', 'status');
  message.setAttribute('aria-live', 'polite');
  const say = (text, kind = 'info') => {
    message.textContent = text;
    message.classList.toggle('is-error', kind === 'error');
    if (el('status')) el('status').textContent = text;
  };
  // Marking pushes fresh figures to the account stream, so it happens only when
  // the price moved; the stream's listener below must not start the next mark.
  let marked;
  const mark = () => {
    const close = lastClose();
    if (close !== undefined && symbol && close !== marked) { marked = close; broker.setMark(symbol, close); }
    return close;
  };

  // ── order ticket ──
  const qty = numberInput('Quantity', ticket.qty, '1');
  const limit = numberInput('Limit price', ticket.price, '0.01');
  const leverage = numberInput('Leverage', '', '1');
  leverage.placeholder = 'Account default';
  const expiry = node('input', 'acct-expiry');
  expiry.type = 'datetime-local';
  expiry.setAttribute('aria-label', 'Expiry');
  const expiryField = field('Expiry', expiry);
  const limitField = field('Price', limit);
  const preview = node('div', 'acct-preview');
  preview.setAttribute('role', 'status');
  const place = button('Place', () => { void placeTicket(); }, 'oac-btn oac-btn--primary');
  place.id = 'acct-place';
  const invalidate = () => { previewed = null; place.disabled = true; preview.textContent = ''; };
  const read = () => {
    ticket.qty = Number(qty.value);
    ticket.price = limit.value === '' ? undefined : Number(limit.value);
    ticket.leverage = leverage.value === '' ? undefined : Number(leverage.value);
    const at = expiry.value === '' ? NaN : new Date(expiry.value).getTime() / 1000;
    ticket.expiresAt = Number.isFinite(at) ? at : undefined;
    return ticketRequest(ticket, symbol);
  };
  const showType = () => { limitField.hidden = ticket.type !== 'LIMIT'; expiryField.hidden = ticket.duration !== 'GTD'; };
  for (const input of [qty, limit, leverage, expiry]) input.addEventListener('input', invalidate);

  async function previewTicket() {
    mark();
    const req = read();
    const result = await engine.previewOrder(req);
    if (!alive) return;
    if (!result.ok) { invalidate(); preview.textContent = result.reason; preview.classList.add('is-error'); return; }
    const p = result.preview;
    preview.classList.toggle('is-error', p.rejectReason !== undefined);
    preview.textContent = p.rejectReason !== undefined
      ? `Would be refused: ${p.rejectReason}`
      : `Value ${fmt(p.estimatedValue ?? 0)}  Margin ${fmt(p.marginRequired ?? 0)}  Available after ${fmt(p.marginAvailableAfter ?? 0)}`;
    previewed = p.rejectReason === undefined ? req : null;
    place.disabled = previewed === null;
  }
  async function placeTicket() {
    if (previewed === null) return;
    const req = previewed;
    invalidate();
    mark();
    approveOrder(req);
    const result = track(await engine.placeOrder(req));
    if (!alive) return;
    say(result.ok ? `${req.side} ${req.qty} ${symbol} ${req.type} ${req.duration}: ${engine.brokerStatus(result.clientId) ?? 'sent'}`
      : `Not placed: ${result.reason}`, result.ok ? 'info' : 'error');
    await refresh();
  }

  // ── position commands ──
  const positionLine = node('p', 'acct-position');
  const partQty = numberInput('Quantity to close', 1, '1');
  const commands = [];
  const command = (label, kind, run) => {
    const b = button(label, async () => {
      mark();
      approveCommand(kind);
      const result = track(await run());
      if (!alive) return;
      say(result.ok ? `${label}: ${engine.brokerStatus(result.clientId) ?? result.intent}` : `${label} refused: ${result.reason}`, result.ok ? 'info' : 'error');
      await refresh();
    });
    commands.push(b);
    return b;
  };
  const closeAll = command('Close position', 'close', () => engine.closePosition({ symbol }));
  const closePart = command('Close part', 'close', () => engine.closePosition({ symbol, qty: Number(partQty.value) }));
  const reverse = command('Reverse', 'reverse', () => engine.reversePosition({ symbol }));
  closeAll.id = 'acct-close';
  closePart.id = 'acct-close-part';
  reverse.id = 'acct-reverse';

  // ── provider bracket ──
  const stop = numberInput('Stop', price === undefined ? undefined : Number((price * 0.99).toFixed(2)), '0.01');
  const target = numberInput('Target', price === undefined ? undefined : Number((price * 1.02).toFixed(2)), '0.01');
  const bracket = button('Place bracket', async () => {
    mark();
    approveCommand('bracket');
    const req = { symbol, side: ticket.side, type: 'MARKET', qty: Number(qty.value), stopLoss: Number(stop.value), takeProfit: Number(target.value) };
    const result = track(await engine.placeBracket(req));
    if (!alive) return;
    say(result.ok ? `Bracket placed: stop and target are linked by the provider` : `Bracket refused: ${result.reason}`, result.ok ? 'info' : 'error');
    await refresh();
  });
  bracket.id = 'acct-bracket';

  const fills = node('ol', 'acct-fills');
  const connection = button('Drop connection', () => {
    if (connection.dataset.state === 'down') {
      void reconnect().then((result) => {
        if (!alive) return;
        say(result.ok ? 'Reconnected to the simulated provider' : `Reconnect failed: ${result.reason}`, result.ok ? 'info' : 'error');
        return refresh();
      });
      connection.dataset.state = 'up';
      connection.textContent = 'Drop connection';
    } else {
      broker.disconnect();
      connection.dataset.state = 'down';
      connection.textContent = 'Reconnect';
      say('Connection to the simulated provider dropped; figures are stale');
    }
  });
  connection.id = 'acct-connection';
  connection.dataset.state = 'up';

  async function refresh() {
    const close = mark();
    const [positions, executions] = await Promise.all([accounts.positions(), accounts.executions({ symbol, limit: 5 })]);
    if (!alive) return;
    const held = positions.ok ? positions.rows.find((p) => p.symbol === symbol) : undefined;
    const flat = held === undefined;
    if (!positions.ok) positionLine.textContent = positions.cancelled ? '' : `Position unavailable: ${positions.reason}`;
    else if (flat) positionLine.textContent = `No open position in ${symbol}`;
    else {
      // Adding zero turns a negative zero into zero, so a flat mark reads +0.00.
      const pnl = (close === undefined ? 0 : (close - held.avgPrice) * held.netQty) + 0;
      positionLine.textContent = `${held.netQty > 0 ? 'Long' : 'Short'} ${Math.abs(held.netQty)} @ ${fmt(held.avgPrice)}  P&L ${pnl >= 0 ? '+' : ''}${fmt(pnl)}`;
    }
    for (const b of commands) b.disabled = flat;
    fills.textContent = '';
    for (const row of executions.ok ? executions.rows : []) {
      fills.appendChild(node('li', undefined, `${row.side} ${row.qty} @ ${fmt(row.price)}  ${new Date(row.time * 1000).toLocaleTimeString()}`));
    }
    if (executions.ok && executions.rows.length === 0) fills.appendChild(node('li', 'acct-empty', 'No executions yet'));
  }

  const group = (text) => node('div', 'acct-group', text);
  const row = (...children) => { const r = node('div', 'acct-row'); r.append(...children); return r; };
  const previewButton = button('Preview', () => { void previewTicket(); });
  previewButton.id = 'acct-preview';
  root.append(
    head, summaryHost, note,
    group('Order'),
    row(segment('Side', [['BUY', 'Buy'], ['SELL', 'Sell']], ticket.side, (v) => { ticket.side = v; invalidate(); }),
      segment('Type', [['MARKET', 'Market'], ['LIMIT', 'Limit']], ticket.type, (v) => { ticket.type = v; invalidate(); showType(); })),
    row(field('Qty', qty), limitField, field('Leverage', leverage)),
    row(segment('Duration', TICKET_DURATIONS.map((d) => [d, d]), ticket.duration, (v) => { ticket.duration = v; invalidate(); showType(); }), expiryField),
    preview,
    Object.assign(row(previewButton, place), { className: 'acct-row acct-actions' }),
    group('Position'),
    positionLine,
    row(closeAll, field('Qty', partQty), closePart, reverse),
    group('Provider bracket'),
    row(field('Stop', stop), field('Target', target), bracket),
    group('Executions'),
    fills,
    row(connection, message),
  );
  place.disabled = true;
  showType();
  const summary = mountAccountSummary(context, summaryHost, { source: accounts });
  // A switch or a reconnect changes what the panel describes; a fresh reading
  // of the same account only changes the summary, which repaints itself.
  let seen = '';
  const off = accounts.subscribe((state) => {
    const key = `${state.selectedId}|${state.status}`;
    if (key === seen) return;
    seen = key;
    invalidate();
    void refresh();
  });
  // The chart's own pointer capture would take a click that lands on this panel.
  root.addEventListener('pointerdown', (event) => event.stopPropagation());
  const closeOverlay = context.openOverlay(root, {
    anchor, placement: 'below', dismissOnOutside: false, initialFocus: previewButton,
    onClose: () => { alive = false; off(); summary.destroy(); panel = null; },
  });
  function close() { closeOverlay(); }
  panel = { root, close };
  void refresh();
  return true;
}
