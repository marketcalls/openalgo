import type { DataFeed, SymbolMatch } from 'openalgo-charts';
import { h, type WidgetContext } from './context';
import { widgetText } from './localization';

export type { SymbolMatch };

/**
 * A host's lookup. The original query-only callback remains valid; `signal`
 * aborts once a newer query or a closed picker makes the answer stale.
 */
export type SymbolSearch = (query: string, context?: { signal: AbortSignal }) => Promise<readonly SymbolMatch[]> | readonly SymbolMatch[];
export const SEARCH_DEBOUNCE_MS = 150;

/**
 * The feed's own search, for a widget whose host passes no lookup. The exact
 * symbol on the chart's exchange goes first: Enter takes the first result,
 * and typed text alone used to keep the chart's exchange.
 */
export function feedSymbolSearch(feed: DataFeed | undefined, exchange: () => string): SymbolSearch | undefined {
  if (typeof feed?.searchSymbols !== 'function') return undefined;
  return async (query, context) => {
    const hits = await feed.searchSymbols!({ query, signal: context?.signal });
    const typed = query.trim().toUpperCase();
    const at = hits.findIndex(hit => !hit.contractGroup && hit.exchange === exchange() && hit.symbol.toUpperCase() === typed);
    return at > 0 ? [hits[at]!, ...hits.slice(0, at), ...hits.slice(at + 1)] : hits; // at is a found index
  };
}

export interface SymbolPickerOptions {
  search: SymbolSearch;
  onSelect(symbol: string, exchange?: string): void;
  /** Changes to this key invalidate answers for the previous chart context. */
  context?: () => unknown;
  variant?: 'desktop' | 'mobile';
}

export interface SymbolPickerHandle {
  open(query?: string): void;
  /** Raw entry may be committed only after a search has finished without matches. */
  canCommitRaw(): boolean;
  close(): void;
  destroy(): void;
}

/** Accept secure absolute URLs and root-relative host assets only. */
export function safeSymbolIconUrl(value: string | undefined): string | null {
  if (typeof value !== 'string') return null;
  const candidate = value.trim();
  if (/^https:\/\/[^\s]+$/i.test(candidate)) {
    try { const url = new URL(candidate); return url.username || url.password ? null : url.href; } catch { return null; }
  }
  return /^\/(?!\/)[\w./%-]+(?:\?[\w=&.%-]+)?$/.test(candidate) ? candidate : null;
}

let nextListId = 0;

/** Attach the same result controller to either widget input or a host input. */
export function mountSymbolPicker(ctx: WidgetContext, input: HTMLInputElement, options: SymbolPickerOptions): SymbolPickerHandle {
  const doc = ctx.document;
  const mobile = options.variant === 'mobile';
  let destroyed = false;
  let sequence = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let pending: AbortController | null = null;
  let panel: HTMLElement | null = null;
  let list: HTMLElement | null = null;
  let closeOverlay: (() => void) | null = null;
  let hits: readonly SymbolMatch[] = [];
  let category = '';
  let expanded: SymbolMatch | null = null;
  let visible: SymbolMatch[] = [];
  let active = 0;
  let contextAtQuery: string | undefined;
  let query = '';
  let searching = false;

  const clearTimer = (): void => { if (timer !== null) { clearTimeout(timer); timer = null; } };
  const invalidate = (): void => { sequence++; clearTimer(); pending?.abort(); pending = null; };
  const close = (): void => {
    invalidate();
    const closer = closeOverlay;
    closeOverlay = null;
    panel = null;
    list = null;
    hits = [];
    visible = [];
    expanded = null;
    category = '';
    searching = false;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-controls');
    closer?.();
  };
  const ensurePanel = (): void => {
    if (panel !== null) return;
    panel = h(doc, 'div', `oac-symbol-picker ${mobile ? 'oac-mobile-results' : 'oac-menu oac-sym__results'}`, {
      role: mobile ? 'region' : 'listbox', 'aria-label': widgetText(ctx, 'schema.ui.symbolResults', {}, 'Symbols'),
    });
    // Focus stays in the field, as in any combobox: the top bar puts the
    // chart's symbol back into its field on blur, and a selection is refused
    // once the field no longer holds the text that was searched.
    panel.addEventListener('mousedown', event => event.preventDefault());
    if (mobile) {
      const header = h(doc, 'div', 'oac-mobile-results__head');
      const title = h(doc, 'strong');
      title.textContent = widgetText(ctx, 'schema.ui.symbolResults', {}, 'Symbols');
      const button = h(doc, 'button', 'oac-mobile__action', { type: 'button' });
      button.dataset.mobileAction = 'close-search';
      button.textContent = widgetText(ctx, 'schema.ui.closeSearch', {}, 'Close');
      button.addEventListener('click', close);
      header.append(title, button);
      panel.appendChild(header);
    }
    const categories = h(doc, 'div', 'oac-symbol-picker__categories');
    panel.appendChild(categories);
    list = h(doc, 'div', mobile ? 'oac-mobile-results__list' : 'oac-menu__body');
    list.setAttribute('role', 'listbox');
    list.id = `oac-symbol-picker-${++nextListId}`;
    panel.appendChild(list);
    input.setAttribute('aria-controls', list.id);
    input.setAttribute('aria-expanded', 'true');
    const currentPanel = panel;
    closeOverlay = ctx.openOverlay(panel, {
      anchor: input, placement: 'below', initialFocus: null, dismissOnOutside: true,
      onClose: () => { if (panel === currentPanel) close(); },
    });
  };
  const select = (hit: SymbolMatch): void => {
    if (destroyed || searching || !visible.includes(hit) || input.value.trim() !== query
      || (options.context === undefined ? undefined : JSON.stringify(options.context())) !== contextAtQuery) return;
    const symbol = hit.symbol.trim();
    if (symbol === '') return;
    // Leave the field while the results still show: a field that commits on
    // change holds its typed text back until then, so only the pick lands.
    input.blur();
    close();
    options.onSelect(symbol, hit.exchange);
  };
  const paint = (): void => {
    if (panel === null || list === null) return;
    const categories = panel.querySelector('.oac-symbol-picker__categories') as HTMLElement;
    categories.textContent = '';
    const classes = Array.from(new Set(hits.map(hit => hit.assetClass?.trim()).filter((value): value is string => Boolean(value))));
    if (classes.length > 1) {
      for (const value of ['', ...classes]) {
        const button = h(doc, 'button', 'oac-symbol-picker__category', { type: 'button', 'aria-pressed': String(category === value) });
        button.textContent = value || widgetText(ctx, 'schema.ui.allAssets', {}, 'All');
        button.addEventListener('click', () => { invalidate(); category = value; expanded = null; active = 0; paint(); });
        categories.appendChild(button);
      }
    }
    list.textContent = '';
    const filtered = hits.filter(hit => category === '' || hit.assetClass === category);
    const group = expanded?.contractGroup;
    visible = group === undefined ? filtered.slice() : group.contracts.filter(hit => typeof hit.symbol === 'string');
    if (group !== undefined) {
      const back = h(doc, 'button', 'oac-symbol-picker__back', { type: 'button' });
      back.textContent = widgetText(ctx, 'schema.ui.backToSymbols', {}, 'Back to symbols');
      back.addEventListener('click', () => { expanded = null; active = 0; paint(); });
      list.appendChild(back);
      if (group.label) { const label = h(doc, 'div', 'oac-head'); label.textContent = group.label; list.appendChild(label); }
    }
    visible.forEach((hit, index) => {
      if (typeof hit.symbol !== 'string') return;
      const button = h(doc, 'button', `oac-symbol-picker__row oac-menu__row${index === active ? ' is-active' : ''}`, { type: 'button', role: 'option' });
      if (mobile) button.dataset.mobileAction = 'pick-symbol';
      const icon = safeSymbolIconUrl(hit.iconUrl);
      if (icon !== null) { const image = h(doc, 'img', 'oac-symbol-picker__icon', { src: icon, alt: '' }); button.appendChild(image); }
      const symbol = h(doc, 'span', 'oac-menu__label');
      symbol.textContent = hit.exchange ? `${hit.exchange}:${hit.symbol}` : hit.symbol;
      button.appendChild(symbol);
      if (hit.name) { const name = h(doc, 'span', 'oac-menu__sub'); name.textContent = hit.name; button.appendChild(name); }
      if (hit.contractGroup) { const groupHint = h(doc, 'span', 'oac-symbol-picker__group'); groupHint.textContent = widgetText(ctx, 'schema.ui.showContracts', {}, 'Contracts'); button.appendChild(groupHint); }
      button.addEventListener('click', event => {
        event.stopPropagation();
        if (hit.contractGroup) { expanded = hit; active = 0; paint(); } else select(hit);
      });
      list?.appendChild(button);
    });
    if (visible.length === 0) {
      const empty = h(doc, 'div', 'oac-symbol-picker__empty', { role: 'status' });
      empty.textContent = widgetText(ctx, 'schema.ui.noSymbols', {}, 'No symbols found');
      list.appendChild(empty);
    }
  };
  const search = (value: string): void => {
    invalidate();
    query = value.trim();
    if (query === '') { close(); return; }
    category = '';
    expanded = null;
    hits = [];
    visible = [];
    active = 0;
    contextAtQuery = options.context === undefined ? undefined : JSON.stringify(options.context());
    const ticket = sequence;
    searching = true;
    ensurePanel();
    if (panel !== null) (panel.querySelector('.oac-symbol-picker__categories') as HTMLElement).textContent = '';
    const status = (key: `schema.${string}`, fallback: string): void => {
      if (list === null) return;
      const row = h(doc, 'div', 'oac-symbol-picker__status', { role: 'status' });
      row.textContent = widgetText(ctx, key, {}, fallback);
      list.textContent = '';
      list.appendChild(row);
    };
    status('schema.ui.searchingSymbols', 'Searching');
    // Typed text stays committable: a lookup that fails leaves raw entry to the field.
    const failed = (): void => { if (ticket !== sequence) return; searching = false; status('schema.ui.symbolSearchFailed', 'Search unavailable'); };
    timer = setTimeout(() => {
      timer = null;
      pending = new AbortController();
      let answer: Promise<readonly SymbolMatch[]>;
      try { answer = Promise.resolve(options.search(query, { signal: pending.signal })); } catch { failed(); return; }
      void answer.then(next => {
        if (destroyed || ticket !== sequence || panel === null || input.value.trim() !== query || (options.context === undefined ? undefined : JSON.stringify(options.context())) !== contextAtQuery) return;
        searching = false;
        hits = next.filter(hit => typeof hit.symbol === 'string' && hit.symbol.trim() !== '');
        if (hits.length === 0) { close(); return; }
        active = 0;
        paint();
      }, failed);
    }, SEARCH_DEBOUNCE_MS);
  };
  const onInput = (): void => search(input.value);
  const onKey = (event: KeyboardEvent): void => {
    if (event.isComposing || event.keyCode === 229) return;
    if (event.key === 'Escape') { if (panel !== null) { event.preventDefault(); close(); } return; }
    if (searching || input.value.trim() !== query
      || (options.context === undefined ? undefined : JSON.stringify(options.context())) !== contextAtQuery) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (visible.length === 0) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      active = (active + (event.key === 'ArrowDown' ? 1 : -1) + visible.length) % visible.length;
      paint();
    } else if (event.key === 'Enter' && visible[active] !== undefined) {
      event.preventDefault();
      event.stopImmediatePropagation();
      const hit = visible[active]!; // checked in the condition above
      if (hit.contractGroup) { expanded = hit; active = 0; paint(); } else select(hit);
    }
  };
  const onBlur = (event: FocusEvent): void => {
    const next = event.relatedTarget as Node | null | undefined;
    if (!next || panel?.contains(next) !== true) close();
  };
  input.addEventListener('input', onInput);
  input.addEventListener('keydown', onKey);
  input.addEventListener('blur', onBlur);
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-haspopup', 'listbox');
  input.setAttribute('aria-expanded', 'false');
  const offSymbol = ctx.bus.on('symbol', close);
  const offInterval = ctx.bus.on('interval', close);
  return {
    open: (value?: string) => { if (destroyed) return; input.focus(); if (value !== undefined) input.value = value; if (input.value.trim() !== '') search(input.value); },
    canCommitRaw: () => !searching && visible.length === 0,
    close,
    destroy: () => { if (destroyed) return; destroyed = true; close(); offSymbol(); offInterval(); input.removeEventListener('input', onInput); input.removeEventListener('keydown', onKey); input.removeEventListener('blur', onBlur); },
  };
}

/** Rules to add to the widget's shared stylesheet or a custom host stylesheet. */
export const SYMBOL_PICKER_CSS = `
.oac-widget .oac-symbol-picker{min-width:250px;max-width:min(420px,calc(100vw - 24px))}
.oac-widget .oac-symbol-picker__categories{display:flex;gap:4px;overflow-x:auto;padding:5px 7px;scrollbar-color:var(--oac-sb-thumb) var(--oac-panel);scrollbar-width:thin}
.oac-widget .oac-symbol-picker__categories::-webkit-scrollbar{height:6px}
.oac-widget .oac-symbol-picker__categories::-webkit-scrollbar-track{background:var(--oac-panel)}
.oac-widget .oac-symbol-picker__categories::-webkit-scrollbar-thumb{background:var(--oac-sb-thumb);border-radius:3px}
.oac-widget .oac-symbol-picker__categories::-webkit-scrollbar-thumb:hover{background:var(--oac-sb-thumb-hover)}
.oac-widget .oac-symbol-picker__categories:empty{display:none}
.oac-widget .oac-symbol-picker__category,.oac-widget .oac-symbol-picker__back{background:transparent;border:0;color:inherit;cursor:pointer;padding:4px 7px;font:inherit}
.oac-widget .oac-symbol-picker__category[aria-pressed=true]{background:var(--oac-elev);border-radius:4px}
.oac-widget .oac-symbol-picker__row{display:flex;align-items:center;gap:7px;width:100%;text-align:left}
.oac-widget .oac-symbol-picker__icon{width:18px;height:18px;object-fit:contain}
.oac-widget .oac-symbol-picker__group{margin-left:auto;opacity:.7}
.oac-widget .oac-symbol-picker__empty,.oac-widget .oac-symbol-picker__status{padding:9px;color:var(--oac-mut)}
`;
