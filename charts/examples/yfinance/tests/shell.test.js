// The shell furniture in ui.js: toasts, the overlay stack, the chart-state
// card and the theme switch. All of it runs against a small document double
// below, which models exactly what the code reads: a tree, `hidden`, focus,
// attributes and a handful of selectors.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { darkTheme, lightTheme } from '/dist/openalgo-charts.mjs';
import {
  toast, TOAST_MS, TOAST_MAX, TOAST_LEAVE_MS,
  openOverlay, closeOverlay, closeTopOverlay, topOverlay, openOverlays, overlayKeydown, overlayMutations,
  focusable, focusables, tabTarget, isOverlayNode,
  setChartState, chartState, LOADING_DELAY_MS,
  setTheme, toggleTheme, currentTheme, chartTheme, THEME_KEY,
  announce, initShell, initOverlays,
} from '../src/ui.js';

// ── a document double ──────────────────────────────────────────────────
// The listener maps outlive each test's document: ui.js wires its focus
// and key listeners once per page, and a fresh document per test still has
// to reach them.
let doc;
const docListeners = {};
const winListeners = {};
let observers = [];

function matches(n, sel) {
  if (sel === '*') return true;
  if (sel[0] === '#') return n.id === sel.slice(1);
  if (sel[0] === '.') return n.classes.has(sel.slice(1));
  if (sel[0] === '[') {
    const m = /^\[([^=\]]+)="((?:\\.|[^"\\])*)"\]$/.exec(sel);
    return Boolean(m) && n.getAttribute(m[1]) === m[2].replace(/\\(.)/g, '$1');
  }
  return n.tagName === sel.toUpperCase();
}

class FakeNode {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.nodeType = 1;
    this.children = [];
    this.parentElement = null;
    this.attrs = new Map();
    this.classes = new Set();
    this.hidden = false;
    this.disabled = false;
    this.textContent = '';
    this.innerHTML = '';
    this.id = '';
    this.dataset = {};
    this.listeners = {};
    this.style = { setProperty(k, v) { this[k] = v; } };
  }
  get classList() {
    const s = this.classes;
    return { add: (c) => s.add(c), remove: (c) => s.delete(c), contains: (c) => s.has(c) };
  }
  get className() { return [...this.classes].join(' '); }
  set className(v) { this.classes = new Set(String(v).split(/\s+/).filter(Boolean)); }
  setAttribute(k, v) { this.attrs.set(k, String(v)); }
  getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }
  hasAttribute(k) { return this.attrs.has(k); }
  appendChild(c) {
    if (c.parentElement) c.remove();
    c.parentElement = this;
    this.children.push(c);
    return c;
  }
  append(...cs) { for (const c of cs) this.appendChild(c); }
  remove() {
    const p = this.parentElement;
    if (!p) return;
    p.children.splice(p.children.indexOf(this), 1);
    this.parentElement = null;
    // A focused element that leaves the document leaves focus on the body.
    if (doc.activeElement && this.contains(doc.activeElement)) doc.activeElement = doc.body;
  }
  contains(n) { for (let p = n; p; p = p.parentElement) if (p === this) return true; return false; }
  get isConnected() { return doc.body.contains(this); }
  * descendants() { for (const c of this.children) { yield c; yield* c.descendants(); } }
  querySelectorAll(sel) { return [...this.descendants()].filter((n) => matches(n, sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  dispatch(type, extra = {}) { for (const fn of this.listeners[type] || []) fn({ type, target: this, ...extra }); }
  click() { this.dispatch('click'); }
  focus() {
    if (!this.isConnected) return;
    doc.activeElement = this;
    for (const fn of docListeners.focusin || []) fn({ target: this });
  }
}

/** A node with an id, a class, or attributes, appended to `parent`. */
function make(tag, parent, props = {}) {
  const n = new FakeNode(tag);
  if (props.id) { n.id = props.id; n.setAttribute('id', props.id); }
  if (props.className) n.className = props.className;
  for (const k of Object.keys(props.attrs || {})) n.setAttribute(k, props.attrs[k]);
  if (props.hidden) n.hidden = true;
  if (props.disabled) n.disabled = true;
  if (parent) parent.appendChild(n);
  return n;
}

function installDom() {
  const body = new FakeNode('body');
  const store = new Map();
  doc = {
    body,
    activeElement: body,
    documentElement: { dataset: {}, style: {} },
    getElementById: (id) => body.querySelector('#' + id),
    querySelector: (sel) => body.querySelector(sel),
    querySelectorAll: (sel) => body.querySelectorAll(sel),
    createElement: (tag) => new FakeNode(tag),
    addEventListener: (type, fn) => { (docListeners[type] = docListeners[type] || []).push(fn); },
    dispatchEvent: (ev) => { (docListeners[ev.type] || []).forEach((fn) => fn(ev)); return true; },
  };
  doc.body.contains = function contains(n) { for (let p = n; p; p = p.parentElement) if (p === this) return true; return false; };
  globalThis.document = doc;
  globalThis.window = { addEventListener: (type, fn) => { (winListeners[type] = winListeners[type] || []).push(fn); } };
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => { store.set(k, String(v)); },
    removeItem: (k) => { store.delete(k); },
  };
  globalThis.MutationObserver = class { constructor(cb) { this.cb = cb; observers.push(this); } observe() {} };
  globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } };
  return store;
}

/** The markup index.html carries for the chart-state card. */
function chartStateMarkup() {
  const host = make('div', doc.body, { id: 'chartstate', hidden: true });
  make('div', host, { id: 'cs-dots', hidden: true });
  const card = make('div', host, { id: 'cs-card' });
  make('div', card, { id: 'cs-title' });
  make('div', card, { id: 'cs-text' });
  make('button', card, { id: 'cs-dismiss' });
  make('button', card, { id: 'cs-retry' });
  return host;
}

function keyEvent(key, extra = {}) {
  return { key, preventDefault: vi.fn(), stopImmediatePropagation: vi.fn(), ...extra };
}

beforeEach(() => {
  vi.useFakeTimers();
  observers = [];
  installDom();
  initOverlays();
  // Leave nothing on the stack from the previous test.
  while (closeTopOverlay()) { /* drain */ }
});
afterEach(() => { vi.useRealTimers(); });

// ── toasts ─────────────────────────────────────────────────────────────
describe('toasts', () => {
  it('raises an error toast that stays until it is dismissed', () => {
    const host = make('div', doc.body, { id: 'toasts' });
    const t = toast('error', 'history failed (500)');
    expect(host.children.length).toBe(1);
    expect(host.children[0]).toBe(t.node);
    expect(t.node.className).toBe('toast toast--error');
    const [msg, x] = t.node.children;
    expect(msg.textContent).toBe('history failed (500)');
    expect(x.getAttribute('aria-label')).toBe('Dismiss');
    vi.advanceTimersByTime(60_000);
    expect(host.children.length).toBe(1);
    x.click();
    expect(t.node.classes.has('is-out')).toBe(true);
    vi.advanceTimersByTime(TOAST_LEAVE_MS);
    expect(host.children.length).toBe(0);
  });

  it('lets an info toast go on its own, and holds it while the pointer is on it', () => {
    const host = make('div', doc.body, { id: 'toasts' });
    const t = toast('info', 'layout saved');
    t.node.dispatch('pointerenter');
    vi.advanceTimersByTime(TOAST_MS.info * 3);
    expect(host.children.length).toBe(1);
    t.node.dispatch('pointerleave');
    vi.advanceTimersByTime(TOAST_MS.info + TOAST_LEAVE_MS);
    expect(host.children.length).toBe(0);
  });

  it('stacks newest last and drops the oldest past the cap', () => {
    const host = make('div', doc.body, { id: 'toasts' });
    for (let i = 0; i < TOAST_MAX + 2; i++) toast('success', 'n' + i);
    expect(host.children.length).toBe(TOAST_MAX);
    expect(host.children[0].children[0].textContent).toBe('n2');
    expect(host.children[TOAST_MAX - 1].children[0].textContent).toBe('n' + (TOAST_MAX + 1));
  });

  it('creates a polite live-region host when the page has none, and treats an unknown kind as info', () => {
    const t = toast('mystery', 'hello', { ms: 10 });
    const host = doc.getElementById('toasts');
    expect(host.getAttribute('role')).toBe('status');
    expect(host.getAttribute('aria-live')).toBe('polite');
    expect(t.node.className).toBe('toast toast--info');
    vi.advanceTimersByTime(10 + TOAST_LEAVE_MS);
    expect(host.children.length).toBe(0);
  });
});

// ── overlay stack ──────────────────────────────────────────────────────
describe('overlay stack', () => {
  function dialog(id, closerId) {
    const wrap = make('div', doc.body, { id, hidden: true });
    const card = make('div', wrap);
    const x = make('button', card, { id: closerId });
    x.addEventListener('click', () => { wrap.hidden = true; });
    make('input', card, { id: id + '-field' });
    make('button', card, { id: id + '-ok' });
    return wrap;
  }

  it('moves focus in, past disabled and hidden controls, and hands it back on close', () => {
    const opener = make('button', doc.body, { id: 'opener' });
    opener.focus();
    const dlg = make('div', doc.body, { id: 'setmodal' });
    make('button', dlg, { id: 'dead', disabled: true });
    make('button', dlg, { id: 'unseen', hidden: true });
    const box = make('div', dlg, { hidden: true });
    make('button', box, { id: 'under-hidden' });
    const first = make('button', dlg, { id: 'first' });
    openOverlay(dlg);
    expect(doc.activeElement).toBe(first);
    expect(topOverlay()).toBe(dlg);
    closeOverlay(dlg);
    expect(doc.activeElement).toBe(opener);
    expect(topOverlay()).toBe(null);
  });

  it('lands past the close button, and hands focus back to what was focused at open', () => {
    const opener = make('button', doc.body, { id: 'opener' });
    doc.activeElement = opener;                   // focused, but no focusin was heard
    const dlg = make('div', doc.body, { id: 'setmodal' });
    const head = make('div', dlg, { className: 'set-head' });
    const x = make('button', head, { id: 'set-x' });
    x.closest = (sel) => (sel === '.set-head' ? head : null);
    const tab = make('button', dlg, { id: 'tab' });
    openOverlay(dlg);
    expect(doc.activeElement).toBe(tab);
    closeOverlay(dlg);
    expect(doc.activeElement).toBe(opener);
  });

  it('leaves focus where the opener put it, and still knows where it came from', () => {
    const opener = make('button', doc.body, { id: 'opener' });
    opener.focus();
    const dlg = make('div', doc.body, { id: 'cmpmodal' });
    make('button', dlg, { id: 'x' });
    const field = make('input', dlg, { id: 'cmp-sym' });
    field.focus();                    // compare.js focuses its box before the observer runs
    openOverlay(dlg);
    expect(doc.activeElement).toBe(field);
    closeOverlay(dlg);
    expect(doc.activeElement).toBe(opener);
  });

  it('Escape closes the newest overlay only, and swallows the key', () => {
    const a = dialog('setmodal', 'set-x');
    const b = dialog('cmpmodal', 'cmp-x');
    a.hidden = false; openOverlay(a);
    b.hidden = false; openOverlay(b);
    const e = keyEvent('Escape');
    overlayKeydown(e);
    expect(b.hidden).toBe(true);
    expect(a.hidden).toBe(false);
    expect(openOverlays()).toEqual([a]);
    expect(e.preventDefault).toHaveBeenCalled();
    expect(e.stopImmediatePropagation).toHaveBeenCalled();
  });

  it('lets Escape through to the page when nothing is open', () => {
    const e = keyEvent('Escape');
    overlayKeydown(e);
    expect(e.preventDefault).not.toHaveBeenCalled();
    expect(e.stopImmediatePropagation).not.toHaveBeenCalled();
  });

  it('keeps Tab inside the open overlay', () => {
    make('button', doc.body, { id: 'outside' });
    const dlg = make('div', doc.body, { id: 'chartset' });
    const first = make('button', dlg, { id: 'a' });
    const mid = make('input', dlg, { id: 'b' });
    const last = make('button', dlg, { id: 'c' });
    openOverlay(dlg);
    last.focus();
    let e = keyEvent('Tab', { shiftKey: false });
    overlayKeydown(e);
    expect(e.preventDefault).toHaveBeenCalled();
    expect(doc.activeElement).toBe(first);
    e = keyEvent('Tab', { shiftKey: true });
    overlayKeydown(e);
    expect(doc.activeElement).toBe(last);
    mid.focus();
    e = keyEvent('Tab', { shiftKey: false });
    overlayKeydown(e);
    expect(e.preventDefault).not.toHaveBeenCalled();   // the browser moves within the dialog itself
    doc.activeElement = doc.body;                       // focus lost with a hidden control
    e = keyEvent('Tab', { shiftKey: false });
    overlayKeydown(e);
    expect(doc.activeElement).toBe(first);
  });

  it('tabTarget wraps at the ends and stays out of the way in the middle', () => {
    expect(tabTarget(3, 2, false)).toBe(0);
    expect(tabTarget(3, -1, false)).toBe(0);
    expect(tabTarget(3, 1, false)).toBe(null);
    expect(tabTarget(3, 0, true)).toBe(2);
    expect(tabTarget(3, -1, true)).toBe(2);
    expect(tabTarget(3, 1, true)).toBe(null);
  });

  it('follows the document: hidden flips and menu nodes coming and going', () => {
    const dlg = dialog('setmodal', 'set-x');
    dlg.hidden = false;
    overlayMutations([{ type: 'attributes', target: dlg }]);
    expect(topOverlay()).toBe(dlg);
    dlg.hidden = true;
    overlayMutations([{ type: 'attributes', target: dlg }]);
    expect(topOverlay()).toBe(null);
    const menu = make('div', doc.body, { className: 'menu' });
    make('button', menu, { id: 'row' });
    overlayMutations([{ type: 'childList', addedNodes: [menu], removedNodes: [] }]);
    expect(topOverlay()).toBe(menu);
    expect(doc.activeElement.id).toBe('row');
    overlayMutations([{ type: 'childList', addedNodes: [], removedNodes: [menu] }]);
    expect(topOverlay()).toBe(null);
    const plain = make('div', doc.body, { id: 'legend' });
    overlayMutations([{ type: 'attributes', target: plain }, { type: 'childList', addedNodes: [plain], removedNodes: [] }]);
    expect(topOverlay()).toBe(null);
    expect(isOverlayNode(plain)).toBe(false);
    expect(isOverlayNode(menu)).toBe(true);
  });

  it('closes each kind the way its module would', () => {
    const cset = dialog('chartset', 'cset-x');
    const clicked = vi.fn();
    cset.querySelector('#cset-x').addEventListener('click', clicked);
    cset.hidden = false; openOverlay(cset);
    closeTopOverlay();
    expect(clicked).toHaveBeenCalledTimes(1);   // Cancel semantics: the live preview reverts
    expect(cset.hidden).toBe(true);

    const ax = make('div', doc.body, { id: 'axmenu' });
    make('button', ax, { className: 'axrow' });
    const sub = make('div', doc.body, { id: 'axsub' });
    openOverlay(ax);
    closeTopOverlay();
    expect(ax.hidden).toBe(true);
    expect(sub.hidden).toBe(true);

    const menu = make('div', doc.body, { className: 'menu' });
    make('button', menu);
    openOverlay(menu);
    closeTopOverlay();
    expect(menu.isConnected).toBe(false);
    expect(closeTopOverlay()).toBe(false);
    // The rail's flyouts keep their own keyboard, so the stack leaves them be.
    expect(isOverlayNode(make('div', doc.body, { className: 'fly' }))).toBe(false);
  });

  it('restores focus to the rebuilt toolbar button by its accessible name', () => {
    const bar = make('div', doc.body, { id: 'shellbar' });
    const opener = make('button', bar, { attrs: { 'aria-label': 'Chart type' } });
    opener.focus();
    const menu = make('div', doc.body, { className: 'menu' });
    make('button', menu);
    openOverlay(menu);
    opener.remove();                                    // renderToolbar() rebuilt the bar
    const twin = make('button', bar, { attrs: { 'aria-label': 'Chart type' } });
    menu.remove();
    closeOverlay(menu);
    expect(doc.activeElement).toBe(twin);
  });

  it('does not pull focus back when it has already moved on', () => {
    const opener = make('button', doc.body, { id: 'opener' });
    const other = make('button', doc.body, { id: 'other' });
    opener.focus();
    const dlg = make('div', doc.body, { id: 'setmodal' });
    make('button', dlg);
    openOverlay(dlg);
    other.focus();
    closeOverlay(dlg);
    expect(doc.activeElement).toBe(other);
  });

  it('knows what can take focus', () => {
    const a = make('a', doc.body);
    expect(focusable(a)).toBe(false);
    a.setAttribute('href', '#');
    expect(focusable(a)).toBe(true);
    const d = make('div', doc.body, { attrs: { tabindex: '0' } });
    expect(focusable(d)).toBe(true);
    d.setAttribute('tabindex', '-1');
    expect(focusable(d)).toBe(false);
    expect(focusables(doc.body)).toEqual([a]);
  });
});

// ── chart state ────────────────────────────────────────────────────────
describe('chart state', () => {
  it('shows the dots only once a load has taken a beat', () => {
    const host = chartStateMarkup();
    setChartState('loading', { symbol: 'aapl', interval: '1d' });
    expect(chartState()).toBe('loading');
    expect(host.hidden).toBe(true);
    vi.advanceTimersByTime(LOADING_DELAY_MS);
    expect(host.hidden).toBe(false);
    expect(host.dataset.state).toBe('loading');
    expect(doc.getElementById('cs-title').textContent).toBe('Loading AAPL 1D...');
    expect(doc.getElementById('cs-retry').hidden).toBe(true);
    expect(doc.getElementById('cs-card').getAttribute('role')).toBe('status');
  });

  it('a warm load that lands inside the delay never flashes it', () => {
    const host = chartStateMarkup();
    setChartState('loading', { symbol: 'AAPL', interval: '1d' });
    vi.advanceTimersByTime(LOADING_DELAY_MS - 1);
    setChartState('ready');
    vi.advanceTimersByTime(LOADING_DELAY_MS * 2);
    expect(host.hidden).toBe(true);
    expect(chartState()).toBe('ready');
  });

  it('names the symbol and interval in the empty state', () => {
    const host = chartStateMarkup();
    setChartState('empty', { symbol: 'ZZZZ', interval: '5m' });
    expect(host.hidden).toBe(false);
    expect(host.dataset.state).toBe('empty');
    expect(doc.getElementById('cs-title').textContent).toBe('No data for ZZZZ on 5M');
    expect(doc.getElementById('cs-text').textContent).toMatch(/longer range/);
    expect(doc.getElementById('cs-retry').hidden).toBe(false);
    expect(doc.getElementById('cs-dismiss').hidden).toBe(true);
  });

  it('the error state is an alert with the message, a retry and a dismiss', () => {
    const host = chartStateMarkup();
    const retry = vi.fn();
    initShell({ load: vi.fn() });
    setChartState('error', { symbol: 'AAPL', interval: '1d', message: 'history failed (502)', retry });
    expect(host.dataset.state).toBe('error');
    expect(doc.getElementById('cs-card').getAttribute('role')).toBe('alert');
    expect(doc.getElementById('cs-title').textContent).toBe('Could not load AAPL 1D');
    expect(doc.getElementById('cs-text').textContent).toBe('history failed (502)');
    expect(doc.getElementById('cs-dismiss').hidden).toBe(false);
    doc.getElementById('cs-retry').click();
    expect(retry).toHaveBeenCalledTimes(1);
    doc.getElementById('cs-dismiss').click();
    expect(host.hidden).toBe(true);
    expect(chartState()).toBe('ready');
  });

  it('the unsupported state names the missing session and offers the choice that loads', () => {
    const host = chartStateMarkup();
    const back = vi.fn();
    initShell({ load: vi.fn() });
    setChartState('unsupported', { symbol: 'aapl', interval: '1d', retry: back });
    expect(chartState()).toBe('unsupported');
    expect(host.hidden).toBe(false);
    expect(host.dataset.state).toBe('unsupported');
    expect(doc.getElementById('cs-card').getAttribute('role')).toBe('status');
    expect(doc.getElementById('cs-title').textContent).toBe('Extended hours are not available for AAPL 1D');
    expect(doc.getElementById('cs-text').textContent).toMatch(/intraday bars of US listed stocks/);
    const retry = doc.getElementById('cs-retry');
    expect(retry.textContent).toBe('Use regular hours');
    expect(doc.getElementById('cs-dismiss').hidden).toBe(false);
    retry.click();
    expect(back).toHaveBeenCalledTimes(1);
    // Any other state puts the ordinary retry back.
    setChartState('error', { symbol: 'AAPL', message: 'offline' });
    expect(retry.textContent).toBe('Try again');
  });

  it('shows the dots for a load and never for an empty or failed one', () => {
    const host = chartStateMarkup();
    const dots = host.children[0];
    setChartState('error', { message: 'offline' });
    expect(dots.hidden).toBe(true);
    setChartState('empty', { symbol: 'ZZZZ' });
    expect(dots.hidden).toBe(true);
    setChartState('loading', { symbol: 'AAPL' });
    vi.advanceTimersByTime(LOADING_DELAY_MS);
    expect(dots.hidden).toBe(false);
  });

  it('blanks the stage only when the bars coming belong to another symbol', () => {
    const host = chartStateMarkup();
    setChartState('loading', { symbol: 'AAPL', interval: '1d', blank: true });
    vi.advanceTimersByTime(LOADING_DELAY_MS);
    expect(host.dataset.blank).toBe('1');
    setChartState('loading', { symbol: 'AAPL', interval: '1d' });
    vi.advanceTimersByTime(LOADING_DELAY_MS);
    expect(host.dataset.blank).toBe('');
  });

  it('retries through the page loader when the state names none', () => {
    chartStateMarkup();
    const load = vi.fn();
    initShell({ load });
    setChartState('error', { message: 'offline' });
    doc.getElementById('cs-retry').click();
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('initShell draws the three dots once', () => {
    chartStateMarkup();
    initShell({});
    const dots = doc.getElementById('cs-dots');
    expect(dots.children.length).toBe(3);
    expect(dots.children.map((d) => d.style['--i'])).toEqual(['0', '1', '2']);
    initShell({});
    expect(dots.children.length).toBe(3);
  });
});

// ── theme ──────────────────────────────────────────────────────────────
describe('theme', () => {
  it('comes back in the saved theme and flips the charts with the shell', () => {
    localStorage.setItem(THEME_KEY, 'light');
    const chart = { setTheme: vi.fn() };
    const chart2 = { setTheme: vi.fn() };
    const app = { chart, chart2 };
    initShell(app);
    expect(currentTheme()).toBe('light');
    expect(doc.documentElement.dataset.theme).toBe('light');
    expect(doc.documentElement.style.colorScheme).toBe('light');
    // The demo's palettes sit over the engine's, so every key the engine
    // knows keeps a value, and the light one stays light.
    const light = chartTheme();
    for (const k of Object.keys(lightTheme)) expect(light[k], k).toBeDefined();
    expect(light.background).toBe('#ffffff');
    expect(chart.setTheme).toHaveBeenLastCalledWith(light);
    const heard = vi.fn();
    doc.addEventListener('oac:theme', heard);
    toggleTheme();
    expect(currentTheme()).toBe('dark');
    expect(localStorage.getItem(THEME_KEY)).toBe('dark');
    const dark = chartTheme();
    for (const k of Object.keys(darkTheme)) expect(dark[k], k).toBeDefined();
    expect(dark.background).not.toBe(light.background);
    expect(chart.setTheme).toHaveBeenLastCalledWith(dark);
    expect(chart2.setTheme).toHaveBeenLastCalledWith(dark);
    expect(heard).toHaveBeenCalledTimes(1);
    expect(heard.mock.calls[0][0].detail).toEqual({ theme: 'dark' });
    setTheme('sepia');
    expect(currentTheme()).toBe('dark');
  });

  it('announces a switch through the live region, and not the restore on load', () => {
    const live = make('div', doc.body, { id: 'live' });
    localStorage.setItem(THEME_KEY, 'light');
    initShell({});
    vi.advanceTimersByTime(100);
    expect(live.textContent).toBe('');
    setTheme('dark');
    expect(live.textContent).toBe('');
    vi.advanceTimersByTime(40);
    expect(live.textContent).toBe('dark theme');
    announce('layout saved');
    expect(live.textContent).toBe('');
    vi.advanceTimersByTime(40);
    expect(live.textContent).toBe('layout saved');
  });
});
