/**
 * Toasts: the notices a user should not miss. The status line is one row and
 * is overwritten by the next thing that happens, so a failed load or a saved
 * layout also gets one of these. Errors stay until dismissed; the rest go on
 * their own, and the clock stops while the pointer rests on one so a message
 * can be read at the reader's pace rather than the timer's.
 */
import { chromeIconSvg } from 'openalgo-charts/draw';
import { widgetText, type WidgetTranslationOptions } from './localization';

export type ToastKind = 'info' | 'success' | 'error';

/** How long each kind stays, in ms. 0 keeps it until it is dismissed. */
export const TOAST_MS: Readonly<Record<ToastKind, number>> = { info: 4000, success: 3500, error: 0 };
/** Newest at the bottom; beyond this many the oldest goes. */
export const TOAST_MAX = 5;
/** How long the leave transition runs before the node is removed. */
export const TOAST_LEAVE_MS = 160;

export interface ToastOptions {
  /** Overrides the kind's stay. 0 keeps it up. */
  ms?: number;
}

export interface ToastHandle {
  readonly node: HTMLElement;
  dismiss(): void;
}

export interface Toaster {
  toast(message: string, kind?: ToastKind, opts?: ToastOptions): ToastHandle;
  /** Take every toast down now. */
  clear(): void;
  /** Number of toasts currently showing. */
  count(): number;
  destroy(): void;
}

/**
 * Mount the toast stack into `host` (an empty element the shell positions
 * over the chart). `doc` is the host's document unless given, for a fake DOM.
 */
export function mountToasts(host: HTMLElement, doc: Document = host.ownerDocument, translation: WidgetTranslationOptions = {}): Toaster {
  host.classList.add('oac-toasts');
  host.setAttribute('role', 'status');
  host.setAttribute('aria-live', 'polite');
  const live = new Set<ToastHandle>();

  const toast = (message: string, kind: ToastKind = 'info', opts: ToastOptions = {}): ToastHandle => {
    const known = kind in TOAST_MS ? kind : 'info';
    const node = doc.createElement('div');
    node.className = 'oac-toast oac-toast--' + known;
    const msg = doc.createElement('span');
    msg.className = 'oac-toast__msg';
    msg.textContent = message;
    const x = doc.createElement('button');
    x.type = 'button';
    x.className = 'oac-toast__x';
    x.setAttribute('aria-label', widgetText(translation, 'Dismiss'));
    x.innerHTML = chromeIconSvg('close');
    node.appendChild(msg);
    node.appendChild(x);

    const ms = opts.ms !== undefined ? opts.ms : TOAST_MS[known];
    let timer: ReturnType<typeof setTimeout> | 0 = 0;
    let gone = false;
    const handle: ToastHandle = {
      node,
      dismiss: () => {
        if (gone) return;
        gone = true;
        if (timer !== 0) clearTimeout(timer);
        live.delete(handle);
        node.classList.add('is-out');
        setTimeout(() => node.remove(), TOAST_LEAVE_MS);
      },
    };
    const arm = (): void => { if (ms > 0) timer = setTimeout(handle.dismiss, ms); };
    x.addEventListener('click', handle.dismiss);
    node.addEventListener('pointerenter', () => { if (timer !== 0) clearTimeout(timer); timer = 0; });
    node.addEventListener('pointerleave', arm);

    host.appendChild(node);
    live.add(handle);
    // The oldest goes first, and goes at once: a stack past its limit is
    // already too much to read, so a leave transition would only add to it.
    while (live.size > TOAST_MAX) {
      const oldest = live.values().next().value as ToastHandle;
      live.delete(oldest);
      oldest.node.remove();
    }
    arm();
    return handle;
  };

  return {
    toast,
    clear: () => { for (const t of Array.from(live)) t.dismiss(); },
    count: () => live.size,
    destroy: () => {
      for (const t of Array.from(live)) t.node.remove();
      live.clear();
      host.remove();
    },
  };
}
