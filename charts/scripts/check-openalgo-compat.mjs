/**
 * Exercise the actual OpenAlgo /trading app with its installed Charts package.
 * Run only against an isolated OpenAlgo worktree with its own node_modules:
 * node scripts/check-openalgo-compat.mjs --frontend /tmp/openalgo/frontend
 * Add --objects true only when the host includes the shared Objects integration.
 * Add --navigation true to validate the wheel routing introduced in 2.1.8.
 * Add --branding true to validate corner branding and optional watermark settings.
 * Add --foundations true for candle-center snapping, interval sync and volume averages.
 * Add --templates true for named study templates on the selected chart.
 * Add --correctness true for volume, hover, pan and linked readout regressions.
 * Add --workspaces true for complete named chart grids.
 * Add --oi true for history capability, readouts, studies and persistence.
 * Add --alerts true for source controls, live delivery, persistence and replay guards.
 * Add --consumer-checks /absolute/checks.mjs for additional checkTradingWorkspace checks;
 * they run last, after every pane is put back on 5m.
 * Use --browser chromium|firefox|webkit to select the rendering engine.
 * Use --port <n> to serve on a fixed port; without it a free one is picked at random.
 * A defect in the host's own chrome is printed as HOST FINDING and kept in the
 * report's hostFindings; it fails nothing.
 * Every group can run in the same invocation as the others.
 *
 * No backend is started. Vite proxies are removed and every API/WS is mocked.
 * The app source is unchanged; an entry wrapper records terminal instances so
 * assertions can inspect the real series, drawings, feed and replay state.
 */
import assert from 'node:assert/strict';
import { checkChartCorrectness } from './check-openalgo-correctness.mjs';
import { checkWorkspaces } from './check-openalgo-workspaces.mjs';
import { checkOpenInterest } from './check-openalgo-open-interest.mjs';
import { checkAlerts } from './check-openalgo-alerts.mjs';
import { checkToolbar } from './check-openalgo-toolbar.mjs';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, rm, writeFile, lstat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium, firefox, webkit, expect } from '@playwright/test';

const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, i, all) => {
  if (value.startsWith('--')) pairs.push([value.slice(2), all[i + 1]]);
  return pairs;
}, []));
assert(args.frontend, '--frontend must name an isolated OpenAlgo frontend');
const browserType = { chromium, firefox, webkit }[args.browser ?? 'chromium'];
assert(browserType, '--browser must be chromium, firefox or webkit');
const frontend = resolve(args.frontend);
assert((await lstat(join(frontend, '..', '.git'))).isFile(), 'Use a linked OpenAlgo git worktree');
assert(!(await lstat(join(frontend, 'node_modules'))).isSymbolicLink(), 'Use copied dependencies in an isolated checkout');
const requireApp = createRequire(join(frontend, 'package.json'));
const { createServer, loadConfigFromFile } = await import(pathToFileURL(requireApp.resolve('vite')).href);
const chartsManifest = JSON.parse(await readFile(join(frontend, 'node_modules/openalgo-charts/package.json'), 'utf8'));
const cache = await mkdtemp(join(tmpdir(), 'openalgo-compat-'));
const report = { label: args.label ?? chartsManifest.version, chartsVersion: chartsManifest.version, checks: [], requests: [], websocket: [], pageErrors: [], consoleErrors: [], blocked: [] };
report.distHashes = Object.fromEntries(await Promise.all(['openalgo-charts.mjs', 'openalgo-charts.profile.mjs', 'openalgo-charts.indicators.mjs', 'openalgo-charts.draw.mjs', 'openalgo-charts.transform.mjs'].map(async (file) => [file, createHash('sha256').update(await readFile(join(frontend, 'node_modules/openalgo-charts/dist', file))).digest('hex')])));
report.wireIdentity = args['legacy-topic'] ? 'top-level with legacy topic workaround' : 'canonical top-level only';
const fixedNow = Date.parse('2026-09-10T06:32:00Z');
const symbols = [
  { symbol: 'BHEL', exchange: 'NSE', name: 'Bharat Heavy Electricals', lotsize: 1, tick_size: 0.05, freeze_qty: 100000 },
  { symbol: 'NIFTY29SEP26FUT', exchange: 'NFO', name: 'Nifty Futures', lotsize: 65, tick_size: 0.05, freeze_qty: 1800 },
  { symbol: 'NIFTY', exchange: 'NSE_INDEX', name: 'Nifty 50', lotsize: 1, tick_size: 0.0005 },
  ...(args.oi === 'true' ? [
    { symbol: 'BTCUSD', exchange: 'CRYPTO', instrumenttype: 'SPOT', name: 'Bitcoin Spot', lotsize: 1, tick_size: 0.01 },
    { symbol: 'BTCUSD.P', exchange: 'CRYPTO', instrumenttype: 'PERPFUT', name: 'Bitcoin Perpetual', lotsize: 1, tick_size: 0.01 },
  ] : []),
];
function history(body) {
  const interval = body.interval;
  const seconds = /^\d+[mh]$/.test(interval)
    ? Number(interval.slice(0, -1)) * (interval.endsWith('h') ? 3600 : 60)
    : 86400;
  const rows = [];
  for (let day = 8; day <= 10; day++) {
    const start = Date.parse(`2026-09-${day.toString().padStart(2, '0')}T03:45:00Z`) / 1000;
    const end = seconds === 86400 ? start : Math.min(start + 375 * 60 - seconds, Math.floor(fixedNow / 1000 / seconds) * seconds);
    for (let timestamp = start; timestamp <= end; timestamp += seconds) {
      const base = 100 + Math.sin(rows.length / 7) * 5;
      rows.push({ timestamp, open: base, high: base + 2, low: base - 1, close: base + 0.5, volume: 1000 + rows.length * 10 });
      if (seconds === 86400) break;
    }
  }
  if (args.oi !== 'true') return rows;
  const derivative = body.exchange === 'NFO' || body.symbol === 'BTCUSD.P';
  return rows.map((bar, index) => ({ ...bar,
    ...(derivative && index === rows.length - 14 ? {} : {
      oi: derivative && index !== rows.length - 20 ? 10000 + index * 10 : 0,
    }),
  }));
}
let orderCounter = 0;
let mockOrders = [];
let mockPositions = [];
let analyzer = false;
let historyVolumeBoost = 0;
const config = (await loadConfigFromFile({ command: 'serve', mode: 'test' }, join(frontend, 'vite.config.ts'))).config;
const server = await createServer({
  ...config, configFile: false, root: frontend, cacheDir: cache, logLevel: 'error',
  server: { host: '127.0.0.1', port: args.port ? Number(args.port) : 19000 + Math.floor(Math.random() * 10000), strictPort: !!args.port, hmr: false, proxy: {} },
  plugins: [...config.plugins, {
    name: 'openalgo-compat-observer',
    transformIndexHtml(html) { return html.replace('src="/src/main.tsx"', 'src="/openalgo-compat-entry.ts"'); },
    resolveId(id) { if (id === '/openalgo-compat-entry.ts') return '\0openalgo-compat-entry'; },
    load(id) {
      if (id !== '\0openalgo-compat-entry') return;
      return `import { TradingTerminal } from '/src/lib/trading/terminal.ts';
        window.__compatTerminals = [];
        const init = TradingTerminal.prototype.init;
        TradingTerminal.prototype.init = function(...args) {
          window.__compatTerminals.push(this);
          return init.apply(this, args);
        };
        import('/src/main.tsx');`;
    },
  }],
});
let browser;
let page;
let reloading = false;
try {
  await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await browserType.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, serviceWorkers: 'block' });
  page = await context.newPage();
  report.runtimeEvents = [];
  await page.exposeFunction('__reportCompatRuntimeError', error => report.runtimeEvents.push(error));
  report.consoleTraces = [];
  await page.exposeFunction('__reportCompatConsoleTrace', trace => report.consoleTraces.push({ after: report.checks.at(-1), ...trace }));
  await page.addInitScript(() => {
    window.addEventListener('error', event => window.__reportCompatRuntimeError({
      type: 'error', message: event.message, stack: event.error?.stack,
    }));
    window.addEventListener('unhandledrejection', event => window.__reportCompatRuntimeError({
      type: 'unhandledrejection', message: String(event.reason), stack: event.reason?.stack,
    }));
    const original = console.error;
    console.error = (...args) => {
      window.__reportCompatConsoleTrace({ message: args.map(String).join(' '), visibility: document.visibilityState, ready: document.readyState, stack: new Error().stack });
      original.apply(console, args);
    };
  });
  // Freeze market wall time without replacing native timers. A synthetic timer
  // scheduler can deliver Firefox visibility events inside a pending React
  // render during reload, producing warnings absent with the browser's tasks.
  await page.addInitScript(now => {
    const NativeDate = Date;
    window.__compatFixedNow = now;
    function FixedDate(...args) {
      if (!new.target) return new NativeDate(window.__compatFixedNow).toString();
      return Reflect.construct(NativeDate, args.length ? args : [window.__compatFixedNow], new.target);
    }
    Object.setPrototypeOf(FixedDate, NativeDate);
    FixedDate.prototype = NativeDate.prototype;
    FixedDate.now = () => window.__compatFixedNow;
    window.Date = FixedDate;
  }, fixedNow);
  report.pageErrorDetails = [];
  report.failedRequests = [];
  page.on('requestfailed', request => report.failedRequests.push({ after: report.checks.at(-1), url: request.url(), failure: request.failure() }));
  page.on('pageerror', (error) => {
    report.pageErrors.push(error.message);
    report.pageErrorDetails.push({ after: report.checks.at(-1), duringReload: reloading, name: error.name, message: error.message, stack: error.stack });
  });
  const consoleReads = [];
  page.on('console', (message) => {
    if (message.type() !== 'error') return;
    const index = report.consoleErrors.push(message.text()) - 1;
    // Some browsers stringify an Error as just "Error". Preserve its actual
    // message so the deliberate mode-refusal check cannot hide another error.
    consoleReads.push(Promise.all(message.args().map(arg => arg.evaluate(value =>
      value instanceof Error ? value.message : String(value)
    ))).then(parts => { if (parts.length) report.consoleErrors[index] = parts.join(' '); }).catch(() => {}));
  });
  await context.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin) {
      report.blocked.push(request.url());
      return route.abort();
    }
    const path = url.pathname.replace(/\/$/, '');
    if (path === '/custom-indicators/index.json') return route.fulfill({ json: [{ file: 'compat.js', mtime: 1 }] });
    if (path === '/custom-indicators/compat.js') return route.fulfill({ contentType: 'text/javascript', body: `export default function({registerIndicator}) {
      registerIndicator({id:'compat-close',name:'Compatibility Close',category:'Custom',placement:'onchart',inputs:[],plots:[{key:'close',type:'line'}],calc(bars) {
        window.__compatCustomCalls = (window.__compatCustomCalls || 0) + 1;
        return {close:bars.map(bar=>bar.close)};
      }});
    }` });
    if (!path.startsWith('/api/') && !path.startsWith('/auth/') && !path.startsWith('/socket.io')) return route.continue();
    let body = {};
    try { body = request.postDataJSON() ?? {}; } catch { /* transport body */ }
    report.requests.push({ path, method: request.method(), body });
    let json = { status: 'success', data: [] };
    if (path === '/auth/session-status') json = { status: 'success', logged_in: true, authenticated: true, broker: 'fixture', user: 'compat', api_key: 'synthetic-only', active_sessions: 1 };
    else if (path === '/auth/analyzer-mode') json = { status: 'success', data: { analyze_mode: analyzer } };
    else if (path === '/auth/csrf-token') json = { csrf_token: 'synthetic-csrf' };
    else if (path === '/api/broker/capabilities') json = { status: 'success', data: { broker_name: 'Fixture', broker_type: 'IN_stock', supported_exchanges: ['NSE', 'NFO', 'NSE_INDEX'], leverage_config: false } };
    else if (path === '/api/websocket/apikey') json = { status: 'success', api_key: 'synthetic-only' };
    else if (path === '/api/websocket/config') json = { status: 'success', websocket_url: 'ws://fixture.invalid/feed' };
    else if (path === '/api/v1/intervals') json.data = { minutes: ['1m', '5m', '15m', '30m'], hours: ['1h'], days: ['D'], weeks: ['W'], months: ['M'] };
    else if (path === '/api/v1/search') json.data = symbols.filter((symbol) => symbol.symbol.includes(body.query ?? '') && (!body.exchange || symbol.exchange === body.exchange));
    else if (path === '/api/v1/symbol') json.data = symbols.find((symbol) => symbol.symbol === body.symbol && symbol.exchange === body.exchange);
    else if (path === '/api/v1/history') json.data = history(body).map((bar) => ({ ...bar, volume: bar.volume + historyVolumeBoost }));
    else if (path === '/api/v1/quotes') json.data = { ltp: 111, bid: 110.95, ask: 111.05, volume: 15000, prev_close: 99 };
    else if (path === '/api/v1/depth') json.data = { ltp: 111, bids: [{ price: 110.95, quantity: 10 }], asks: [{ price: 111.05, quantity: 20 }], volume: 15000, prev_close: 99 };
    else if (path === '/api/v1/analyzer') json.data = { analyze_mode: analyzer };
    else if (path === '/api/v1/orderbook') json.data = { orders: mockOrders };
    else if (path === '/api/v1/positionbook') json.data = mockPositions;
    else if (path === '/api/v1/placeorder') json = { status: 'success', orderid: `fixture-${++orderCounter}`, mode: analyzer ? 'analyze' : 'live' };
    else if (path === '/api/v1/modifyorder') {
      mockOrders = mockOrders.map((order) => order.orderid === body.orderid ? { ...order, ...body } : order);
      json = { status: 'success', orderid: body.orderid };
    } else if (path === '/api/v1/cancelorder') {
      mockOrders = mockOrders.filter((order) => order.orderid !== body.orderid);
      json = { status: 'success', orderid: body.orderid };
    }
    else if (path.startsWith('/socket.io')) return route.fulfill({ status: 503, body: 'Socket.IO disabled in fixture' });
    return route.fulfill({ status: 200, json });
  });
  const sockets = [];
  const subscriptions = new Map();
  await context.routeWebSocket('**/*', (socket) => {
    sockets.push(socket);
    subscriptions.set(socket, new Set());
    socket.onClose(() => subscriptions.delete(socket));
    socket.onMessage((wire) => {
      let message;
      try { message = JSON.parse(wire.toString()); } catch { return; }
      report.websocket.push(message);
      const key = `${message.mode}:${message.symbol}:${message.exchange}`;
      if (message.action === 'subscribe') subscriptions.get(socket)?.add(key);
      if (message.action === 'unsubscribe') subscriptions.get(socket)?.delete(key);
      if (message.action === 'authenticate') socket.send(JSON.stringify({ type: 'auth', status: 'success' }));
      else if (message.action === 'ping') socket.send(JSON.stringify({ type: 'pong' }));
      else socket.send(JSON.stringify({ type: message.action, status: 'success' }));
    });
  });
  const check = async (name, fn) => { await fn(); report.checks.push(name); console.log(`PASS ${name}`); };
  // A defect in the host's own chrome, found on the way. It is printed and
  // kept in the report on every run, and fails nothing: it is not this
  // package's to fix, and the package's gate should not wait on it.
  report.hostFindings = [];
  const hostFinding = message => { report.hostFindings.push({ after: report.checks.at(-1), message }); console.log(`HOST FINDING ${message}`); };
  const terminal = async (fn, arg) => page.evaluate(({ source, arg }) => {
    const t = window.__compatTerminals?.findLast((item) => !item.destroyed && item.chart);
    if (!t) throw new Error('No active terminal');
    return (0, eval)(`(${source})`)(t, arg);
  }, { source: fn.toString(), arg });
  // Toolbar setters keep the old chart visible while the next history load runs.
  // Wait for that chart's context before driving Replay or another interaction.
  const waitReady = () => page.waitForFunction(() => window.__compatTerminals?.some(t => {
    const context = t.chart?.getDataContext();
    return !t.destroyed && !t.dataUnavailable?.() && t.price?.getData().length > 0 && context?.symbol === t.sym?.symbol
      && context?.exchange === t.sym?.exchange && context?.interval === t.interval;
  }));
  const waitDialogClosed = () => page.waitForFunction(() => !document.querySelector('[role="dialog"]')
    && getComputedStyle(document.body).pointerEvents !== 'none');
  const reload = async () => {
    // Let state changes from the preceding interaction paint before automation
    // interrupts the document with navigation and its visibility event.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    reloading = true;
    try { return await page.reload(); }
    finally { reloading = false; }
  };
  const sendDepth = async (symbol, exchange, ltp) => {
    for (const socket of sockets) {
      try { socket.send(JSON.stringify({ type: 'market_data', symbol, exchange, ...(args['legacy-topic'] ? { topic: `${symbol}.${exchange}` } : {}), mode: 3, data: {
        ltp, timestamp: fixedNow, depth: { buy: [{ price: ltp - 0.05, quantity: 10, orders: 2 }], sell: [{ price: ltp + 0.05, quantity: 20, orders: 3 }] },
      } })); } catch { /* a StrictMode terminal was destroyed */ }
    }
    await page.waitForFunction((price) => window.__compatTerminals?.some((t) => !t.destroyed && t.lastLtp === price), ltp);
  };
  const waitForSubscription = (symbol, exchange, mode, count = 1) => expect.poll(() =>
    [...subscriptions.values()].filter(items => items.has(`${mode}:${symbol}:${exchange}`)).length).toBeGreaterThanOrEqual(count);
  const sendLtp = async (symbol, exchange, ltp) => {
    await waitForSubscription(symbol, exchange, 1);
    for (const [socket, items] of subscriptions) {
      if (items.has(`1:${symbol}:${exchange}`)) socket.send(JSON.stringify({
        type: 'market_data', symbol, exchange, mode: 1, data: { ltp, timestamp: fixedNow },
      }));
    }
    await page.waitForFunction(price => window.__compatTerminals?.some(t => !t.destroyed && t.lastLtp === price), ltp);
  };
  await page.goto(`${origin}/trading`);
  if (args.workspaces === 'true') {
    await page.getByRole('button', { name: 'Workspaces', exact: true }).click({ timeout: 5000 });
    await page.getByRole('dialog', { name: 'Chart workspaces' }).waitFor();
    await page.getByRole('button', { name: 'Close', exact: true }).click();
    await expect(page.locator('[data-slot="dialog-overlay"]')).toHaveCount(0);
  }
  if (args.templates === 'true') {
    await page.getByRole('button', { name: 'Templates', exact: true }).click({ timeout: 5000 });
    await page.getByRole('dialog', { name: 'Indicator templates' }).waitFor();
    await page.getByRole('button', { name: 'Close', exact: true }).click();
    await expect(page.locator('[data-slot="dialog-overlay"]')).toHaveCount(0);
  }
  await check('unchanged /trading mounts real chart', async () => {
    await waitReady();
    assert(await page.locator('canvas').count() > 0);
    assert.equal(await terminal((t) => t.sym.symbol), 'BHEL');
    assert(report.requests.some((r) => r.path === '/api/v1/history' && r.body.interval === '5m'));
  });
  if (args.toolbar === 'true') await checkToolbar({ page, check, screenshot: args.screenshot, orderCount: () => orderCounter, hostFinding });
  if (args.branding === 'true') {
    await check('host branding links follow disabled and custom chart branding', async () => {
      const mark = await terminal(t => t.chart.brandingOptions());
      assert(mark && mark.href === 'https://openalgo.in');
      const link = page.getByRole('link', { name: mark.label, exact: true });
      await link.waitFor({ state: 'visible' });
      await terminal(t => t.chart.setBranding(false));
      await link.waitFor({ state: 'detached' });
      await terminal(t => t.chart.setBranding({ label: 'Research charts', href: 'https://example.com/research' }));
      const custom = page.getByRole('link', { name: 'Research charts', exact: true });
      await custom.waitFor({ state: 'visible' });
      assert.equal(await custom.getAttribute('href'), 'https://example.com/research');
      await terminal(t => t.chart.setBranding(true));
      await link.waitFor({ state: 'visible' });
      assert.equal(orderCounter, 0);
    });
    await check('optional watermark uses actual settings, persistence and current symbol context', async () => {
      assert.equal(await terminal(t => t.chart.watermarkOptions().visible), false);
      const openSettings = () => terminal(async t => t.cb.onChartSettings(await t.chartSettings()));
      await openSettings();
      await page.getByRole('button', { name: 'Appearance', exact: true }).click();
      const show = page.getByRole('checkbox', { name: 'Show watermark', exact: true });
      assert.equal(await show.isChecked(), false);
      await show.check();
      await page.getByRole('button', { name: 'Cancel', exact: true }).click();
      await waitDialogClosed();
      assert.equal(await terminal(t => t.chart.watermarkOptions().visible), false);
      await openSettings();
      await page.getByRole('button', { name: 'Appearance', exact: true }).click();
      await show.check();
      await page.getByRole('button', { name: 'Ok', exact: true }).click();
      await waitDialogClosed();
      await page.waitForFunction(() => window.__compatTerminals.some(t => !t.destroyed && t.chart?.watermarkOptions().visible));
      assert.match(await terminal(t => t.chart.exportSVG()), /BHEL/);
      await reload();
      await waitReady();
      assert.equal(await terminal(t => t.chart.watermarkOptions().visible), true);
      await terminal(async (t, symbol) => t.loadSymbol(symbol), symbols[1]);
      await waitReady();
      assert.match(await terminal(t => t.chart.exportSVG()), /NIFTY29SEP26FUT/);
      await terminal(t => t.applyChartSettings({ 'watermark.text': 'Research' }));
      await terminal(t => t.setInterval('15m'));
      await waitReady();
      assert.match(await terminal(t => t.chart.exportSVG()), /Research/);
      await terminal(t => { t.startReplay(); t.commitReplayPick(); });
      await page.waitForFunction(() => window.__compatTerminals.some(t => !t.destroyed && t.replayState() !== null));
      await terminal(t => t.applyChartSettings({ 'watermark.visible': false }));
      assert.match(await terminal(t => t.chart.exportSVG()), /Replay/);
      await terminal(t => t.stopReplay());
      await terminal(t => t.applyChartSettings({ 'watermark.text': '', 'watermark.visible': false }));
      await terminal(async (t, symbol) => { await t.loadSymbol(symbol); t.setInterval('5m'); }, symbols[0]);
      await waitReady();
      assert.equal(await terminal(t => t.chart.watermarkOptions().visible), false);
      assert.equal(orderCounter, 0);
    });
  }
  if (args.navigation === 'true') {
    await check('trackpad, horizontal wheel and price-axis scaling retain host order authority', async () => {
      const before = await terminal(t => ({ range: t.chart.getVisibleLogicalRange(), spacing: t.chart.timeScale.barSpacing }));
      const orderCount = orderCounter;
      const wheel = (t, input) => {
        const r = t.container.getBoundingClientRect();
        t.container.dispatchEvent(new WheelEvent('wheel', {
          bubbles: true, cancelable: true,
          clientX: r.left + (input.axis ? r.width - 5 : r.width / 2), clientY: r.top + r.height * 0.4,
          deltaX: input.x, deltaY: input.y,
        }));
      };
      await terminal(wheel, { x: 0, y: -1 });
      await page.waitForTimeout(450);
      const tiny = await terminal(t => t.chart.timeScale.barSpacing);
      assert(Math.abs(tiny / before.spacing - 1.0009535561) < 1e-7);
      const from = await terminal(t => t.chart.getVisibleLogicalRange().from);
      await terminal(wheel, { x: 60, y: 0 });
      await page.waitForTimeout(450);
      assert.equal(await terminal(t => t.chart.timeScale.barSpacing), tiny);
      assert((await terminal(t => t.chart.getVisibleLogicalRange().from)) > from);
      const scale = await terminal(t => t.price.priceScale().priceRange());
      await terminal(wheel, { x: 0, y: -100, axis: true });
      await page.waitForTimeout(100);
      const scaled = await terminal(t => t.price.priceScale().priceRange());
      assert.equal(await terminal(t => t.chart.timeScale.barSpacing), tiny);
      assert(scaled.max - scaled.min < scale.max - scale.min);
      assert.equal(orderCounter, orderCount);
      await terminal((t, range) => { t.chart.setAutoScale(true); t.chart.setVisibleLogicalRange(range); }, before.range);
    });
  }
  await check('depth-only subscription updates seeded candle and bid/ask', async () => {
    const before = await terminal((t) => ({ n: t.rawBars.length, bar: t.rawBars.at(-1) }));
    await sendDepth('BHEL', 'NSE', 111.25);
    const after = await terminal((t) => ({ n: t.rawBars.length, bar: t.price.getData().at(-1), depth: t.depthActive }));
    assert.equal(after.n, before.n);
    assert.equal(after.bar.time, before.bar.time);
    assert.equal(after.bar.open, before.bar.open);
    assert.equal(after.bar.close, 111.25);
    assert.equal(after.bar.volume, before.bar.volume);
    assert.equal(after.depth, true);
    assert(report.websocket.some((m) => m.action === 'subscribe' && [3, 'Depth'].includes(m.mode)));
    assert(!report.websocket.some((m) => m.action === 'subscribe' && [1, 'LTP'].includes(m.mode) && (m.symbol === 'BHEL' || m.symbols?.some((s) => s.symbol === 'BHEL'))));
  });
  await check('history reconciliation repairs volume without replacing the live price', async () => {
    const before = await terminal((t) => ({ first: t.rawBars[0], last: t.rawBars.at(-1) }));
    historyVolumeBoost = 7000;
    await terminal((t) => t.runReconcile());
    const after = await terminal((t) => ({ first: t.rawBars[0], last: t.rawBars.at(-1) }));
    assert.equal(after.first.volume, before.first.volume + 7000);
    assert.equal(after.last.volume, before.last.volume + 7000);
    assert.equal(after.last.close, before.last.close);
    await sendDepth('BHEL', 'NSE', 112);
    assert.equal(await terminal((t) => t.rawBars.at(-1).volume), after.last.volume);
  });
  await check('disarmed chart click opens ticket without order; armed path sends derivative units', async () => {
    await terminal(async (t, symbol) => { await t.loadSymbol(symbol); t.setQty(2); t.setArmed(false); t.placeCtx('BUY', 'MARKET'); }, symbols[1]);
    await page.getByRole('dialog').waitFor();
    assert.equal(orderCounter, 0);
    await page.keyboard.press('Escape');
    await expect(page.locator('[data-slot="dialog-overlay"]')).toHaveCount(0);
    await waitDialogClosed();
    await waitReady();
    await terminal((t) => { t.setArmed(true); t.placeCtx('BUY', 'MARKET'); });
    await page.waitForFunction(() => document.body.innerText.includes('fixture-1'));
    const order = report.requests.findLast((r) => r.path === '/api/v1/placeorder').body;
    assert.equal(order.quantity, 130);
    assert.equal(order.symbol, 'NIFTY29SEP26FUT');
    assert.equal(order.exchange, 'NFO');
    assert.equal(order.product, 'MIS');
    assert.equal(order.action, 'BUY');
    assert.equal(order.pricetype, 'MARKET');
    assert.equal(order.mode, undefined);
  });
  await check('mode mismatch refuses the ticket before submitting an order', async () => {
    analyzer = true;
    await page.evaluate(now => { window.__compatFixedNow = now; }, fixedNow + 1);
    const count = orderCounter;
    const refusal = await terminal(async (t) => {
      await t.trade.getServerMode(0);
      try {
        await t.placeTicket({ symbol: t.sym.symbol, exchange: t.sym.exchange, action: 'BUY', pricetype: 'MARKET', product: 'MIS', quantity: 65 });
        return null;
      } catch (error) { return error.message; }
    });
    assert.match(refusal, /mode/);
    assert.equal(orderCounter, count);
    analyzer = false;
    await page.evaluate(now => { window.__compatFixedNow = now; }, fixedNow + 6000);
    await terminal((t) => t.trade.getServerMode(0));
  });
  await check('WS order update and canvas drag/cancel preserve stop-limit context', async () => {
    mockOrders = [{ orderid: 'fixture-open', symbol: symbols[1].symbol, exchange: 'NFO', action: 'BUY', pricetype: 'SL', product: 'NRML', quantity: '130', price: '102.5', trigger_price: '102', order_status: 'trigger pending', filled_quantity: '0' }];
    mockPositions = [{ symbol: symbols[1].symbol, exchange: 'NFO', product: 'NRML', quantity: '-65', average_price: '99' }];
    for (const socket of sockets) {
      try { socket.send(JSON.stringify({ ...mockOrders[0], type: 'order_update', mode: 'live' })); } catch { /* closed StrictMode socket */ }
    }
    await page.waitForFunction(() => window.__compatTerminals.some((t) => !t.destroyed && t.orderLines.get('fixture-open')?.order.qty === 130));
    await terminal((t) => t.pollBook());
    await page.waitForFunction(() => window.__compatTerminals.some((t) => !t.destroyed && t.orderLines.get('fixture-open')?.line._group));
    const points = await terminal((t) => {
      const box = t.container.getBoundingClientRect();
      const group = t.orderLines.get('fixture-open').line._group;
      return { x: box.x + (group.x0 + group.closeX0) / 2, y: box.y + t.chart.priceToCoordinate(102, 0), toY: box.y + t.chart.priceToCoordinate(103, 0) };
    });
    report.dragPoints = points;
    report.dragTarget = await page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.outerHTML.slice(0, 500), points);
    await page.mouse.move(points.x, points.y);
    await page.mouse.down();
    await page.mouse.move(points.x, points.toY, { steps: 5 });
    await page.mouse.up();
    await page.waitForFunction(() => window.__compatTerminals.some((t) => !t.destroyed && t.orderLines.get('fixture-open')?.order.triggerPrice !== 102), null, { timeout: 3000 });
    const modify = report.requests.findLast((r) => r.path === '/api/v1/modifyorder').body;
    assert(Math.abs(modify.trigger_price - 103) <= 0.1);
    assert(Math.abs(modify.trigger_price * 20 - Math.round(modify.trigger_price * 20)) < 1e-8);
    assert.equal(modify.price, 102.5);
    assert.equal(modify.quantity, 130);
    assert.equal(modify.product, 'NRML');
    assert.equal(modify.exchange, 'NFO');
    const close = await terminal((t) => {
      const box = t.container.getBoundingClientRect();
      const group = t.orderLines.get('fixture-open').line._group;
      return { x: box.x + (group.closeX0 + group.x1) / 2, y: box.y + t.chart.priceToCoordinate(t.orderLines.get('fixture-open').line.price, 0) };
    });
    await page.mouse.click(close.x, close.y);
    await page.waitForFunction(() => window.__compatTerminals.some((t) => !t.destroyed && !t.orderLines.has('fixture-open')));
    assert.equal(report.requests.findLast((r) => r.path === '/api/v1/cancelorder').body.orderid, 'fixture-open');
    const before = orderCounter;
    await terminal((t) => t.exitPosition());
    assert.equal(orderCounter, before + 1);
    const exit = report.requests.findLast((r) => r.path === '/api/v1/placeorder').body;
    assert.equal(exit.action, 'BUY');
    assert.equal(exit.quantity, 65);
    assert.equal(exit.product, 'NRML');
    mockPositions = [];
  });
  await check('replay selection and playback block orders while live data remains isolated', async () => {
    const count = orderCounter;
    await terminal((t) => t.startReplay());
    assert.equal(await terminal((t) => t.replayPickingBar()), true);
    await terminal((t) => { t.placeCtx('SELL', 'MARKET'); t.exitPosition(); });
    const refusal = await terminal(async (t) => { try { await t.placeTicket({}); return null; } catch (error) { return error.message; } });
    assert.match(refusal, /Replay/);
    await terminal((t) => t.commitReplayPick());
    await page.waitForFunction(() => window.__compatTerminals.some((t) => !t.destroyed && t.replayActive()));
    const before = await terminal((t) => ({ n: t.price.getData().length, total: t.rawBars.length, last: t.price.getData().at(-1) }));
    assert(before.n < before.total);
    await sendDepth('NIFTY29SEP26FUT', 'NFO', 115.5);
    const after = await terminal((t) => ({ n: t.price.getData().length, last: t.price.getData().at(-1), live: t.rawBars.at(-1).close }));
    assert.equal(after.n, before.n);
    assert.deepEqual(after.last, before.last);
    assert.equal(after.live, 115.5);
    await terminal((t) => { t.placeCtx('SELL', 'MARKET'); t.replayStep(); t.stopReplay(); });
    assert.equal(orderCounter, count);
    assert.equal(await terminal((t) => t.price.getData().at(-1).close), 115.5);
  });
  if (args['probe-host']) {
    await terminal((t) => t.startReplay(10));
    await page.waitForFunction(() => window.__compatTerminals.some((t) => !t.destroyed && t.replayActive()));
    const before = await terminal((t) => t.price.getData().length);
    await terminal((t) => t.runReconcile());
    const after = await terminal((t) => ({ visibleBars: t.price.getData().length, sourceBars: t.rawBars.length, replayActive: t.replayActive() }));
    report.hostReconcileProbe = { before, ...after, overwroteReplay: after.visibleBars > before };
    console.log(`OBSERVATION host history reconciliation during replay: ${JSON.stringify(report.hostReconcileProbe)}`);
    await terminal((t) => t.stopReplay());
  }
  await check('persisted drawings, indicator, grid and interval survive reload', async () => {
    await terminal(async (t) => {
      await t.applyChartCommands([{ op: 'draw', group: 'compat', shapes: [{ kind: 'level', price: 103, label: 'Compatibility' }] }]);
      await t.addIndicatorById('ema');
      t.setGrid(false, false);
      t.setInterval('15m');
    });
    await page.waitForFunction(() => window.__compatTerminals.some((t) => !t.destroyed && t.interval === '15m' && t.draw?.toJSON().drawings.length));
    await reload();
    await waitReady();
    await page.waitForFunction(() => window.__compatTerminals.some((t) => !t.destroyed && t.draw?.toJSON().drawings.length));
    const state = await terminal((t) => ({ interval: t.interval, symbol: t.sym.symbol, drawings: t.draw.toJSON().drawings, indicators: t.activeIndicators, gridV: t.gridV, gridH: t.gridH }));
    assert.equal(state.interval, '15m');
    assert.equal(state.symbol, 'NIFTY29SEP26FUT');
    assert.equal(state.drawings[0].id, 'ai:compat:0');
    assert(state.indicators.some((i) => i.indicatorId === 'ema'));
    assert.equal(state.gridV, false);
    assert.equal(state.gridH, false);
  });
  await check('runtime custom indicator receives the shared chart API and survives reload', async () => {
    await terminal((t) => t.addIndicatorById('compat-close'));
    await page.waitForFunction(() => window.__compatCustomCalls > 0);
    await reload();
    await waitReady();
    await page.waitForFunction(() => window.__compatCustomCalls > 0);
    assert(await terminal((t) => t.listIndicators().some((indicator) => indicator.indicatorId === 'compat-close')));
  });
  await check('saved TPO and session volume profiles attach and survive live updates', async () => {
    for (const kind of ['tpo', 'session-volume-profile']) {
      await terminal(async (t, kind) => { t.setChartType(kind); await t.profileLayer?.ready; }, kind);
      await reload();
      await waitReady();
      await terminal(async (t) => t.profileLayer?.ready);
      assert.equal(await terminal((t) => t.ctype), kind);
      assert.equal(await terminal((t) => !!t.profileLayer?.primitive), true);
      await sendDepth('NIFTY29SEP26FUT', 'NFO', kind === 'tpo' ? 116 : 117);
      await terminal((t) => t.profileLayer.refresh(true));
      assert.equal(await terminal((t) => t.profileLayer.primitive.warning()), null);
    }
  });
  await check('daily broker interval and quote-only symbol retain correct contracts', async () => {
    await terminal(async (t, symbol) => { t.setChartType('candlestick'); await t.loadSymbol(symbol); t.setInterval('D'); }, symbols[2]);
    await page.waitForFunction(() => window.__compatTerminals.some((t) => !t.destroyed && t.interval === 'D' && t.price?.getData().length === 3));
    await waitReady();
    assert(report.requests.some((r) => r.path === '/api/v1/history' && r.body.interval === 'D'));
    assert.equal(await terminal((t) => t.tradeBtns), null);
    assert.equal(await terminal((t) => t.sym.tick), 0.05);
    assert.equal(await terminal((t) => t.builder), null);
    assert(report.websocket.some((m) => m.action === 'subscribe' && [1, 'LTP'].includes(m.mode)));
  });
  await check('two-pane layout restores independent pane state after reload', async () => {
    await page.getByRole('button', { name: 'Chart layout: Single' }).click();
    await page.getByTitle('2 columns', { exact: true }).click();
    const waitTwo = () => page.waitForFunction(() => window.__compatTerminals.filter((t) => !t.destroyed && t.price?.getData().length > 0).length === 2);
    await waitTwo();
    await reload();
    await waitTwo();
    assert.equal(await page.evaluate(() => localStorage.getItem('oa-trading-layout')), 'cols2');
    const panes = await page.evaluate(() => window.__compatTerminals.filter((t) => !t.destroyed && t.chart).map((t) => ({ key: t.sk, interval: t.interval, symbol: t.sym.symbol })));
    assert.equal(panes.find((p) => p.key === 'oa-trading-p0').symbol, 'NIFTY');
    assert.equal(panes.find((p) => p.key === 'oa-trading-p0').interval, 'D');
    assert.equal(panes.find((p) => p.key === 'oa-trading-p1').symbol, 'BHEL');
    assert.equal(panes.find((p) => p.key === 'oa-trading-p1').interval, '5m');
  });
  if (args.objects === 'true') {
    await check('Objects follows the pane last used anywhere inside its card', async () => {
      await page.evaluate(() => {
        const pane = window.__compatTerminals.find((t) => !t.destroyed && t.sk === 'oa-trading-p0');
        pane.container.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
      });
      await page.getByRole('button', { name: 'Objects' }).click();
      await page.getByRole('complementary', { name: 'Objects' }).getByText(/Pane 1/).waitFor();
      await page.evaluate(() => {
        const pane = window.__compatTerminals.find((t) => !t.destroyed && t.sk === 'oa-trading-p1');
        pane.container.closest('section').focus();
      });
      await page.getByRole('complementary', { name: 'Objects' }).getByText(/Pane 2/).waitFor();
    });
    await check('indicator visibility and actionable identity survive rebuild and reload', async () => {
      const details = await page.evaluate(async () => {
        const pane = window.__compatTerminals.find((t) => !t.destroyed && t.sk === 'oa-trading-p1');
        await pane.addIndicatorById('ema');
        const row = pane.objects.list().find((object) => object.kind === 'indicator');
        return { id: row.id, name: row.name };
      });
      const panel = page.getByRole('complementary', { name: 'Objects' });
      await panel.getByRole('button', { name: `Hide ${details.name}` }).click();
      assert.equal(await page.evaluate(() => {
        const pane = window.__compatTerminals.find((t) => !t.destroyed && t.sk === 'oa-trading-p1');
        return pane.objects.list().find((object) => object.kind === 'indicator').visible;
      }), false);
      await page.evaluate(() => {
        const pane = window.__compatTerminals.find((t) => !t.destroyed && t.sk === 'oa-trading-p1');
        pane.setInterval('15m');
      });
      await page.waitForFunction((oldId) => {
        const pane = window.__compatTerminals.find((t) => !t.destroyed && t.sk === 'oa-trading-p1');
        const row = pane?.objects?.list().find((object) => object.kind === 'indicator');
        return row && row.id === oldId && row.visible === false
          && !pane.dataUnavailable() && pane.chart.getDataContext()?.interval === '15m';
      }, details.id);
      await panel.getByRole('button', { name: `Settings for ${details.name}` }).click();
      await page.getByRole('heading', { name: details.name }).waitFor();
      await page.keyboard.press('Escape');
      await reload();
      await page.waitForFunction(() => window.__compatTerminals.filter((t) => !t.destroyed && t.price?.getData().length > 0).length === 2);
      await page.evaluate(() => {
        const pane = window.__compatTerminals.find((t) => !t.destroyed && t.sk === 'oa-trading-p1');
        pane.container.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
      });
      await page.waitForFunction(() => {
        const pane = window.__compatTerminals.find((t) => !t.destroyed && t.sk === 'oa-trading-p1');
        return pane?.objects?.list().some((object) => object.kind === 'indicator');
      });
      const hidden = await page.evaluate(() => {
        const pane = window.__compatTerminals.find((t) => !t.destroyed && t.sk === 'oa-trading-p1');
        const row = pane.objects.list().find((object) => object.kind === 'indicator');
        return { model: row.visible, saved: pane.activeIndicators.find((item) => item.indicatorId === 'ema')?.visible };
      });
      assert.deepEqual(hidden, { model: false, saved: false });
      await panel.getByRole('button', { name: `Show ${details.name}` }).click();
      assert.equal(await page.evaluate(() => {
        const pane = window.__compatTerminals.find((t) => !t.destroyed && t.sk === 'oa-trading-p1');
        return pane.objects.list().find((object) => object.kind === 'indicator').visible;
      }), true);
    });
    await check('drawing object actions reuse selection, editor, history and persistence', async () => {
      await page.evaluate(async () => {
        const pane = window.__compatTerminals.find((t) => !t.destroyed && t.sk === 'oa-trading-p1');
        await pane.setDrawTool(null);
        pane.draw.add({ id: 'ai:objects-text:0', tool: 'text', paneIndex: 0,
          points: [{ time: pane.rawBars.at(-2).time, price: 100 }], style: { color: '#4f8cff' },
          text: { value: 'Object note' } });
      });
      const panel = page.getByRole('complementary', { name: 'Objects' });
      await panel.getByRole('button', { name: 'Select Text' }).click();
      await page.getByRole('button', { name: 'Colour' }).waitFor();
      await panel.getByRole('button', { name: 'Settings for Text' }).click();
      await page.getByRole('heading', { name: 'Text' }).waitFor();
      await page.keyboard.press('Escape');
      await panel.getByRole('button', { name: 'Lock Text' }).click();
      await panel.getByRole('button', { name: 'Hide Text' }).click();
      await panel.getByRole('button', { name: 'Focus Text' }).click();
      const changed = await page.evaluate(() => {
        const pane = window.__compatTerminals.find((t) => !t.destroyed && t.sk === 'oa-trading-p1');
        const drawing = pane.draw.get('ai:objects-text:0');
        return { locked: drawing.locked, visible: drawing.visible, saved: pane.drawJson.drawings.some((d) => d.id === drawing.id && d.locked && d.visible === false) };
      });
      assert.deepEqual(changed, { locked: true, visible: false, saved: true });
      await panel.getByRole('button', { name: 'Remove Text' }).click();
      assert.equal(await page.evaluate(() => {
        const pane = window.__compatTerminals.find((t) => !t.destroyed && t.sk === 'oa-trading-p1');
        return pane.draw.get('ai:objects-text:0');
      }), undefined);
      await page.evaluate(() => {
        const pane = window.__compatTerminals.find((t) => !t.destroyed && t.sk === 'oa-trading-p1');
        pane.undoDraw();
      });
      assert.equal(await page.evaluate(() => {
        const pane = window.__compatTerminals.find((t) => !t.destroyed && t.sk === 'oa-trading-p1');
        return pane.draw.get('ai:objects-text:0')?.id;
      }), 'ai:objects-text:0');
      await panel.getByRole('button', { name: 'Show Text' }).click();
      await panel.getByRole('button', { name: 'Unlock Text' }).click();
      assert.deepEqual(await page.evaluate(() => {
        const pane = window.__compatTerminals.find((t) => !t.destroyed && t.sk === 'oa-trading-p1');
        const drawing = pane.draw.get('ai:objects-text:0');
        return { visible: drawing.visible, locked: drawing.locked };
      }), { visible: true, locked: false });
    });
    await check('profile object is settings-only and Objects sends no orders during replay', async () => {
      const ordersBefore = report.requests.filter((request) => ['/api/v1/placeorder', '/api/v1/modifyorder', '/api/v1/cancelorder'].includes(request.path)).length;
      await page.evaluate(async () => {
        const pane = window.__compatTerminals.find((t) => !t.destroyed && t.sk === 'oa-trading-p1');
        pane.setChartType('tpo');
        await pane.profileLayer?.ready;
      });
      const panel = page.getByRole('complementary', { name: 'Objects' });
      await panel.getByText('Time Price Opportunity').waitFor();
      assert.equal(await panel.getByRole('button', { name: 'Hide Time Price Opportunity' }).count(), 0);
      assert.equal(await panel.getByRole('button', { name: 'Remove Time Price Opportunity' }).count(), 0);
      assert.equal(await panel.getByRole('button', { name: 'Lock Time Price Opportunity' }).count(), 0);
      assert.equal(await panel.getByRole('button', { name: 'Focus Time Price Opportunity' }).count(), 0);
      await page.evaluate(() => {
        const pane = window.__compatTerminals.find((t) => !t.destroyed && t.sk === 'oa-trading-p1');
        pane.startReplay(); pane.commitReplayPick();
      });
      await panel.getByRole('button', { name: 'Settings for Time Price Opportunity' }).click();
      const chartSettings = page.getByRole('heading', { name: 'Chart settings' });
      await chartSettings.waitFor();
      await page.keyboard.press('Escape');
      await chartSettings.waitFor({ state: 'detached' });
      await panel.getByRole('button', { name: /Settings for/ }).first().click();
      await chartSettings.waitFor();
      await page.keyboard.press('Escape');
      await chartSettings.waitFor({ state: 'detached' });
      const ordersAfter = report.requests.filter((request) => ['/api/v1/placeorder', '/api/v1/modifyorder', '/api/v1/cancelorder'].includes(request.path)).length;
      assert.equal(ordersAfter, ordersBefore);
      await page.evaluate(() => {
        const pane = window.__compatTerminals.find((t) => !t.destroyed && t.sk === 'oa-trading-p1');
        pane.stopReplay();
      });
    });
  }
  if (args.foundations === 'true') {
    await check('interval sync is selectable in the real workspace and survives reload', async () => {
      await page.evaluate(() => {
        for (const pane of window.__compatTerminals.filter(t => !t.destroyed)) {
          pane.stopReplay();
          pane.setChartType('candlestick');
        }
      });
      await page.getByRole('button', { name: 'Chart sync', exact: true }).click();
      await page.getByRole('checkbox', { name: 'Interval', exact: true }).check();
      await page.keyboard.press('Escape');
      await terminal(t => t.setInterval('15m'));
      const bothReady = async () => {
        try {
          await page.waitForFunction(() => {
            const panes = window.__compatTerminals.filter(t => !t.destroyed);
            return panes.length === 2 && panes.every(t => t.interval === '15m' && t.chart?.getDataContext()?.interval === '15m');
          });
        } catch (error) {
          report.foundationPanes = await page.evaluate(() => window.__compatTerminals.map(t => ({
            key: t.sk, destroyed: t.destroyed, interval: t.interval, context: t.chart?.getDataContext(),
            groupInterval: t.link?.interval(), options: t.link?.options(),
          })));
          throw error;
        }
      };
      await bothReady();
      await reload();
      await bothReady();
      assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('oa-trading-sync')).interval), true);
    });
    await check('settings expose candle-center snapping and volume averages on the existing scale', async () => {
      await terminal(async t => t.cb.onChartSettings(await t.chartSettings()));
      await page.getByRole('button', { name: 'Appearance', exact: true }).click();
      await page.getByRole('checkbox', { name: 'Snap to candle center', exact: true }).check();
      await page.getByRole('button', { name: 'Volume', exact: true }).click();
      await page.getByRole('checkbox', { name: 'Show moving average', exact: true }).check();
      await page.getByRole('spinbutton', { name: 'Period', exact: true }).fill('3');
      await page.getByRole('button', { name: 'Ok', exact: true }).click();
      await waitDialogClosed();
      await page.waitForFunction(() => window.__compatTerminals.some(t => !t.destroyed && t.chart?.crosshairSnapToBar()));
      const volume = await terminal(t => ({
        sameScale: t.volumeMA.priceScale() === t.volume.priceScale(),
        bars: t.volume.getData(), average: t.volumeMA.getData(),
        price: t.price.getData(), style: t.chart.primarySeriesInfo().style, theme: t.chart.theme(),
      }));
      assert.equal(volume.sameScale, true);
      assert(volume.average.length > 3);
      assert.equal(volume.average[0].close, NaN);
      for (let i = 2; i < volume.average.length; i++) {
        const expected = (volume.bars[i - 2].close + volume.bars[i - 1].close + volume.bars[i].close) / 3;
        assert(Math.abs(volume.average[i].close - expected) < 1e-8);
      }
      assert(volume.bars.every((b, i) => b.color === (volume.price[i].close >= volume.price[i].open
        ? volume.style.upColor ?? volume.theme.upColor : volume.style.downColor ?? volume.theme.downColor)));
      await reload();
      await waitReady();
      await page.waitForFunction(() => window.__compatTerminals.some(t => !t.destroyed && t.volumeMA?.getData().length > 3));
      assert.equal(await terminal(t => t.chart.crosshairSnapToBar()), true);
    });
    await check('volume average stays on the replay prefix while its period changes', async () => {
      await terminal(t => t.beginReplayAt(3));
      await terminal(t => t.applyChartSettings({ 'volume.maPeriod': 2 }));
      const counts = await terminal(t => ({ price: t.price.getData().length, volume: t.volume.getData().length, average: t.volumeMA.getData().length }));
      assert.deepEqual(counts, { price: 4, volume: 4, average: 4 });
      await terminal(t => t.stopReplay());
      assert(await terminal(t => t.volumeMA.getData().length > 4));
    });
    await check('volume direction renders in both theme palettes after chart rebuilds', async () => {
      for (const mode of ['dark', 'light']) {
        const toggle = page.getByRole('button', { name: `Switch to ${mode} mode`, exact: true });
        if (await toggle.count()) await toggle.click();
        await page.waitForFunction(mode => window.__compatTerminals.filter(t => !t.destroyed)
          .every(t => t.getTheme().mode === mode), mode);
        await terminal(t => {
          t.rawBars = t.rawBars.map((bar, index) => ({ ...bar, close: bar.open + (index % 2 ? -0.4 : 0.4) }));
          t.setPriceData();
        });
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        const paint = await terminal(t => {
          const palette = t.volumeCandleStyle();
          const volumes = t.volume.getData();
          const colors = [...new Set(volumes.map(bar => bar.color))];
          const probe = document.createElement('canvas').getContext('2d');
          const wanted = colors.map(color => {
            probe.fillStyle = color;
            probe.fillRect(0, 0, 1, 1);
            return [...probe.getImageData(0, 0, 1, 1).data].slice(0, 3);
          });
          const ink = wanted.map(() => 0);
          for (const canvas of t.container.querySelectorAll('canvas')) {
            const context = canvas.getContext('2d');
            if (!context || !canvas.width || !canvas.height) continue;
            const start = Math.floor(canvas.height * 0.9);
            const pixels = context.getImageData(0, start, canvas.width, canvas.height - start).data;
            for (let i = 0; i < pixels.length; i += 4) {
              wanted.forEach((rgb, index) => {
                if (pixels[i + 3] > 200 && rgb.every((value, channel) => Math.abs(value - pixels[i + channel]) < 4)) ink[index]++;
              });
            }
          }
          return { colors, expected: [palette.upColor, palette.downColor], ink };
        });
        assert.deepEqual(paint.colors.sort(), paint.expected.sort());
        assert(paint.ink.every(count => count > 30), `${mode} volume pixels: ${paint.ink}`);
        if (args.screenshot) await page.screenshot({ path: resolve(args.screenshot.replace(/\.png$/, `-${mode}.png`)), fullPage: true });
      }
    });
  }
  if (args.templates === 'true') {
    await check('named study templates preserve repeated instances on the focused chart and reload', async () => {
      const originalOrderCount = orderCounter;
      assert.equal(await page.getByRole('button', { name: 'Templates', exact: true }).count(), 1);
      const studies = [
        { indicatorId: 'ema', settings: { length: 9, 'plot.ema.color': '#ff9800' }, paneIndex: 0, visible: true },
        { indicatorId: 'ema', settings: { length: 9, 'plot.ema.color': '#ff9800' }, paneIndex: 0, visible: true },
        { indicatorId: 'rsi', settings: { length: 14 }, paneIndex: 1, visible: false },
        { indicatorId: 'rsi', settings: { length: 21 }, paneIndex: 1, visible: true },
      ];
      await terminal((t, list) => t.applyIndicatorTemplate(list, 'replace'), studies);
      const targetKey = await terminal(t => t.sk);
      const focus = async () => {
        const box = await terminal(t => { const r = t.container.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; });
        await page.mouse.click(box.x, box.y);
      };
      const snapshots = () => page.evaluate(() => window.__compatTerminals.filter(t => !t.destroyed).map(t => ({
        key: t.sk, studies: t.captureIndicatorTemplate(), bars: t.price.getData().length, range: t.chart.getVisibleLogicalRange(),
      })));
      await focus();
      const before = await snapshots();
      const expected = before.find(item => item.key === targetKey).studies;
      await page.getByRole('button', { name: 'Templates', exact: true }).click();
      await page.getByLabel('New template name', { exact: true }).fill('Study group');
      await page.getByRole('button', { name: 'Save current studies', exact: true }).click();
      await page.getByRole('status').filter({ hasText: 'Template saved' }).waitFor();
      await page.getByRole('button', { name: 'Close', exact: true }).click();
      await waitDialogClosed();
      await terminal(t => t.applyIndicatorTemplate([], 'replace'));
      await terminal((t, symbol) => t.loadSymbol(symbol), symbols[0]);
      await waitReady();
      await focus();
      const cleared = await snapshots();
      await page.getByRole('button', { name: 'Templates', exact: true }).click();
      await page.getByRole('button', { name: 'Replace studies', exact: true }).click();
      await page.getByRole('status').filter({ hasText: 'Studies replaced' }).waitFor();
      const applied = await snapshots();
      assert.deepEqual(applied.find(item => item.key === targetKey).studies, expected);
      for (const pane of applied) {
        const prior = cleared.find(item => item.key === pane.key);
        assert.equal(pane.bars, prior.bars);
        assert.deepEqual(pane.range, prior.range);
        if (pane.key !== targetKey) assert.deepEqual(pane.studies, before.find(item => item.key === pane.key).studies);
      }
      await page.getByRole('button', { name: 'Close', exact: true }).click();
      await waitDialogClosed();
      await reload();
      await waitReady();
      await page.waitForFunction(({ key, count }) => window.__compatTerminals.some(t => !t.destroyed && t.sk === key && t.chart?.indicators().length === count), { key: targetKey, count: expected.length });
      assert.deepEqual((await snapshots()).find(item => item.key === targetKey).studies, expected);
      await focus();
      await page.getByRole('button', { name: 'Templates', exact: true }).click();
      await page.getByLabel('Saved template', { exact: true }).selectOption({ label: 'Study group' });
      if (args.screenshot) await page.screenshot({ path: resolve(args.screenshot.replace(/\.png$/, '-templates.png')), fullPage: true, animations: 'disabled' });
      assert.equal(orderCounter, originalOrderCount);
      await page.getByRole('button', { name: 'Close', exact: true }).click();
      await waitDialogClosed();
    });
  }
  if (args.templates === 'true') {
    await check('template imports, exports and storage failures preserve the chart and catalog', async () => {
      const ordersBefore = orderCounter;
      const before = await terminal(t => t.captureIndicatorTemplate());
      await page.getByRole('button', { name: 'Templates', exact: true }).click();
      await page.getByLabel('Saved template', { exact: true }).selectOption({ label: 'Study group' });
      const downloadPromise = page.waitForEvent('download');
      await page.getByRole('button', { name: 'Export JSON', exact: true }).click();
      const download = await downloadPromise;
      const stream = await download.createReadStream();
      const chunks = []; for await (const chunk of stream) chunks.push(chunk);
      const exported = JSON.parse(Buffer.concat(chunks).toString());
      assert.equal(exported.kind, 'indicator-template');
      assert.deepEqual(exported.indicators, before);
      const upload = async (name, indicators) => {
        const doc = { kind: 'indicator-template', version: 1, id: 'imported', name, createdAt: 1, updatedAt: 1, indicators };
        const input = page.getByLabel('Import template JSON', { exact: true });
        await expect(input).toBeEnabled();
        await input.setInputFiles({ name: 'template.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(doc)) });
        await page.getByRole('status').filter({ hasText: 'Template imported' }).waitFor();
      };
      await upload('Unavailable custom study', [{ indicatorId: 'absent-local-study', settings: {}, paneIndex: 1 }]);
      await page.getByRole('button', { name: 'Replace studies', exact: true }).click();
      await page.getByRole('alert').filter({ hasText: 'absent-local-study' }).waitFor();
      assert.deepEqual(await terminal(t => t.captureIndicatorTemplate()), before);
      await upload('Empty studies', []);
      await page.getByRole('button', { name: 'Replace studies', exact: true }).click();
      await page.getByRole('status').filter({ hasText: 'Studies replaced' }).waitFor();
      assert.deepEqual(await terminal(t => t.captureIndicatorTemplate()), []);
      await page.getByLabel('Saved template', { exact: true }).selectOption({ label: 'Study group' });
      await page.getByRole('button', { name: 'Replace studies', exact: true }).click();
      await page.getByRole('status').filter({ hasText: 'Studies replaced' }).waitFor();
      await page.evaluate(() => {
        window.__originalCatalogPut = IDBObjectStore.prototype.put;
        IDBObjectStore.prototype.put = function(...args) {
          if (this.name === 'catalogs') throw new DOMException('Fixture storage rejected', 'QuotaExceededError');
          return window.__originalCatalogPut.apply(this, args);
        };
      });
      await page.getByLabel('New template name', { exact: true }).fill('Rejected save');
      await page.getByRole('button', { name: 'Save current studies', exact: true }).click();
      await page.getByRole('alert').filter({ hasText: 'Fixture storage rejected' }).waitFor();
      assert.equal(await page.getByLabel('New template name', { exact: true }).inputValue(), 'Rejected save');
      assert.equal(await page.getByRole('option', { name: 'Rejected save', exact: true }).count(), 0);
      await page.evaluate(() => { IDBObjectStore.prototype.put = window.__originalCatalogPut; delete window.__originalCatalogPut; });
      await page.getByRole('button', { name: 'Refresh templates', exact: true }).click();
      await page.getByRole('status').filter({ hasText: 'Templates refreshed' }).waitFor();
      assert.equal(await page.getByRole('option', { name: 'Rejected save', exact: true }).count(), 0);
      await page.setViewportSize({ width: 390, height: 844 });
      // Resizing starts a max-width transition; measure its finished layout.
      await page.getByRole('dialog', { name: 'Indicator templates' }).evaluate(el => {
        for (const animation of el.getAnimations()) animation.finish();
      });
      const dimensions = await page.getByRole('dialog', { name: 'Indicator templates' }).evaluate(el => ({ width: el.getBoundingClientRect().width, scroll: el.scrollWidth, client: el.clientWidth }));
      assert(dimensions.width <= 358 && dimensions.scroll <= dimensions.client + 1);
      if (args.screenshot) await page.screenshot({ path: resolve(args.screenshot.replace(/\.png$/, '-templates-mobile.png')), fullPage: true, animations: 'disabled' });
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.getByRole('button', { name: 'Close', exact: true }).click();
      await waitDialogClosed();
      assert.equal(orderCounter, ordersBefore);
    });
  }
  if (args.correctness === 'true') await checkChartCorrectness({ page, terminal, report, sendDepth, screenshot: args.screenshot });
  if (args.oi === 'true') await checkOpenInterest({ page, terminal, check, reload, sendDepth, screenshot: args.screenshot, orderCount: () => orderCounter });
  if (args.alerts === 'true') await checkAlerts({ page, terminal, check, reload, sendDepth, screenshot: args.screenshot, orderCount: () => orderCounter, hostFinding });
  if (args.workspaces === 'true') await checkWorkspaces({ page, check, reload, screenshot: args.screenshot, orderCount: () => orderCounter, sendDepth });
  if (args['consumer-checks']) {
    // The consumer's checks start from an intraday grid: they wait for more
    // than ten bars in every pane, and the core checks end with a daily pane
    // of three. Leave replay and return every pane to 5m first.
    await page.evaluate(() => {
      for (const t of window.__compatTerminals.filter(t => !t.destroyed && t.chart)) { t.stopReplay(); t.setInterval('5m'); }
    });
    await page.waitForFunction(() => window.__compatTerminals.filter(t => !t.destroyed && t.chart)
      .every(t => t.interval === '5m' && !t.dataUnavailable() && t.price?.getData().length > 10));
    const file = resolve(args['consumer-checks']);
    report.consumerChecks = { file, sha256: createHash('sha256').update(await readFile(file)).digest('hex') };
    const { checkTradingWorkspace } = await import(pathToFileURL(file).href);
    assert.equal(typeof checkTradingWorkspace, 'function', 'Consumer module must export checkTradingWorkspace');
    await checkTradingWorkspace({ page, check, expect, report, reload, sendDepth, sendLtp, waitForSubscription,
      screenshot: args.screenshot, output: args.output, orderCount: () => orderCounter });
  }
  await check('no browser runtime errors or external HTTP', async () => {
    await Promise.all(consoleReads);
    // WebKit reports fetches cancelled/refused on a departing document as
    // pageerrors even when caught. Classify only this network diagnostic during
    // reload, to caught fixture API/index reads; window errors/rejections fail.
    report.reloadNetworkNotices = [];
    const unexpected = report.pageErrorDetails.filter(error => {
      const url = error.stack?.match(/^(?:Fetch API|XMLHttpRequest) cannot load (https?:\/\/\S+) due to access control checks\./)?.[1];
      const departing = browserType === webkit && error.duringReload
        && (url?.startsWith(`${origin}/api/`) || url?.startsWith(`${origin}/socket.io/`)
          || url === `${origin}/custom-indicators/index.json` || url === `${origin}/openscript/index.json`);
      if (departing) report.reloadNetworkNotices.push({ ...error, url,
        cancelledRequestObserved: report.failedRequests.some(request => request.url === url && request.failure?.errorText === 'Load request cancelled'),
      });
      return !departing;
    });
    assert.deepEqual(unexpected, []);
    assert.deepEqual(report.runtimeEvents, []);
    assert.deepEqual(report.consoleErrors.filter((message) => !message.startsWith('Failed to load resource:') && !message.includes('refusing to place, caller expects live mode but the OpenAlgo server is in analyzer mode')), []);
    assert.deepEqual(report.blocked, []);
  });
  if (args.screenshot) await page.screenshot({ path: resolve(args.screenshot), fullPage: true });
  await context.close();
} catch (error) {
  report.failure = error.stack ?? String(error);
  if (page) report.failurePage = { url: page.url(), text: await page.locator('body').innerText().catch(() => '') };
  console.error(report.failure);
  process.exitCode = 1;
} finally {
  await browser?.close();
  await server.close();
  await rm(cache, { recursive: true, force: true });
  if (args.output) await writeFile(resolve(args.output), `${JSON.stringify(report, null, 2)}\n`);
  console.log(`${report.label}: ${report.checks.length} browser compatibility checks passed`);
  if (report.hostFindings?.length) console.log(`${report.label}: ${report.hostFindings.length} host finding(s), listed above`);
}
