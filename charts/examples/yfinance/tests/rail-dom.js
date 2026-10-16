// A small DOM for the rail tests: a tree with classes, attributes, focus,
// a parser for the markup the rail writes through innerHTML, and event
// dispatch with a capture phase, so the real handlers can be driven from
// node. The rail's own selectors are simple (a tag, a class, an attribute,
// a descendant), and that is all the matcher understands.

const dataKey = (attr) => attr.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
const VOID = new Set(['br', 'hr', 'img', 'input', 'use', 'path', 'circle', 'rect', 'line', 'meta', 'link']);

export class FakeEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.bubbles = init.bubbles !== false;
    this.defaultPrevented = false;
    this.propagationStopped = false;
    this.target = null;
    this.currentTarget = null;
    Object.assign(this, init);
  }
  preventDefault() { this.defaultPrevented = true; }
  stopPropagation() { this.propagationStopped = true; }
}

class Listeners {
  constructor() { this.capture = new Map(); this.bubble = new Map(); }
  add(type, fn, opts) {
    const cap = opts === true || (opts && opts.capture === true);
    const m = cap ? this.capture : this.bubble;
    if (!m.has(type)) m.set(type, []);
    m.get(type).push(fn);
  }
  remove(type, fn, opts) {
    const cap = opts === true || (opts && opts.capture === true);
    const m = cap ? this.capture : this.bubble;
    const list = m.get(type);
    if (list) m.set(type, list.filter((f) => f !== fn));
  }
  run(phase, ev, self) {
    const list = (phase === 'capture' ? this.capture : this.bubble).get(ev.type) || [];
    for (const fn of list.slice()) {
      ev.currentTarget = self;
      fn.call(self, ev);
      if (ev.propagationStopped) return;
    }
  }
}

function parseSimple(sel) {
  // tag#id.class[attr="v"][attr] as one compound.
  const out = { tag: null, id: null, classes: [], attrs: [] };
  const re = /([a-zA-Z][\w-]*)|#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]/g;
  let m;
  while ((m = re.exec(sel))) {
    if (m[1]) out.tag = m[1].toLowerCase();
    else if (m[2]) out.id = m[2];
    else if (m[3]) out.classes.push(m[3]);
    else if (m[4]) out.attrs.push({ name: m[4], value: m[5] });
  }
  return out;
}

function matchesSimple(node, s) {
  if (s.tag && node.tagName.toLowerCase() !== s.tag) return false;
  if (s.id && node.id !== s.id) return false;
  for (const c of s.classes) if (!node.classList.contains(c)) return false;
  for (const a of s.attrs) {
    if (!node.hasAttribute(a.name)) return false;
    if (a.value !== undefined && node.getAttribute(a.name) !== a.value) return false;
  }
  return true;
}

export class FakeNode {
  constructor(tag, doc) {
    this.tagName = String(tag).toUpperCase();
    this.ownerDocument = doc;
    this.children = [];
    this.parentNode = null;
    this._attrs = new Map();
    this._classes = new Set();
    this._listeners = new Listeners();
    this._text = '';
    this.dataset = {};
    this.style = {
      _p: {},
      setProperty(k, v) { this._p[k] = v; },
      removeProperty(k) { delete this._p[k]; },
      getPropertyValue(k) { return this._p[k] || ''; },
    };
    this.hidden = false;
    this.tabIndex = -1;
    this.value = '';
    this.checked = false;
    this.rect = null;
    this.size = null;
  }
  get parentElement() { return this.parentNode; }
  get id() { return this._attrs.get('id') || ''; }
  set id(v) { this._attrs.set('id', v); }
  get className() { return Array.from(this._classes).join(' '); }
  set className(v) { this._classes = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get classList() {
    const set = this._classes;
    return {
      add: (...cs) => { for (const c of cs) set.add(c); },
      remove: (...cs) => { for (const c of cs) set.delete(c); },
      toggle: (c, on) => { const want = on === undefined ? !set.has(c) : Boolean(on); if (want) set.add(c); else set.delete(c); return want; },
      contains: (c) => set.has(c),
    };
  }
  // `data-*` attributes and `dataset` are one store, as in a browser.
  setAttribute(k, v) {
    if (k === 'class') { this.className = v; return; }
    if (k === 'tabindex') { this.tabIndex = Number(v); return; }
    if (k.startsWith('data-')) { this.dataset[dataKey(k)] = String(v); return; }
    this._attrs.set(k, String(v));
  }
  getAttribute(k) {
    if (k === 'class') return this.className;
    if (k.startsWith('data-')) { const v = this.dataset[dataKey(k)]; return v === undefined ? null : v; }
    return this._attrs.has(k) ? this._attrs.get(k) : null;
  }
  hasAttribute(k) {
    if (k === 'class') return this._classes.size > 0;
    if (k.startsWith('data-')) return this.dataset[dataKey(k)] !== undefined;
    return this._attrs.has(k);
  }
  removeAttribute(k) { if (k.startsWith('data-')) delete this.dataset[dataKey(k)]; else this._attrs.delete(k); }
  appendChild(c) {
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this;
    this.children.push(c);
    return c;
  }
  get nextSibling() {
    const siblings = this.parentNode ? this.parentNode.children : [];
    return siblings[siblings.indexOf(this) + 1] ?? null;
  }
  insertBefore(c, ref) {
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this;
    const i = ref ? this.children.indexOf(ref) : -1;
    if (i >= 0) this.children.splice(i, 0, c); else this.children.push(c);
    return c;
  }
  removeChild(c) {
    const i = this.children.indexOf(c);
    if (i >= 0) this.children.splice(i, 1);
    c.parentNode = null;
    return c;
  }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  get firstChild() { return this.children[0] || null; }
  get isConnected() {
    const doc = this.ownerDocument;
    return doc.body.contains(this) || doc.head.contains(this);
  }
  contains(n) {
    for (let x = n; x; x = x.parentNode) if (x === this) return true;
    return false;
  }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  set textContent(v) { this.children = []; this._text = String(v); }
  get innerHTML() { return this._html !== undefined ? this._html : this.textContent; }
  set innerHTML(v) {
    this.children = [];
    this._text = '';
    this._html = String(v);
    parseInto(this, String(v));
  }
  matches(sel) { return sel.split(',').some((part) => matchesSimple(this, parseSimple(part.trim()))); }
  closest(sel) {
    if (this.matches(sel)) return this;
    const up = this.parentNode;
    return up && up.tagName ? up.closest(sel) : null;
  }
  all() {
    const out = [];
    const walk = (n) => { for (const c of n.children) { out.push(c); walk(c); } };
    walk(this);
    return out;
  }
  querySelectorAll(sel) {
    const parts = sel.split(',').map((p) => p.trim().split(/\s+/).map(parseSimple));
    return this.all().filter((n) => parts.some((chain) => {
      const last = chain[chain.length - 1];
      if (!matchesSimple(n, last)) return false;
      // Ancestors must match the leading compounds, in order.
      let idx = chain.length - 2;
      for (let a = n.parentNode; a && idx >= 0 && a !== this.parentNode; a = a.parentNode) {
        if (matchesSimple(a, chain[idx])) idx -= 1;
      }
      return idx < 0;
    }));
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  addEventListener(t, fn, o) { this._listeners.add(t, fn, o); }
  removeEventListener(t, fn, o) { this._listeners.remove(t, fn, o); }
  dispatchEvent(ev) { return this.ownerDocument.dispatch(ev, this); }
  focus() {
    const doc = this.ownerDocument;
    if (doc.activeElement === this) return;
    const prev = doc.activeElement;
    doc.activeElement = this;
    if (prev && prev !== doc.body) {
      prev.dispatchEvent(new FakeEvent('blur', { bubbles: false }));
      prev.dispatchEvent(new FakeEvent('focusout', { relatedTarget: this }));
    }
    this.dispatchEvent(new FakeEvent('focus', { bubbles: false }));
    this.dispatchEvent(new FakeEvent('focusin'));
  }
  blur() {
    const doc = this.ownerDocument;
    if (doc.activeElement !== this) return;
    doc.activeElement = doc.body;
    this.dispatchEvent(new FakeEvent('blur', { bubbles: false }));
  }
  click() { this.dispatchEvent(new FakeEvent('click', { detail: 1, target: this })); }
  getBoundingClientRect() {
    const r = this.rect || { left: 0, top: 0, width: 32, height: 32 };
    return { left: r.left, top: r.top, width: r.width, height: r.height, right: r.left + r.width, bottom: r.top + r.height };
  }
  get offsetWidth() { return this.size ? this.size.width : 100; }
  get offsetHeight() { return this.size ? this.size.height : 20; }
}

const ENTITIES = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"' };

/** Parse the markup the rail writes: tags, double-quoted attributes, text. */
function parseInto(root, html) {
  const doc = root.ownerDocument;
  const re = /<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[\w:-]+(?:="[^"]*")?)*)\s*(\/?)>|([^<]+)/g;
  const stack = [root];
  let m;
  while ((m = re.exec(html))) {
    if (m[1]) { if (stack.length > 1) stack.pop(); continue; }
    if (m[2]) {
      const node = new FakeNode(m[2], doc);
      const attrRe = /([\w:-]+)(?:="([^"]*)")?/g;
      let a;
      while ((a = attrRe.exec(m[3] || ''))) {
        const name = a[1];
        const value = a[2] === undefined ? '' : a[2];
        node.setAttribute(name, value);
      }
      stack[stack.length - 1].appendChild(node);
      if (!m[4] && !VOID.has(m[2].toLowerCase())) stack.push(node);
      continue;
    }
    if (m[5]) {
      // One pass, not four: unescaping &amp; first would turn the literal
      // "&amp;lt;" into "&lt;" and then into "<", which is a different string
      // than the markup asked for.
      const text = m[5].replace(/&(?:amp|lt|gt|quot);/g, (e) => ENTITIES[e]);
      stack[stack.length - 1]._text += text;
    }
  }
}

export class FakeDocument {
  constructor() {
    this._listeners = new Listeners();
    this.body = new FakeNode('body', this);
    this.head = new FakeNode('head', this);
    this.documentElement = new FakeNode('html', this);
    this.activeElement = this.body;
    this.fullscreenElement = null;
    this.window = null;
  }
  createElement(tag) { return new FakeNode(tag, this); }
  getElementById(id) {
    for (const n of [...this.head.all(), ...this.body.all()]) if (n.id === id) return n;
    return null;
  }
  querySelectorAll(sel) { return this.body.querySelectorAll(sel); }
  querySelector(sel) { return this.body.querySelector(sel); }
  addEventListener(t, fn, o) { this._listeners.add(t, fn, o); }
  removeEventListener(t, fn, o) { this._listeners.remove(t, fn, o); }
  /** Capture from the window down to the target, then bubble back up. */
  dispatch(ev, target) {
    ev.target = target;
    const path = [];
    for (let n = target; n; n = n.parentNode) path.push(n);
    const hosts = [this.window, this, ...path.reverse()].filter(Boolean);
    for (const h of hosts) {
      h._listeners.run('capture', ev, h);
      if (ev.propagationStopped) return !ev.defaultPrevented;
    }
    for (const h of hosts.slice().reverse()) {
      if (!ev.bubbles && h !== target) continue;
      h._listeners.run('bubble', ev, h);
      if (ev.propagationStopped) return !ev.defaultPrevented;
    }
    return !ev.defaultPrevented;
  }
}

export class FakeWindow {
  constructor(doc) {
    this._listeners = new Listeners();
    this.innerWidth = 1280;
    this.innerHeight = 800;
    this.document = doc;
    doc.window = this;
  }
  addEventListener(t, fn, o) { this._listeners.add(t, fn, o); }
  removeEventListener(t, fn, o) { this._listeners.remove(t, fn, o); }
  dispatchEvent(ev) {
    ev.target = this;
    this._listeners.run('capture', ev, this);
    if (!ev.propagationStopped) this._listeners.run('bubble', ev, this);
    return !ev.defaultPrevented;
  }
}

/**
 * The page the rail needs: the stage with the rail and the chart in it, the
 * status line, the legacy controls, the dialogs (hidden). Installs
 * `document` and `window` on the global and returns the nodes.
 */
export function railPage() {
  const doc = new FakeDocument();
  const win = new FakeWindow(doc);
  const add = (parent, tag, id, extra = {}) => {
    const n = doc.createElement(tag);
    if (id) n.id = id;
    Object.assign(n, extra);
    parent.appendChild(n);
    return n;
  };
  const stage = add(doc.body, 'main', 'stage');
  stage.className = 'stage has-rail';
  const rail = add(stage, 'div', 'rail');
  rail.className = 'rail';
  const chart = add(stage, 'div', 'chart', { tabIndex: 0 });
  const status = add(doc.body, 'span', 'status');
  const drawtool = add(doc.body, 'select', 'drawtool');
  const magnet = add(doc.body, 'input', 'magnet');
  for (const id of ['chartset', 'setmodal', 'cmpmodal', 'textmodal']) add(doc.body, 'div', id, { hidden: true });
  globalThis.document = doc;
  globalThis.window = win;
  return { doc, win, stage, rail, chart, status, drawtool, magnet };
}

/** A key event dispatched from `target` (default: the chart), through the window's capture listeners. */
export function pressKey(key, init = {}, target = document.getElementById('chart')) {
  const ev = new FakeEvent('keydown', { key, ...init });
  target.dispatchEvent(ev);
  return ev;
}

/** A click on `node`, optionally from a child (the chevron) and with a click count. */
export function clickOn(node, { from = node, detail = 1 } = {}) {
  const ev = new FakeEvent('click', { detail, clientX: 0, clientY: 0 });
  from.dispatchEvent(ev);
  return ev;
}

/** A pointer event (pointerenter, pointerleave, pointerdown) on `node`. */
export function pointer(type, node) {
  const ev = new FakeEvent(type, { bubbles: type === 'pointerdown' });
  node.dispatchEvent(ev);
  return ev;
}
