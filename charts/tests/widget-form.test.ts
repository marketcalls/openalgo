/**
 * The widget's control renderer: the three schema vocabularies folded into
 * one control model, the rows it draws, the values it reports, and the
 * furniture the dialogs share.
 *
 * The first half of this file is a small DOM: a node tree with parents and
 * children, listeners with capture and bubble phases, focus, attributes,
 * simple selectors and layout answers a test can set. It is what the widget
 * dialogs reach for and nothing more, so a call they make that a browser
 * would answer and this does not is a test failure rather than a silent
 * pass. `tests/widget-dialogs.test.ts` imports it from here; the suites below
 * register only when this file is the one being collected, so that import
 * does not drag them along.
 */
import { describe, it, expect } from 'vitest';
import { makeCtx } from './helpers/fake-ctx';
import { INDICATOR_SOURCES } from 'openalgo-charts';
import type { ChartSettingsInput } from 'openalgo-charts';
import { chromeIconSvg, LINE_STYLE_OPTIONS, FONT_OPTIONS, type SettingsField } from 'openalgo-charts/draw';
import {
  controlsFromInputs, controlsFromFields, renderForm, formatNumber, placePanel, openPanel,
  dialogFrame, tabList, button, selectionPoint, type FormControl,
} from '../src/widget/form';

// ── a small DOM ───────────────────────────────────────────────────────────

const RECT = { left: 0, top: 0, width: 0, height: 0 };

export class FakeEvent {
  type: string;
  bubbles: boolean;
  target: unknown = null;
  currentTarget: unknown = null;
  defaultPrevented = false;
  _stop = false;
  _stopNow = false;
  [key: string]: unknown;
  constructor(type: string, init: Record<string, unknown> = {}) {
    this.type = type;
    this.bubbles = init.bubbles !== false;
    Object.assign(this, init);
  }
  preventDefault(): void { this.defaultPrevented = true; }
  stopPropagation(): void { this._stop = true; }
  stopImmediatePropagation(): void { this._stop = true; this._stopNow = true; }
}

type Listener = { fn: (e: FakeEvent) => void; capture: boolean };

/** `start` and every node above it, nearest first. */
function ancestorsOf(start: FakeNode): FakeNode[] {
  const out: FakeNode[] = [];
  for (let n: FakeNode | null = start; n !== null; n = n.parentNode) out.push(n);
  return out;
}

export class FakeNode {
  ownerDocument: FakeDocument;
  parentNode: FakeNode | null = null;
  childNodes: FakeNode[] = [];
  nodeType = 0;
  nodeName = '';
  _listeners = new Map<string, Listener[]>();
  constructor(doc: FakeDocument) { this.ownerDocument = doc; }
  get parentElement(): FakeElement | null { return this.parentNode !== null && this.parentNode.nodeType === 1 ? this.parentNode as FakeElement : null; }
  get firstChild(): FakeNode | null { return this.childNodes[0] ?? null; }
  get lastChild(): FakeNode | null { return this.childNodes[this.childNodes.length - 1] ?? null; }
  get children(): FakeElement[] { return this.childNodes.filter((c) => c.nodeType === 1) as FakeElement[]; }
  get isConnected(): boolean { return ancestorsOf(this).some((n) => n.nodeType === 9); }
  appendChild<T extends FakeNode>(child: T): T {
    if (child.parentNode !== null) child.parentNode.removeChild(child);
    child.parentNode = this;
    this.childNodes.push(child);
    return child;
  }
  append(...nodes: Array<FakeNode | string>): void {
    for (const n of nodes) this.appendChild(typeof n === 'string' ? this.ownerDocument.createTextNode(n) : n);
  }
  insertBefore<T extends FakeNode>(child: T, ref: FakeNode | null): T {
    if (child.parentNode !== null) child.parentNode.removeChild(child);
    const i = ref === null ? -1 : this.childNodes.indexOf(ref);
    child.parentNode = this;
    if (i < 0) this.childNodes.push(child); else this.childNodes.splice(i, 0, child);
    return child;
  }
  replaceChild<T extends FakeNode>(next: FakeNode, old: T): T {
    this.insertBefore(next, old);
    this.removeChild(old);
    return old;
  }
  removeChild<T extends FakeNode>(child: T): T {
    const i = this.childNodes.indexOf(child);
    if (i >= 0) { this.childNodes.splice(i, 1); child.parentNode = null; }
    return child;
  }
  remove(): void { if (this.parentNode !== null) this.parentNode.removeChild(this); }
  contains(node: FakeNode | null): boolean {
    for (let n = node; n !== null; n = n.parentNode) if (n === this) return true;
    return false;
  }
  addEventListener(type: string, fn: (e: FakeEvent) => void, opts?: boolean | { capture?: boolean }): void {
    const capture = opts === true || (typeof opts === 'object' && opts.capture === true);
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    (this._listeners.get(type) as Listener[]).push({ fn, capture });
  }
  removeEventListener(type: string, fn: (e: FakeEvent) => void, opts?: boolean | { capture?: boolean }): void {
    const capture = opts === true || (typeof opts === 'object' && opts.capture === true);
    const list = this._listeners.get(type);
    if (list) this._listeners.set(type, list.filter((l) => !(l.fn === fn && l.capture === capture)));
  }
  _run(ev: FakeEvent, capture: boolean): void {
    for (const l of (this._listeners.get(ev.type) ?? []).slice()) {
      if (l.capture !== capture) continue;
      ev.currentTarget = this;
      l.fn.call(this, ev);
      if (ev._stopNow) return;
    }
  }
  dispatchEvent(ev: FakeEvent): boolean {
    ev.target = this;
    const path = ancestorsOf(this);
    const doc = this.ownerDocument;
    if (path[path.length - 1] === doc && doc.defaultView !== null) path.push(doc.defaultView);
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
  /** Build and dispatch in one call; returns the event. */
  fire(type: string, init: Record<string, unknown> = {}): FakeEvent {
    const ev = new FakeEvent(type, init);
    this.dispatchEvent(ev);
    return ev;
  }
}

export class FakeText extends FakeNode {
  nodeValue: string;
  constructor(doc: FakeDocument, text: string) {
    super(doc);
    this.nodeType = 3;
    this.nodeName = '#text';
    this.nodeValue = String(text);
  }
  get textContent(): string { return this.nodeValue; }
  set textContent(v: string) { this.nodeValue = String(v); }
  get outerHTML(): string { return this.nodeValue; }
}

class ClassList {
  constructor(private readonly el: FakeElement) {}
  get _set(): Set<string> { return new Set(this.el._className.split(/\s+/).filter(Boolean)); }
  _write(s: Set<string>): void { this.el._className = Array.from(s).join(' '); }
  add(...c: string[]): void { const s = this._set; for (const x of c) s.add(x); this._write(s); }
  remove(...c: string[]): void { const s = this._set; for (const x of c) s.delete(x); this._write(s); }
  contains(c: string): boolean { return this._set.has(c); }
  toggle(c: string, on?: boolean): boolean {
    const s = this._set;
    const want = on === undefined ? !s.has(c) : on;
    if (want) s.add(c); else s.delete(c);
    this._write(s);
    return want;
  }
}

const dataKey = (attr: string): string => attr.slice(5).replace(/-([a-z])/g, (_, c: string) => c.toUpperCase());

/** `tag#id.a.b[attr="v"]`, one compound selector, no combinators. */
function matchesSimple(el: FakeElement, sel: string): boolean {
  let rest = sel;
  const m = /^[a-zA-Z][\w-]*|^\*/.exec(rest);
  if (m) {
    if (m[0] !== '*' && el.tagName !== m[0].toUpperCase()) return false;
    rest = rest.slice(m[0].length);
  }
  const re = /#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]|:not\(\[([\w-]+)\]\)/g;
  let k: RegExpExecArray | null;
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

export class FakeElement extends FakeNode {
  tagName: string;
  _className = '';
  classList: ClassList;
  _attrs = new Map<string, string>();
  style: Record<string, string> & { setProperty(k: string, v: string): void; removeProperty(k: string): void };
  dataset: Record<string, string> = {};
  hidden = false;
  disabled = false;
  checked = false;
  _value = '';
  _html = '';
  htmlFor = '';
  placeholder = '';
  min = '';
  max = '';
  step = '';
  rows = 0;
  title = '';
  offsetWidth = 120;
  offsetHeight = 28;
  clientWidth = 0;
  clientHeight = 0;
  rect: Partial<typeof RECT> | null = null;
  width = 0;
  height = 0;
  getContext?: (kind: string) => unknown;
  constructor(doc: FakeDocument, tag: string) {
    super(doc);
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.nodeName = this.tagName;
    this.classList = new ClassList(this);
    const style: Record<string, string> = {};
    this.style = Object.assign(style, {
      setProperty(k: string, v: string) { style[k] = v; },
      removeProperty(k: string) { delete style[k]; },
    }) as FakeElement['style'];
    if (tag === 'canvas') this.getContext = () => makeCtx().ctx;
  }
  get id(): string { return this._attrs.get('id') ?? ''; }
  set id(v: string) { this._attrs.set('id', String(v)); }
  get type(): string { return this._attrs.get('type') ?? ''; }
  set type(v: string) { this._attrs.set('type', String(v)); }
  get tabIndex(): number { return Number(this._attrs.get('tabindex') ?? (this.tagName === 'BUTTON' || this.tagName === 'INPUT' ? 0 : -1)); }
  set tabIndex(v: number) { this._attrs.set('tabindex', String(v)); }
  get className(): string { return this._className; }
  set className(v: string) { this._className = String(v); }
  get isContentEditable(): boolean {
    const v = this.getAttribute('contenteditable');
    return v !== null && v !== 'false';
  }
  /** A select reports the value of one of its options, the way a browser does. */
  get value(): string {
    if (this.tagName !== 'SELECT') return this._value;
    const opts = this.querySelectorAll('option') as FakeElement[];
    return opts.some((o) => o.value === this._value) ? this._value : (opts[0]?.value ?? '');
  }
  set value(v: string) { this._value = String(v); }
  get textContent(): string { return this.childNodes.map((c) => (c as FakeText | FakeElement).textContent).join(''); }
  set textContent(v: string) {
    this.childNodes = [];
    this._html = '';
    if (v !== '' && v !== null && v !== undefined) this.appendChild(this.ownerDocument.createTextNode(v));
  }
  /** Markup is kept as a string (the icons); an empty string clears the children. */
  get innerHTML(): string { return this._html + this.childNodes.map((c) => (c as FakeElement | FakeText).outerHTML).join(''); }
  set innerHTML(v: string) { this.childNodes = []; this._html = String(v); }
  get outerHTML(): string { return `<${this.tagName.toLowerCase()}>${this.innerHTML}</${this.tagName.toLowerCase()}>`; }
  setAttribute(k: string, v: string): void { if (k.startsWith('data-')) this.dataset[dataKey(k)] = String(v); else this._attrs.set(k, String(v)); }
  getAttribute(k: string): string | null {
    if (k.startsWith('data-')) { const v = this.dataset[dataKey(k)]; return v === undefined ? null : String(v); }
    return this._attrs.has(k) ? (this._attrs.get(k) as string) : null;
  }
  hasAttribute(k: string): boolean { return k.startsWith('data-') ? this.dataset[dataKey(k)] !== undefined : this._attrs.has(k); }
  removeAttribute(k: string): void { if (k.startsWith('data-')) delete this.dataset[dataKey(k)]; else this._attrs.delete(k); }
  matches(sel: string): boolean { return sel.split(',').some((s) => matchesSimple(this, s.trim())); }
  closest(sel: string): FakeElement | null {
    for (const n of ancestorsOf(this)) {
      if (n.nodeType !== 1) return null;
      if ((n as FakeElement).matches(sel)) return n as FakeElement;
    }
    return null;
  }
  _descendants(out: FakeElement[] = []): FakeElement[] {
    for (const c of this.childNodes) if (c.nodeType === 1) { out.push(c as FakeElement); (c as FakeElement)._descendants(out); }
    return out;
  }
  querySelectorAll(sel: string): FakeElement[] {
    const parts = sel.trim().split(/\s+/);
    let set = this._descendants();
    for (let i = 0; i < parts.length; i++) {
      const hits = set.filter((e) => matchesSimple(e, parts[i]));
      if (i === parts.length - 1) return hits;
      const next: FakeElement[] = [];
      for (const h of hits) for (const d of h._descendants()) if (!next.includes(d)) next.push(d);
      set = next;
    }
    return [];
  }
  querySelector(sel: string): FakeElement | null { return this.querySelectorAll(sel)[0] ?? null; }
  getBoundingClientRect(): { left: number; top: number; width: number; height: number; right: number; bottom: number } {
    if (this.rect !== null) {
      const r = { ...RECT, ...this.rect };
      return { ...r, right: r.left + r.width, bottom: r.top + r.height };
    }
    const p = this.parentElement !== null ? this.parentElement.getBoundingClientRect() : { ...RECT, right: 0, bottom: 0 };
    const left = p.left + this.offsetLeft;
    const top = p.top + this.offsetTop;
    return { left, top, width: this.offsetWidth, height: this.offsetHeight, right: left + this.offsetWidth, bottom: top + this.offsetHeight };
  }
  get offsetLeft(): number { return parseFloat(this.style.left) || 0; }
  get offsetTop(): number { return parseFloat(this.style.top) || 0; }
  focus(): void {
    const doc = this.ownerDocument;
    if (doc.activeElement === this) return;
    const prev = doc.activeElement;
    doc.activeElement = this;
    if (prev !== null && prev !== doc.body) prev.fire('blur', { bubbles: false });
    this.fire('focus', { bubbles: false });
    this.fire('focusin');
  }
  blur(): void {
    const doc = this.ownerDocument;
    if (doc.activeElement !== this) return;
    doc.activeElement = doc.body;
    this.fire('blur', { bubbles: false });
  }
  click(): FakeEvent { return this.fire('click'); }
  select(): void {}
  setPointerCapture(): void {}
  releasePointerCapture(): void {}
}

export class FakeDocument extends FakeNode {
  defaultView: FakeWindow | null = null;
  documentElement: FakeElement;
  head: FakeElement;
  body: FakeElement;
  activeElement: FakeElement;
  constructor() {
    super(null as unknown as FakeDocument);
    this.ownerDocument = this;
    this.nodeType = 9;
    this.nodeName = '#document';
    this.documentElement = this.appendChild(new FakeElement(this, 'html'));
    this.head = this.documentElement.appendChild(new FakeElement(this, 'head'));
    this.body = this.documentElement.appendChild(new FakeElement(this, 'body'));
    this.activeElement = this.body;
  }
  createElement(tag: string): FakeElement { return new FakeElement(this, tag); }
  createTextNode(t: string): FakeText { return new FakeText(this, t); }
  createRange(): { selectNodeContents(): void; collapse(): void } { return { selectNodeContents() {}, collapse() {} }; }
  getElementById(id: string): FakeElement | null { return this.documentElement.querySelector('#' + id); }
  querySelector(sel: string): FakeElement | null { return this.documentElement.querySelector(sel); }
  querySelectorAll(sel: string): FakeElement[] { return this.documentElement.querySelectorAll(sel); }
}

export class FakeWindow extends FakeNode {
  innerWidth: number;
  innerHeight: number;
  document: FakeDocument;
  constructor(doc: FakeDocument, width: number, height: number) {
    super(doc);
    this.nodeName = '#window';
    this.innerWidth = width;
    this.innerHeight = height;
    this.document = doc;
  }
  getSelection(): { removeAllRanges(): void; addRange(): void } { return { removeAllRanges() {}, addRange() {} }; }
}

export interface Dom {
  doc: FakeDocument;
  win: FakeWindow;
  /** A `.oac-widget` root at 0,0 sized `width` x `height`. */
  root: FakeElement;
  /** The chart container inside it, offset by a rail's width and a top bar's height. */
  chartEl: FakeElement;
}

/** A document with a widget root and a chart container laid out inside it. */
export function installDom({ width = 1000, height = 700, railW = 42, barH = 40 } = {}): Dom {
  const doc = new FakeDocument();
  const win = new FakeWindow(doc, width, height);
  doc.defaultView = win;
  const root = doc.createElement('div');
  root.className = 'oac-widget';
  root.rect = { left: 0, top: 0, width, height };
  doc.body.appendChild(root);
  const chartEl = doc.createElement('div');
  chartEl.className = 'oac-chart';
  chartEl.rect = { left: railW, top: barH, width: width - railW, height: height - barH };
  chartEl.clientWidth = width - railW;
  chartEl.clientHeight = height - barH;
  root.appendChild(chartEl);
  return { doc, win, root, chartEl };
}

/** The document as the widget code types it. */
export const asDoc = (d: FakeDocument): Document => d as unknown as Document;
export const asEl = (e: FakeElement): HTMLElement => e as unknown as HTMLElement;

// ── the suites (only when this file is the one under test) ────────────────

const isEntry = (expect.getState().testPath ?? '').replace(/\\/g, '/').endsWith('/widget-form.test.ts');
const suite: typeof describe = isEntry ? describe : ((() => {}) as unknown as typeof describe);

const doc = (): Document => asDoc(installDom().doc);

suite('controlsFromInputs', () => {
  it('folds a source input into a select over the canonical sources and keeps a pair as one row', () => {
    const inputs: ChartSettingsInput[] = [
      { key: 'period', type: 'number', label: 'Period', default: 14, min: 1, max: 500, step: 1, group: 'Inputs' },
      { key: 'source', type: 'source', label: 'Source', default: 'close', group: 'Inputs' },
      { key: 'symbol.body', type: 'colorPair', label: 'Body', group: 'Candles', enabled: { key: 'symbol.bodyVisible', default: true },
        up: { key: 'symbol.upColor', label: 'Up', default: '#0f0' }, down: { key: 'symbol.downColor', label: 'Down', default: '#f00' } },
      { key: 'flag', type: 'boolean', label: 'Flag', default: false },
    ];
    const c = controlsFromInputs(inputs);
    expect(c.map((x) => x.kind)).toEqual(['number', 'select', 'colorPair', 'boolean']);
    expect(c[0]).toMatchObject({ min: 1, max: 500, step: 1, group: 'Inputs' });
    expect(c[1].options).toBe(INDICATOR_SOURCES);
    expect(c[2].pair).toEqual({ enabled: { key: 'symbol.bodyVisible' }, up: { key: 'symbol.upColor', label: 'Up' }, down: { key: 'symbol.downColor', label: 'Down' } });
  });
});

suite('controlsFromFields', () => {
  /**
   * 2.2.1: the field is on every member of the union, so a variant that forgot
   * to copy it would drop the help text for that one type only, which is
   * exactly the kind of gap that ships.
   */
  it('carries a tooltip through for every input type, colourPair included', () => {
    const inputs: ChartSettingsInput[] = [
      { key: 'n', type: 'number', label: 'N', default: 1, tooltip: 'number help' },
      { key: 'b', type: 'boolean', label: 'B', default: true, tooltip: 'boolean help' },
      { key: 'c', type: 'color', label: 'C', default: '#fff', tooltip: 'colour help' },
      { key: 't', type: 'text', label: 'T', default: '', tooltip: 'text help' },
      { key: 's', type: 'select', label: 'S', default: 'x', options: [{ label: 'X', value: 'x' }], tooltip: 'select help' },
      { key: 'src', type: 'source', label: 'Src', default: 'close', tooltip: 'source help' },
      { key: 'p', type: 'colorPair', label: 'P', tooltip: 'pair help',
        up: { key: 'p.u', label: 'Up', default: '#0f0' }, down: { key: 'p.d', label: 'Down', default: '#f00' } },
    ];
    expect(controlsFromInputs(inputs).map((c) => c.tooltip)).toEqual([
      'number help', 'boolean help', 'colour help', 'text help', 'select help', 'source help', 'pair help',
    ]);
  });

  it('leaves tooltip undefined when the schema does not set one', () => {
    const controls = controlsFromInputs([{ key: 'n', type: 'number', label: 'N', default: 1 }]);
    expect(controls[0].tooltip).toBeUndefined();
  });

  it('maps each draw-tier kind onto a control and names the group in our words', () => {
    const fields: SettingsField[] = [
      { path: 'style.color', label: 'Color', kind: 'color', group: 'line' },
      { path: 'style.lineStyle', label: 'Line style', kind: 'lineStyle', options: LINE_STYLE_OPTIONS, group: 'line' },
      { path: 'style.fillOpacity', label: 'Fill opacity', kind: 'opacity', group: 'fill' },
      { path: 'style.levels', label: 'Levels', kind: 'levels', group: 'levels' },
      { path: 'text.value', label: 'Text', kind: 'text', group: 'text' },
      { path: 'text.fontFamily', label: 'Font', kind: 'select', options: FONT_OPTIONS, group: 'text' },
      { path: 'props.free', label: 'Free', kind: 'select', group: 'behavior' },
      { path: 'style.extendLeft', label: 'Extend left', kind: 'boolean', group: 'behavior' },
    ];
    const c = controlsFromFields(fields);
    expect(c.map((x) => x.kind)).toEqual(['color', 'select', 'opacity', 'custom', 'multiline', 'select', 'text', 'boolean']);
    expect(c[1].options).toBe(LINE_STYLE_OPTIONS);
    expect(c[3].custom).toBe('levels');
    expect(c.map((x) => x.group)).toEqual(['Line', 'Line', 'Fill', 'Levels', 'Text', 'Text', 'Behavior', 'Behavior']);
  });
});

suite('renderForm', () => {
  const controls: FormControl[] = [
    { key: 'a.on', kind: 'boolean', label: 'Switch', group: 'One' },
    { key: 'a.n', kind: 'number', label: 'Number', group: 'One', min: 1, max: 10, step: 0.5 },
    { key: 'a.pair', kind: 'colorPair', label: 'Body', group: 'Two',
      pair: { enabled: { key: 'a.pairOn' }, up: { key: 'a.up', label: 'Up' }, down: { key: 'a.down', label: 'Down' } } },
    { key: 'a.sel', kind: 'select', label: 'Pick', group: 'Two', options: [{ value: 'x', label: 'X' }, { value: 'y', label: 'Y' }] },
    { key: 'a.op', kind: 'opacity', label: 'Opacity', group: 'Two' },
    { key: 'a.txt', kind: 'text', label: 'Text', group: 'Two' },
  ];
  const values = { 'a.on': true, 'a.n': 3, 'a.pairOn': false, 'a.up': 'rgba(38,166,154,0.4)', 'a.down': '#ef5350', 'a.sel': 'y', 'a.op': 0.25, 'a.txt': 'hi' };

  function mount(extra: Partial<Parameters<typeof renderForm>[2]> = {}) {
    const d = doc();
    const host = d.createElement('div');
    const changes: Array<[string, unknown]> = [];
    const form = renderForm(host, controls, { values, idPrefix: 't', onChange: (k, v) => changes.push([k, v]), ...extra });
    return { host: host as unknown as FakeElement, form, changes, d };
  }

  /**
   * 2.2.1: a label has nowhere to explain itself in a dense panel, so the help
   * text rides on a mark beside it. It must not reshape the row. Since 2.5.10
   * the text reaches assistive technology as the control's description, not
   * as part of its name, and the mark is no tab stop: its title never showed
   * on focus, so the stop gave a keyboard user nothing to read.
   */
  it('renders a help mark inside the label only for a control that carries a tooltip', () => {
    const d = doc();
    const host = d.createElement('div');
    renderForm(host, [
      { key: 'a.n', kind: 'number', label: 'Length', tooltip: 'Bars in the window.' },
      { key: 'a.plain', kind: 'number', label: 'Plain' },
      { key: 'a.blank', kind: 'number', label: 'Blank', tooltip: '' },
    ], { values: {}, idPrefix: 't', onChange: () => {} });
    const rows = (host as unknown as FakeElement).querySelectorAll('.oac-row');
    expect(rows.length).toBe(3);

    const mark = rows[0].querySelector('.oac-help');
    expect(mark).not.toBeNull();
    expect(mark!.textContent).toBe('?');
    expect(mark!.title).toBe('Bars in the window.');
    expect(mark!.getAttribute('aria-hidden')).toBe('true');
    expect(mark!.getAttribute('aria-label')).toBeNull();
    expect(mark!.getAttribute('tabindex')).toBeNull();
    expect(rows[0].querySelector('input')!.getAttribute('aria-description')).toBe('Bars in the window.');
    expect(rows[1].querySelector('input')!.getAttribute('aria-description')).toBeNull();
    // Inside the label, so it stays with the words when a long label wraps.
    expect(rows[0].querySelector('.oac-row__label')!.querySelector('.oac-help')).not.toBeNull();

    expect(rows[1].querySelector('.oac-help')).toBeNull();
    // An empty string is not help text; it would draw a mark with nothing behind it.
    expect(rows[2].querySelector('.oac-help')).toBeNull();
  });

  it('marks a paired-colour row and a boolean row too, not only the plain shape', () => {
    const d = doc();
    const host = d.createElement('div');
    renderForm(host, [
      { key: 'a.on', kind: 'boolean', label: 'Show', tooltip: 'Draw the band.' },
      { key: 'a.pair', kind: 'colorPair', label: 'Body', tooltip: 'Up and down colours.',
        pair: { up: { key: 'a.up', label: 'Up' }, down: { key: 'a.down', label: 'Down' } } },
    ], { values: {}, idPrefix: 't', onChange: () => {} });
    const rows = (host as unknown as FakeElement).querySelectorAll('.oac-row');
    expect(rows[0].querySelector('.oac-help')!.title).toBe('Draw the band.');
    expect(rows[0].querySelector('input')!.getAttribute('aria-description')).toBe('Draw the band.');
    expect(rows[1].querySelector('.oac-help')!.title).toBe('Up and down colours.');
    // The pair's label points at its first swatch, which carries the description.
    const target = (host as unknown as FakeElement).querySelector(`#${(rows[1].querySelector('label') as FakeElement).htmlFor}`)!;
    expect(target.getAttribute('aria-description')).toBe('Up and down colours.');
    // The pair still renders both swatches: the mark must not have displaced one.
    expect(rows[1].querySelectorAll('input[type=color]').length).toBe(2);
  });

  it('puts the rows under a heading in a group it names, so a second Color says whose', () => {
    const { host } = mount();
    const groups = host.querySelectorAll('[role="group"]');
    expect(groups).toHaveLength(2);
    const heads = host.querySelectorAll('.oac-head');
    expect(groups.map((g) => host.querySelector(`#${g.getAttribute('aria-labelledby')}`))).toEqual(heads);
    expect(groups[0].querySelectorAll('.oac-row').map((r) => r.dataset.key)).toEqual(['a.on', 'a.n']);
    expect(groups[1].querySelectorAll('.oac-row').map((r) => r.dataset.key)).toEqual(['a.pair', 'a.sel', 'a.op', 'a.txt']);
  });

  it('draws group heads once, a switch in the switch column, and a pair as one row of two swatches', () => {
    const { host } = mount();
    expect(host.querySelectorAll('.oac-head').map((h) => h.textContent)).toEqual(['One', 'Two']);
    const rows = host.querySelectorAll('.oac-row');
    expect(rows.length).toBe(6);
    const sw = rows[0];
    expect(sw.childNodes[0]).toBe(sw.querySelector('input[type="checkbox"]'));
    expect((sw.querySelector('input') as FakeElement).checked).toBe(true);
    const pair = rows[2];
    expect(pair.querySelectorAll('input[type="color"]').length).toBe(2);
    const [up, down] = pair.querySelectorAll('input[type="color"]');
    expect(up.value).toBe('#26a69a');   // rgba folded to hex for the picker
    expect(down.value).toBe('#ef5350');
    expect(up.title).toBe('Up');
    expect(down.title).toBe('Down');
    expect((pair.querySelector('input[type="checkbox"]') as FakeElement).checked).toBe(false);
    expect((pair.querySelector('label') as FakeElement).htmlFor).toBe('t-a-pairOn');
  });

  it('reports values in the declared type: a clamped number, a fraction for opacity, a string for a select', () => {
    const { host, changes } = mount();
    const n = host.querySelector('#t-a-n') as FakeElement;
    n.value = '12';
    n.fire('change');
    expect(changes.pop()).toEqual(['a.n', 10]);
    expect(n.value).toBe('10');
    n.value = '';
    n.fire('change');
    expect(changes.length).toBe(0);
    expect(n.value).toBe('10');
    const range = host.querySelector('input[type="range"]') as FakeElement;
    range.value = '40';
    range.fire('input');
    expect(host.querySelector('output')?.textContent).toBe('40%');
    expect(changes.length).toBe(0);
    range.fire('change');
    expect(changes.pop()).toEqual(['a.op', 0.4]);
    const sel = host.querySelector('select') as FakeElement;
    expect(sel.value).toBe('y');
    sel.value = 'x';
    sel.fire('change');
    expect(changes.pop()).toEqual(['a.sel', 'x']);
    const cb = host.querySelector('#t-a-on') as FakeElement;
    cb.checked = false;
    cb.fire('change');
    expect(changes.pop()).toEqual(['a.on', false]);
  });

  it('emits colours and sliders on input only when live, and never the same value twice in a row', () => {
    const quiet = mount();
    const up = quiet.host.querySelector('#t-a-up') as FakeElement;
    up.value = '#123456';
    up.fire('input');
    expect(quiet.changes.length).toBe(0);
    up.fire('change');
    expect(quiet.changes).toEqual([['a.up', 'rgba(18,52,86,0.4)']]);
    const live = mount({ live: true });
    const up2 = live.host.querySelector('#t-a-up') as FakeElement;
    up2.value = '#abcdef';
    up2.fire('input');
    up2.fire('change');
    expect(live.changes).toEqual([['a.up', 'rgba(171,205,239,0.4)']]);
  });

  it('draws a control with a reason disabled and titled, one option of a select included', () => {
    const { host } = mount({
      unavailable: (key, option) => (key === 'a.n' ? 'no data' : key === 'a.sel' && option === 'y' ? 'not here' : null),
    });
    const n = host.querySelector('#t-a-n') as FakeElement;
    expect(n.disabled).toBe(true);
    expect(n.title).toBe('no data');
    expect((n.closest('.oac-row') as FakeElement).classList.contains('oac-row--off')).toBe(true);
    const opts = host.querySelectorAll('option');
    expect(opts[1].disabled).toBe(true);
    expect(opts[1].title).toBe('not here');
    expect(opts[0].disabled).toBe(false);
  });

  it('keeps a value outside the option list as its own entry rather than snapping to the first', () => {
    const { host } = mount({ values: { ...values, 'a.sel': 'custom-stack' } });
    const sel = host.querySelector('select') as FakeElement;
    expect(sel.querySelectorAll('option').map((o) => o.value)).toEqual(['x', 'y', 'custom-stack']);
    expect(sel.value).toBe('custom-stack');
  });

  it('syncs every control the user is not in, and collects the whole form', () => {
    const { host, form } = mount();
    const txt = host.querySelector('#t-a-txt') as FakeElement;
    txt.focus();
    txt.value = 'typing';
    form.sync({ ...values, 'a.txt': 'from-chart', 'a.n': 7, 'a.op': 0.5 });
    expect(txt.value).toBe('typing');
    expect((host.querySelector('#t-a-n') as FakeElement).value).toBe('7');
    expect((host.querySelector('input[type="range"]') as FakeElement).value).toBe('50');
    expect(form.values()).toMatchObject({ 'a.on': true, 'a.n': 7, 'a.pairOn': false, 'a.up': 'rgba(38,166,154,0.4)', 'a.sel': 'y', 'a.op': 0.5, 'a.txt': 'typing' });
    expect(form.focusFirst()).toBe(true);
  });

  it('hands a custom row to the dialog and drops it when the dialog declines', () => {
    const d = doc();
    const host = d.createElement('div');
    renderForm(host, [
      { key: 'style.levels', kind: 'custom', label: 'Levels', custom: 'levels' },
      { key: 'x.skip', kind: 'custom', label: 'Skip', custom: 'skip' },
    ], { values: {}, idPrefix: 'c', onChange: () => {}, custom: (c) => (c.custom === 'levels' ? d.createElement('button') : null) });
    const rows = (host as unknown as FakeElement).querySelectorAll('.oac-row');
    expect(rows.length).toBe(1);
    expect(rows[0].querySelector('button')).not.toBeNull();
  });
});

suite('value helpers', () => {
  it('prints numbers without float noise', () => {
    expect(formatNumber(2.0000000000000004)).toBe('2');
    expect(formatNumber(1.5)).toBe('1.5');
    expect(formatNumber(0.1 + 0.2)).toBe('0.3');
  });
});

suite('furniture', () => {
  it('builds the frame in the standard places and closes from the top-right control', () => {
    const d = doc();
    let closed = 0;
    const f = dialogFrame(d, { title: 'Chart settings', onClose: () => { closed++; } });
    const card = f.el as unknown as FakeElement;
    expect(card.getAttribute('role')).toBe('dialog');
    expect(card.classList.contains('oac-panel')).toBe(true);
    expect(card.querySelector('.oac-dialog__title')?.textContent).toBe('Chart settings');
    expect(card.getAttribute('aria-labelledby')).toBe(card.querySelector('.oac-dialog__title')?.id);
    (f.closeButton as unknown as FakeElement).click();
    expect(closed).toBe(1);
    expect(card.children.map((c) => c.className)).toEqual(['oac-dialog__head', 'oac-dialog__body', 'oac-dialog__foot']);
    const foot = card.querySelector('.oac-dialog__foot') as FakeElement;
    expect(foot.children.map((c) => c.className)).toEqual(['oac-dialog__lead', 'oac-spacer', 'oac-dialog__actions']);
  });

  it('keeps the widget chords out of a dialog while letting Escape and Tab through', () => {
    const d = doc();
    const f = dialogFrame(d, { title: 'x', onClose: () => {} });
    const card = f.el as unknown as FakeElement;
    const seen: string[] = [];
    (d.body as unknown as FakeElement).appendChild(card);
    (d.body as unknown as FakeElement).addEventListener('keydown', (e) => seen.push(String(e.key)));
    card.fire('keydown', { key: 'Delete' });
    card.fire('keydown', { key: 'Escape' });
    card.fire('keydown', { key: 'Tab' });
    expect(seen).toEqual(['Escape', 'Tab']);
  });

  it('draws tabs with glyphs and moves the selection with the arrow keys', () => {
    const d = doc();
    const picked: string[] = [];
    const list = tabList(d, [{ id: 'a', label: 'A', icon: 'settings' }, { id: 'b', label: 'B' }], 'a', 'rail', (id) => picked.push(id));
    const nav = list.el as unknown as FakeElement;
    (d.body as unknown as FakeElement).appendChild(nav);
    const tabs = nav.querySelectorAll('[role="tab"]');
    expect(tabs.length).toBe(2);
    expect(tabs[0].getAttribute('aria-selected')).toBe('true');
    expect(tabs[0].querySelector('.oac-glyph')?.innerHTML).toBe(chromeIconSvg('settings'));
    expect(tabs[1].querySelector('.oac-glyph')).toBeNull();
    tabs[0].focus();
    tabs[0].fire('keydown', { key: 'ArrowDown' });
    expect(picked).toEqual(['b']);
    // The buttons stay in place, so the arrow key lands focus on the picked tab.
    expect(d.activeElement).toBe(tabs[1]);
    expect(tabs[1].getAttribute('aria-selected')).toBe('true');
    expect(tabs[0].getAttribute('aria-selected')).toBe('false');
    tabs[1].click();
    expect(picked).toEqual(['b', 'b']);
    list.setActive('a');
    expect(tabs[0].tabIndex).toBe(0);
    expect(tabs[1].tabIndex).toBe(-1);
  });

  it('labels an icon-only button for assistive technology and stops its click at the button', () => {
    const d = doc();
    let hits = 0;
    const b = button(d, { label: 'Delete', icon: 'trash', iconOnly: true, chord: 'Del', variant: 'danger', onClick: () => { hits++; } }) as unknown as FakeElement;
    const host = d.createElement('div') as unknown as FakeElement;
    let bubbled = 0;
    host.addEventListener('click', () => { bubbled++; });
    host.appendChild(b);
    expect(b.getAttribute('aria-label')).toBe('Delete');
    expect(b.title).toBe('Delete (Del)');
    expect(b.classList.contains('oac-btn--danger')).toBe(true);
    b.click();
    expect(hits).toBe(1);
    expect(bubbled).toBe(0);
  });
});

suite('placement', () => {
  it('places a panel at a point and keeps it inside the root', () => {
    const { doc: d, root } = installDom({ width: 500, height: 300 });
    const panel = d.createElement('div');
    panel.offsetWidth = 200;
    panel.offsetHeight = 100;
    root.appendChild(panel);
    placePanel(asEl(root), asEl(panel), { point: { x: 100, y: 50 } });
    expect([panel.style.left, panel.style.top]).toEqual(['100px', '50px']);
    placePanel(asEl(root), asEl(panel), { point: { x: 450, y: 280 } });
    expect([panel.style.left, panel.style.top]).toEqual(['296px', '196px']);
  });

  it('places a panel below its anchor, and above it when the bottom has no room', () => {
    const { doc: d, root } = installDom({ width: 500, height: 300 });
    const anchor = d.createElement('button');
    anchor.rect = { left: 40, top: 20, width: 80, height: 28 };
    root.appendChild(anchor);
    const panel = d.createElement('div');
    panel.offsetWidth = 200;
    panel.offsetHeight = 100;
    root.appendChild(panel);
    placePanel(asEl(root), asEl(panel), { anchor: asEl(anchor) });
    expect([panel.style.left, panel.style.top]).toEqual(['40px', '54px']);
    anchor.rect = { left: 40, top: 250, width: 80, height: 28 };
    placePanel(asEl(root), asEl(panel), { anchor: asEl(anchor) });
    expect(panel.style.top).toBe('144px');
  });

  it('puts a popover under the lowest anchor of a selection, offset by the chart container', () => {
    const { root, chartEl } = installDom({ width: 1000, height: 700, railW: 42, barH: 40 });
    const chart = {
      timeToCoordinate: (t: number) => t / 10,
      priceToCoordinate: (p: number) => 600 - p,
      panes: () => [{ element: { parentElement: asEl(chartEl) } as unknown as HTMLElement }],
    };
    const p = selectionPoint(asEl(root), chart, [{ paneIndex: 0, points: [{ time: 1000, price: 100 }, { time: 3000, price: 300 }] }]);
    expect(p).toEqual({ x: 42 + 100, y: 40 + 500 + 12 });
    expect(selectionPoint(asEl(root), chart, [])).toEqual({ x: 102, y: 100 });
  });
});

suite('openPanel', () => {
  function host() {
    const calls: string[] = [];
    let onClose: (() => void) | undefined;
    return {
      calls,
      openOverlay: (_el: HTMLElement, opts?: { onClose?: () => void }) => {
        calls.push('open');
        onClose = opts?.onClose;
        return () => { calls.push('closer'); onClose?.(); };
      },
      shellClose: () => onClose?.(),
    };
  }

  it('closing from the dialog asks the shell once and does not run the dismiss path', () => {
    const d = doc();
    const h = host();
    let dismissed = 0;
    const panel = d.createElement('div');
    const s = openPanel(h, panel, {}, () => { dismissed++; });
    expect(s.isOpen()).toBe(true);
    s.close();
    s.close();
    expect(h.calls).toEqual(['open', 'closer']);
    expect(dismissed).toBe(0);
    expect(s.isOpen()).toBe(false);
  });

  it('closing from the shell runs the dismiss path once and never calls the closer back', () => {
    const d = doc();
    const h = host();
    let dismissed = 0;
    const panel = d.createElement('div');
    const s = openPanel(h, panel, {}, () => { dismissed++; s.close(); });
    h.shellClose();
    expect(dismissed).toBe(1);
    expect(h.calls).toEqual(['open']);
    expect(s.isOpen()).toBe(false);
  });
});
