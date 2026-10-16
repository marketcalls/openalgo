// A small DOM for the modules that build real trees: a node tree with
// parents and children, listeners with capture and bubble phases, focus,
// a handful of attributes and selectors, and layout answers a test can
// set. It is not a browser; it is exactly what properties.js, the text
// editor and the level editor reach for, so a call they make that a
// browser would answer and this does not is a test failure rather than a
// silent pass.

const RECT = { left: 0, top: 0, width: 0, height: 0 };

class FakeEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.bubbles = init.bubbles !== false;
    Object.assign(this, init);
    this.target = null;
    this.currentTarget = null;
    this.defaultPrevented = false;
    this._stop = false;
    this._stopNow = false;
  }
  preventDefault() { this.defaultPrevented = true; }
  stopPropagation() { this._stop = true; }
  stopImmediatePropagation() { this._stop = true; this._stopNow = true; }
}

class FakeNode {
  constructor(doc) {
    this.ownerDocument = doc;
    this.parentNode = null;
    this.childNodes = [];
    this._listeners = new Map();
  }
  get parentElement() { return this.parentNode && this.parentNode.nodeType === 1 ? this.parentNode : null; }
  get firstChild() { return this.childNodes[0] || null; }
  get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  get previousElementSibling() {
    const siblings = this.parentNode ? this.parentNode.children : [];
    return siblings[siblings.indexOf(this) - 1] || null;
  }
  get isConnected() {
    let n = this;
    while (n) { if (n.nodeType === 9) return true; n = n.parentNode; }
    return false;
  }
  appendChild(child) {
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = this;
    this.childNodes.push(child);
    return child;
  }
  append(...nodes) { for (const n of nodes) this.appendChild(typeof n === 'string' ? this.ownerDocument.createTextNode(n) : n); }
  insertBefore(child, ref) {
    if (child.parentNode) child.parentNode.removeChild(child);
    const i = ref ? this.childNodes.indexOf(ref) : -1;
    child.parentNode = this;
    if (i < 0) this.childNodes.push(child); else this.childNodes.splice(i, 0, child);
    return child;
  }
  removeChild(child) {
    const i = this.childNodes.indexOf(child);
    if (i >= 0) { this.childNodes.splice(i, 1); child.parentNode = null; }
    return child;
  }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  contains(node) {
    for (let n = node; n; n = n.parentNode) if (n === this) return true;
    return false;
  }
  addEventListener(type, fn, opts) {
    const capture = opts === true || !!(opts && opts.capture === true);
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type).push({ fn, capture });
  }
  removeEventListener(type, fn, opts) {
    const capture = opts === true || !!(opts && opts.capture === true);
    const list = this._listeners.get(type);
    if (list) this._listeners.set(type, list.filter((l) => !(l.fn === fn && l.capture === capture)));
  }
  _run(ev, capture) {
    for (const l of (this._listeners.get(ev.type) || []).slice()) {
      if (l.capture !== capture) continue;
      ev.currentTarget = this;
      l.fn.call(this, ev);
      if (ev._stopNow) return;
    }
  }
  dispatchEvent(ev) {
    ev.target = this;
    const path = [];
    for (let n = this; n; n = n.parentNode) path.push(n);
    const doc = this.ownerDocument;
    if (doc && path[path.length - 1] === doc && doc.defaultView) path.push(doc.defaultView);
    // Capture: outermost first, stopping short of the target.
    for (let i = path.length - 1; i >= 1; i--) {
      path[i]._run(ev, true);
      if (ev._stop) return !ev.defaultPrevented;
    }
    this._run(ev, true);
    if (!ev._stop) this._run(ev, false);
    if (ev._stop || !ev.bubbles) return !ev.defaultPrevented;
    for (let i = 1; i < path.length; i++) {
      path[i]._run(ev, false);
      if (ev._stop) break;
    }
    return !ev.defaultPrevented;
  }
  /** Convenience: build and dispatch in one call; returns the event. */
  fire(type, init = {}) {
    const ev = new FakeEvent(type, init);
    this.dispatchEvent(ev);
    return ev;
  }
}

class FakeText extends FakeNode {
  constructor(doc, text) {
    super(doc);
    this.nodeType = 3;
    this.nodeName = '#text';
    this.nodeValue = String(text);
  }
  get textContent() { return this.nodeValue; }
  set textContent(v) { this.nodeValue = String(v); }
}

class ClassList {
  constructor(el) { this.el = el; }
  get _set() { return new Set(this.el._className.split(/\s+/).filter(Boolean)); }
  _write(s) { this.el._className = Array.from(s).join(' '); }
  add(...c) { const s = this._set; for (const x of c) s.add(x); this._write(s); }
  remove(...c) { const s = this._set; for (const x of c) s.delete(x); this._write(s); }
  contains(c) { return this._set.has(c); }
  toggle(c, on) {
    const s = this._set;
    const want = on === undefined ? !s.has(c) : !!on;
    if (want) s.add(c); else s.delete(c);
    this._write(s);
    return want;
  }
}

const dataKey = (attr) => attr.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());

/** `tag#id.a.b[attr="v"]`, one compound selector, no combinators. */
function matchesSimple(el, sel) {
  let rest = sel;
  const m = rest.match(/^[a-zA-Z][\w-]*|^\*/);
  if (m) {
    if (m[0] !== '*' && el.tagName !== m[0].toUpperCase()) return false;
    rest = rest.slice(m[0].length);
  }
  const re = /#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]|:not\(\[([\w-]+)\]\)/g;
  let k;
  while ((k = re.exec(rest))) {
    if (k[1] !== undefined && el.id !== k[1]) return false;
    if (k[2] !== undefined && !el.classList.contains(k[2])) return false;
    if (k[3] !== undefined) {
      if (!el.hasAttribute(k[3])) return false;
      if (k[4] !== undefined && el.getAttribute(k[3]) !== k[4]) return false;
    }
    if (k[5] !== undefined && el.hasAttribute(k[5])) return false;
  }
  return true;
}

class FakeElement extends FakeNode {
  constructor(doc, tag) {
    super(doc);
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.nodeName = this.tagName;
    this._className = '';
    this.classList = new ClassList(this);
    this._attrs = new Map();
    this.style = {
      setProperty(k, v) { this[k] = v; },
      removeProperty(k) { delete this[k]; },
    };
    this.dataset = {};
    this.hidden = false;
    this.disabled = false;
    this.value = '';
    this.checked = false;
    this._html = '';
    // Layout answers, settable by a test.
    this.offsetWidth = 120;
    this.offsetHeight = 28;
    this.rect = null;
    if (tag === 'canvas') {
      // A fixed 7px per character keeps frame maths checkable by hand.
      this.getContext = () => ({ font: '', measureText: (s) => ({ width: s.length * 7 }) });
    }
  }
  get id() { return this._attrs.get('id') || ''; }
  set id(v) { this._attrs.set('id', String(v)); }
  // A control's `type` is an attribute too, so `input[type="checkbox"]` finds it.
  get type() { return this._attrs.get('type') || ''; }
  set type(v) { this._attrs.set('type', String(v)); }
  get className() { return this._className; }
  set className(v) { this._className = String(v); }
  get isContentEditable() {
    const v = this.getAttribute('contenteditable');
    return v !== null && v !== 'false';
  }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(''); }
  set textContent(v) {
    this.childNodes = [];
    this._html = '';
    if (v !== '' && v !== null && v !== undefined) this.appendChild(this.ownerDocument.createTextNode(v));
  }
  /** Markup is kept as a string (the icons); an empty string clears the children. */
  get innerHTML() { return this._html + this.childNodes.map((c) => (c.nodeType === 3 ? c.nodeValue : c.outerHTML)).join(''); }
  set innerHTML(v) { this.childNodes = []; this._html = String(v); }
  get outerHTML() { return `<${this.tagName.toLowerCase()}>${this.innerHTML}</${this.tagName.toLowerCase()}>`; }
  // `data-*` attributes and `dataset` are one store, as in a browser.
  setAttribute(k, v) { if (k.startsWith('data-')) this.dataset[dataKey(k)] = String(v); else this._attrs.set(k, String(v)); }
  getAttribute(k) {
    if (k.startsWith('data-')) { const v = this.dataset[dataKey(k)]; return v === undefined ? null : String(v); }
    return this._attrs.has(k) ? this._attrs.get(k) : null;
  }
  hasAttribute(k) { return k.startsWith('data-') ? this.dataset[dataKey(k)] !== undefined : this._attrs.has(k); }
  removeAttribute(k) { if (k.startsWith('data-')) delete this.dataset[dataKey(k)]; else this._attrs.delete(k); }
  matches(sel) { return sel.split(',').some((s) => matchesSimple(this, s.trim())); }
  closest(sel) {
    for (let n = this; n && n.nodeType === 1; n = n.parentNode) if (n.matches(sel)) return n;
    return null;
  }
  _descendants(out = []) {
    for (const c of this.childNodes) if (c.nodeType === 1) { out.push(c); c._descendants(out); }
    return out;
  }
  querySelectorAll(sel) {
    const parts = sel.trim().split(/\s+/);
    let set = this._descendants();
    for (let i = 0; i < parts.length; i++) {
      const hits = set.filter((e) => matchesSimple(e, parts[i]));
      if (i === parts.length - 1) return hits;
      const next = [];
      for (const h of hits) for (const d of h._descendants()) if (!next.includes(d)) next.push(d);
      set = next;
    }
    return [];
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  getBoundingClientRect() {
    if (this.rect) return { ...RECT, ...this.rect, right: (this.rect.left || 0) + (this.rect.width || 0), bottom: (this.rect.top || 0) + (this.rect.height || 0) };
    const p = this.parentElement ? this.parentElement.getBoundingClientRect() : RECT;
    const left = p.left + this.offsetLeft;
    const top = p.top + this.offsetTop;
    return { left, top, width: this.offsetWidth, height: this.offsetHeight, right: left + this.offsetWidth, bottom: top + this.offsetHeight };
  }
  get offsetLeft() { return parseFloat(this.style.left) || 0; }
  get offsetTop() { return parseFloat(this.style.top) || 0; }
  focus() {
    const doc = this.ownerDocument;
    if (doc.activeElement === this) return;
    const prev = doc.activeElement;
    doc.activeElement = this;
    if (prev && prev !== doc.body && prev.fire) prev.fire('blur', { bubbles: false });
    this.fire('focus', { bubbles: false });
    this.fire('focusin');
  }
  blur() {
    const doc = this.ownerDocument;
    if (doc.activeElement !== this) return;
    doc.activeElement = doc.body;
    this.fire('blur', { bubbles: false });
  }
  click() { return this.fire('click'); }
  select() {}
  setPointerCapture() {}
  releasePointerCapture() {}
}

class FakeDocument extends FakeNode {
  constructor() {
    super(null);
    this.ownerDocument = this;
    this.nodeType = 9;
    this.nodeName = '#document';
    this.defaultView = null;
    this.documentElement = this.appendChild(new FakeElement(this, 'html'));
    this.head = this.documentElement.appendChild(new FakeElement(this, 'head'));
    this.body = this.documentElement.appendChild(new FakeElement(this, 'body'));
    this.activeElement = this.body;
    this.fullscreenElement = null;
  }
  createElement(tag) { return new FakeElement(this, tag); }
  createTextNode(t) { return new FakeText(this, t); }
  createRange() { return { selectNodeContents() {}, collapse() {} }; }
  getElementById(id) { return this.documentElement.querySelector('#' + id); }
  querySelector(sel) { return this.documentElement.querySelector(sel); }
  querySelectorAll(sel) { return this.documentElement.querySelectorAll(sel); }
}

class FakeWindow extends FakeNode {
  constructor(doc, width, height) {
    super(doc);
    this.nodeType = 0;
    this.nodeName = '#window';
    this.innerWidth = width;
    this.innerHeight = height;
    this.document = doc;
  }
  getSelection() { return { removeAllRanges() {}, addRange() {} }; }
}

/**
 * Install `document`, `window` and `localStorage` on the global. Returns
 * them, plus `stage` (a positioned host at 42,60 sized `width` x `height`)
 * and `chart` (the chart container inside it, at the host's origin), the
 * pair every bar test mounts against.
 */
export function installDom({ width = 1200, height = 700 } = {}) {
  const doc = new FakeDocument();
  const win = new FakeWindow(doc, width + 42, height + 60);
  doc.defaultView = win;
  const store = new Map();
  const localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => { store.set(k, String(v)); },
    removeItem: (k) => { store.delete(k); },
    clear: () => { store.clear(); },
  };
  globalThis.document = doc;
  globalThis.window = win;
  globalThis.localStorage = localStorage;
  const stage = doc.createElement('main');
  stage.className = 'stage';
  stage.rect = { left: 0, top: 60, width: width + 42, height };
  doc.body.appendChild(stage);
  const rail = doc.createElement('div');
  rail.id = 'rail';
  stage.appendChild(rail);
  const chart = doc.createElement('div');
  chart.id = 'chart';
  chart.rect = { left: 42, top: 60, width, height };
  stage.appendChild(chart);
  return { document: doc, window: win, localStorage, store, stage, chart, FakeEvent };
}

export { FakeEvent };
