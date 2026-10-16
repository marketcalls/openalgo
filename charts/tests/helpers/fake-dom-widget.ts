/**
 * A fake DOM with enough of the tree, selector and event model for the widget
 * tier: `fake-dom.ts` gives a Chart canvases and listeners; the widget also
 * needs a document with a body, `querySelector`, `closest`, `classList`,
 * `dataset`, focus, and events that capture and bubble.
 *
 * Deliberately not a browser. `innerHTML` stores the string and clears the
 * children (the widget only writes it on glyph leaves, which nothing queries
 * into), selectors cover the compound forms the widget uses, and layout is
 * whatever a test sets on `offsetWidth`, `offsetHeight` and `rect`.
 */
import { makeCtx } from './fake-ctx';

export interface FakeEventInit {
  bubbles?: boolean;
  detail?: number;
  key?: string;
  code?: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  shiftKey?: boolean;
  clientX?: number;
  clientY?: number;
  button?: number;
  buttons?: number;
  pointerId?: number;
  pointerType?: string;
  relatedTarget?: unknown;
}

export class FakeEvent {
  public readonly type: string;
  public target: FakeNode | null = null;
  public currentTarget: FakeNode | null = null;
  public readonly bubbles: boolean;
  public defaultPrevented = false;
  public propagationStopped = false;
  public immediateStopped = false;
  public detail: number;
  public key: string;
  public code: string;
  public ctrlKey: boolean;
  public metaKey: boolean;
  public altKey: boolean;
  public shiftKey: boolean;
  public clientX: number;
  public clientY: number;
  public button: number;
  public buttons: number;
  public pointerId: number;
  public pointerType: string;
  public relatedTarget: unknown;

  public constructor(type: string, init: FakeEventInit = {}) {
    this.type = type;
    this.bubbles = init.bubbles ?? !['focus', 'blur', 'pointerenter', 'pointerleave'].includes(type);
    this.detail = init.detail ?? 1;
    this.key = init.key ?? '';
    this.code = init.code ?? '';
    this.ctrlKey = init.ctrlKey ?? false;
    this.metaKey = init.metaKey ?? false;
    this.altKey = init.altKey ?? false;
    this.shiftKey = init.shiftKey ?? false;
    this.clientX = init.clientX ?? 0;
    this.clientY = init.clientY ?? 0;
    this.button = init.button ?? 0;
    this.buttons = init.buttons ?? 0;
    this.pointerId = init.pointerId ?? 1;
    this.pointerType = init.pointerType ?? 'mouse';
    this.relatedTarget = init.relatedTarget ?? null;
  }

  public preventDefault(): void { this.defaultPrevented = true; }
  public stopPropagation(): void { this.propagationStopped = true; }
  public stopImmediatePropagation(): void { this.propagationStopped = true; this.immediateStopped = true; }
}

interface Listener { fn: (e: FakeEvent) => void; capture: boolean; once: boolean }

class FakeClassList {
  private readonly _el: FakeElement;
  public constructor(el: FakeElement) { this._el = el; }
  private _set(): Set<string> { return new Set(this._el.className.split(/\s+/).filter(Boolean)); }
  private _write(s: Set<string>): void { this._el.className = Array.from(s).join(' '); }
  public add(...names: string[]): void { const s = this._set(); for (const n of names) s.add(n); this._write(s); }
  public remove(...names: string[]): void { const s = this._set(); for (const n of names) s.delete(n); this._write(s); }
  public contains(name: string): boolean { return this._set().has(name); }
  public toggle(name: string, force?: boolean): boolean {
    const s = this._set();
    const on = force ?? !s.has(name);
    if (on) s.add(name); else s.delete(name);
    this._write(s);
    return on;
  }
  public get length(): number { return this._set().size; }
}

class FakeStyle {
  [key: string]: unknown;
  private readonly _props = new Map<string, string>();
  public setProperty(name: string, value: string): void { this._props.set(name, value); }
  public removeProperty(name: string): string { const v = this._props.get(name) ?? ''; this._props.delete(name); return v; }
  public getPropertyValue(name: string): string { return this._props.get(name) ?? ''; }
}

export class FakeNode {
  public nodeType = 1;
  public parentNode: FakeNode | null = null;
  public childNodes: FakeNode[] = [];
  public ownerDocument: FakeDocument;
  protected readonly _listeners = new Map<string, Listener[]>();

  public constructor(doc: FakeDocument) { this.ownerDocument = doc; }

  public get parentElement(): FakeElement | null {
    return this.parentNode instanceof FakeElement ? this.parentNode : null;
  }

  public get isConnected(): boolean {
    if (this instanceof FakeDocument) return true;
    for (let n = this.parentNode; n !== null; n = n.parentNode) if (n instanceof FakeDocument) return true;
    return false;
  }

  public addEventListener(type: string, fn: (e: FakeEvent) => void, opts?: boolean | { capture?: boolean; once?: boolean; passive?: boolean }): void {
    const capture = typeof opts === 'boolean' ? opts : opts?.capture === true;
    const once = typeof opts === 'object' && opts?.once === true;
    const list = this._listeners.get(type) ?? [];
    list.push({ fn, capture, once });
    this._listeners.set(type, list);
  }

  public removeEventListener(type: string, fn: (e: FakeEvent) => void, opts?: boolean | { capture?: boolean }): void {
    const capture = typeof opts === 'boolean' ? opts : opts?.capture === true;
    const list = this._listeners.get(type);
    if (list === undefined) return;
    this._listeners.set(type, list.filter((l) => !(l.fn === fn && l.capture === capture)));
  }

  /** Run this node's listeners for one phase. */
  public runListeners(e: FakeEvent, capture: boolean): void {
    const list = this._listeners.get(e.type);
    if (list === undefined) return;
    e.currentTarget = this;
    for (const l of list.slice()) {
      if (l.capture !== capture) continue;
      if (l.once) this.removeEventListener(e.type, l.fn, l.capture);
      l.fn(e);
      if (e.immediateStopped) return;
    }
  }

  /** Capture from the document down, target, then bubble up. Returns `!defaultPrevented`. */
  public dispatchEvent(e: FakeEvent): boolean {
    e.target = this;
    const path: FakeNode[] = [this];
    for (let n = this.parentNode; n !== null; n = n.parentNode) path.push(n);
    for (let i = path.length - 1; i >= 1; i--) {
      path[i].runListeners(e, true);
      if (e.propagationStopped) return !e.defaultPrevented;
    }
    this.runListeners(e, true);
    if (!e.propagationStopped) this.runListeners(e, false);
    if (e.propagationStopped || !e.bubbles) return !e.defaultPrevented;
    for (let i = 1; i < path.length; i++) {
      path[i].runListeners(e, false);
      if (e.propagationStopped) break;
    }
    return !e.defaultPrevented;
  }

  /** The old fake-dom's shorthand: dispatch a plain object as the event. */
  public dispatch(type: string, event: Record<string, unknown>): void {
    const e = new FakeEvent(type, event as FakeEventInit);
    Object.assign(e, event);
    this.dispatchEvent(e);
  }

  public get children(): FakeElement[] { return this.childNodes.filter((c): c is FakeElement => c instanceof FakeElement); }
  public get firstChild(): FakeNode | null { return this.childNodes[0] ?? null; }
  public get lastChild(): FakeNode | null { return this.childNodes[this.childNodes.length - 1] ?? null; }
  public get firstElementChild(): FakeElement | null { return this.children[0] ?? null; }

  public appendChild<T extends FakeNode>(child: T): T {
    child.parentNode?.removeChild(child);
    child.parentNode = this;
    this.childNodes.push(child);
    return child;
  }

  public append(...nodes: (FakeNode | string)[]): void {
    for (const n of nodes) this.appendChild(typeof n === 'string' ? this.ownerDocument.createTextNode(n) : n);
  }

  public prepend(...nodes: FakeNode[]): void {
    for (const n of nodes.reverse()) this.insertBefore(n, this.firstChild);
  }

  public insertBefore<T extends FakeNode>(child: T, ref: FakeNode | null): T {
    if (ref === null) return this.appendChild(child);
    child.parentNode?.removeChild(child);
    const i = this.childNodes.indexOf(ref);
    child.parentNode = this;
    this.childNodes.splice(i < 0 ? this.childNodes.length : i, 0, child);
    return child;
  }

  public removeChild<T extends FakeNode>(child: T): T {
    const i = this.childNodes.indexOf(child);
    if (i >= 0) this.childNodes.splice(i, 1);
    child.parentNode = null;
    return child;
  }

  public replaceChildren(...nodes: FakeNode[]): void {
    for (const c of this.childNodes.slice()) this.removeChild(c);
    for (const n of nodes) this.appendChild(n);
  }

  public remove(): void { this.parentNode?.removeChild(this); }

  public replaceWith(other: FakeNode): void {
    const p = this.parentNode;
    if (p === null) return;
    p.insertBefore(other, this);
    p.removeChild(this);
  }

  public contains(n: FakeNode | null): boolean {
    for (let c: FakeNode | null = n; c !== null; c = c.parentNode) if (c === this) return true;
    return false;
  }

  public get textContent(): string {
    return this.childNodes.map((c) => c.textContent).join('');
  }

  public set textContent(v: string) {
    for (const c of this.childNodes.slice()) this.removeChild(c);
    if (v !== '') this.appendChild(this.ownerDocument.createTextNode(v));
  }

  /** Depth-first descendants. */
  public descendants(): FakeElement[] {
    const out: FakeElement[] = [];
    const walk = (n: FakeNode): void => {
      for (const c of n.childNodes) {
        if (c instanceof FakeElement) { out.push(c); walk(c); }
      }
    };
    walk(this);
    return out;
  }

  public querySelectorAll(selector: string): FakeElement[] {
    return this.descendants().filter((el) => el.matches(selector));
  }

  public querySelector(selector: string): FakeElement | null {
    return this.querySelectorAll(selector)[0] ?? null;
  }

  public getElementById(id: string): FakeElement | null {
    return this.descendants().find((el) => el.id === id) ?? null;
  }
}

export class FakeText extends FakeNode {
  public data: string;
  public constructor(doc: FakeDocument, data: string) { super(doc); this.nodeType = 3; this.data = data; }
  public override get textContent(): string { return this.data; }
  public override set textContent(v: string) { this.data = v; }
}

interface Compound { tag: string | null; id: string | null; classes: string[]; attrs: { name: string; value: string | null }[] }

function parseCompound(s: string): Compound {
  const out: Compound = { tag: null, id: null, classes: [], attrs: [] };
  const re = /^(\*|[a-zA-Z][\w-]*)|#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]/g;
  let rest = s;
  while (rest.length > 0) {
    re.lastIndex = 0;
    const m = re.exec(rest);
    if (m === null || m.index !== 0) throw new Error(`fake-dom: unsupported selector "${s}"`);
    if (m[1] !== undefined) out.tag = m[1] === '*' ? null : m[1].toUpperCase();
    else if (m[2] !== undefined) out.id = m[2];
    else if (m[3] !== undefined) out.classes.push(m[3]);
    else out.attrs.push({ name: m[4], value: m[5] ?? null });
    rest = rest.slice(m[0].length);
  }
  return out;
}

interface Step { compound: Compound; combinator: ' ' | '>' | null }

/**
 * Split one selector into compounds joined by descendant (space) or child
 * (`>`) combinators, leaving whitespace inside `[...]` and quotes alone.
 * Comma-separated alternatives are split first by `splitAlternatives`.
 */
function parseSelector(sel: string): Step[] {
  const steps: Step[] = [];
  let buf = '';
  let depth = 0;
  let quote = false;
  let pending: ' ' | '>' | null = null;
  const flush = (): void => {
    if (buf.trim() === '') return;
    steps.push({ compound: parseCompound(buf.trim()), combinator: steps.length === 0 ? null : pending ?? ' ' });
    buf = '';
    pending = null;
  };
  for (const ch of sel) {
    if (ch === '"') quote = !quote;
    if (!quote) {
      if (ch === '[') depth++;
      if (ch === ']') depth--;
      if (depth === 0) {
        if (ch === '>') { flush(); pending = '>'; continue; }
        if (/\s/.test(ch)) { flush(); continue; }
      }
    }
    buf += ch;
  }
  flush();
  return steps;
}

function splitAlternatives(sel: string): string[] {
  const out: string[] = [];
  let buf = '';
  let depth = 0;
  let quote = false;
  for (const ch of sel) {
    if (ch === '"') quote = !quote;
    if (!quote && ch === '[') depth++;
    if (!quote && ch === ']') depth--;
    if (!quote && depth === 0 && ch === ',') { out.push(buf); buf = ''; continue; }
    buf += ch;
  }
  out.push(buf);
  return out.map((s) => s.trim()).filter((s) => s !== '');
}

export class FakeElement extends FakeNode {
  public readonly tagName: string;
  public className = '';
  public readonly classList = new FakeClassList(this);
  public readonly style = new FakeStyle();
  public readonly dataset: Record<string, string | undefined> = {};
  public readonly attributes = new Map<string, string>();
  public offsetWidth = 0;
  public offsetHeight = 0;
  public clientWidth = 0;
  public clientHeight = 0;
  public rect: { left: number; top: number; width: number; height: number } | null = null;
  public value = '';
  public checked = false;
  public disabled = false;
  public placeholder = '';
  public title = '';
  public href = '';
  public download = '';
  private _innerHTML = '';
  private _type: string | null = null;
  public width = 0;
  public height = 0;
  /** Clicks on this element, for a test asserting a download anchor fired. */
  public clicks = 0;

  public constructor(doc: FakeDocument, tag: string) {
    super(doc);
    this.tagName = tag.toUpperCase();
  }

  public get id(): string { return this.attributes.get('id') ?? ''; }
  public set id(v: string) { this.attributes.set('id', v); }

  public get type(): string { return this._type ?? (this.tagName === 'INPUT' ? 'text' : this.tagName === 'BUTTON' ? 'submit' : ''); }
  public set type(v: string) { this._type = v; this.attributes.set('type', v); }

  public get hidden(): boolean { return this.attributes.has('hidden'); }
  public set hidden(v: boolean) { if (v) this.attributes.set('hidden', ''); else this.attributes.delete('hidden'); }

  public get tabIndex(): number {
    const t = this.attributes.get('tabindex');
    if (t !== undefined) return Number(t);
    return ['BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'A'].includes(this.tagName) ? 0 : -1;
  }
  public set tabIndex(v: number) { this.attributes.set('tabindex', String(v)); }

  public get isContentEditable(): boolean { return this.attributes.get('contenteditable') === 'true'; }

  public getAttribute(name: string): string | null {
    if (name === 'class') return this.className === '' ? null : this.className;
    if (name.startsWith('data-')) {
      const key = name.slice(5).replace(/-([a-z])/g, (_, c: string) => c.toUpperCase());
      const v = this.dataset[key];
      if (v !== undefined) return v;
    }
    return this.attributes.get(name) ?? null;
  }
  public setAttribute(name: string, value: string): void {
    if (name === 'class') { this.className = value; return; }
    if (name === 'type') { this._type = value; }
    if (name.startsWith('data-')) {
      this.dataset[name.slice(5).replace(/-([a-z])/g, (_, c: string) => c.toUpperCase())] = value;
      return;
    }
    this.attributes.set(name, String(value));
  }
  public hasAttribute(name: string): boolean { return this.getAttribute(name) !== null; }
  public removeAttribute(name: string): void {
    if (name === 'class') { this.className = ''; return; }
    if (name.startsWith('data-')) { delete this.dataset[name.slice(5).replace(/-([a-z])/g, (_, c: string) => c.toUpperCase())]; return; }
    this.attributes.delete(name);
  }

  public get innerHTML(): string { return this._innerHTML !== '' ? this._innerHTML : this.childNodes.map((c) => c.textContent).join(''); }
  public set innerHTML(v: string) {
    for (const c of this.childNodes.slice()) this.removeChild(c);
    this._innerHTML = v;
  }

  public override get textContent(): string {
    // `(>|$)` so an unterminated trailing tag goes too: `/<[^>]*>/g` leaves a
    // bare `<script` behind, which is not what a browser's textContent returns.
    return this._innerHTML !== '' ? this._innerHTML.replace(/<[^>]*(?:>|$)/g, '') : super.textContent;
  }
  public override set textContent(v: string) {
    this._innerHTML = '';
    for (const c of this.childNodes.slice()) this.removeChild(c);
    if (v !== '') this.appendChild(this.ownerDocument.createTextNode(v));
  }

  public matches(selector: string): boolean {
    return splitAlternatives(selector).some((alt) => {
      const steps = parseSelector(alt);
      if (steps.length === 0) return false;
      if (!this._matchCompound(steps[steps.length - 1].compound)) return false;
      // Right to left: a child combinator names the parent, a descendant one
      // any ancestor above the last match.
      let anc: FakeElement | null = this.parentElement;
      for (let i = steps.length - 1; i >= 1; i--) {
        const c = steps[i - 1].compound;
        if (steps[i].combinator === '>') {
          if (anc === null || !anc._matchCompound(c)) return false;
        } else {
          while (anc !== null && !anc._matchCompound(c)) anc = anc.parentElement;
          if (anc === null) return false;
        }
        anc = anc.parentElement;
      }
      return true;
    });
  }

  private _matchCompound(c: Compound): boolean {
    if (c.tag !== null && c.tag !== this.tagName) return false;
    if (c.id !== null && this.id !== c.id) return false;
    for (const cls of c.classes) if (!this.classList.contains(cls)) return false;
    for (const a of c.attrs) {
      const v = this.getAttribute(a.name);
      if (v === null) return false;
      if (a.value !== null && v !== a.value) return false;
    }
    return true;
  }

  public closest(selector: string): FakeElement | null {
    if (this.matches(selector)) return this;
    for (let n = this.parentElement; n !== null; n = n.parentElement) if (n.matches(selector)) return n;
    return null;
  }

  public getBoundingClientRect(): { left: number; top: number; right: number; bottom: number; width: number; height: number; x: number; y: number } {
    const r = this.rect ?? { left: 0, top: 0, width: this.offsetWidth, height: this.offsetHeight };
    return { ...r, right: r.left + r.width, bottom: r.top + r.height, x: r.left, y: r.top };
  }

  public focus(): void {
    const doc = this.ownerDocument;
    if (doc.activeElement === this) return;
    const prev = doc.activeElement;
    doc.activeElement = this;
    if (prev !== null && prev !== doc.body) {
      prev.dispatchEvent(new FakeEvent('blur', { relatedTarget: this }));
      prev.dispatchEvent(new FakeEvent('focusout', { relatedTarget: this }));
    }
    this.dispatchEvent(new FakeEvent('focus', { relatedTarget: prev }));
    this.dispatchEvent(new FakeEvent('focusin', { relatedTarget: prev }));
  }

  public blur(): void {
    const doc = this.ownerDocument;
    if (doc.activeElement !== this) return;
    doc.activeElement = doc.body;
    this.dispatchEvent(new FakeEvent('blur'));
    this.dispatchEvent(new FakeEvent('focusout'));
  }

  public click(): void {
    this.clicks++;
    this.dispatchEvent(new FakeEvent('click', { detail: 1 }));
  }

  public select(): void {}
  public setPointerCapture(): void {}
  public releasePointerCapture(): void {}
  public scrollIntoView(): void {}

  // canvas
  public getContext(): unknown { return makeCtx().ctx; }
  public toBlob(cb: (b: null) => void): void { cb(null); }
}

export class FakeDocument extends FakeNode {
  public readonly documentElement: FakeElement;
  public readonly head: FakeElement;
  public readonly body: FakeElement;
  public activeElement: FakeElement;
  public readonly defaultView: null = null;
  public readonly fullscreenElement: null = null;

  public constructor() {
    super(null as unknown as FakeDocument);
    this.ownerDocument = this;
    this.nodeType = 9;
    this.documentElement = new FakeElement(this, 'html');
    this.head = new FakeElement(this, 'head');
    this.body = new FakeElement(this, 'body');
    super.appendChild(this.documentElement);
    this.documentElement.appendChild(this.head);
    this.documentElement.appendChild(this.body);
    this.activeElement = this.body;
  }

  public createElement(tag: string): FakeElement { return new FakeElement(this, tag); }
  public createElementNS(_ns: string, tag: string): FakeElement { return new FakeElement(this, tag); }
  public createTextNode(text: string): FakeText { return new FakeText(this, text); }
}

/** A fresh document with a body to mount into. */
export function fakeWidgetDocument(): FakeDocument {
  return new FakeDocument();
}

/** A container the widget can be built in, appended to the body. */
export function fakeContainer(doc: FakeDocument, width = 800, height = 600): FakeElement {
  const el = doc.createElement('div');
  el.clientWidth = width;
  el.clientHeight = height;
  el.offsetWidth = width;
  el.offsetHeight = height;
  el.rect = { left: 0, top: 0, width, height };
  doc.body.appendChild(el);
  return el;
}

/** Dispatch a keydown on `target` (the document's active element by default). */
export function fireKey(target: FakeNode, key: string, init: FakeEventInit = {}): FakeEvent {
  const e = new FakeEvent('keydown', { key, ...init });
  target.dispatchEvent(e);
  return e;
}

/** Dispatch any event on `target`. */
export function fire(target: FakeNode, type: string, init: FakeEventInit = {}): FakeEvent {
  const e = new FakeEvent(type, init);
  target.dispatchEvent(e);
  return e;
}

/** Everything the chart needs on `globalThis` to attach input in node. */
export function ensureWindowGlobal(): void {
  const g = globalThis as { window?: unknown };
  g.window ??= {};
}
