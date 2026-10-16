/**
 * The grid's link groups: several named groups with channels of their own, a
 * chart in one group or none, chart type and drawings wired end to end, the
 * workspace that saves them, and the flat channels an older reader applies.
 */
import { beforeAll, describe, expect, it } from 'vitest';
import type { Drawing } from '../src/draw/index';
import '../src/indicators/index';
import { parseWorkspacePayload, type WorkspacePayload } from '../src/workspace/index';
import type { ChartGrid, ChartGridCell } from '../src/widget/index';
import { ensureWindowGlobal } from './helpers/fake-dom-widget';
import { el, flush, makeGrid, walk } from './widget-grid-harness';

beforeAll(ensureWindowGlobal);

const ids = (grid: ChartGrid): string[] => grid.cells().map(c => c.id);
const symbols = (grid: ChartGrid): string[] => grid.cells().map(c => c.widget.symbol());
const groupOf = (grid: ChartGrid): Array<string | null> => grid.cells().map(c => c.linkGroup);

/** A trend line from the lowest low to the highest high of what the chart shows. */
function trend(cell: ChartGridCell): Drawing {
  const bars = cell.widget.series.getData() as Array<{ time: number; low: number; high: number }>;
  const low = bars.reduce((a, b) => (b.low < a.low ? b : a));
  const high = bars.reduce((a, b) => (b.high > a.high ? b : a));
  return cell.widget.draw.add({ tool: 'trend-line', paneIndex: 0, style: {},
    points: [{ time: low.time, price: low.low }, { time: high.time, price: high.high }] });
}
const lines = (cell: ChartGridCell): number => cell.widget.draw.drawings().filter(d => d.tool === 'trend-line').length;

describe('chart grid link groups', () => {
  it('starts with one group holding every chart and saves the desk as it did before groups', () => {
    const { grid, root } = makeGrid({ preset: '2x2', links: { symbol: true } });
    const groups = grid.linkGroups();
    expect(groups).toHaveLength(1);
    expect(groups[0]).toMatchObject({ id: 'a', letter: 'A', name: 'Group A', cells: ids(grid) });
    expect(groupOf(grid)).toEqual(['a', 'a', 'a', 'a']);
    const payload = grid.getWorkspace();
    expect(Object.keys(payload.sync).sort()).toEqual(['appearance', 'crosshair', 'interval', 'symbol', 'viewport']);
    expect(payload.panes.some(p => 'linkGroup' in p)).toBe(false);
    // No marks and no layer over the grid until groups are used.
    expect(root.querySelectorAll('.oac-grid__mark')).toHaveLength(0);
    expect(root.querySelectorAll('.oac-grid__overlay')).toHaveLength(0);
    expect(grid.cells().map(c => el(c.element).getAttribute('aria-label'))).toEqual(['Chart 1', 'Chart 2', 'Chart 3', 'Chart 4']);
  });

  it('links each group on its own channels, with nothing crossing between groups', () => {
    const { grid } = makeGrid({ preset: '2x2', links: { symbol: true } });
    const [a, b, c, d] = grid.cells();
    const second = grid.addLinkGroup(c.id, { name: 'Majors' })!;
    expect(grid.setLinkGroup(d.id, second)).toBe(true);
    grid.setGroupLinks(second, { symbol: true, interval: true });
    a.widget.setSymbol('INFY');
    expect(symbols(grid)).toEqual(['INFY', 'INFY', 'AAA', 'AAA']);
    c.widget.setSymbol('TCS');
    expect(symbols(grid)).toEqual(['INFY', 'INFY', 'TCS', 'TCS']);
    d.widget.setInterval('5m');
    expect(grid.cells().map(x => x.widget.interval())).toEqual(['1m', '1m', '5m', '5m']);
    expect(b.linkGroup).toBe('a');
    expect(grid.linkGroups().map(g => [g.id, g.name, g.cells.length])).toEqual([['a', 'Group A', 2], [second, 'Majors', 2]]);
  });

  it('brings a chart that joins a group onto what the group links, and leaves an unlinked chart alone', () => {
    const { grid } = makeGrid({ preset: '1x3', links: { symbol: true } });
    const [a, b, c] = grid.cells();
    grid.setLinkGroup(c.id, null);
    a.widget.setSymbol('SBIN');
    expect(symbols(grid)).toEqual(['SBIN', 'SBIN', 'AAA']);
    c.widget.setSymbol('WIPRO');
    expect(symbols(grid)).toEqual(['SBIN', 'SBIN', 'WIPRO']);
    grid.setLinkGroup(c.id, 'a');
    expect(symbols(grid)).toEqual(['SBIN', 'SBIN', 'SBIN']);
    expect(b.linkGroup).toBe('a');
  });

  it('starts a new group from the chart that makes it, never from an instrument a group once had', () => {
    const { grid } = makeGrid({ preset: '1x3' });
    const [a, b, c] = grid.cells();
    const group = grid.addLinkGroup(a.id, { links: { symbol: true } })!;
    grid.setLinkGroup(b.id, group);
    a.widget.setSymbol('ONE');
    expect(symbols(grid)).toEqual(['ONE', 'ONE', 'AAA']);
    // Everyone leaves; the group is gone, and a chart that starts a group with its letter keeps its own instrument.
    grid.setLinkGroup(a.id, null);
    grid.setLinkGroup(b.id, null);
    expect(grid.linkGroups().map(g => g.id)).toEqual(['a']);
    c.widget.setSymbol('TWO');
    const again = grid.addLinkGroup(c.id, { links: { symbol: true } })!;
    grid.setLinkGroup(b.id, again);
    expect(symbols(grid)).toEqual(['ONE', 'TWO', 'TWO']);
  });

  it('keeps a group letter when an earlier group empties, and gives no more than sixteen', () => {
    const { grid } = makeGrid({ preset: '4x4' });
    const cells = grid.cells();
    const made = cells.slice(1).map(c => grid.addLinkGroup(c.id));
    expect(made.every(id => id !== null)).toBe(true);
    expect(grid.linkGroups().map(g => g.letter).join('')).toBe('ABCDEFGHIJKLMNOP');
    expect(grid.addLinkGroup(cells[0].id)).toBeNull();
    grid.setLinkGroup(cells[1].id, 'a');
    expect(grid.linkGroups().some(g => g.letter === 'B')).toBe(false);
    expect(grid.linkGroups().find(g => g.cells.includes(cells[2].id))?.letter).toBe('C');
  });

  it('keeps each group letter through a save and a restore, the letters an emptied group left free included', () => {
    const { grid } = makeGrid({ preset: '1x3' });
    const [a, b, c] = grid.cells();
    grid.addLinkGroup(b.id);
    grid.addLinkGroup(c.id);
    grid.setLinkGroup(a.id, grid.linkGroups()[1].id);
    expect(grid.linkGroups().map(g => g.letter)).toEqual(['B', 'C']);
    const payload = parseWorkspacePayload(JSON.stringify(grid.getWorkspace()));
    expect(grid.applyWorkspace(payload)).toEqual({ applied: true });
    expect(grid.linkGroups().map(g => [g.id, g.letter])).toEqual([['b', 'B'], ['c', 'C']]);
    // A group made after the restore takes the first letter still free.
    expect(grid.addLinkGroup(grid.cells()[2].id)).toBe('a');
  });

  it('switches the active chart group with setLinks, every group when the active chart links with none', () => {
    const { grid } = makeGrid({ preset: '1x3' });
    const [a, b, c] = grid.cells();
    const second = grid.addLinkGroup(b.id)!;
    grid.setActive(a.id);
    grid.setLinks({ symbol: true });
    expect(grid.linkGroups().map(g => g.links.symbol)).toEqual([true, false]);
    expect(grid.linkOptions().symbol).toBe(true);
    grid.setLinkGroup(c.id, null);
    grid.setActive(c.id);
    expect(grid.linkOptions()).toMatchObject({ crosshair: false, viewport: false, symbol: false });
    grid.setLinks({ interval: true });
    expect(grid.linkGroups().map(g => g.links.interval)).toEqual([true, true]);
    expect(grid.setGroupLinks('zz', { symbol: true })).toBe(false);
    expect(grid.setGroupLinks(second, { crosshair: false })).toBe(true);
  });

  it('says so when links, groups or the active chart group change', () => {
    const { grid } = makeGrid({ preset: '1x2' });
    const seen: boolean[] = [];
    grid.on('links', o => seen.push(o.symbol));
    const [a, b] = grid.cells();
    grid.addLinkGroup(b.id, { links: { symbol: true } });
    grid.setActive(b.id);
    grid.setActive(a.id);
    grid.setLinks({ symbol: true });
    expect(seen).toEqual([false, true, false, true]);
  });

  it('names groups within bounds and marks each chart with its group, in text as well as colour', () => {
    const { grid, root } = makeGrid({ preset: '1x3' });
    const [a, b, c] = grid.cells();
    const second = grid.addLinkGroup(b.id)!;
    grid.setLinkGroup(c.id, null);
    expect(grid.renameLinkGroup(second, '   ')).toBe(false);
    expect(grid.renameLinkGroup(second, 'x'.repeat(121))).toBe(false);
    expect(grid.renameLinkGroup('zz', 'Banks')).toBe(false);
    expect(grid.renameLinkGroup(second, '  Banks ')).toBe(true);
    const marks = root.querySelectorAll('.oac-grid__mark');
    expect(marks.map(m => m.getAttribute('aria-label'))).toEqual(['Linked in Group A', 'Linked in Banks', 'Not linked']);
    expect(marks.map(m => m.querySelector('.oac-grid__chip')?.textContent)).toEqual(['A', 'B', '']);
    expect(marks.map(m => m.dataset.group)).toEqual(['A', 'B', undefined]);
    expect([a, b, c].map(x => el(x.element).getAttribute('aria-label'))).toEqual([
      'Chart 1, linked in Group A', 'Chart 2, linked in Banks', 'Chart 3, not linked',
    ]);
    // The mark sits at the start of the chart's own bar and opens the link menu there.
    expect(el(b.widget.root).querySelector('.oac-topbar')?.firstElementChild).toBe(marks[1]);
    marks[1].click();
    expect(grid.active().id).toBe(b.id);
    const menu = root.querySelector('.oac-grid__overlay [role="menu"]');
    expect(menu?.getAttribute('aria-label')).toBe('Linking');
    // Back to one group holding every chart: the marks go, and a name brings them back.
    grid.setLinkGroup(b.id, 'a');
    grid.setLinkGroup(c.id, 'a');
    expect(root.querySelectorAll('.oac-grid__mark')).toHaveLength(0);
    grid.renameLinkGroup('a', 'Desk');
    expect(root.querySelectorAll('.oac-grid__mark')).toHaveLength(3);
  });
});

describe('chart grid chart type linking', () => {
  it('carries a chart type to the charts of its group only, as a step of the chart it was chosen on', async () => {
    const { grid } = makeGrid({ preset: '1x3', links: { chartType: true, crosshair: false, viewport: false } });
    const [a, b, c] = grid.cells();
    for (const x of grid.cells()) x.widget.series.setData(walk(120));
    await flush();
    grid.setLinkGroup(c.id, null);
    for (const x of grid.cells()) x.widget.history.clear();
    a.widget.setChartType('line');
    expect(grid.cells().map(x => x.widget.chartType())).toEqual(['line', 'line', 'candlestick']);
    // The follower's timeline did not take the leader's step.
    expect(b.widget.history.canUndo()).toBe(false);
    a.widget.history.undo();
    await flush();
    expect(grid.cells().map(x => x.widget.chartType())).toEqual(['candlestick', 'candlestick', 'candlestick']);
  });

  it('adopts the active chart type when the channel is switched on, and saves the switch', () => {
    const { grid } = makeGrid({ preset: '1x2' });
    const [a, b] = grid.cells();
    b.widget.setChartType('area');
    grid.setActive(b.id);
    grid.setLinks({ chartType: true });
    expect(a.widget.chartType()).toBe('area');
    expect(grid.getWorkspace().sync).toMatchObject({ chartType: true });
    expect(parseWorkspacePayload(JSON.stringify(grid.getWorkspace())).sync.chartType).toBe(true);
  });

  it('refuses a saved group linked on chart type whose charts disagree', () => {
    const { grid } = makeGrid({ preset: '1x2' });
    const payload = grid.getWorkspace();
    payload.sync.chartType = true;
    payload.panes[1].chartType = 'line';
    expect(grid.applyWorkspace(payload)).toEqual({ applied: false, reason: 'linked chart types differ between charts' });
  });
});

describe('chart grid drawings linking', () => {
  async function desk(exchange = 'NSE') {
    const made = makeGrid({ preset: '1x3', exchange, links: { drawings: true, crosshair: false, viewport: false } });
    for (const x of made.grid.cells()) x.widget.series.setData(walk(150, 812));
    await flush();
    return made;
  }

  it('shares a drawing with the charts of its group on the same instrument, and with no other group', async () => {
    const { grid } = await desk();
    const [a, b, c] = grid.cells();
    grid.addLinkGroup(c.id, { links: { drawings: true } });
    trend(a);
    expect([lines(a), lines(b), lines(c)]).toEqual([1, 1, 0]);
    // A chart on another instrument in the same group gets none.
    b.widget.setSymbol('OTHER');
    b.widget.series.setData(walk(150, 400));
    trend(a);
    expect(lines(a)).toBe(2);
    expect(lines(b)).toBe(0);
  });

  it('shares between charts whose host names no exchange', async () => {
    const { grid } = await desk('');
    const [a, b] = grid.cells();
    trend(a);
    expect(lines(b)).toBe(1);
  });

  it('keeps a drawing made before the switch went on private until the chart shares it', async () => {
    const { grid } = makeGrid({ preset: '1x2', links: { crosshair: false, viewport: false } });
    for (const x of grid.cells()) x.widget.series.setData(walk(150, 812));
    await flush();
    const [a, b] = grid.cells();
    trend(a);
    expect(grid.shareDrawings(a.id)).toBe(0);
    grid.setLinks({ drawings: true });
    expect(lines(b)).toBe(0);
    expect(grid.shareDrawings(a.id)).toBe(1);
    expect(lines(b)).toBe(1);
    expect(grid.shareDrawings('nope')).toBe(0);
  });

  it('stops sharing when a chart leaves the group, keeping what it already received', async () => {
    const { grid } = await desk();
    const [a, b] = grid.cells();
    trend(a);
    grid.setLinkGroup(b.id, null);
    trend(a);
    expect([lines(a), lines(b)]).toEqual([2, 1]);
  });
});

describe('chart grid saved link groups', () => {
  function grouped(): ChartGrid {
    const { grid } = makeGrid({ preset: '2x2', links: { symbol: true, crosshair: true, viewport: false } });
    const [, , c, d] = grid.cells();
    const second = grid.addLinkGroup(c.id, { name: 'Banks', links: { symbol: true, chartType: true, drawings: true, whenMissing: 'hide' } })!;
    grid.setLinkGroup(d.id, second);
    c.widget.setSymbol('HDFC');
    return grid;
  }

  it('writes groups, each chart group and flat channels off, and reads them all back', () => {
    const source = grouped();
    const payload = parseWorkspacePayload(JSON.stringify(source.getWorkspace()));
    expect(payload.sync.groups).toEqual([
      { id: 'a', name: 'Group A', crosshair: true, viewport: false, symbol: true, interval: false, appearance: false },
      // A new group starts on the grid's channels, with its own over them.
      { id: 'b', name: 'Banks', crosshair: true, viewport: false, symbol: true, interval: false, appearance: false, chartType: true, drawings: true, whenMissing: 'hide' },
    ]);
    expect(payload.panes.map(p => p.linkGroup)).toEqual(['a', 'a', 'b', 'b']);
    // Charts in two groups on two instruments: an older reader applying these to the whole desk changes nothing.
    expect(payload.sync).toMatchObject({ crosshair: false, viewport: false, symbol: false, interval: false, appearance: false });
    const { grid: target } = makeGrid();
    expect(target.applyWorkspace(payload)).toEqual({ applied: true });
    expect(symbols(target)).toEqual(['AAA', 'AAA', 'HDFC', 'HDFC']);
    expect(target.linkGroups().map(g => [g.id, g.name, g.cells.length, g.links.symbol, g.links.chartType, g.links.whenMissing]))
      .toEqual([['a', 'Group A', 2, true, false, 'nearest'], ['b', 'Banks', 2, true, true, 'hide']]);
    target.cells()[3].widget.setSymbol('ICICI');
    expect(symbols(target)).toEqual(['AAA', 'AAA', 'ICICI', 'ICICI']);
    const again = parseWorkspacePayload(JSON.stringify(target.getWorkspace()));
    expect(again.sync).toEqual({ ...payload.sync });
  });

  it('opens whole in a reader that knows no groups, because the flat channels it applies ask nothing', () => {
    const payload = grouped().getWorkspace();
    const old = JSON.parse(JSON.stringify(payload)) as WorkspacePayload;
    delete old.sync.groups;
    for (const pane of old.panes) delete pane.linkGroup;
    const { grid } = makeGrid();
    expect(grid.applyWorkspace(old)).toEqual({ applied: true });
    expect(symbols(grid)).toEqual(['AAA', 'AAA', 'HDFC', 'HDFC']);
  });

  it('writes the one group flags flat when a named group holds every chart', () => {
    const { grid } = makeGrid({ preset: '1x2', links: { symbol: true } });
    grid.renameLinkGroup('a', 'Desk');
    const sync = grid.getWorkspace().sync;
    expect(sync).toMatchObject({ symbol: true, crosshair: true, viewport: true, groups: [{ id: 'a', name: 'Desk', symbol: true }] });
  });

  it('refuses a saved group whose linked charts disagree, and accepts groups that differ from each other', () => {
    const payload = grouped().getWorkspace();
    const { grid } = makeGrid({ preset: '1x2' });
    const broken = JSON.parse(JSON.stringify(payload)) as WorkspacePayload;
    broken.panes[3].symbol = 'SBIN';
    expect(grid.applyWorkspace(broken)).toEqual({ applied: false, reason: 'linked symbols differ between charts' });
    const undeclared = JSON.parse(JSON.stringify(payload)) as WorkspacePayload;
    undeclared.panes[0].linkGroup = 'zz';
    expect(grid.applyWorkspace(undeclared).reason).toMatch(/undeclared link group zz/);
    expect(grid.cells()).toHaveLength(2);
    expect(grid.applyWorkspace(payload)).toEqual({ applied: true });
  });

  it('reads a group saved under the name the grid gave it back as unnamed, so a desk back to one group is plain again', () => {
    const { grid: source } = makeGrid({ preset: '1x3', links: { symbol: true } });
    source.addLinkGroup(source.cells()[2].id);
    const payload = parseWorkspacePayload(JSON.stringify(source.getWorkspace()));
    expect(payload.sync.groups?.map(g => g.name)).toEqual(['Group A', 'Group B']);
    const { grid, root } = makeGrid();
    expect(grid.applyWorkspace(payload)).toEqual({ applied: true });
    expect(grid.linkGroups().map(g => g.name)).toEqual(['Group A', 'Group B']);
    expect(root.querySelectorAll('.oac-grid__mark')).toHaveLength(3);
    grid.setLinkGroup(grid.cells()[2].id, 'a');
    expect(root.querySelectorAll('.oac-grid__mark')).toHaveLength(0);
    const sync = grid.getWorkspace().sync;
    expect(sync.groups).toBeUndefined();
    expect(sync).toMatchObject({ symbol: true });
    expect(grid.getWorkspace().panes.some(p => 'linkGroup' in p)).toBe(false);
    // A name the user gave is kept, and so is a default name read in another language.
    const named = JSON.parse(JSON.stringify(payload)) as WorkspacePayload;
    named.sync.groups![1].name = 'Banks';
    const { grid: other } = makeGrid({ translate: (key, fallback) => (key === 'Group {letter}' ? 'Gruppe {letter}' : fallback) });
    other.applyWorkspace(named);
    expect(other.linkGroups().map(g => g.name)).toEqual(['Group A', 'Banks']);
  });

  it('keeps an unlinked chart unlinked through a save and a restore', () => {
    const { grid } = makeGrid({ preset: '1x3', links: { symbol: true } });
    grid.setLinkGroup(grid.cells()[2].id, null);
    const payload = parseWorkspacePayload(JSON.stringify(grid.getWorkspace()));
    expect(payload.panes.map(p => p.linkGroup ?? null)).toEqual(['a', 'a', null]);
    const { grid: target } = makeGrid();
    target.applyWorkspace(payload);
    expect(groupOf(target)).toEqual(['a', 'a', null]);
    target.cells()[0].widget.setSymbol('MOVE');
    expect(symbols(target)).toEqual(['MOVE', 'MOVE', 'AAA']);
  });

  it('puts the charts a larger layout adds in the active chart group', () => {
    const { grid } = makeGrid({ preset: '1x2' });
    const second = grid.addLinkGroup(grid.cells()[1].id)!;
    grid.setActive(grid.cells()[1].id);
    grid.setPreset('2x2');
    expect(groupOf(grid)).toEqual(['a', second, second, second]);
    grid.setLinkGroup(grid.cells()[3].id, null);
    grid.setActive(grid.cells()[3].id);
    grid.setPreset('1x4');
    expect(groupOf(grid)).toEqual(['a', second, second, null]);
  });
});
