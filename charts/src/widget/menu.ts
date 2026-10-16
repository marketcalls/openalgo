/**
 * The chrome's shared popup menu and its file helpers: the menu every bar,
 * the drawing toolbar and the dialogs open from a button, and the two calls
 * that name and hand over a file the capture and export rows make.
 *
 * A module of its own so a part that only wants a menu does not depend on
 * the top bar, and through it on the layouts and the persistence code.
 */
import { chromeIcon, chromeIconSvg } from 'openalgo-charts/draw';
import { h, glyph, type WidgetContext } from './context';
import { widgetText } from './localization';
import { ariaKeys } from './keymap';

export interface MenuRow {
  label: string;
  /**
   * A chrome icon id for a glyph before the label. Once one row has a glyph,
   * every row keeps the column, so the labels share a left edge; an id the
   * registry does not carry leaves its slot empty. Since 2.5.10.
   */
  icon?: string | undefined;
  sub?: string | undefined;
  /** Shown at the right edge, for a chord. */
  key?: string | undefined;
  /** Makes the row one of a set of choices, true for the current one; a row without it is an action. */
  on?: boolean;
  disabled?: boolean;
  danger?: boolean;
  onSelect: () => void;
}

export interface MenuOptions {
  /** A search box at the top with this placeholder; rows filter as the user types. */
  find?: string;
  ariaLabel?: string;
  /** Where the menu opens: under the anchor (default), or beside it, as a column of buttons wants. Since 2.6.0. */
  placement?: 'below' | 'beside';
  /** Beside only: a wider element the menu clears as well as the anchor (the rail, not one button in it). Since 2.6.0. */
  edge?: HTMLElement | undefined;
}

/** A menu row's glyph: the registry's, or an empty slot the stylesheet sizes like one. */
const rowGlyph = (id: string | undefined): string =>
  id !== undefined && chromeIcon(id) !== undefined ? chromeIconSvg(id) : '<svg aria-hidden="true"></svg>';

/**
 * A popup menu under `anchor`, or beside it. Rows are buttons; a `{ head }` string starts a
 * group. Returns the closer. Exported for the dialog tier, whose context menu
 * and pickers want the same shape. It reads only the document, the overlay
 * opener and the translations, so any widget context serves, and so does a
 * bottom bar context.
 */
export function openMenu(ctx: WidgetContext | Pick<WidgetContext, 'document' | 'openOverlay' | 'translate'>, anchor: HTMLElement, rows: ReadonlyArray<MenuRow | string>, opts: MenuOptions = {}): () => void {
  const doc = ctx.document;
  const m = h(doc, 'div', 'oac-menu', { role: 'menu' });
  if (opts.ariaLabel) m.setAttribute('aria-label', opts.ariaLabel);
  let find: HTMLInputElement | null = null;
  if (opts.find) {
    const wrap = h(doc, 'div', 'oac-menu__find');
    find = h(doc, 'input', undefined, { type: 'text', placeholder: opts.find, 'aria-label': opts.find });
    wrap.appendChild(find);
    m.appendChild(wrap);
  }
  const body = h(doc, 'div', 'oac-menu__body');
  m.appendChild(body);
  let close: () => void = () => {};
  const glyphs = rows.some((r) => typeof r !== 'string' && r.icon !== undefined);

  const paint = (q: string): void => {
    const needle = q.trim().toLowerCase();
    body.textContent = '';
    let shown = 0;
    // A group heading is only worth drawing once something under it survives
    // the filter, so it is held back until the first matching row appears.
    let pending: string | null = null;
    for (const r of rows) {
      if (typeof r === 'string') { pending = r; continue; }
      if (needle !== '' && !r.label.toLowerCase().includes(needle) && !(r.sub ?? '').toLowerCase().includes(needle)) continue;
      if (pending !== null) {
        const g = h(doc, 'div', 'oac-head');
        g.textContent = pending;
        body.appendChild(g);
        pending = null;
      }
      // A row with an `on` is one of a set of choices; any other is an action, which has no checked state.
      const b = h(doc, 'button', 'oac-menu__row' + (r.danger ? ' is-danger' : ''), {
        type: 'button', role: r.on === undefined ? 'menuitem' : 'menuitemradio', 'aria-disabled': String(r.disabled === true),
      });
      if (r.on !== undefined) b.setAttribute('aria-checked', String(r.on));
      if (glyphs) b.appendChild(glyph(doc, rowGlyph(r.icon), 'chrome'));
      const label = h(doc, 'span', 'oac-menu__label');
      label.textContent = r.label;
      b.appendChild(label);
      if (r.sub) {
        const s = h(doc, 'span', 'oac-menu__sub');
        s.textContent = r.sub;
        b.appendChild(s);
      }
      if (r.key) {
        // Shown beside the name, said as the row's shortcut rather than read into its name.
        const k = h(doc, 'kbd', 'oac-menu__key', { 'aria-hidden': 'true' });
        k.textContent = r.key;
        b.appendChild(k);
        b.setAttribute('aria-keyshortcuts', ariaKeys(r.key));
      }
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        if (r.disabled) return;
        close();
        r.onSelect();
      });
      body.appendChild(b);
      shown++;
    }
    if (shown === 0) {
      const e = h(doc, 'div', 'oac-menu__empty');
      e.textContent = widgetText(ctx, 'No match');
      body.appendChild(e);
    }
  };
  paint('');
  if (find !== null) {
    const input = find;
    input.addEventListener('input', () => paint(input.value));
    // Enter picks the only remaining row, so a unique search needs no click.
    input.addEventListener('keydown', (e) => {
      if ((e as KeyboardEvent).key !== 'Enter') return;
      // The pick closes the menu and focus returns to its button, which the
      // same Enter would otherwise press and reopen (the bottom bar's zones).
      e.preventDefault();
      const only = body.querySelectorAll('.oac-menu__row');
      if (only.length === 1) (only[0] as HTMLElement).click();
    });
  }
  m.addEventListener('keydown', (e) => {
    const ke = e as KeyboardEvent;
    const items = Array.from(body.querySelectorAll('.oac-menu__row')) as HTMLElement[];
    const at = items.indexOf(doc.activeElement as HTMLElement);
    if (ke.key === 'ArrowDown') { items[(at + 1) % items.length]?.focus(); ke.preventDefault(); ke.stopPropagation(); }
    else if (ke.key === 'ArrowUp') { items[(at - 1 + items.length) % items.length]?.focus(); ke.preventDefault(); ke.stopPropagation(); }
  });
  close = ctx.openOverlay(m, { anchor, placement: opts.placement ?? 'below', edge: opts.edge, initialFocus: find ?? (body.querySelector('.oac-menu__row[aria-checked="true"]') as HTMLElement | null) ?? undefined });
  return close;
}

/** Hand `text` to the browser as a file. False when the runtime has no way to (no `Blob`, no object URLs). */
export function downloadText(doc: Document, filename: string, text: string, mime: string): boolean {
  const g = globalThis as { Blob?: typeof Blob; URL?: typeof URL };
  if (g.Blob === undefined || g.URL === undefined || typeof g.URL.createObjectURL !== 'function') return false;
  const a = doc.createElement('a');
  const url = g.URL.createObjectURL(new g.Blob([text], { type: mime }));
  try {
    a.href = url;
    a.download = filename;
    (doc.body ?? doc.documentElement).appendChild(a);
    a.click();
  } finally {
    a.remove();
    // Revoking synchronously races browser downloads, including successful handoff.
    setTimeout(() => g.URL?.revokeObjectURL(url), 0);
  }
  return true;
}

/** `SYMBOL-5m-2026-01-31-09-15` with the characters a filename cannot carry removed. */
export function captureName(symbol: string, interval: string, now: Date = new Date()): string {
  const stamp = now.toISOString().slice(0, 16).replace(/[:T]/g, '-');
  return `${(symbol || 'chart').replace(/[^A-Za-z0-9._-]/g, '')}-${interval || 'chart'}-${stamp}`;
}
