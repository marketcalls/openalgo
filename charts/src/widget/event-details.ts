import { DEFAULT_TIMEZONE } from 'openalgo-charts';
import type { ChartEvent, ChartEventDetails, EventDetailSpan, EventMarkerDetails } from 'openalgo-charts';
import { createOverlayStack, h, type OverlayStack } from './context';
import { widgetText, type WidgetTranslationOptions } from './localization';
import { safeNewsUrl } from './news-panel';
// A pure helper: importing it by path inlines the event layer's copy and nothing else of it.
import { copyEvent } from '../primitives/event-markers';

export type EventDetailsLoader = (
  event: ChartEvent,
  context: { signal: AbortSignal },
) => Promise<ChartEventDetails | string | null>;

/** A button under an event's details. */
export interface EventDetailAction {
  /** Shown as text. */
  label: string;
  /** Called with a copy of the shown event, once the popup has closed. */
  run(event: ChartEvent): void;
}

export interface EventDetailsLabels {
  title: string;
  close: string;
  events: string;
  loading: string;
  empty: string;
  error: string;
}

export interface EventDetailsPopupOptions {
  /** Host-owned lookup. No request is made unless a loader is supplied. */
  loadDetails?: EventDetailsLoader;
  /** Receives the original UTC timestamp in seconds. Defaults to Asia/Kolkata. */
  formatTime?: (time: number) => string;
  labels?: Partial<EventDetailsLabels>;
  /** The buttons for an event, asked each time one is shown. None by default. */
  actions?: (event: ChartEvent) => readonly EventDetailAction[];
  /** Pass the widget context's stack to share focus, Escape and shortcut handling. */
  overlays?: OverlayStack;
  styleNonce?: string | undefined;
  /** Set false when the host already includes EVENT_DETAILS_CSS. */
  injectStyles?: boolean;
}

export const EVENT_DETAILS_CSS = `
.oac-event-layer{position:absolute;inset:0;pointer-events:none;z-index:50}
.oac-event-details{position:absolute;pointer-events:auto;box-sizing:border-box;width:340px;max-width:calc(100% - 16px);max-height:calc(100% - 16px);overflow:auto;background:var(--oac-panel,#171b23);color:var(--oac-tx,#d9dfe8);border:1px solid var(--oac-bd,#343b48);border-radius:8px;box-shadow:var(--oac-shadow,0 12px 32px #0005);font:12px/1.5 var(--oac-font,system-ui,sans-serif);scrollbar-width:thin;scrollbar-color:var(--oac-sb-thumb,#414958) var(--oac-panel,#171b23)}
.oac-event-details::-webkit-scrollbar{width:6px;height:6px}
.oac-event-details::-webkit-scrollbar-track{background:var(--oac-panel,#171b23)}
.oac-event-details::-webkit-scrollbar-thumb{background:var(--oac-sb-thumb,#414958);border-radius:3px}
.oac-event-details::-webkit-scrollbar-thumb:hover{background:var(--oac-sb-thumb-hover,#586276)}
.oac-event-details__header{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 12px;border-bottom:1px solid var(--oac-bd,#343b48)}
.oac-event-details__heading{margin:0;font:600 12px/1.5 var(--oac-font,system-ui,sans-serif)}
.oac-event-details button{font:inherit;cursor:pointer;border:1px solid var(--oac-bd,#343b48);border-radius:4px;padding:4px 8px;background:var(--oac-elev,#252c37);color:inherit;text-align:left}
.oac-event-details button:hover{background:var(--oac-elev-2,#333d4b)}
.oac-event-details button:focus-visible{outline:2px solid var(--oac-ring,#74a7fa);outline-offset:2px}
.oac-event-details__members{display:flex;flex-wrap:wrap;gap:6px;padding:10px 12px 0}
.oac-event-details__members button{max-width:100%;overflow-wrap:anywhere}
.oac-event-details__members button[aria-pressed="true"]{border-color:var(--oac-acc,#74a7fa);background:var(--oac-on-bg,#274263)}
.oac-event-details__content{padding:12px;overflow-wrap:anywhere}
.oac-event-details__title{margin:0 0 4px;font-size:14px;font-weight:600}
.oac-event-details__time,.oac-event-details__status{color:var(--oac-mut,#a0aabc)}
.oac-event-details__summary{white-space:pre-wrap;margin:10px 0 0}
.oac-event-details__fields{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:5px 12px;margin:10px 0 0}
.oac-event-details__fields dt{color:var(--oac-mut,#a0aabc)}
.oac-event-details__fields dd{margin:0;text-align:right;white-space:pre-wrap}
.oac-event-details__status{padding:0 12px 10px}
.oac-event-details__status:empty{display:none}
.oac-event-details__subhead{margin:10px 0 0;font-size:12px;font-weight:600}
.oac-event-details__text,.oac-event-details__list{margin:6px 0 0}
.oac-event-details__list{padding-left:18px}
.oac-event-details a{color:var(--oac-acc,#74a7fa)}
.oac-event-details__actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:6px;padding:0 12px 12px}
.oac-event-details__actions:empty{display:none}
`;

/**
 * The popup's words in the host's language. The widget passes its own
 * translator, so a translated widget shows a translated popup; a host that
 * mounts the popup itself gets English, or its own `labels`.
 */
export function eventDetailsLabels(translation: WidgetTranslationOptions): EventDetailsLabels {
  return {
    title: widgetText(translation, 'Event details'), close: widgetText(translation, 'Close'), events: widgetText(translation, 'Events'),
    loading: widgetText(translation, 'Loading details...'), empty: widgetText(translation, 'No additional details.'),
    error: widgetText(translation, 'Unable to load additional details.'),
  };
}

/**
 * A selectable event popup. Feed content is untrusted: every string becomes
 * text, and a link opens only an http or https URL. Destroy it when its host
 * is disposed.
 */
export class EventDetailsPopup {
  public readonly element: HTMLElement;
  private readonly _doc: Document;
  private readonly _overlays: OverlayStack;
  private readonly _ownOverlays: boolean;
  private readonly _labels: EventDetailsLabels;
  private readonly _formatTime: (time: number) => string;
  private _close: (() => void) | null = null;
  private _abort: AbortController | null = null;
  private _revision = 0;
  private _disposed = false;
  private _events: ChartEvent[] = [];
  private _members: HTMLButtonElement[] = [];
  private _content: HTMLElement;
  private _status: HTMLElement;
  private _actions: HTMLElement;
  private _anchor: { x: number; y: number } | undefined;

  public constructor(private readonly _container: HTMLElement, private readonly _options: EventDetailsPopupOptions = {}) {
    this._doc = _container.ownerDocument;
    this._labels = { ...eventDetailsLabels({}), ..._options.labels };
    const formatter = new Intl.DateTimeFormat(undefined, {
      timeZone: DEFAULT_TIMEZONE, dateStyle: 'medium', timeStyle: 'short',
    });
    this._formatTime = _options.formatTime ?? (time => {
      const date = new Date(time * 1000);
      return Number.isFinite(date.getTime()) ? formatter.format(date) : String(time);
    });
    this._ownOverlays = _options.overlays === undefined;
    this._overlays = _options.overlays ?? createOverlayStack(_container, this._doc);
    if (this._ownOverlays) this._overlays.layer.classList.add('oac-event-layer');
    if (_options.injectStyles !== false && this._doc.getElementById('oac-event-details-style') === null) {
      const style = h(this._doc, 'style', undefined, { id: 'oac-event-details-style' });
      if (_options.styleNonce !== undefined) style.setAttribute('nonce', _options.styleNonce);
      style.textContent = EVENT_DETAILS_CSS;
      this._doc.head.appendChild(style);
    }
    this.element = h(this._doc, 'section', 'oac-event-details', { role: 'dialog', 'aria-label': this._labels.title });
    for (const name of ['pointerdown', 'pointerup', 'click', 'dblclick', 'wheel', 'keydown']) {
      this.element.addEventListener(name, event => event.stopPropagation());
    }
    this._content = h(this._doc, 'div', 'oac-event-details__content');
    this._status = h(this._doc, 'div', 'oac-event-details__status', { role: 'status', 'aria-live': 'polite' });
    this._actions = h(this._doc, 'div', 'oac-event-details__actions');
  }

  /** Anchor coordinates are CSS pixels relative to the supplied container. */
  public open(details: EventMarkerDetails, anchor?: { x: number; y: number }): void {
    if (this._disposed) return;
    this.close();
    if (details.events.length === 0) return;
    this._events = details.events.map(copyEvent);
    this._anchor = anchor === undefined ? undefined : { ...anchor };
    const header = h(this._doc, 'header', 'oac-event-details__header');
    const heading = h(this._doc, 'h2', 'oac-event-details__heading');
    heading.textContent = this._labels.title;
    const close = h(this._doc, 'button', undefined, { type: 'button', 'data-action': 'close-event-details' });
    close.textContent = this._labels.close;
    close.addEventListener('click', () => this.close());
    header.append(heading, close);
    this.element.replaceChildren(header);
    this._members = [];
    if (this._events.length > 1) {
      const members = h(this._doc, 'div', 'oac-event-details__members', { role: 'group', 'aria-label': this._labels.events });
      this._members = this._events.map((event, index) => {
        const button = h(this._doc, 'button', undefined, { type: 'button', 'data-event-index': String(index) });
        button.textContent = event.title ?? event.label;
        button.addEventListener('click', () => this._select(index));
        members.appendChild(button);
        return button;
      });
      this.element.appendChild(members);
    }
    this.element.append(this._content, this._status, this._actions);
    this._close = this._overlays.open(this.element, {
      placement: 'below', modal: false, initialFocus: close,
      onClose: () => { this._close = null; this._cancel(); },
    });
    this._select(0);
    this._position();
  }

  public close(): void {
    this._cancel();
    this._close?.();
    this._close = null;
  }

  public destroy(): void {
    if (this._disposed) return;
    this._disposed = true;
    this.close();
    this._events = [];
    this._members = [];
    if (this._ownOverlays) this._overlays.destroy();
  }

  private _cancel(): void {
    this._revision++;
    this._abort?.abort();
    this._abort = null;
  }

  private _select(index: number): void {
    this._cancel();
    // 0 of a non-empty list, or the index of a member button built from this list.
    const event = this._events[index]!;
    this._members.forEach((button, at) => button.setAttribute('aria-pressed', String(at === index)));
    this._render(event, event.details);
    this._actions.replaceChildren(...(this._options.actions?.(copyEvent(event)) ?? []).map(action => {
      const button = h(this._doc, 'button', undefined, { type: 'button' });
      button.textContent = action.label;
      // Closed first, so whatever the action opens is not closed under it.
      button.addEventListener('click', () => { const shown = copyEvent(event); this.close(); action.run(shown); });
      return button;
    }));
    this._status.textContent = '';
    this.element.removeAttribute('aria-busy');
    const loader = this._options.loadDetails;
    if (loader === undefined) return;
    const revision = this._revision;
    const controller = new AbortController();
    this._abort = controller;
    this._status.textContent = this._labels.loading;
    this.element.setAttribute('aria-busy', 'true');
    const current = (): boolean => !this._disposed && this._close !== null && revision === this._revision && !controller.signal.aborted;
    const failed = (): void => {
      if (!current()) return;
      this.element.removeAttribute('aria-busy');
      this._status.textContent = this._labels.error;
      this._position();
    };
    try {
      Promise.resolve(loader(copyEvent(event), { signal: controller.signal })).then(details => {
        if (!current()) return;
        this._status.textContent = '';
        this.element.removeAttribute('aria-busy');
        this._render(event, details ?? event.details);
      }, failed);
    } catch { failed(); }
  }

  private _render(event: ChartEvent, details: ChartEventDetails | string | undefined): void {
    const title = h(this._doc, 'h3', 'oac-event-details__title');
    title.textContent = event.title ?? event.label;
    const time = h(this._doc, 'div', 'oac-event-details__time');
    time.textContent = this._formatTime(event.time);
    this._content.replaceChildren(title, time);
    const summary = typeof details === 'string' ? details : details?.summary;
    if (summary) {
      const paragraph = h(this._doc, 'p', 'oac-event-details__summary');
      paragraph.textContent = summary;
      this._content.appendChild(paragraph);
    }
    const fields = typeof details === 'object' ? details.fields : undefined;
    if (fields?.length) {
      const list = h(this._doc, 'dl', 'oac-event-details__fields');
      for (const field of fields) {
        const label = h(this._doc, 'dt');
        const value = h(this._doc, 'dd');
        label.textContent = field.label;
        value.textContent = field.value;
        list.append(label, value);
      }
      this._content.appendChild(list);
    }
    let rich = false;
    const blocks: unknown[] = typeof details === 'object' && Array.isArray(details.blocks) ? details.blocks : [];
    for (const block of blocks) {
      // Checked field by field: a feed can send any shape.
      const { type, text, items } = (block ?? {}) as { type?: unknown; text?: unknown; items?: unknown };
      const node = type === 'heading' ? h(this._doc, 'h4', 'oac-event-details__subhead')
        : type === 'paragraph' ? h(this._doc, 'p', 'oac-event-details__text')
          : type === 'list' ? h(this._doc, 'ul', 'oac-event-details__list') : null;
      if (node === null) continue;
      if (type !== 'list') this._inline(node, text);
      else if (Array.isArray(items)) for (const item of items) this._inline(node.appendChild(h(this._doc, 'li')), item);
      // A block that carried no usable text leaves no empty box behind.
      if (node.textContent) { this._content.appendChild(node); rich = true; }
    }
    if (!summary && !fields?.length && !rich) {
      const empty = h(this._doc, 'p', 'oac-event-details__summary');
      empty.textContent = this._labels.empty;
      this._content.appendChild(empty);
    }
    this._position();
  }

  /** Text only: a feed's string never reaches the page as markup, and a link only as a vetted URL. */
  private _inline(parent: HTMLElement, text: unknown): void {
    if (typeof text === 'string') { parent.append(text); return; }
    if (!Array.isArray(text)) return;
    for (const span of text as Array<Partial<EventDetailSpan> | null>) {
      if (typeof span?.text !== 'string') continue;
      const url = safeNewsUrl(span.href);
      let node: HTMLElement = url === null ? h(this._doc, 'span')
        : h(this._doc, 'a', undefined, { href: url, target: '_blank', rel: 'noopener noreferrer', referrerpolicy: 'no-referrer' });
      node.textContent = span.text;
      for (const tag of ['em', 'strong'] as const) {
        if (span[tag] !== true) continue;
        const wrap = h(this._doc, tag);
        wrap.appendChild(node);
        node = wrap;
      }
      parent.appendChild(node);
    }
  }

  private _position(): void {
    const bounds = this._container.getBoundingClientRect();
    const layer = this._overlays.layer.getBoundingClientRect();
    const offsetX = this._ownOverlays ? 0 : bounds.left - layer.left;
    const offsetY = this._ownOverlays ? 0 : bounds.top - layer.top;
    this.element.style.maxWidth = `${Math.max(0, bounds.width - 16)}px`;
    this.element.style.maxHeight = `${Math.max(0, bounds.height - 16)}px`;
    const width = this.element.offsetWidth;
    const height = this.element.offsetHeight;
    const x = this._anchor?.x;
    const y = this._anchor?.y;
    this.element.style.left = `${offsetX + Math.max(0, Math.min(Number.isFinite(x) ? x! : bounds.width - width - 8, bounds.width - width - 8))}px`;
    this.element.style.top = `${offsetY + Math.max(0, Math.min(Number.isFinite(y) ? y! - height - 12 : 8, bounds.height - height - 8))}px`;
  }
}
