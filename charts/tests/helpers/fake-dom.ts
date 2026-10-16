/** Minimal fake DOM so Pane/Chart can be constructed in node tests. */
import { makeCtx } from './fake-ctx';

export function fakeDocument(): Document {
  const make = (tag: string): unknown => {
    const el: Record<string, unknown> = {
      tagName: tag.toUpperCase(),
      style: {} as Record<string, string>,
      children: [] as unknown[],
      appendChild(c: unknown) { (this.children as unknown[]).push(c); return c; },
      remove() {},
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 600 }),
      // Record listeners so interaction tests can drive the real handlers
      // (pointerdown/move/up) without a browser.
      __listeners: new Map<string, Function[]>(),
      addEventListener(type: string, fn: Function) {
        const m = this.__listeners as Map<string, Function[]>;
        if (!m.has(type)) m.set(type, []);
        (m.get(type) as Function[]).push(fn);
      },
      removeEventListener(type: string, fn: Function) {
        const m = this.__listeners as Map<string, Function[]>;
        const list = m.get(type);
        if (list) m.set(type, list.filter((f) => f !== fn));
      },
      dispatch(type: string, event: unknown) {
        for (const fn of (this.__listeners as Map<string, Function[]>).get(type) ?? []) fn(event);
      },
      setPointerCapture() {},
      releasePointerCapture() {},
      setAttribute() {},
      getAttribute: () => null,
      hasAttribute: () => false,
    };
    if (tag === 'canvas') {
      el.width = 0;
      el.height = 0;
      el.getContext = () => makeCtx().ctx;
    }
    return el;
  };
  return { createElement: (t: string) => make(t) } as unknown as Document;
}

/** A fake element that records listeners, for driving real pointer handlers. */
export interface FakeElement extends HTMLElement {
  dispatch(type: string, event: unknown): void;
}

/** Build a pointer-event-ish object the chart's handlers accept. */
export function pointer(
  type: 'down' | 'move' | 'up',
  x: number,
  y: number,
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    clientX: x, clientY: y,
    pointerId: 1, pointerType: 'mouse',
    button: 0, buttons: type === 'up' ? 0 : 1,
    preventDefault() {}, stopPropagation() {},
    ...extra,
  };
}
