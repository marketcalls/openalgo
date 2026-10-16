/**
 * Named watchlists in a dock panel: one table of the active list, whose rows
 * take their prices only from a quote source.
 *
 * Three decisions worth recording:
 *
 * - **A row without a quote shows no price.** The chart's bars are never read
 *   here, because a last candle presented as a quote is a wrong number with
 *   nothing to say so.
 * - **Streams follow the rows on screen.** An intersection observer reports
 *   which rows are visible, and only those hold a subscription; a list switch,
 *   a hidden page or closing the panel releases them.
 * - **Sorting is stable and holds still under the hand.** Ties keep list
 *   order and unknown values sink in either direction. While the pointer is
 *   over the rows, or focus is in them, prices update in place but rows do not
 *   move, so a click cannot land on a row that jumped there a moment before.
 */
import type { InstrumentKey, QuoteFeed } from 'openalgo-charts';
import type { Watchlist, WatchlistCatalog, WatchlistEntry, WatchlistStore } from 'openalgo-charts/workspace';
import type { WidgetContext } from './context';
import { button, el, selectBox } from './form';
import { errorText, widgetText } from './localization';
import type { PanelDockContent } from './panel-dock';
import { QuoteBoard, quoteChange, type QuoteBoardStatus, type QuoteRowStatus } from './quote-board';
import { mountSymbolPicker, type SymbolPickerHandle } from './symbol-picker';

export type WatchlistSortKey = 'list' | 'symbol' | 'last' | 'change' | 'percent';
export interface WatchlistSort { key: WatchlistSortKey; direction: 'ascending' | 'descending' }

export interface WatchlistPanelOptions {
  /** Named lists: a `WatchlistRepository` from `openalgo-charts/workspace`, or any implementation of its store contract. */
  store: WatchlistStore;
  /** Quotes for the rows on screen. Without one, rows show symbols only. */
  quotes?: QuoteFeed;
  /** A snapshot older than this is shown as stale. Default 60000 ms. */
  staleAfterMs?: number;
  /** Refresh interval for a snapshot-only source. 0 disables. Default 15000 ms. */
  pollMs?: number;
  /** A row was chosen, by click or Enter. */
  onSelect?(instrument: InstrumentKey): void;
  /**
   * The instrument the host charts for an entry. The panel saves what it adds
   * in this form, and compares entries with the chart through it, so a row is
   * marked as, and refused as a repeat of, what choosing it would chart.
   * Default: unchanged. The widget upper-cases the symbol, as its symbol box does.
   */
  normalize?(instrument: InstrumentKey): InstrumentKey;
  /** Price text for a row. Default: the locale's grouping with two to six decimals. */
  formatPrice?(value: number, instrument: InstrumentKey): string;
}

export interface WatchlistPanelHandle extends PanelDockContent {
  readonly el: HTMLElement;
  /** Read the lists from the store again, replacing what is shown. */
  reload(): Promise<void>;
}

interface Row {
  entry: WatchlistEntry;
  el: HTMLTableRowElement;
  open: HTMLButtonElement;
  last: HTMLElement;
  change: HTMLElement;
  percent: HTMLElement;
}

const COLUMNS = [['symbol', 'Symbol'], ['last', 'Last'], ['change', 'Chg'], ['percent', 'Chg%']] as const;
const SORT_KEY = 'watchlist-sort';
const keyOf = (entry: InstrumentKey): string => JSON.stringify([entry.symbol, entry.exchange]);
const sameInstrument = (a: InstrumentKey, b: InstrumentKey): boolean => a.symbol === b.symbol && a.exchange === b.exchange;

/**
 * The last sort per list store, for a context whose storage keeps nothing: the
 * dock rebuilds the panel on every switch, and the sort should outlive that.
 */
const lastSort = new WeakMap<WatchlistStore, WatchlistSort>();

function readSort(raw: unknown): WatchlistSort {
  const value = raw as Partial<WatchlistSort> | null;
  const key = value?.key;
  return key === 'symbol' || key === 'last' || key === 'change' || key === 'percent'
    ? { key, direction: value?.direction === 'ascending' ? 'ascending' : 'descending' } : { key: 'list', direction: 'ascending' };
}

/** Mount the watchlist into a host element, typically the widget's panel dock. */
export function mountWatchlistPanel(ctx: WidgetContext, host: HTMLElement, options: WatchlistPanelOptions): WatchlistPanelHandle {
  const doc = ctx.document;
  const store = options.store;
  const text = (key: string, fallback: string, values: Record<string, string | number> = {}): string =>
    widgetText(ctx, `schema.ui.watchlist.${key}`, values, fallback);
  /** An instrument as a row and a message name it. */
  const describeEntry = (entry: InstrumentKey): string =>
    entry.exchange === '' ? entry.symbol : text('entry', '{symbol} on {exchange}', { symbol: entry.symbol, exchange: entry.exchange });
  const root = el(doc, 'div', 'oac-watchlist');
  root.setAttribute('aria-label', text('title', 'Watchlist'));

  // ── list controls ────────────────────────────────────────────────────
  const bar = el(doc, 'div', 'oac-watchlist__bar');
  const { wrap: selectWrap, select } = selectBox(doc);
  select.setAttribute('aria-label', text('list', 'Watchlist'));
  const labelled = (label: string, name: string, onClick: () => void): HTMLButtonElement => {
    const b = button(doc, { label, onClick });
    b.setAttribute('aria-label', name);
    return b;
  };
  const newButton = labelled(text('new', 'New'), text('newList', 'New list'), () => editName('create'));
  const renameButton = labelled(text('rename', 'Rename'), text('renameList', 'Rename list'), () => editName('rename'));
  const deleteButton = labelled(text('delete', 'Delete'), text('deleteList', 'Delete list'), () => askDelete());
  bar.append(selectWrap, newButton, renameButton, deleteButton);

  const nameForm = el(doc, 'form', 'oac-watchlist__name');
  nameForm.hidden = true;
  const nameInput = el(doc, 'input');
  nameInput.type = 'text';
  nameInput.maxLength = 120;
  nameInput.setAttribute('aria-label', text('name', 'List name'));
  nameInput.autocomplete = 'off';
  const saveName = button(doc, { label: text('save', 'Save'), variant: 'primary', onClick: () => { void submitName(); } });
  const cancelName = button(doc, { label: text('cancel', 'Cancel'), onClick: () => closeForms() });
  nameForm.append(nameInput, cancelName, saveName);

  const confirm = el(doc, 'div', 'oac-watchlist__confirm');
  confirm.hidden = true;
  const confirmText = el(doc, 'span', 'oac-watchlist__confirm-text');
  const keepButton = button(doc, { label: text('keep', 'Keep list'), onClick: () => closeForms() });
  const dropButton = button(doc, { label: '', variant: 'danger', onClick: () => { void removeList(); } });
  confirm.append(confirmText, keepButton, dropButton);

  const add = el(doc, 'div', 'oac-watchlist__add');
  const input = el(doc, 'input');
  input.type = 'search';
  input.placeholder = text('addPlaceholder', 'Add symbol');
  input.setAttribute('aria-label', text('addSymbol', 'Add symbol'));
  input.autocomplete = 'off';
  const addCurrent = button(doc, { label: '', onClick: () => { const current = ctx.symbol(); if (current.symbol !== '') void addEntry({ ...current }); } });
  addCurrent.classList.add('oac-watchlist__add-current');
  add.append(input, addCurrent);

  const status = el(doc, 'div', 'oac-watchlist__status');
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  const message = el(doc, 'div', 'oac-watchlist__message');
  message.setAttribute('role', 'alert');
  message.hidden = true;
  const empty = el(doc, 'p', 'oac-watchlist__empty');
  empty.hidden = true;

  // ── the table ────────────────────────────────────────────────────────
  const scroll = el(doc, 'div', 'oac-watchlist__scroll');
  const table = el(doc, 'table', 'oac-watchlist__table');
  const caption = el(doc, 'caption', 'oac-sr');
  const head = el(doc, 'thead');
  const headRow = el(doc, 'tr');
  const headers = new Map<WatchlistSortKey, HTMLElement>();
  for (const [key, label] of COLUMNS) {
    const th = el(doc, 'th', `oac-watchlist__col oac-watchlist__col--${key}`);
    th.setAttribute('scope', 'col');
    th.dataset.sort = key;
    const sortButton = el(doc, 'button', 'oac-watchlist__sort', text(`column.${key}`, label));
    sortButton.type = 'button';
    sortButton.addEventListener('click', () => cycleSort(key));
    th.appendChild(sortButton);
    headRow.appendChild(th);
    headers.set(key, th);
  }
  const actionsHead = el(doc, 'th', 'oac-watchlist__col oac-watchlist__col--actions');
  actionsHead.appendChild(el(doc, 'span', 'oac-sr', text('actions', 'Actions')));
  headRow.appendChild(actionsHead);
  head.appendChild(headRow);
  const body = el(doc, 'tbody');
  table.append(caption, head, body);
  scroll.appendChild(table);
  root.append(bar, nameForm, confirm, add, status, message, empty, scroll);
  host.appendChild(root);

  // ── state ────────────────────────────────────────────────────────────
  let catalog: WatchlistCatalog | null = null;
  let listId: string | null = null;
  let sort = readSort(ctx.storage?.get(SORT_KEY) ?? lastSort.get(store) ?? null);
  let formMode: 'create' | 'rename' | null = null;
  let pointerHold = false, focusHold = false;
  let order: string[] = [];
  let pending = false, destroyed = false, loadFailed = false;
  const rows = new Map<string, Row>();
  const visibleRows = new Set<Element>();
  let number: Intl.NumberFormat, percent: Intl.NumberFormat;
  try {
    number = new Intl.NumberFormat(ctx.locale, { minimumFractionDigits: 2, maximumFractionDigits: 6 });
    percent = new Intl.NumberFormat(ctx.locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  } catch {
    number = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 6 });
    percent = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  const board = new QuoteBoard({ feed: options.quotes, staleAfterMs: options.staleAfterMs, pollMs: options.pollMs, onChange: () => schedule() });
  const win = doc.defaultView as (Window & { IntersectionObserver?: typeof IntersectionObserver }) | null;
  const Observer = win?.IntersectionObserver;
  const observer = Observer ? new Observer(entries => {
    for (const entry of entries) {
      if (entry.isIntersecting) visibleRows.add(entry.target); else visibleRows.delete(entry.target);
    }
    syncVisible();
  }, { root: scroll }) : null;

  const current = (): Watchlist | null => catalog?.lists.find(item => item.id === listId) ?? null;
  const canonical = (entry: InstrumentKey): InstrumentKey => {
    if (options.normalize) {
      try {
        const next = options.normalize({ symbol: entry.symbol, exchange: entry.exchange });
        if (typeof next?.symbol === 'string' && typeof next.exchange === 'string') return { symbol: next.symbol, exchange: next.exchange };
      } catch { /* A host mapping that fails leaves the entry as saved. */ }
    }
    return { symbol: entry.symbol, exchange: entry.exchange };
  };
  const price = (value: number, entry: InstrumentKey): string => {
    if (options.formatPrice) {
      try { return String(options.formatPrice(value, { ...entry })); } catch { /* A host formatter failing falls back to the default. */ }
    }
    return number.format(value);
  };
  const signed = (value: number, format: (n: number) => string): string => (value > 0 ? '+' : value < 0 ? '-' : '') + format(Math.abs(value));
  // One formatter per zone, not per row: every quote repaints each row's time.
  let stamp: { zone: string; format: Intl.DateTimeFormat | null } | null = null;
  const clock = (ms: number): string => {
    const zone = ctx.chart.timezone();
    if (stamp?.zone !== zone) {
      let format: Intl.DateTimeFormat | null = null;
      try { format = new Intl.DateTimeFormat(ctx.locale, { timeZone: zone, timeStyle: 'medium' }); } catch { /* An unusable locale or zone falls back to ISO text. */ }
      stamp = { zone, format };
    }
    try { if (stamp.format !== null) return stamp.format.format(new Date(ms)); } catch { /* Out of range: ISO text below. */ }
    return new Date(ms).toISOString();
  };
  const write = (node: HTMLElement, value: string): void => { if (node.textContent !== value) node.textContent = value; };

  function schedule(): void {
    if (pending || destroyed) return;
    pending = true;
    queueMicrotask(() => { pending = false; paint(); });
  }

  /** Which rows want quotes: those on screen, in screen order, and none while the page is hidden. */
  function syncVisible(): void {
    if (destroyed) return;
    const hidden = (doc as Document & { hidden?: boolean }).hidden === true;
    board.setVisible(hidden ? [] : order.map(key => rows.get(key)!).filter(row => observer === null || visibleRows.has(row.el)).map(row => row.entry));
  }

  function showMessage(value: string): void { message.textContent = value; message.hidden = value === ''; }

  function fail(error: unknown): void {
    const conflict = error instanceof Error && error.name === 'WatchlistConflictError';
    showMessage(conflict ? text('conflict', 'The watchlists changed in another session. The saved lists are shown.')
      : errorText(ctx, error));
    void reload();
  }

  function apply(next: WatchlistCatalog, force = false): void {
    if (destroyed || (!force && catalog !== null && next.revision < catalog.revision)) return;
    catalog = next;
    loadFailed = false;
    const ids = new Set(next.lists.map(item => item.id));
    listId = next.activeListId !== null && ids.has(next.activeListId) ? next.activeListId
      : listId !== null && ids.has(listId) ? listId : next.lists[0]?.id ?? null;
    syncRows();
  }

  /** Rows for the displayed list: kept by identity, so a live row keeps its node and its focus. */
  function syncRows(): void {
    const entries = current()?.entries ?? [];
    const keys = new Set(entries.map(keyOf));
    for (const [key, row] of rows) {
      if (keys.has(key)) continue;
      observer?.unobserve(row.el);
      visibleRows.delete(row.el);
      row.el.remove();
      rows.delete(key);
    }
    for (const entry of entries) {
      const key = keyOf(entry);
      if (!rows.has(key)) rows.set(key, createRow(entry));
      else rows.get(key)!.entry = entry;
    }
    order = order.filter(key => keys.has(key));
    for (const entry of entries) if (!order.includes(keyOf(entry))) order.push(keyOf(entry));
    paint();
    syncVisible();
  }

  function createRow(entry: WatchlistEntry): Row {
    const tr = el(doc, 'tr', 'oac-watchlist__row');
    tr.dataset.symbol = entry.symbol;
    tr.dataset.exchange = entry.exchange;
    const th = el(doc, 'th', 'oac-watchlist__instrument');
    th.setAttribute('scope', 'row');
    const open = el(doc, 'button', 'oac-watchlist__open');
    open.type = 'button';
    open.setAttribute('aria-label', describeEntry(entry));
    open.appendChild(el(doc, 'span', 'oac-watchlist__symbol', entry.symbol));
    if (entry.exchange !== '') open.appendChild(el(doc, 'span', 'oac-watchlist__exchange', entry.exchange));
    const row: Row = {
      entry, el: tr, open,
      last: el(doc, 'td', 'oac-watchlist__last'),
      change: el(doc, 'td', 'oac-watchlist__change'),
      percent: el(doc, 'td', 'oac-watchlist__percent'),
    };
    open.addEventListener('click', () => options.onSelect?.({ ...row.entry }));
    open.addEventListener('keydown', event => onRowKey(event as KeyboardEvent, row));
    th.appendChild(open);
    const actions = el(doc, 'td', 'oac-watchlist__actions');
    actions.appendChild(button(doc, {
      label: text('remove', 'Remove {name}', { name: describeEntry(entry) }), icon: 'close', iconOnly: true,
      onClick: () => { void removeEntry(row.entry); },
    }));
    tr.append(th, row.last, row.change, row.percent, actions);
    body.appendChild(tr);
    observer?.observe(tr);
    return row;
  }

  function onRowKey(event: KeyboardEvent, row: Row): void {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    event.stopPropagation();
    const step = event.key === 'ArrowDown' ? 1 : -1;
    if (event.altKey) {
      // Only list order is the user's own; a value sort would move the row straight back.
      if (sort.key === 'list') moveRow(row.entry, step);
      return;
    }
    const at = order.indexOf(keyOf(row.entry));
    // Past either end there is no key, and a lookup with none finds no row.
    (rows as ReadonlyMap<string | undefined, Row>).get(order[at + step])?.open.focus();
  }

  /**
   * Moves run one at a time, each computed from the catalog the one before it
   * saved, so a held key is a run of moves rather than a conflict with itself.
   * The revision still refuses a move another session has overtaken, and a move
   * that throws past its own handler is dropped alone, not with every move queued
   * behind it.
   */
  let moving: Promise<void> = Promise.resolve();
  function moveRow(entry: WatchlistEntry, step: number): void {
    moving = moving.then(async () => {
      const list = current();
      if (destroyed || list === null || catalog === null || sort.key !== 'list') return;
      const index = list.entries.findIndex(item => sameInstrument(item, entry));
      const target = index + step;
      if (index < 0 || target < 0 || target >= list.entries.length) return;
      showMessage('');
      try { await store.moveEntry(list.id, entry, target, { expectedRevision: catalog.revision }); } catch (error) { fail(error); }
    }).catch(() => {});
  }

  function sorted(): string[] {
    const entries = current()?.entries ?? [];
    if (sort.key === 'list') return entries.map(keyOf);
    const direction = sort.direction === 'ascending' ? 1 : -1;
    const value = (entry: WatchlistEntry): number | string | null => {
      if (sort.key === 'symbol') return entry.symbol;
      const quote = board.row(entry).quote;
      if (quote === null) return null;
      if (sort.key === 'last') return quote.last;
      return quoteChange(quote)?.[sort.key === 'change' ? 'change' : 'percent'] ?? null;
    };
    return entries.map((entry, index) => ({ key: keyOf(entry), index, value: value(entry) })).sort((a, b) => {
      if (a.value === null || b.value === null) return a.value === b.value ? a.index - b.index : a.value === null ? 1 : -1;
      const c = typeof a.value === 'string' ? a.value.localeCompare(b.value as string) : a.value - (b.value as number);
      return c !== 0 ? c * direction : a.index - b.index;
    }).map(item => item.key);
  }

  function cycleSort(key: WatchlistSortKey): void {
    const first = key === 'symbol' ? 'ascending' : 'descending';
    sort = sort.key !== key ? { key, direction: first }
      : sort.direction === first ? { key, direction: first === 'ascending' ? 'descending' : 'ascending' }
        : { key: 'list', direction: 'ascending' };
    ctx.storage?.set(SORT_KEY, sort);
    lastSort.set(store, sort);
    paint();
    syncVisible();
  }

  function stateLabel(state: QuoteRowStatus): string {
    return {
      loading: text('state.loading', 'Loading'), live: text('state.live', 'Live'), delayed: text('state.delayed', 'Delayed'),
      snapshot: text('state.snapshot', 'Snapshot'), stale: text('state.stale', 'Stale'),
      unavailable: text('state.unavailable', 'No quote'), error: text('state.error', 'Could not load'),
    }[state];
  }

  const shown = (): boolean => [...rows.values()].some(row => board.row(row.entry).quote !== null);

  function statusText(state: QuoteBoardStatus): string {
    switch (state) {
      case 'unavailable': return text('status.unavailable', 'No quote source. Rows show symbols only.');
      case 'snapshot': return text('status.snapshot', 'Snapshot quotes');
      case 'connecting': return text('status.connecting', 'Connecting to quotes');
      case 'live': return text('status.live', 'Live quotes');
      // The stale warning is about values on screen; with none shown it would be false.
      case 'reconnecting': return shown() ? text('status.reconnecting', 'Reconnecting. Quotes shown may be stale.') : text('status.reconnectingEmpty', 'Reconnecting to quotes.');
      case 'disconnected': return shown() ? text('status.disconnected', 'Quotes disconnected. Values shown are stale.') : text('status.disconnectedEmpty', 'Quotes disconnected.');
      case 'error': return text('status.error', 'Quotes could not refresh: {error}', { error: board.error() ?? '' });
      default: return '';
    }
  }

  function paint(): void {
    if (destroyed) return;
    const list = current();
    const lists = catalog?.lists ?? [];
    // List selector: rebuilt only when the names or order changed.
    const signature = JSON.stringify(lists.map(item => [item.id, item.name]));
    if (select.dataset.signature !== signature) {
      select.dataset.signature = signature;
      select.textContent = '';
      for (const item of lists) {
        const option = el(doc, 'option', undefined, item.name);
        option.value = item.id;
        select.appendChild(option);
      }
      if (lists.length === 0) {
        const option = el(doc, 'option', undefined, text('noLists', 'No lists'));
        option.value = '';
        select.appendChild(option);
      }
    }
    select.value = list?.id ?? '';
    select.disabled = lists.length === 0 || loadFailed;
    renameButton.disabled = deleteButton.disabled = list === null || loadFailed;
    newButton.disabled = loadFailed || lists.length >= 100;
    caption.textContent = list?.name ?? text('title', 'Watchlist');

    const chartInstrument = ctx.symbol();
    const inList = list?.entries.some(entry => sameInstrument(canonical(entry), chartInstrument)) === true;
    addCurrent.textContent = chartInstrument.symbol === '' ? text('addChart', 'Add chart symbol') : text('addCurrent', 'Add {symbol}', { symbol: chartInstrument.symbol });
    addCurrent.disabled = chartInstrument.symbol === '' || inList || loadFailed;
    addCurrent.title = inList ? text('inList', 'Already in this list') : '';
    input.disabled = loadFailed;

    for (const row of rows.values()) {
      const state = board.row(row.entry);
      const quote = state.quote;
      row.el.dataset.state = state.status;
      if (sameInstrument(canonical(row.entry), chartInstrument)) row.el.setAttribute('aria-current', 'true');
      else row.el.removeAttribute('aria-current');
      const move = quote === null ? null : quoteChange(quote);
      write(row.last, quote !== null ? price(quote.last, row.entry)
        : state.status === 'loading' ? text('quoteLoading', '...') : text('noQuote', 'n/a'));
      write(row.change, move === null ? '' : signed(move.change, n => price(n, row.entry)));
      write(row.percent, move === null ? '' : `${signed(move.percent, n => percent.format(n))}%`);
      for (const cell of [row.change, row.percent]) {
        cell.classList.toggle('is-up', move !== null && move.change > 0);
        cell.classList.toggle('is-down', move !== null && move.change < 0);
      }
      // The exchange's own time when the provider gave one, in the chart's zone like every other time.
      const at = quote?.time !== undefined ? quote.time * 1000 : state.receivedAt;
      const title = at === null ? stateLabel(state.status) : `${stateLabel(state.status)} ${clock(at)}`;
      if (row.last.title !== title) row.last.title = title;
    }

    // Order: the sort, unless the hand is on the rows and the sort follows values.
    const held = sort.key !== 'list' && (pointerHold || focusHold);
    const wanted = held ? order.concat(sorted().filter(key => !order.includes(key))).filter(key => rows.has(key)) : sorted();
    const active = doc.activeElement as HTMLElement | null;
    wanted.forEach((key, index) => {
      const node = rows.get(key)!.el;
      if (body.children[index] !== node) body.insertBefore(node, body.children[index] ?? null);
    });
    // Moving a row can drop focus from a control inside it.
    if (active !== null && root.contains(active) && doc.activeElement !== active) active.focus();
    const moved = wanted.join('\n') !== order.join('\n');
    order = wanted;
    if (moved) queueMicrotask(syncVisible);

    for (const [key, th] of headers) {
      th.setAttribute('aria-sort', sort.key === key ? sort.direction : 'none');
    }
    const quoteState = board.status();
    const described = statusText(quoteState);
    write(status, described);
    status.hidden = described === '';
    status.dataset.state = quoteState;
    empty.hidden = loadFailed || (lists.length > 0 && (list?.entries.length ?? 0) > 0);
    write(empty, lists.length === 0 ? text('empty.none', 'No watchlists yet. Add a symbol to start one.')
      : text('empty.list', 'This list is empty. Add the chart symbol or type one above.'));
    scroll.hidden = (list?.entries.length ?? 0) === 0;
  }

  // ── changes ──────────────────────────────────────────────────────────
  async function reload(): Promise<void> {
    try { apply(await store.load(), true); }
    catch (error) {
      if (destroyed) return;
      loadFailed = true;
      showMessage(text('loadFailed', 'Watchlists could not load: {error}', { error: errorText(ctx, error) }));
      paint();
    }
  }

  async function addEntry(typed: WatchlistEntry): Promise<void> {
    showMessage('');
    const entry = canonical(typed);
    const list = current();
    // Another spelling of a listed instrument would chart the same thing from two rows.
    if (list?.entries.some(item => sameInstrument(canonical(item), entry))) {
      showMessage(text('duplicate', '{name} is already in this list', { name: describeEntry(entry) }));
      return;
    }
    try {
      if (list === null) {
        const created = await store.createList(text('defaultName', 'Watchlist'), [entry]);
        await store.setActiveList(created.id);
      } else await store.addEntry(list.id, entry);
    } catch (error) { fail(error); }
  }

  async function removeEntry(entry: WatchlistEntry): Promise<void> {
    const list = current();
    if (list === null) return;
    showMessage('');
    try { await store.removeEntry(list.id, entry); } catch (error) { fail(error); }
  }

  function closeForms(): void {
    formMode = null;
    nameForm.hidden = true;
    confirm.hidden = true;
  }

  function editName(mode: 'create' | 'rename'): void {
    closeForms();
    formMode = mode;
    nameInput.value = mode === 'rename' ? current()?.name ?? '' : text('newName', 'List {number}', { number: (catalog?.lists.length ?? 0) + 1 });
    nameForm.hidden = false;
    nameInput.focus();
    nameInput.select?.();
  }

  async function submitName(): Promise<void> {
    const name = nameInput.value.trim();
    const mode = formMode;
    if (name === '' || mode === null) return;
    const list = current();
    closeForms();
    showMessage('');
    try {
      if (mode === 'create') {
        const created = await store.createList(name);
        await store.setActiveList(created.id);
      } else if (list !== null) await store.renameList(list.id, name);
    } catch (error) { fail(error); }
  }

  function askDelete(): void {
    const list = current();
    if (list === null) return;
    closeForms();
    confirmText.textContent = text('confirmDelete', 'Delete {name} and its {count} symbols?', { name: list.name, count: list.entries.length });
    dropButton.textContent = text('deleteNamed', 'Delete {name}', { name: list.name });
    confirm.hidden = false;
    keepButton.focus();
  }

  async function removeList(): Promise<void> {
    const list = current();
    closeForms();
    if (list === null) return;
    showMessage('');
    try { await store.removeList(list.id); } catch (error) { fail(error); }
  }

  // ── events ───────────────────────────────────────────────────────────
  const onSelectList = (): void => {
    const id = select.value;
    if (id === '' || id === listId || catalog === null) return;
    // Switch at once: the old list's streams are released before the store answers.
    listId = id;
    closeForms();
    syncRows();
    store.setActiveList(id).catch(fail);
  };
  select.addEventListener('change', onSelectList);
  const onSubmit = (event: Event): void => { event.preventDefault(); void submitName(); };
  nameForm.addEventListener('submit', onSubmit);
  const onNameKey = (event: Event): void => { if ((event as KeyboardEvent).key === 'Escape' && !nameForm.hidden) { event.stopPropagation(); closeForms(); } };
  nameForm.addEventListener('keydown', onNameKey);
  let picker: SymbolPickerHandle | null = null;
  if (ctx.symbolSearch) {
    picker = mountSymbolPicker(ctx, input, {
      search: ctx.symbolSearch,
      onSelect: (symbol, exchange) => { input.value = ''; void addEntry({ symbol, exchange: exchange ?? ctx.symbol().exchange }); },
    });
  }
  const onAddKey = (event: Event): void => {
    const key = (event as KeyboardEvent).key;
    if (key !== 'Enter' || event.defaultPrevented) return;
    event.preventDefault();
    const symbol = input.value.trim().toUpperCase();
    // A shown result takes Enter in the picker's own listener first; what
    // reaches here is typed text, committed as the top bar commits it: once
    // no search is running that could still find what the user meant.
    if (symbol === '' || (picker !== null && !picker.canCommitRaw())) return;
    picker?.close();
    input.value = '';
    // Raw text carries no venue: it is saved on the chart's own exchange.
    void addEntry({ symbol, exchange: ctx.symbol().exchange });
  };
  input.addEventListener('keydown', onAddKey);
  const onEnter = (): void => { pointerHold = true; };
  const onLeave = (): void => { pointerHold = false; schedule(); };
  // The rows, not the header: a click on a column heading is a deliberate sort.
  body.addEventListener('pointerenter', onEnter);
  body.addEventListener('pointerleave', onLeave);
  const onFocusIn = (): void => { focusHold = true; };
  const onFocusOut = (event: Event): void => {
    const next = (event as FocusEvent).relatedTarget as Node | null;
    if (next === null || !body.contains(next)) { focusHold = false; schedule(); }
  };
  body.addEventListener('focusin', onFocusIn);
  body.addEventListener('focusout', onFocusOut);
  // Keys typed here are the panel's, and a press here is never a pan on the chart.
  const stopKeys = (event: Event): void => { if ((event as KeyboardEvent).key !== 'Escape' && (event as KeyboardEvent).key !== 'Tab') event.stopPropagation(); };
  const stopPointer = (event: Event): void => { event.stopPropagation(); };
  root.addEventListener('keydown', stopKeys);
  root.addEventListener('pointerdown', stopPointer);
  const onVisibility = (): void => syncVisible();
  doc.addEventListener('visibilitychange', onVisibility);
  const offContext = ctx.chart.on('data:context', () => schedule());
  // Row times are shown in the chart's zone, and a stale row gets no quote to repaint it.
  const offZone = ctx.chart.on('timezone:changed', () => schedule());
  const offStore = store.subscribe(next => apply(next));

  const destroy = (): void => {
    if (destroyed) return;
    destroyed = true;
    board.destroy();
    observer?.disconnect();
    picker?.destroy();
    offStore();
    offContext();
    offZone();
    doc.removeEventListener('visibilitychange', onVisibility);
    select.removeEventListener('change', onSelectList);
    nameForm.removeEventListener('submit', onSubmit);
    nameForm.removeEventListener('keydown', onNameKey);
    input.removeEventListener('keydown', onAddKey);
    body.removeEventListener('pointerenter', onEnter);
    body.removeEventListener('pointerleave', onLeave);
    body.removeEventListener('focusin', onFocusIn);
    body.removeEventListener('focusout', onFocusOut);
    root.removeEventListener('keydown', stopKeys);
    root.removeEventListener('pointerdown', stopPointer);
    rows.clear();
    visibleRows.clear();
    root.remove();
  };
  paint();
  void reload();
  return { el: root, initialFocus: select, reload, destroy };
}

/** Rules to add to the widget's shared stylesheet or a custom host stylesheet. */
export const WATCHLIST_PANEL_CSS = `
.oac-widget .oac-watchlist { display: flex; flex-direction: column; gap: 6px; height: 100%; min-height: 0; padding: 8px 10px 0; box-sizing: border-box; font-size: 12px; }
.oac-widget .oac-watchlist__bar, .oac-widget .oac-watchlist__add, .oac-widget .oac-watchlist__name, .oac-widget .oac-watchlist__confirm { display: flex; align-items: center; gap: 4px; flex: none; min-width: 0; }
.oac-widget .oac-watchlist__bar .oac-select { flex: 1 1 auto; min-width: 0; }
.oac-widget .oac-watchlist__bar .oac-select select { width: 100%; min-width: 0; }
.oac-widget .oac-watchlist .oac-btn { height: 26px; padding: 0 7px; font-size: 11px; flex: none; }
.oac-widget .oac-watchlist__name[hidden], .oac-widget .oac-watchlist__confirm[hidden], .oac-widget .oac-watchlist__scroll[hidden] { display: none; }
.oac-widget .oac-watchlist__name input, .oac-widget .oac-watchlist__add input { flex: 1 1 auto; min-width: 0; height: 26px; }
.oac-widget .oac-watchlist__confirm { flex-wrap: wrap; }
.oac-widget .oac-watchlist__confirm-text { flex: 1 1 100%; color: var(--oac-tx); overflow-wrap: anywhere; }
.oac-widget .oac-watchlist__add-current { max-width: 45%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.oac-widget .oac-watchlist__status { flex: none; font-size: 11px; color: var(--oac-mut); }
.oac-widget .oac-watchlist__status[data-state="live"] { color: var(--oac-tx); }
.oac-widget .oac-watchlist__status[data-state="reconnecting"], .oac-widget .oac-watchlist__status[data-state="disconnected"], .oac-widget .oac-watchlist__status[data-state="error"] { color: var(--oac-danger); }
.oac-widget .oac-watchlist__message { flex: none; font-size: 11px; color: var(--oac-danger); overflow-wrap: anywhere; }
.oac-widget .oac-watchlist__empty { margin: 6px 0; font-size: 11px; color: var(--oac-mut); }
.oac-widget .oac-watchlist__scroll { flex: 1 1 auto; min-height: 0; overflow: auto; overscroll-behavior: contain; margin: 0 -10px; }
/* Numbers take the width they need and the symbol the rest, so a price is never the part cut short. */
.oac-widget .oac-watchlist__table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
.oac-widget .oac-watchlist__table thead th { position: sticky; top: 0; z-index: 1; background: var(--oac-panel); border-bottom: 1px solid var(--oac-bd-soft); padding: 0; }
.oac-widget .oac-watchlist__sort { width: 100%; height: 24px; padding: 0 6px; border: 0; background: none; color: var(--oac-mut); font: 600 10px/1 var(--oac-font); text-transform: uppercase; letter-spacing: .04em; text-align: right; white-space: nowrap; cursor: pointer; }
.oac-widget .oac-watchlist__col--symbol .oac-watchlist__sort { text-align: left; padding-left: 10px; }
.oac-widget .oac-watchlist__sort:hover, .oac-widget th[aria-sort="ascending"] .oac-watchlist__sort, .oac-widget th[aria-sort="descending"] .oac-watchlist__sort { color: var(--oac-tx); }
.oac-widget th[aria-sort="ascending"] .oac-watchlist__sort::after { content: " \\2191"; }
.oac-widget th[aria-sort="descending"] .oac-watchlist__sort::after { content: " \\2193"; }
.oac-widget .oac-watchlist__col--symbol { width: 100%; }
.oac-widget .oac-watchlist__col--actions { width: 26px; min-width: 26px; }
.oac-widget .oac-watchlist__row { height: 28px; border-bottom: 1px solid var(--oac-bd-soft); }
.oac-widget .oac-watchlist__row:hover, .oac-widget .oac-watchlist__row:focus-within { background: var(--oac-elev); }
/* On the cell: some engines paint no shadow on a table row. */
.oac-widget .oac-watchlist__row[aria-current="true"] > th { box-shadow: inset 2px 0 0 var(--oac-acc); }
.oac-widget .oac-watchlist__row td, .oac-widget .oac-watchlist__row th { padding: 0 6px; text-align: right; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 400; }
.oac-widget .oac-watchlist__row .oac-watchlist__instrument { padding: 0; max-width: 0; text-align: left; }
.oac-widget .oac-watchlist__open { display: block; width: 100%; height: 28px; line-height: 28px; padding: 0 6px 0 10px; border: 0; background: none; color: var(--oac-tx); font: inherit; text-align: left; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.oac-widget .oac-watchlist__symbol { font-weight: 600; }
.oac-widget .oac-watchlist__exchange { margin-left: 5px; font-size: 10px; color: var(--oac-mut); }
.oac-widget .oac-watchlist__last { color: var(--oac-tx); }
/* The theme's own pair, lifted to read as text. A fallback colour here would pin one palette. */
.oac-widget .oac-watchlist .is-up { color: var(--oac-up); }
.oac-widget .oac-watchlist .is-down { color: var(--oac-down); }
.oac-widget .oac-watchlist__row[data-state="stale"] td, .oac-widget .oac-watchlist__row[data-state="unavailable"] td, .oac-widget .oac-watchlist__row[data-state="error"] td, .oac-widget .oac-watchlist__row[data-state="loading"] td { color: var(--oac-mut); }
.oac-widget .oac-watchlist__row[data-state="stale"] .oac-watchlist__last { text-decoration: underline dotted; text-underline-offset: 3px; }
.oac-widget .oac-watchlist__actions { padding: 0 4px 0 0 !important; }
.oac-widget .oac-watchlist__actions .oac-btn { width: 22px; height: 22px; padding: 0; border-color: transparent; background: transparent; color: var(--oac-mut); opacity: 0; }
.oac-widget .oac-watchlist__row:hover .oac-watchlist__actions .oac-btn, .oac-widget .oac-watchlist__row:focus-within .oac-watchlist__actions .oac-btn { opacity: 1; }
.oac-widget .oac-panel-dock[data-sheet="true"] .oac-watchlist__actions .oac-btn { opacity: 1; width: 32px; height: 32px; }
.oac-widget .oac-panel-dock[data-sheet="true"] .oac-watchlist__row, .oac-widget .oac-panel-dock[data-sheet="true"] .oac-watchlist__open { height: 40px; line-height: 40px; }
@media (hover: none) { .oac-widget .oac-watchlist__actions .oac-btn { opacity: 1; } }
`;
