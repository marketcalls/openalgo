import type { WidgetContext } from './context';
import { button, el } from './form';
import { widgetText } from './localization';

export type PanelDockId = 'data' | 'objects' | 'watchlist' | 'news';
export interface PanelDockState { panel: PanelDockId | null; width: number }
export interface PanelDockContent { initialFocus?: HTMLElement; destroy(): void }
export interface PanelDockOptions {
  data(host: HTMLElement): PanelDockContent;
  objects(host: HTMLElement): PanelDockContent;
  /** Named symbol lists. Its tab appears only when this is supplied. */
  watchlist?(host: HTMLElement): PanelDockContent;
  /** The chart instrument's news. Its tab appears only when this is supplied. */
  news?(host: HTMLElement): PanelDockContent;
  state?: unknown;
  onChange?(state: PanelDockState): void;
}
export interface PanelDockHandle {
  el: HTMLElement;
  open(panel: PanelDockId, focus?: boolean): void;
  close(): void;
  toggle(panel: PanelDockId): void;
  state(): PanelDockState;
  restore(state: unknown): void;
  destroy(): void;
}
const MIN_WIDTH = 240, MAX_WIDTH = 480, DEFAULT_WIDTH = 300;
const PANELS: readonly PanelDockId[] = ['data', 'objects', 'watchlist', 'news'];
const LABELS: Record<PanelDockId, string> = { data: 'Data', objects: 'Objects', watchlist: 'Watchlist', news: 'News' };

/** Older documents have no dock; malformed preferences cannot hide the plot. */
export function sanitizePanelDockState(raw: unknown): PanelDockState {
  const state = typeof raw === 'object' && raw !== null ? raw as Record<string, unknown> : {};
  return {
    panel: PANELS.includes(state.panel as PanelDockId) ? state.panel as PanelDockId : null,
    width: typeof state.width === 'number' && Number.isFinite(state.width)
      ? Math.round(Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, state.width))) : DEFAULT_WIDTH,
  };
}

/** A host-owned information dock. It mounts just one content observer at a time. */
export function mountPanelDock(ctx: WidgetContext, stage: HTMLElement, opts: PanelDockOptions): PanelDockHandle {
  const doc = ctx.document;
  const text = (key: string, fallback: string): string => widgetText(ctx, `schema.ui.dock.${key}`, {}, fallback);
  const panel = el(doc, 'aside', 'oac-panel-dock');
  panel.hidden = true;
  panel.setAttribute('aria-label', text('title', 'Chart information'));
  const grip = el(doc, 'div', 'oac-panel-dock__resize');
  grip.setAttribute('role', 'separator'); grip.setAttribute('aria-orientation', 'vertical');
  grip.setAttribute('aria-label', text('resize', 'Resize information panel'));
  grip.tabIndex = 0;
  const header = el(doc, 'div', 'oac-panel-dock__header');
  const tabs = el(doc, 'div', 'oac-panel-dock__tabs');
  tabs.setAttribute('role', 'group'); tabs.setAttribute('aria-label', text('panels', 'Information panels'));
  // A source the host did not supply has no tab: an empty panel is a control with nothing behind it.
  const available = PANELS.filter(id => typeof opts[id] === 'function');
  const tabButtons = new Map(available.map(id => [id, button(doc, { label: text(id, LABELS[id]), onClick: () => open(id) })]));
  const pressTabs = (active: PanelDockId | null): void => { for (const [id, tab] of tabButtons) tab.setAttribute('aria-pressed', String(id === active)); };
  const closeButton = button(doc, { label: text('close', 'Close'), onClick: () => close() });
  closeButton.classList.add('oac-panel-dock__close');
  tabs.append(...tabButtons.values()); header.append(tabs, closeButton);
  const body = el(doc, 'div', 'oac-panel-dock__body');
  panel.append(grip, header, body); stage.appendChild(panel);
  const state = sanitizePanelDockState(opts.state);
  let current: PanelDockContent | null = null;
  let closeOverlay: (() => void) | null = null;
  let destroyed = false, relocating = false;
  let restoreFocus: HTMLElement | null = null;
  let drag: { x: number; width: number; pointer: number } | null = null;
  const rootWidth = (): number => ctx.root.getBoundingClientRect().width || ctx.root.clientWidth || 1000;
  const narrow = (): boolean => rootWidth() <= 640;
  const maxWidth = (): number => Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, rootWidth() - 320));
  const announce = (): void => { opts.onChange?.({ ...state }); };
  const resize = (width: number): void => {
    state.width = Math.round(Math.max(MIN_WIDTH, Math.min(maxWidth(), width)));
    panel.style.width = `${state.width}px`;
    grip.setAttribute('aria-valuemin', String(MIN_WIDTH));
    grip.setAttribute('aria-valuemax', String(maxWidth()));
    grip.setAttribute('aria-valuenow', String(state.width));
  };
  const detachOverlay = (): void => {
    if (!closeOverlay) return;
    relocating = true;
    const dismiss = closeOverlay; closeOverlay = null; dismiss();
    relocating = false;
  };
  const place = (focus = false): void => {
    if (destroyed || state.panel === null) return;
    const focused = doc.activeElement !== null && panel.contains(doc.activeElement) ? doc.activeElement as HTMLElement : null;
    const sheet = narrow();
    if (sheet !== (panel.dataset.sheet === 'true')) detachOverlay();
    panel.dataset.sheet = String(sheet);
    grip.hidden = sheet;
    if (sheet && !closeOverlay) {
      closeOverlay = ctx.openOverlay(panel, {
        placement: 'center', modal: true, initialFocus: focused ?? current?.initialFocus ?? closeButton,
        restoreFocus: false,
        onClose: () => { closeOverlay = null; if (!relocating) close(); },
      });
    } else if (!sheet) {
      if (panel.parentElement !== stage) stage.appendChild(panel);
      panel.classList.remove('oac-dialog');
      panel.removeAttribute('aria-modal'); panel.removeAttribute('role');
      panel.style.position = ''; panel.style.left = ''; panel.style.top = ''; panel.style.transform = '';
      resize(state.width);
      if (focus) (current?.initialFocus ?? closeButton).focus();
      else focused?.focus();
    }
  };
  function close(): void {
    if (state.panel === null) return;
    state.panel = null; drag = null;
    detachOverlay();
    current?.destroy(); current = null; body.textContent = ''; panel.hidden = true;
    stage.appendChild(panel);
    pressTabs(null);
    const focused = doc.activeElement;
    if (restoreFocus?.isConnected && (focused === null || focused === doc.body || panel.contains(focused))) restoreFocus.focus();
    restoreFocus = null;
    announce();
  }
  function open(id: PanelDockId, focus = true): void {
    if (destroyed) return;
    const mount = opts[id];
    if (!available.includes(id) || mount === undefined) return;
    if (state.panel === id && current !== null) { if (focus) (current.initialFocus ?? closeButton).focus(); return; }
    if (state.panel === null || current === null) restoreFocus = doc.activeElement as HTMLElement | null;
    current?.destroy(); body.textContent = '';
    state.panel = id; panel.hidden = false;
    pressTabs(id);
    current = mount(body);
    place(focus); announce();
  }
  const onKey = (event: KeyboardEvent): void => {
    if (event.key === 'Escape' && ctx.overlays.size() === 0) { event.preventDefault(); event.stopPropagation(); close(); }
    if (event.target !== grip || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault(); event.stopPropagation();
    resize(event.key === 'Home' ? MIN_WIDTH : event.key === 'End' ? maxWidth()
      : state.width + (event.key === 'ArrowLeft' ? 10 : -10) * (event.shiftKey ? 5 : 1));
    announce();
  };
  const onDown = (event: PointerEvent): void => {
    if (event.button !== 0 || narrow()) return;
    event.preventDefault(); event.stopPropagation();
    drag = { x: event.clientX, width: state.width, pointer: event.pointerId };
    grip.setPointerCapture?.(event.pointerId); grip.focus();
  };
  const onMove = (event: PointerEvent): void => {
    if (!drag || drag.pointer !== event.pointerId) return;
    event.preventDefault(); resize(drag.width + drag.x - event.clientX);
  };
  const onUp = (event: PointerEvent): void => {
    if (!drag || drag.pointer !== event.pointerId) return;
    drag = null; announce();
    try { grip.releasePointerCapture?.(event.pointerId); } catch { /* Capture can end with a cancelled gesture. */ }
  };
  panel.addEventListener('keydown', onKey);
  grip.addEventListener('pointerdown', onDown); grip.addEventListener('pointermove', onMove);
  grip.addEventListener('pointerup', onUp); grip.addEventListener('pointercancel', onUp);
  const win = doc.defaultView;
  const onResize = (): void => { if (!narrow()) resize(state.width); place(); };
  win?.addEventListener?.('resize', onResize);
  const Resize = (win as (Window & { ResizeObserver?: typeof ResizeObserver }) | null)?.ResizeObserver;
  const observer = Resize ? new Resize(onResize) : null; observer?.observe(ctx.root);
  resize(state.width);
  const initial = state.panel; state.panel = null;
  if (initial !== null) open(initial, false);
  return {
    el: panel, open, close, toggle: id => { if (state.panel === id) close(); else open(id); },
    state: () => ({ ...state }),
    // A saved panel whose source this dock lacks restores as closed, never as whatever was open.
    restore: raw => { const next = sanitizePanelDockState(raw); resize(next.width); if (next.panel === null || !available.includes(next.panel)) close(); else open(next.panel, false); },
    destroy: () => {
      if (destroyed) return; close(); destroyed = true; observer?.disconnect(); win?.removeEventListener?.('resize', onResize);
      panel.removeEventListener('keydown', onKey); grip.removeEventListener('pointerdown', onDown);
      grip.removeEventListener('pointermove', onMove); grip.removeEventListener('pointerup', onUp); grip.removeEventListener('pointercancel', onUp);
      panel.remove();
    },
  };
}

export const PANEL_DOCK_CSS = `
.oac-widget .oac-panel-dock { position: relative; flex: none; min-width: 0; min-height: 0; display: flex; flex-direction: column; background: var(--oac-panel); border-left: 1px solid var(--oac-bd); }
.oac-widget .oac-panel-dock__header { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 9px 10px; border-bottom: 1px solid var(--oac-bd-soft); flex: none; }
.oac-widget .oac-panel-dock__tabs { display: flex; flex-wrap: wrap; gap: 3px; min-width: 0; }
.oac-widget .oac-panel-dock__tabs .oac-btn, .oac-widget .oac-panel-dock__close { padding: 0 6px; }
.oac-widget .oac-panel-dock__tabs .oac-btn { border-color: transparent; background: transparent; }
.oac-widget .oac-panel-dock__tabs .oac-btn[aria-pressed="true"] { background: var(--oac-elev); color: var(--oac-tx); border-color: var(--oac-bd); }
.oac-widget .oac-panel-dock__close { color: var(--oac-mut); }
.oac-widget .oac-panel-dock__body { overflow: auto; min-height: 0; flex: 1 1 auto; overscroll-behavior: contain; }
.oac-widget .oac-panel-dock__resize { position: absolute; z-index: 2; top: 0; bottom: 0; left: -4px; width: 8px; cursor: col-resize; touch-action: none; }
.oac-widget .oac-panel-dock__resize:hover, .oac-widget .oac-panel-dock__resize:focus-visible { background: var(--oac-ring-soft); }
.oac-widget .oac-panel-dock[data-sheet="true"] { position: absolute !important; inset: 0 !important; width: 100% !important; max-width: none !important; height: 100%; max-height: none; transform: none !important; border: 0; border-radius: 0; }
.oac-widget .oac-panel-dock[data-sheet="true"] .oac-panel-dock__header { padding: 12px; }
.oac-widget .oac-panel-dock[data-sheet="true"] .oac-btn { min-height: 40px; }
.oac-widget .oac-panel-dock__body > .oac-objects { width: auto; max-width: none; border: 0; box-shadow: none; }
`;
