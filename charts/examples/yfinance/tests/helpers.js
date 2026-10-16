// Test doubles for the demo modules. The modules reach the page through
// `el(id)` and `localStorage`, so a handful of plain objects stands in for
// the elements a test touches; anything a test does not name is created on
// first use with the fields the demo writes.

/** A node with the properties the demo reads and writes on its controls. */
function fakeNode(id, value) {
  const subs = new Map();
  const classes = new Set();
  const attrs = new Map();
  return {
    id,
    value: value === undefined ? '' : value,
    // Own text plus the children's, the way the real property reads: a
    // toast keeps its message in a child span.
    _text: '',
    get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); },
    set textContent(v) { this._text = String(v); this.children = []; },
    checked: false,
    hidden: false,
    innerHTML: '',
    style: {},
    children: [],
    parentNode: null,
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      toggle: (c, on) => { if (on) classes.add(c); else classes.delete(c); },
      contains: (c) => classes.has(c),
    },
    appendChild(child) { this.children.push(child); child.parentNode = this; return child; },
    append(...nodes) { for (const n of nodes) this.appendChild(n); },
    remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((c) => c !== this); this.parentNode = null; },
    setAttribute(k, v) { attrs.set(k, String(v)); },
    getAttribute(k) { return attrs.has(k) ? attrs.get(k) : null; },
    querySelector(sel) {
      if (!subs.has(sel)) subs.set(sel, { textContent: '', className: '' });
      return subs.get(sel);
    },
    querySelectorAll: () => [],
    addEventListener: () => {},
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 800, bottom: 600, width: 800, height: 600 }),
    offsetWidth: 100,
    offsetHeight: 20,
  };
}

/**
 * Install a `document` whose `getElementById` hands out fake nodes, seeded
 * with `values` for the controls that carry one. Returns the node map so a
 * test can read what the code wrote back.
 */
export function fakeDom(values = {}) {
  const nodes = new Map();
  const get = (id) => {
    if (!nodes.has(id)) nodes.set(id, fakeNode(id, values[id]));
    return nodes.get(id);
  };
  globalThis.document = {
    getElementById: get,
    createElement: (tag) => fakeNode(tag),
    querySelectorAll: () => [],
    body: fakeNode('body'),
  };
  return { get, nodes };
}

/** An in-memory `localStorage`. */
export function fakeStorage() {
  const store = new Map();
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => { store.set(k, String(v)); },
    removeItem: (k) => { store.delete(k); },
    clear: () => { store.clear(); },
  };
  return store;
}

/** A daily bar at `daySec` with one price for the four legs. */
export function flatBar(time, price, volume = 0) {
  return { time, open: price, high: price, low: price, close: price, volume };
}
