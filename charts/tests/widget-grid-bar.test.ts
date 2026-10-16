/**
 * The grid bar and its menus: off unless asked for, the layout picker with its
 * keyboard, maximize, the link menu and its group rows and channel toggles,
 * and the capture rows in the bar and in each chart's own capture menu.
 */
import { beforeAll, describe, expect, it } from 'vitest';
import '../src/indicators/index';
import { layoutIconPath } from '../src/draw/index';
import { CHART_GRID_LAYOUTS, type ChartGrid, type ChartGridLayoutId } from '../src/widget/index';
import { ensureWindowGlobal, fire, fireKey, type FakeDocument, type FakeElement } from './helpers/fake-dom-widget';
import { FakeResizeObserver, el, makeGrid, withWindow } from './widget-grid-harness';

beforeAll(ensureWindowGlobal);

const bar = (root: FakeElement): FakeElement => root.querySelector('.oac-grid__bar')!;
const menu = (root: FakeElement): FakeElement | null => root.querySelector('.oac-grid__overlay [role="menu"]');
const rows = (root: FakeElement): FakeElement[] => menu(root)?.querySelectorAll('.oac-menu__row') ?? [];
const row = (root: FakeElement, label: string): FakeElement => rows(root).find(r => r.querySelector('.oac-menu__label')?.textContent === label)!;
const open = (root: FakeElement, selector: string): void => { bar(root).querySelector(selector)!.click(); };

describe('chart grid bar', () => {
  it('is off unless the host asks for it', () => {
    const { root } = makeGrid({ preset: '2x2' });
    expect(root.querySelector('.oac-grid__bar')).toBeNull();
    expect(root.querySelectorAll('.oac-widget').filter(n => !n.parentElement?.classList.contains('oac-grid__cell'))).toEqual([]);
  });

  it('sits over the charts as a named toolbar with a control for each job', () => {
    const { root } = makeGrid({ preset: 'top-3', toolbar: true });
    const b = bar(root);
    expect(root.firstElementChild).toBe(b);
    expect(b.getAttribute('role')).toBe('toolbar');
    expect(b.getAttribute('aria-label')).toBe('Chart grid');
    // Each name holds the words the control shows, and says the state the picture only draws.
    expect(b.querySelectorAll('button').map(x => x.getAttribute('aria-label')))
      .toEqual(['Arrange charts: Large top, three below', 'Maximize the chart', 'Link: Group A', 'Capture every chart']);
    expect(b.querySelector('.oac-grid__layout .oac-grid__bar-text')?.textContent).toBe('Large top, three below');
  });

  it('keeps each control name and an open tip up to date as the layout and the group change', () => {
    const { grid, root } = makeGrid({ preset: '1x2', toolbar: true });
    const layout = bar(root).querySelector('.oac-grid__layout')!, link = bar(root).querySelector('.oac-grid__link')!;
    fire(layout, 'pointerenter');
    const tip = (): string | null | undefined => root.querySelector('.oac-tip')?.textContent;
    expect(tip()).toBe('Arrange charts: Two columns');
    grid.setPreset('corner-5');
    expect(layout.getAttribute('aria-label')).toBe('Arrange charts: Large corner, five around');
    expect(tip()).toBe('Arrange charts: Large corner, five around');
    grid.setLinkGroup(grid.active().id, null);
    expect(link.getAttribute('aria-label')).toBe('Link: Not linked');
  });

  it('moves between its controls with the arrows, Home and End, and leaves those keys to no chart', () => {
    const { root, doc } = makeGrid({ preset: '1x2', toolbar: true });
    const controls = bar(root).querySelectorAll('button');
    controls[0].focus();
    const at = (): number => controls.indexOf(doc.activeElement as FakeElement);
    const claimed = fireKey(doc.activeElement, 'ArrowRight');
    expect(at()).toBe(1);
    expect(claimed.defaultPrevented).toBe(true);
    fireKey(doc.activeElement, 'End');
    expect(at()).toBe(3);
    fireKey(doc.activeElement, 'ArrowRight');
    expect(at()).toBe(0);
    fireKey(doc.activeElement, 'ArrowLeft');
    expect(at()).toBe(3);
    fireKey(doc.activeElement, 'Home');
    expect(at()).toBe(0);
  });

  it('names its controls through the host translator', () => {
    const translate = (key: string, fallback: string): string => ({ 'Chart grid': 'Rejilla', 'Arrange charts: {name}': 'Disposicion: {name}', 'Two by two': 'Dos por dos' } as Record<string, string>)[key] ?? fallback;
    const { root } = makeGrid({ preset: '2x2', toolbar: true, translate });
    expect(bar(root).getAttribute('aria-label')).toBe('Rejilla');
    expect(bar(root).querySelector('.oac-grid__layout')?.getAttribute('aria-label')).toBe('Disposicion: Dos por dos');
    expect(bar(root).querySelector('.oac-grid__bar-text')?.textContent).toBe('Dos por dos');
  });
});

describe('chart grid layout picker', () => {
  it('offers a tile per layout, drawn from its slots and grouped by chart count, the current one checked', () => {
    const { root } = makeGrid({ preset: 'left-2', toolbar: true });
    open(root, '.oac-grid__layout');
    const picker = menu(root)!;
    expect(picker.getAttribute('aria-label')).toBe('Arrange charts');
    const tiles = picker.querySelectorAll('.oac-grid__tile');
    expect(tiles.map(t => t.dataset.layout)).toEqual(Object.keys(CHART_GRID_LAYOUTS));
    expect(picker.querySelectorAll('[role="group"]').map(g => g.getAttribute('aria-label'))).toEqual([
      '1 chart', '2 charts', '3 charts', '4 charts', '5 charts', '6 charts', '8 charts', '9 charts', '12 charts', '16 charts',
    ]);
    expect(tiles.filter(t => t.getAttribute('aria-checked') === 'true').map(t => t.dataset.layout)).toEqual(['left-2']);
    const tile = tiles.find(t => t.dataset.layout === 'corner-7')!;
    expect(tile.getAttribute('aria-label')).toBe('Large corner, seven around');
    const spec = CHART_GRID_LAYOUTS['corner-7'];
    expect(tile.querySelector('.oac-glyph')?.innerHTML).toContain(`d="${layoutIconPath(spec.rows, spec.columns, spec.slots)}"`);
  });

  it('names the tile under the pointer or the focus in a line under the tiles, the current layout at rest', () => {
    const { root, doc } = makeGrid({ preset: 'left-2', toolbar: true });
    const button = bar(root).querySelector('.oac-grid__layout')!;
    button.focus();
    button.click();
    const caption = (): string | null => menu(root)!.querySelector('.oac-grid__picker-caption')!.textContent;
    expect(caption()).toBe('Large left, two on the right, 3 charts');
    fireKey(doc.activeElement, 'End');
    expect(caption()).toBe('Four by four, 16 charts');
    fire(menu(root)!.querySelectorAll('.oac-grid__tile').find(t => t.dataset.layout === 'corner-5')!, 'pointerenter');
    expect(caption()).toBe('Large corner, five around, 6 charts');
    // One chart is not "One chart, 1 charts".
    fire(menu(root)!.querySelectorAll('.oac-grid__tile').find(t => t.dataset.layout === '1x1')!, 'pointerenter');
    expect(caption()).toBe('One chart');
    // A picture needs no floating tip over the next row: the caption and the tile's own label say it.
    expect(root.querySelector('.oac-tip')?.textContent ?? '').not.toContain('Large corner');
    expect(menu(root)!.querySelector('.oac-grid__picker-caption')!.getAttribute('aria-hidden')).toBe('true');
  });

  it('applies the chosen layout and closes', () => {
    const { grid, root } = makeGrid({ preset: '1x1', toolbar: true });
    open(root, '.oac-grid__layout');
    menu(root)!.querySelectorAll('.oac-grid__tile').find(t => t.dataset.layout === 'corner-5')!.click();
    expect(menu(root)).toBeNull();
    expect(grid.layout().preset).toBe('corner-5');
    expect(grid.cells()).toHaveLength(6);
    expect(bar(root).querySelector('.oac-grid__bar-text')?.textContent).toBe('Large corner, five around');
  });

  it('walks the tiles with the arrow keys, Home and End, and gives the focus back on Escape', () => {
    const { root, doc } = makeGrid({ preset: '2x2', toolbar: true });
    const button = bar(root).querySelector('.oac-grid__layout')!;
    button.focus();
    button.click();
    const focus = (): string | undefined => (doc.activeElement as FakeElement).dataset.layout;
    expect(focus()).toBe('2x2');
    fireKey(doc.activeElement, 'ArrowRight');
    expect(focus()).toBe('1x4');
    fireKey(doc.activeElement, 'ArrowLeft');
    fireKey(doc.activeElement, 'ArrowLeft');
    expect(focus()).toBe('bottom-2');
    // Down to the next row, at the same place or its last tile.
    fireKey(doc.activeElement, 'ArrowDown');
    expect(focus()).toBe('top-3');
    fireKey(doc.activeElement, 'ArrowUp');
    expect(focus()).toBe('top-2');
    fireKey(doc.activeElement, 'End');
    expect(focus()).toBe('4x4');
    fireKey(doc.activeElement, 'ArrowRight');
    expect(focus()).toBe('1x1');
    fireKey(doc.activeElement, 'Escape');
    expect(menu(root)).toBeNull();
    expect(doc.activeElement).toBe(button);
  });

  it('leaves the Layout control out when the host offers no layouts, and out of the arrow keys', () => {
    const { root, doc } = makeGrid({ preset: '1x2', toolbar: true, presets: ['nope' as ChartGridLayoutId] });
    const layout = bar(root).querySelector('.oac-grid__layout')!;
    expect(layout.hidden).toBe(true);
    const max = bar(root).querySelector('.oac-grid__max')!;
    max.focus();
    fireKey(doc.activeElement, 'ArrowLeft');
    expect(doc.activeElement).toBe(bar(root).querySelector('.oac-grid__capture'));
    fireKey(doc.activeElement, 'Home');
    expect(doc.activeElement).toBe(max);
  });

  it('offers only the layouts the host lists, in its order', () => {
    const layouts: ChartGridLayoutId[] = ['2x2', '1x1', 'top-2', 'nope' as ChartGridLayoutId];
    const { root } = makeGrid({ preset: '2x2', toolbar: true, presets: layouts });
    open(root, '.oac-grid__layout');
    expect(menu(root)!.querySelectorAll('.oac-grid__tile').map(t => t.dataset.layout)).toEqual(['2x2', '1x1', 'top-2']);
  });
});

describe('chart grid maximize button', () => {
  it('maximizes and restores the active chart, named for what the press does next', () => {
    const { grid, root } = makeGrid({ preset: '1x2', toolbar: true });
    const max = bar(root).querySelector('.oac-grid__max')!;
    grid.setActive(grid.cells()[1].id);
    max.click();
    expect(grid.maximized()).toBe(grid.cells()[1].id);
    // The name is the action, so no pressed state says the opposite.
    expect(max.getAttribute('aria-label')).toBe('Restore the grid');
    expect(max.getAttribute('aria-pressed')).toBeNull();
    max.click();
    expect(grid.maximized()).toBeNull();
    expect(max.getAttribute('aria-label')).toBe('Maximize the chart');
    expect(max.getAttribute('aria-pressed')).toBeNull();
  });

  it('is off with its reason while there is one chart or the grid is compact', () => {
    const doc: FakeDocument = withWindow();
    const { grid, root } = makeGrid({ preset: '1x1', toolbar: true }, doc);
    const max = bar(root).querySelector('.oac-grid__max')!;
    expect(max.getAttribute('aria-disabled')).toBe('true');
    max.click();
    expect(grid.maximized()).toBeNull();
    grid.setPreset('1x2');
    expect(max.getAttribute('aria-disabled')).toBe('false');
    root.rect = { left: 0, top: 0, width: 400, height: 700 };
    FakeResizeObserver.fire(root);
    expect(max.getAttribute('aria-disabled')).toBe('true');
    fire(max, 'pointerenter');
    expect(root.querySelector('.oac-tip')?.textContent).toContain('The grid shows one chart at a time at this width');
  });
});

describe('chart grid link menu', () => {
  function linked(): { grid: ChartGrid; root: FakeElement; doc: FakeDocument } {
    const made = makeGrid({ preset: '1x3', toolbar: true });
    made.grid.setActive(made.grid.cells()[1].id);
    open(made.root, '.oac-grid__link');
    return made;
  }

  it('lists the groups with the active chart group checked, then that group channels', () => {
    const { root } = linked();
    expect(menu(root)?.getAttribute('aria-label')).toBe('Linking');
    expect(rows(root).map(r => [r.getAttribute('role'), r.querySelector('.oac-menu__label')?.textContent, r.getAttribute('aria-checked')])).toEqual([
      ['menuitemradio', 'Not linked', 'false'], ['menuitemradio', 'Group A', 'true'], ['menuitem', 'New group', null], ['menuitem', 'Rename group', null],
      ['menuitemcheckbox', 'Crosshair', 'true'], ['menuitemcheckbox', 'Nearest bar', 'true'], ['menuitemcheckbox', 'Time range', 'true'],
      ['menuitemcheckbox', 'Symbol', 'false'], ['menuitemcheckbox', 'Interval', 'false'], ['menuitemcheckbox', 'Chart type', 'false'],
      ['menuitemcheckbox', 'Appearance', 'false'], ['menuitemcheckbox', 'Drawings', 'false'], ['menuitem', 'Share this chart\'s drawings', null],
    ]);
    expect(menu(root)?.querySelectorAll('.oac-head').map(h => h.textContent)).toEqual(['Link group', 'Links in Group A']);
    expect(row(root, 'Share this chart\'s drawings').getAttribute('aria-disabled')).toBe('true');
  });

  it('switches a channel of the group and stays open, so several take one visit', () => {
    const { grid, root } = linked();
    row(root, 'Symbol').click();
    row(root, 'Interval').click();
    row(root, 'Nearest bar').click();
    expect(menu(root)).not.toBeNull();
    expect(grid.linkOptions()).toMatchObject({ symbol: true, interval: true, whenMissing: 'hide' });
    expect(row(root, 'Symbol').getAttribute('aria-checked')).toBe('true');
    row(root, 'Crosshair').click();
    expect(row(root, 'Nearest bar').getAttribute('aria-disabled')).toBe('true');
    row(root, 'Drawings').click();
    expect(row(root, 'Share this chart\'s drawings').getAttribute('aria-disabled')).toBe('false');
  });

  it('counts one shared drawing in the singular', () => {
    const { grid, root } = linked();
    const active = grid.active();
    active.widget.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: 1, price: 100 }] });
    row(root, 'Drawings').click();
    row(root, 'Share this chart\'s drawings').click();
    expect(root.querySelectorAll('.oac-toast').map(t => t.textContent)).toContain('Shared 1 drawing');
  });

  it('starts a group for the active chart, takes it out of every group and back', () => {
    const { grid, root } = linked();
    const active = grid.active();
    row(root, 'New group').click();
    expect(active.linkGroup).toBe('b');
    expect(row(root, 'Group B').getAttribute('aria-checked')).toBe('true');
    expect(bar(root).querySelector('.oac-grid__bar-mark .oac-grid__chip')?.textContent).toBe('B');
    row(root, 'Not linked').click();
    expect(active.linkGroup).toBeNull();
    // The group it left had no other chart, so it is gone; and a chart in no group has no channels to show.
    expect(rows(root).map(r => r.querySelector('.oac-menu__label')?.textContent)).toEqual(['Not linked', 'Group A', 'New group', 'Rename group']);
    expect(row(root, 'Rename group').getAttribute('aria-disabled')).toBe('true');
    row(root, 'Group A').click();
    expect(active.linkGroup).toBe('a');
  });

  it('renames the group in place, Enter saving and Escape leaving the name as it was', () => {
    const { grid, root, doc } = linked();
    row(root, 'Rename group').click();
    const input = menu(root)!.querySelector('.oac-grid__rename input')!;
    expect(doc.activeElement).toBe(input);
    expect(input.value).toBe('Group A');
    input.value = '  Banks  ';
    fireKey(input, 'Enter');
    expect(grid.linkGroups()[0].name).toBe('Banks');
    expect(row(root, 'Banks').getAttribute('aria-checked')).toBe('true');
    row(root, 'Rename group').click();
    const again = menu(root)!.querySelector('.oac-grid__rename input')!;
    again.value = 'Other';
    fireKey(again, 'Escape');
    expect(menu(root)).toBeNull();
    expect(grid.linkGroups()[0].name).toBe('Banks');
  });
});

describe('chart grid capture rows', () => {
  it('greys the whole-grid capture with its reason, said once and tied to each row, while one chart is shown', () => {
    const doc: FakeDocument = withWindow();
    const { grid, root } = makeGrid({ preset: '1x2', toolbar: true }, doc);
    grid.maximize();
    open(root, '.oac-grid__capture');
    expect(rows(root).map(r => [r.querySelector('.oac-menu__label')?.textContent, r.getAttribute('aria-disabled'), r.querySelector('.oac-menu__sub')?.textContent]))
      .toEqual([['Download PNG of every chart', 'true', undefined], ['Copy image of every chart', 'true', undefined]]);
    const note = menu(root)!.querySelector('.oac-grid__note')!;
    expect(note.textContent).toBe('Show every chart to capture them together');
    for (const r of rows(root)) expect(r.getAttribute('aria-describedby')).toBe(note.id);
    fireKey(doc.activeElement, 'Escape');
    // At a compact width no layout shows every chart, so the reason names the width, not a step to take.
    grid.restore();
    root.rect = { left: 0, top: 0, width: 400, height: 700 };
    FakeResizeObserver.fire(root);
    open(root, '.oac-grid__capture');
    expect(menu(root)!.querySelector('.oac-grid__note')?.textContent).toBe('The grid shows one chart at a time at this width');
  });

  it('moves from the menu itself to the first row on ArrowDown and to the last on ArrowUp', () => {
    const { root, doc } = makeGrid({ preset: '1x2', toolbar: true });
    const label = (): string | null | undefined => (doc.activeElement as FakeElement).querySelector('.oac-menu__label')?.textContent;
    for (const [key, want] of [['ArrowDown', 'Download PNG of every chart'], ['ArrowUp', 'Copy image of every chart']] as const) {
      open(root, '.oac-grid__capture');
      menu(root)!.focus();
      fireKey(menu(root)!, key);
      expect(label()).toBe(want);
      fireKey(doc.activeElement, 'Escape');
    }
  });

  it('writes no note and keeps every row live while every chart shows', () => {
    const { root } = makeGrid({ preset: '1x2', toolbar: true });
    open(root, '.oac-grid__capture');
    expect(menu(root)!.querySelector('.oac-grid__note')).toBeNull();
    expect(row(root, 'Download PNG of every chart').getAttribute('aria-disabled')).toBe('false');
    expect(row(root, 'Download PNG of every chart').getAttribute('aria-describedby')).toBeNull();
  });

  it('adds the whole grid to each chart own capture menu, and nothing on a grid of one', () => {
    const { grid } = makeGrid({ preset: '1x2' });
    const menuOf = (index: number): FakeElement => {
      const root = el(grid.cells()[index].widget.root);
      root.querySelector('.oac-topbar button[aria-label="Capture chart"]')!.click();
      return root.querySelector('.oac-menu')!;
    };
    const first = menuOf(0);
    expect(first.querySelectorAll('.oac-head').map(h => h.textContent)).toEqual(['Every chart']);
    expect(first.querySelectorAll('.oac-menu__label').map(l => l.textContent).slice(-2)).toEqual(['Download PNG of every chart', 'Copy image of every chart']);
    fireKey(el(grid.cells()[0].widget.root), 'Escape');
    grid.setPreset('1x1');
    const single = menuOf(0);
    expect(single.querySelectorAll('.oac-head')).toHaveLength(0);
    expect(single.querySelectorAll('.oac-menu__label').map(l => l.textContent)).not.toContain('Download PNG of every chart');
  });
});
