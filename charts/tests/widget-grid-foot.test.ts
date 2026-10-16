/**
 * One bottom bar under the chart grid (`bottombar`), acting on the active
 * chart: its ranges, scale toggles and Go to reach that chart alone, the
 * charts then carry neither Go to nor a market status of their own, and the
 * go-to panel opens over the whole grid from the bar. Off, the default, each
 * chart keeps both.
 */
import { beforeAll, describe, expect, it } from 'vitest';
import type { BarsRequest, DataFeed } from '../src/index';
import { SessionCalendar } from '../src/feed/instrument';
import { zonedWallClockToUtcSeconds } from '../src/feed/time';
import type { ChartGrid } from '../src/widget/index';
import { ensureWindowGlobal, type FakeElement } from './helpers/fake-dom-widget';
import { el, flush, makeGrid, walk } from './widget-grid-harness';

beforeAll(ensureWindowGlobal);

const IST = 'Asia/Kolkata';
const NSE = new SessionCalendar({ timezone: IST, sessions: ['0915-1530:23456'] });
/** Wednesday 1 October 2025, 11:00 IST: the market is open. */
const NOW = zonedWallClockToUtcSeconds(2025, 10, 1, 11, 0, 0, IST) * 1000;

/** Each instrument's own seeded walk, ending before the clock. */
const feed: DataFeed = {
  getBars: async (request: BarsRequest) => walk(200, 100 + request.symbol.charCodeAt(0), NOW / 1000 - 200 * 86400),
};
const options = { preset: '1x2' as const, interval: '1d', sessionCalendar: NSE, now: () => NOW, feed };

const cellRoot = (grid: ChartGrid, i: number): FakeElement => el(grid.cells()[i].widget.root);
const marketShown = (grid: ChartGrid, i: number): boolean => cellRoot(grid, i).querySelector('.oac-statusline__market')?.hidden === false;
const foot = (root: FakeElement): FakeElement => root.querySelector('.oac-grid__foot .oac-bottombar')!;

describe('chart grid bottom bar', () => {
  it('is off unless the host asks for it, and each chart keeps Go to and its market status', async () => {
    const { grid, root } = makeGrid(options);
    await flush();
    expect(root.querySelector('.oac-bottombar')).toBeNull();
    for (const i of [0, 1]) {
      expect(cellRoot(grid, i).querySelector('.oac-topbar__goto')).not.toBeNull();
      expect(marketShown(grid, i)).toBe(true);
    }
  });

  it('puts one bar under the charts and takes Go to and the market status off every chart', async () => {
    const { grid, root } = makeGrid({ ...options, bottombar: true });
    await flush();
    const order = root.children.map(child => child.className.split(' ').pop());
    expect(order.slice(0, 3)).toEqual(['oac-grid__tabs', 'oac-grid__cells', 'oac-grid__foot']);
    expect(root.querySelectorAll('.oac-bottombar')).toHaveLength(1);
    for (const i of [0, 1]) {
      expect(cellRoot(grid, i).querySelector('.oac-bottombar')).toBeNull();
      expect(cellRoot(grid, i).querySelector('.oac-topbar__goto')).toBeNull();
      expect(marketShown(grid, i)).toBe(false);
    }
    const status = foot(root).querySelector('.oac-bottombar__status')!;
    expect(status.hidden).toBe(false);
    expect(status.getAttribute('aria-label')).toBe('Market open, closes 15:30');
    expect(foot(root).querySelector('.oac-bottombar__goto')?.textContent).toBe('Go to');
  });

  it('acts on the active chart: a range, a scale toggle, and the pressed range follow the focus', async () => {
    const { grid, root } = makeGrid({ ...options, bottombar: true });
    await flush();
    const range = (id: string): FakeElement => foot(root).querySelector(`.oac-bottombar__range[data-range="${id}"]`)!;
    range('1D').click();
    await flush();
    expect(grid.cells().map(cell => cell.widget.interval())).toEqual(['1m', '1d']);
    expect(range('1D').getAttribute('aria-pressed')).toBe('true');
    grid.setActive(grid.cells()[1].id);
    expect(range('1D').getAttribute('aria-pressed')).toBe('false');
    foot(root).querySelector('.oac-bottombar__icon[data-scale="log"]')!.click();
    const mode = (i: number): string | undefined => {
      const chart = grid.cells()[i].widget.chart;
      return chart.priceAxisState(chart.primaryPaneIndex(), 'right')?.mode;
    };
    expect([mode(0), mode(1)]).toEqual(['linear', 'logarithmic']);
    // A report goes to the chart it is about.
    grid.setActive(grid.cells()[0].id);
    range('5D').click();
    await flush();
    expect(cellRoot(grid, 0).querySelector('.oac-statusline__msg')?.textContent).not.toBe('');
  });

  it('leaves Go to out of a phone chart More sheet as well, since the bar under the grid shows on a phone', async () => {
    const sheetActions = async (bottombar: boolean): Promise<Array<string | undefined>> => {
      const { grid } = makeGrid({ ...options, bottombar, mobile: 'always' });
      await flush();
      cellRoot(grid, 0).querySelector('[data-mobile-action="more"]')!.click();
      const actions = cellRoot(grid, 0).querySelectorAll('.oac-mobile-sheet [data-mobile-action]').map(node => node.dataset.mobileAction);
      grid.destroy();
      return actions;
    };
    const plain = await sheetActions(false);
    expect(plain).toContain('go-to');
    const barred = await sheetActions(true);
    expect(barred).toContain('alerts');
    expect(barred).not.toContain('go-to');
  });

  it('opens Go to over the whole grid, hanging from its own button, for the active chart', async () => {
    const { grid, root } = makeGrid({ ...options, bottombar: true });
    await flush();
    grid.setActive(grid.cells()[1].id);
    const goTo = foot(root).querySelector('.oac-bottombar__goto')!;
    goTo.click();
    const panel = root.querySelector('.oac-grid__overlay .oac-goto')!;
    expect(panel).not.toBeNull();
    expect(cellRoot(grid, 1).querySelector('.oac-goto')).toBeNull();
    expect(goTo.getAttribute('aria-expanded')).toBe('true');
    expect(panel.style.top).not.toBe('');
    // The panel is the active chart's: its hint names that chart's zone, and it closes with its own button.
    expect(panel.querySelector('.oac-goto__hint')?.textContent).toContain('Asia/Kolkata');
    panel.querySelector('button[aria-label="Close"]')!.click();
    expect(root.querySelector('.oac-goto')).toBeNull();
    // A host's own call opens it the same way, from the bar's button.
    expect(grid.cells()[0].widget.openDateNavigation()).toBe(true);
    expect(root.querySelector('.oac-grid__overlay .oac-goto')).not.toBeNull();
    expect(goTo.getAttribute('aria-expanded')).toBe('true');
  });

  it('takes the grid theme and goes with the grid, closing its zone menu', async () => {
    const { grid, root, doc } = makeGrid({ ...options, bottombar: true });
    await flush();
    const wrap = root.querySelector('.oac-grid__foot')!;
    expect(wrap.dataset.theme).toBe('dark');
    grid.setTheme('light');
    expect(wrap.dataset.theme).toBe('light');
    const strip = foot(root);
    strip.querySelector('.oac-bottombar__clock')!.click();
    expect(root.querySelector('.oac-grid__overlay .oac-menu')).not.toBeNull();
    grid.destroy();
    expect(doc.body.querySelector('.oac-bottombar')).toBeNull();
    expect(doc.body.querySelector('.oac-menu')).toBeNull();
    // Its clock and listeners stop with it.
    expect(strip.textContent).toBe('');
  });
});
