/**
 * The chart grid's bar: the layout picker, maximize, the link menu,
 * whole-grid capture and, when the grid keeps them, the desk's saved layouts
 * (the widget's own Layouts menu, grid-saved.ts).
 *
 * The bar is the host's choice (`toolbar`), so it loads when a grid asks for
 * it (lazy.ts), into a strip the grid has already laid out at the bar's
 * height; its menus load when one first opens (grid-menus.ts). Every widget
 * outside such a grid fetches neither.
 *
 * The grid has no widget of its own, so it has no overlay stack to open a
 * menu in. It keeps one over its whole area instead (`createOverlayStack` on
 * a layer that covers the grid), which is what lets a menu opened from the
 * bar hang over the charts below it, with the widget's own Escape, Tab and
 * focus-return rules. The bar and that layer carry `oac-widget`, so every
 * control in them takes the widget's buttons, menus, focus ring and
 * scrollbars rather than a second set of styles that could drift.
 */
import { chromeIconSvg, layoutIconPath } from 'openalgo-charts/draw';
import { h, type OverlayStack, type TipController } from './context';
import { glyphSvg } from './form';
import { CHART_GRID_LAYOUTS, isChartGridLayout, type ChartGridLayoutId } from './grid-layouts';
import type { ChartGridLinkGroup, LinkChannel } from './grid-links';
import type { GridSaved } from './grid-saved';
import { layoutName } from './grid-text';
import { groupMark } from './grid-cells';
import { layoutNeedsAttention } from './layouts-widget';
import { widgetText, type WidgetTranslationOptions } from './localization';
import { rovingIndex } from './roving';
import { addWidgetStyles } from './styles';

// The desk's saved layouts load with the bar that shows them (grid-saved.ts).
export { attachGridSaved } from './grid-saved';

/** What the bar and its menus read from the grid and ask it to do. */
export interface GridBarHost {
  readonly doc: Document;
  readonly text: WidgetTranslationOptions;
  readonly overlays: OverlayStack;
  readonly tips: TipController;
  /** The layouts the picker offers, in its order. */
  readonly layouts: readonly ChartGridLayoutId[];
  /** The layout in force, when it is one of the catalogue's. */
  layout(): string | null;
  setLayout(id: ChartGridLayoutId): void;
  maximized(): boolean;
  /** Why the active chart cannot be maximized now, or null when it can. */
  maximizeBlocked(): string | null;
  toggleMaximize(): void;
  links: {
    groups(): readonly ChartGridLinkGroup[];
    /** The active chart's group, or null when it is in none. */
    current(): ChartGridLinkGroup | null;
    setGroup(id: string | null): void;
    newGroup(): void;
    rename(id: string, name: string): void;
    setChannel(channel: LinkChannel | 'nearest', on: boolean): void;
    share(): number;
  };
  capture: {
    /** Why the grid cannot be captured whole now, or null. */
    blocked(): string | null;
    download(): void;
    copy(): void;
    canCopy(): boolean;
  };
  /** The desk's saved layouts, when the grid keeps them: the bar then has a Layouts control. */
  readonly saved?: Pick<GridSaved, 'controller' | 'open' | 'status'> | undefined;
  /** Open one of the bar's menus under `anchor` (grid-menus.ts, loaded on first use). */
  openMenu(which: 'layouts' | 'link' | 'capture', anchor: HTMLElement): void;
}

export interface GridBarHandle {
  readonly el: HTMLElement;
  /** Repaint every control from the host's state. */
  refresh(): void;
  destroy(): void;
}

const txt = (host: GridBarHost): WidgetTranslationOptions => host.text;

/** A layout's tile: its own slots drawn on the chrome grid. */
export function layoutTileSvg(id: ChartGridLayoutId): string {
  const spec = CHART_GRID_LAYOUTS[id];
  return glyphSvg(layoutIconPath(spec.rows, spec.columns, spec.slots));
}

/** A chrome glyph for a bar control or a menu row. Internal. */
export const chrome = (doc: Document, svg: string): HTMLSpanElement => {
  const span = h(doc, 'span', 'oac-glyph oac-glyph--chrome', { 'aria-hidden': 'true' });
  span.innerHTML = svg;
  return span;
};

// ── the bar ──────────────────────────────────────────────────────────────

/** Mount the grid bar into `el`. */
export function mountGridBar(host: GridBarHost, el: HTMLElement): GridBarHandle {
  const doc = host.doc, t = txt(host);
  addWidgetStyles(doc, GRID_BAR_CSS);
  const button = (className: string, label: string): HTMLButtonElement =>
    h(doc, 'button', `oac-btn ${className}`, { type: 'button', 'aria-label': label });
  const chev = (): HTMLElement => {
    const s = h(doc, 'span', 'oac-chev', { 'aria-hidden': 'true' });
    s.innerHTML = chromeIconSvg('chevron-down');
    return s;
  };

  const layout = button('oac-grid__layout', widgetText(t, 'Arrange charts'));
  layout.setAttribute('aria-haspopup', 'menu');
  const layoutGlyph = chrome(doc, chromeIconSvg('layout'));
  const layoutText = h(doc, 'span', 'oac-grid__bar-text');
  layout.append(layoutGlyph, layoutText, chev());
  // The tip's title is also the button's name, so it carries the words the button shows.
  host.tips.attach(layout, () => {
    const id = host.layout();
    return { title: isChartGridLayout(id) ? widgetText(t, 'Arrange charts: {name}', { name: layoutName(t, id) }) : widgetText(t, 'Arrange charts'), side: 'bottom' };
  });
  layout.addEventListener('click', () => host.openMenu('layouts', layout));
  // A host that offers no layouts gets no picker, rather than one that opens empty.
  layout.hidden = host.layouts.length === 0;

  const max = button('oac-btn--icon oac-grid__max', widgetText(t, 'Maximize the chart'));
  const maxGlyph = chrome(doc, chromeIconSvg('maximize'));
  max.appendChild(maxGlyph);
  const maxLabel = (): string => widgetText(t, host.maximized() ? 'Restore the grid' : 'Maximize the chart');
  host.tips.attach(max, () => ({ title: maxLabel(), sub: host.maximizeBlocked() ?? undefined, side: 'bottom' }));
  max.addEventListener('click', () => { if (host.maximizeBlocked() === null) host.toggleMaximize(); });

  const link = button('oac-grid__link', widgetText(t, 'Link'));
  link.setAttribute('aria-haspopup', 'menu');
  const linkText = h(doc, 'span', 'oac-grid__bar-text');
  linkText.textContent = widgetText(t, 'Link');
  const linkMark = h(doc, 'span', 'oac-grid__bar-mark');
  link.append(chrome(doc, chromeIconSvg('link')), linkText, linkMark, chev());
  host.tips.attach(link, () => {
    const group = host.links.current();
    return { title: widgetText(t, 'Link: {name}', { name: group === null ? widgetText(t, 'Not linked') : group.name }), side: 'bottom' };
  });
  link.addEventListener('click', () => host.openMenu('link', link));

  const capture = button('oac-btn--icon oac-grid__capture', widgetText(t, 'Capture every chart'));
  capture.setAttribute('aria-haspopup', 'menu');
  capture.appendChild(chrome(doc, chromeIconSvg('capture-grid')));
  host.tips.attach(capture, () => ({ title: widgetText(t, 'Capture every chart'), sub: host.capture.blocked() ?? undefined, side: 'bottom' }));
  capture.addEventListener('click', () => host.openMenu('capture', capture));

  const sep = (): HTMLElement => h(doc, 'span', 'oac-sep', { role: 'separator' });
  el.append(layout, max, sep(), link, sep(), capture);

  // The desk's saved layouts, at the far end as in a chart's own bar: the
  // held layout's name, with a dot while it needs the user (unsaved, failing
  // or changed elsewhere), which its name then says in words.
  let saved: HTMLButtonElement | null = null;
  let offSaved: (() => void) | null = null;
  if (host.saved !== undefined) {
    const { controller } = host.saved;
    const title = widgetText(t, 'schema.ui.layouts.title', {}, 'Layouts');
    const held = (): string | null => {
      const state = controller.state();
      return state.catalog?.workspaces.find(doc => doc.id === state.layoutId)?.name ?? null;
    };
    const b = saved = button('oac-grid__saved', title);
    b.setAttribute('aria-haspopup', 'dialog');
    const name = h(doc, 'span', 'oac-grid__bar-text');
    b.append(chrome(doc, chromeIconSvg('folder')), name);
    host.tips.attach(b, () => {
      const at = held();
      const said = at === null ? title : `${title}: ${at}`;
      const status = host.saved?.status();
      // The dot's meaning stays in the name whenever the dot shows.
      return { title: said, label: layoutNeedsAttention(controller.state()) ? `${said}, ${status ?? ''}` : undefined, sub: status, side: 'bottom' };
    });
    const paint = (): void => {
      name.textContent = held() ?? title;
      b.dataset.attention = String(layoutNeedsAttention(controller.state()));
      host.tips.refreshLabel(b);
    };
    offSaved = controller.subscribe(paint);
    paint();
    b.addEventListener('click', () => host.saved?.open(b));
    el.append(h(doc, 'span', 'oac-grid__spacer'), b);
  }
  // A toolbar's own keys: the arrows, Home and End move between its controls,
  // claimed here so no chart pans with them. Tab still reaches each one.
  const controls = [layout, max, link, capture, saved].filter((control): control is HTMLButtonElement => control !== null && !control.hidden);
  el.addEventListener('keydown', e => {
    const at = controls.indexOf(doc.activeElement as HTMLButtonElement);
    const to = rovingIndex(e.key, at, controls.length, ['ArrowLeft', 'ArrowRight']);
    if (to < 0) return;
    e.preventDefault();
    e.stopPropagation();
    controls[to]!.focus(); // the focus is on a control, so to is one of them
  });

  const refresh = (): void => {
    const id = host.layout();
    const known = isChartGridLayout(id);
    layoutGlyph.innerHTML = known ? layoutTileSvg(id) : chromeIconSvg('layout');
    layoutText.textContent = known ? layoutName(t, id) : '';
    layoutText.hidden = !known;
    const maxed = host.maximized();
    // Named for what a press does next (maxLabel), so no pressed state as well.
    maxGlyph.innerHTML = chromeIconSvg(maxed ? 'restore' : 'maximize');
    const blocked = host.maximizeBlocked();
    max.classList.toggle('is-off', blocked !== null);
    max.setAttribute('aria-disabled', String(blocked !== null));
    const group = host.links.current();
    linkMark.replaceChildren(groupMark(doc, group));
    capture.classList.toggle('is-off', host.capture.blocked() !== null);
    for (const control of [layout, max, link, capture]) host.tips.refreshLabel(control);
    // A tip already up says what was true when it opened; a layout picked
    // with the pointer still on the button would leave the previous layout named.
    const up = host.tips.target();
    if (up === layout || up === max || up === link || up === capture) host.tips.show(up);
  };
  refresh();
  return {
    el,
    refresh,
    destroy: () => { offSaved?.(); el.textContent = ''; },
  };
}

/** The bar's own rules, added to the widget sheet when it loads; its strip is laid out by `CHART_GRID_CSS`. */
const GRID_BAR_CSS = `
.oac-grid__bar .oac-grid__bar-text { max-width: 22ch; overflow: hidden; text-overflow: ellipsis; }
.oac-grid__bar-mark { display: inline-flex; }
.oac-grid__spacer { flex: 1 1 auto; }
.oac-grid__saved { min-width: 0; }
.oac-grid__saved[data-attention="true"]::after { content: ''; width: 6px; height: 6px; flex: none; border-radius: 50%; background: var(--oac-amber); }
/* A phone's bar keeps the glyph and the mark; the held layout's name stays in the tip and the accessible name. */
@container oac-grid-bar (max-width: 520px) { .oac-grid__saved > .oac-grid__bar-text { display: none; } }
`;
