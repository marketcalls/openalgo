/**
 * The chart grid bar's menus: the layout picker, the link menu and the
 * whole-grid capture menu.
 *
 * They load on first use (lazy.ts): a grid whose user never opens one, and
 * every widget outside a grid, never fetches them. The bar and the link
 * chips open them through the grid (`GridBarHost.openMenu`).
 */
import { chromeIconSvg } from 'openalgo-charts/draw';
import { h } from './context';
import { chrome, layoutTileSvg, type GridBarHost } from './grid-bar';
import { groupMark } from './grid-cells';
import { CHART_GRID_LAYOUTS, isChartGridLayout, type ChartGridLayoutId } from './grid-layouts';
import type { LinkChannel } from './grid-links';
import { chartCount, layoutName } from './grid-text';
import { widgetText, type WidgetTranslationOptions } from './localization';
import { rovingIndex } from './roving';
import { addWidgetStyles } from './styles';

const txt = (host: GridBarHost): WidgetTranslationOptions => host.text;
/** Ids for the notes menus point their held-back rows at; one page may hold several grids. */
let notes = 0;

/** The glyph each channel row carries, from the chrome registry. */
const CHANNEL_ICON: Readonly<Record<LinkChannel, string>> = {
  crosshair: chromeIconSvg('crosshair'), viewport: chromeIconSvg('time-range'), symbol: chromeIconSvg('search'),
  interval: chromeIconSvg('clock'), chartType: chromeIconSvg('chart-candlestick'), appearance: chromeIconSvg('palette'),
  drawings: chromeIconSvg('drawing-sync'),
};
const CHANNEL_LABEL = {
  crosshair: 'Crosshair', viewport: 'Time range', symbol: 'Symbol', interval: 'Interval',
  chartType: 'Chart type', appearance: 'Appearance', drawings: 'Drawings',
} as const;

interface MenuItem {
  kind: 'radio' | 'check' | 'action';
  label: string;
  sub?: string | undefined;
  checked?: boolean;
  disabled?: boolean;
  icon?: HTMLElement;
  /** Leave the menu open after the choice, so several toggles take one visit. */
  stay?: boolean;
  onSelect(): void;
}

/**
 * A menu of radio, check and action rows over the grid. `build` is read again
 * after every row that keeps the menu open, so a toggle repaints in place and
 * the focus stays on the row that was pressed.
 */
function openRows(host: GridBarHost, anchor: HTMLElement, label: string, build: () => Array<MenuItem | string>,
  extra?: (menu: HTMLElement, repaint: () => void) => void, note?: string | null): () => void {
  const doc = host.doc;
  addWidgetStyles(doc, GRID_MENUS_CSS);
  const menu = h(doc, 'div', 'oac-menu oac-grid__menu', { role: 'menu', 'aria-label': label });
  const noteId = `oac-grid-note-${++notes}`;
  let close: () => void = () => {};
  const paint = (focusAt = -1): void => {
    menu.textContent = '';
    let index = 0;
    for (const item of build()) {
      if (typeof item === 'string') {
        const head = h(doc, 'div', 'oac-head', { role: 'presentation' });
        head.textContent = item;
        menu.appendChild(head);
        continue;
      }
      const row = h(doc, 'button', 'oac-menu__row', {
        type: 'button', role: item.kind === 'radio' ? 'menuitemradio' : item.kind === 'check' ? 'menuitemcheckbox' : 'menuitem',
        'aria-disabled': String(item.disabled === true),
      });
      if (item.kind !== 'action') row.setAttribute('aria-checked', String(item.checked === true));
      if (item.kind === 'check') {
        // A box with the chrome tick, not a native checkbox: a row is one button, and a control inside a button is not allowed.
        const box = h(doc, 'span', 'oac-grid__box', { 'aria-hidden': 'true' });
        box.innerHTML = chromeIconSvg('check');
        row.appendChild(box);
      }
      if (item.icon !== undefined) row.appendChild(item.icon);
      const name = h(doc, 'span', 'oac-menu__label');
      name.textContent = item.label;
      row.appendChild(name);
      if (item.sub !== undefined) {
        const sub = h(doc, 'span', 'oac-menu__sub');
        sub.textContent = item.sub;
        row.appendChild(sub);
      }
      if (item.disabled === true && note != null) row.setAttribute('aria-describedby', noteId);
      const at = index++;
      row.addEventListener('click', e => {
        e.stopPropagation();
        if (item.disabled === true) return;
        if (item.stay !== true) close();
        item.onSelect();
        if (item.stay === true) paint(at);
      });
      menu.appendChild(row);
    }
    if (note != null) {
      // Said once under the rows it holds back, rather than squeezed beside each label.
      const line = h(doc, 'div', 'oac-grid__note', { role: 'none', id: noteId });
      line.textContent = note;
      menu.appendChild(line);
    }
    extra?.(menu, () => paint());
    if (focusAt >= 0) menu.querySelectorAll<HTMLElement>('.oac-menu__row')[focusAt]?.focus();
  };
  paint();
  menu.addEventListener('keydown', e => {
    const rows = Array.from(menu.querySelectorAll<HTMLElement>('.oac-menu__row'));
    const at = rows.indexOf(doc.activeElement as HTMLElement);
    // From no row (the menu itself), down starts at the first row and up at the last.
    const to = rovingIndex(e.key, at, rows.length, ['ArrowUp', 'ArrowDown'], true);
    if (to < 0) return;
    e.preventDefault();
    e.stopPropagation();
    rows[to]!.focus(); // every branch wraps to into the rows, which are not empty
  });
  close = host.overlays.open(menu, { anchor, placement: 'below',
    initialFocus: menu.querySelector<HTMLElement>('.oac-menu__row[aria-checked="true"]') ?? undefined });
  return close;
}

/**
 * The layout picker: one row of tiles per chart count, the current layout
 * checked. Left and Right walk the tiles in order, Up and Down move between
 * rows at the same place, Home and End go to either end.
 */
export function openLayoutPicker(host: GridBarHost, anchor: HTMLElement): () => void {
  const doc = host.doc;
  addWidgetStyles(doc, GRID_MENUS_CSS);
  const menu = h(doc, 'div', 'oac-grid__picker', { role: 'menu', 'aria-label': widgetText(txt(host), 'Arrange charts') });
  const rows: HTMLElement[][] = [];
  const current = host.layout();
  const byCount = new Map<number, ChartGridLayoutId[]>();
  for (const id of host.layouts) {
    const count = CHART_GRID_LAYOUTS[id].slots.length;
    byCount.set(count, [...(byCount.get(count) ?? []), id]);
  }
  let close: () => void = () => {};
  /**
   * The tiles are pictures, so a line under them names the one under the
   * pointer or the focus, and the current layout otherwise. A tooltip would
   * cover the next row of tiles; screen readers hear each tile's own label.
   */
  const describe = (id: ChartGridLayoutId): string => CHART_GRID_LAYOUTS[id].slots.length === 1 ? layoutName(txt(host), id)
    : widgetText(txt(host), '{name}, {count} charts', { name: layoutName(txt(host), id), count: CHART_GRID_LAYOUTS[id].slots.length });
  const caption = h(doc, 'div', 'oac-grid__picker-caption', { 'aria-hidden': 'true' });
  const rest = (): void => { caption.textContent = current !== null && isChartGridLayout(current) ? describe(current) : ''; };
  for (const [count, ids] of byCount) {
    const group = h(doc, 'div', 'oac-grid__picker-row', { role: 'group', 'aria-label': chartCount(txt(host), count) });
    const head = h(doc, 'span', 'oac-grid__picker-count', { 'aria-hidden': 'true' });
    head.textContent = String(count);
    group.appendChild(head);
    const tiles: HTMLElement[] = [];
    for (const id of ids) {
      const name = layoutName(txt(host), id);
      const tile = h(doc, 'button', 'oac-grid__tile', {
        type: 'button', role: 'menuitemradio', 'aria-checked': String(id === current), 'aria-label': name,
      });
      tile.dataset.layout = id;
      tile.appendChild(chrome(doc, layoutTileSvg(id)));
      const say = (): void => { caption.textContent = describe(id); };
      tile.addEventListener('pointerenter', say);
      tile.addEventListener('focus', say);
      tile.addEventListener('click', e => { e.stopPropagation(); close(); host.setLayout(id); });
      tiles.push(tile);
      group.appendChild(tile);
    }
    rows.push(tiles);
    menu.appendChild(group);
  }
  rest();
  menu.appendChild(caption);
  menu.addEventListener('pointerleave', () => { if (!menu.contains(doc.activeElement)) rest(); });
  const flat = rows.flat();
  menu.addEventListener('keydown', e => {
    const at = flat.indexOf(doc.activeElement as HTMLElement);
    if (at < 0) return;
    // flat is rows flattened, so the focused cell has a row, and every row index below wraps into rows.
    const row = rows.findIndex(r => r.includes(flat[at]!));
    const col = rows[row]!.indexOf(flat[at]!);
    let next: HTMLElement | undefined;
    if (e.key === 'ArrowRight') next = flat[(at + 1) % flat.length];
    else if (e.key === 'ArrowLeft') next = flat[(at - 1 + flat.length) % flat.length];
    else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      const to = rows[(row + (e.key === 'ArrowDown' ? 1 : rows.length - 1)) % rows.length]!;
      next = to[Math.min(col, to.length - 1)];
    } else if (e.key === 'Home') next = flat[0];
    else if (e.key === 'End') next = flat[flat.length - 1];
    if (next === undefined) return;
    e.preventDefault();
    e.stopPropagation();
    next.focus();
  });
  close = host.overlays.open(menu, { anchor, placement: 'below',
    initialFocus: flat.find(t => t.getAttribute('aria-checked') === 'true') ?? flat[0] ?? undefined });
  return close;
}

/**
 * The link menu for the active chart: which group it is in, a new group,
 * a name for the group, and the group's channels. Toggles leave the menu
 * open, so a user linking three channels opens it once.
 */
export function openLinkMenu(host: GridBarHost, anchor: HTMLElement): () => void {
  const doc = host.doc, t = txt(host);
  let renaming = false;
  const rows = (): Array<MenuItem | string> => {
    const current = host.links.current();
    const out: Array<MenuItem | string> = [widgetText(t, 'Link group')];
    out.push({ kind: 'radio', label: widgetText(t, 'Not linked'), checked: current === null, icon: groupMark(doc, null), stay: true,
      onSelect: () => host.links.setGroup(null) });
    for (const group of host.links.groups()) {
      out.push({ kind: 'radio', label: group.name, sub: chartCount(t, group.cells.length), checked: current?.id === group.id,
        icon: groupMark(doc, group), stay: true, onSelect: () => host.links.setGroup(group.id) });
    }
    out.push({ kind: 'action', label: widgetText(t, 'New group'), icon: chrome(doc, chromeIconSvg('plus')), stay: true, onSelect: () => host.links.newGroup() });
    out.push({ kind: 'action', label: widgetText(t, 'Rename group'), icon: chrome(doc, chromeIconSvg('rename')), disabled: current === null,
      sub: current === null ? widgetText(t, 'Link this chart to a group first') : undefined, stay: true, onSelect: () => { renaming = true; } });
    if (current === null) return out;
    out.push(widgetText(t, 'Links in {group}', { group: current.name }));
    const o = current.links;
    for (const channel of ['crosshair', 'viewport', 'symbol', 'interval', 'chartType', 'appearance', 'drawings'] as const) {
      out.push({ kind: 'check', label: widgetText(t, CHANNEL_LABEL[channel]), checked: o[channel], stay: true,
        icon: chrome(doc, CHANNEL_ICON[channel]), sub: channel === 'drawings' ? widgetText(t, 'same instrument only') : undefined,
        onSelect: () => host.links.setChannel(channel, !o[channel]) });
      if (channel === 'crosshair') {
        out.push({ kind: 'check', label: widgetText(t, 'Nearest bar'), sub: widgetText(t, 'where a chart has no bar at that time'),
          checked: o.whenMissing === 'nearest', disabled: !o.crosshair, stay: true, icon: h(doc, 'span', 'oac-grid__indent'),
          onSelect: () => host.links.setChannel('nearest', o.whenMissing !== 'nearest') });
      }
    }
    out.push({ kind: 'action', label: widgetText(t, 'Share this chart\'s drawings'), icon: chrome(doc, chromeIconSvg('drawing-sync')),
      disabled: !o.drawings, sub: o.drawings ? undefined : widgetText(t, 'Switch Drawings on first'), onSelect: () => host.links.share() });
    return out;
  };
  // Renaming swaps the rows for a field, in the same menu, so Escape and the
  // focus return behave as they do for the rows.
  const form = (menu: HTMLElement, repaint: () => void): void => {
    const current = host.links.current();
    if (!renaming || current === null) return;
    menu.textContent = '';
    const wrap = h(doc, 'div', 'oac-grid__rename');
    const input = h(doc, 'input', undefined, { type: 'text', 'aria-label': widgetText(t, 'Group name'), maxlength: '120' });
    input.value = current.name;
    const done = (save: boolean): void => {
      if (save && input.value.trim() !== '') host.links.rename(current.id, input.value.trim());
      renaming = false;
      repaint();
      menu.querySelector<HTMLElement>('.oac-menu__row[aria-checked="true"]')?.focus();
    };
    // Enter saves; Escape closes the menu like any other, leaving the name as it was.
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); done(true); }
    });
    const save = h(doc, 'button', 'oac-btn oac-btn--primary', { type: 'button' });
    save.textContent = widgetText(t, 'Save');
    save.addEventListener('click', e => { e.stopPropagation(); done(true); });
    const cancel = h(doc, 'button', 'oac-btn', { type: 'button' });
    cancel.textContent = widgetText(t, 'Cancel');
    cancel.addEventListener('click', e => { e.stopPropagation(); done(false); });
    wrap.append(input, cancel, save);
    menu.appendChild(wrap);
    input.focus();
    input.select();
  };
  return openRows(host, anchor, widgetText(t, 'Linking'), rows, form);
}

/** Download or copy one image of every chart; greyed with the reason while the grid shows one chart. */
export function openCaptureMenu(host: GridBarHost, anchor: HTMLElement): () => void {
  const t = txt(host);
  const blocked = host.capture.blocked();
  const copy = host.capture.canCopy();
  return openRows(host, anchor, widgetText(t, 'Capture every chart'), () => [
    { kind: 'action', label: widgetText(t, 'Download PNG of every chart'), disabled: blocked !== null,
      icon: chrome(host.doc, chromeIconSvg('download')), onSelect: () => host.capture.download() },
    { kind: 'action', label: widgetText(t, 'Copy image of every chart'), disabled: blocked !== null || !copy,
      sub: blocked !== null ? undefined : copy ? widgetText(t, 'paste it anywhere') : widgetText(t, 'needs https or localhost'),
      icon: chrome(host.doc, chromeIconSvg('copy')), onSelect: () => host.capture.copy() },
  ], undefined, blocked);
}

/** The menus' rules, added to the widget sheet when one first opens. */
const GRID_MENUS_CSS = `
.oac-widget .oac-grid__menu { max-width: 380px; }
.oac-grid__menu .oac-menu__row > .oac-glyph { color: var(--oac-mut); }
.oac-grid__indent { width: 16px; flex: none; }
.oac-grid__menu .oac-menu__row[role="menuitemcheckbox"]::before { display: none; }
.oac-grid__menu .oac-menu__row[role="menuitemcheckbox"][aria-checked="true"] { color: var(--oac-tx); }
.oac-grid__box { display: grid; place-items: center; width: 15px; height: 15px; flex: none; border: 1px solid var(--oac-bd);
  border-radius: 4px; background: var(--oac-elev); }
.oac-grid__box > svg { width: 11px; height: 11px; fill: none; stroke: var(--oac-bg); stroke-width: 2.4; stroke-linecap: round;
  stroke-linejoin: round; opacity: 0; }
.oac-grid__menu .oac-menu__row[aria-checked="true"] > .oac-grid__box { background: var(--oac-acc); border-color: var(--oac-acc); }
.oac-grid__menu .oac-menu__row[aria-checked="true"] > .oac-grid__box > svg { opacity: 1; }
.oac-grid__menu .oac-menu__row[aria-disabled="true"] > .oac-grid__box { opacity: .45; }
.oac-grid__menu .oac-menu__row[role="menuitem"]::before { content: ''; width: 6px; margin: 0 2px 0 -2px; flex: none; }
.oac-grid__rename { display: flex; align-items: center; gap: 6px; padding: 4px; }
.oac-grid__rename > input { flex: 1 1 auto; min-width: 140px; }

/* The layout picker: one row of tiles per chart count. */
.oac-grid__picker { display: flex; flex-direction: column; gap: 2px; padding: 6px 8px 6px 6px; max-height: calc(100% - 16px);
  overflow-y: auto; background: var(--oac-panel); border: 1px solid var(--oac-bd); border-radius: 10px; box-shadow: var(--oac-shadow); outline: none; }
.oac-grid__picker-row { display: flex; align-items: center; gap: 3px; }
.oac-grid__picker-count { width: 20px; margin-right: 4px; text-align: right; color: var(--oac-faint); font-size: 11px;
  font-variant-numeric: tabular-nums; }
.oac-grid__tile { display: grid; place-items: center; width: 34px; height: 30px; padding: 0; border: 1px solid transparent;
  border-radius: 6px; background: transparent; color: var(--oac-mut); transition: background .1s, color .1s; }
.oac-grid__tile > .oac-glyph > svg { width: 22px; height: 22px; stroke-width: 1.5; }
.oac-grid__tile:hover, .oac-grid__tile:focus-visible { background: var(--oac-elev-2); color: var(--oac-tx); }
.oac-grid__tile:focus-visible { outline: 2px solid var(--oac-ring); outline-offset: -2px; }
.oac-grid__tile[aria-checked="true"] { background: var(--oac-on-bg); border-color: var(--oac-on-bd); color: var(--oac-acc-2); }
.oac-grid__picker-caption { min-height: 16px; margin: 4px 0 0; padding: 5px 2px 0 28px; border-top: 1px solid var(--oac-bd-soft);
  color: var(--oac-mut); font-size: 11.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.oac-grid__note { max-width: 260px; padding: 6px 8px 4px 31px; border-top: 1px solid var(--oac-bd-soft); margin-top: 3px;
  color: var(--oac-faint); font-size: 11.5px; line-height: 1.4; }

@media (prefers-reduced-motion: reduce) {
  .oac-grid__tile { transition: none; }
}
`;
