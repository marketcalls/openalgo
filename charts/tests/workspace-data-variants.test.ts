import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { migrateWidgetWorkspace, parseWorkspaceDocument, WorkspaceDocumentError } from '../src/workspace/index';
import { createChartGrid, type ChartGrid } from '../src/widget/index';
import type { Bar, BarsRequest, DataFeed } from '../src/index';
import { workspaceFixture } from './helpers/workspace-fixture';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument } from './helpers/fake-dom-widget';

// A saved desk names the series each chart showed, so reopening it asks the
// provider for the same series and never quietly shows the default one.

beforeAll(ensureWindowGlobal);
const grids: ChartGrid[] = [];
afterEach(() => { for (const grid of grids.splice(0)) grid.destroy(); });
const flush = async (): Promise<void> => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
const extended = { session: 'extended' as const };

function withVariant(variant: unknown) {
  const input = workspaceFixture();
  return { ...input, panes: [{ ...input.panes[0], variant }, input.panes[1]] };
}

describe('workspace documents carry data variants', () => {
  it('keeps a pane variant and leaves a pane without one untouched', () => {
    const saved = parseWorkspaceDocument(JSON.stringify(withVariant({ currency: 'USD', session: 'extended' })));
    expect(saved.panes[0].variant).toEqual({ session: 'extended', currency: 'USD' });
    expect(saved.panes[1]).not.toHaveProperty('variant');
    // The default variant is stored as no variant at all.
    expect(parseWorkspaceDocument(withVariant({})).panes[0]).not.toHaveProperty('variant');
  });

  it('refuses a variant it could only serve as some other series', () => {
    for (const variant of [{ session: 'overnight' }, { adjustment: 1 }, { currency: '' }, { region: 'US' }, 'extended']) {
      expect(() => parseWorkspaceDocument(withVariant(variant)), JSON.stringify(variant)).toThrow(WorkspaceDocumentError);
    }
  });

  it('migrates a widget state with its variant', () => {
    const doc = migrateWidgetWorkspace({ version: 1, symbol: 'AAPL', exchange: 'US', interval: '5m', chartType: 'candlestick',
      theme: 'dark', variant: extended, chart: { version: 1 } }, { id: 'w', name: 'W', now: 5 });
    expect(doc.panes[0].variant).toEqual(extended);
  });
});

describe('chart grid carries data variants', () => {
  function makeGrid(feed: DataFeed) {
    const doc = fakeWidgetDocument();
    const grid = createChartGrid(fakeContainer(doc, 1200, 800) as unknown as HTMLElement, {
      document: doc as unknown as Document, pixelRatio: () => 1, feed, preset: '1x2',
      raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} },
      symbol: 'AAPL', exchange: 'US', interval: '1m', now: () => 60_000_000, rail: false,
    });
    grids.push(grid);
    return grid;
  }
  const feed = (requests: BarsRequest[]): DataFeed => ({
    dataVariants: () => ({ sessions: ['regular', 'extended'] }),
    getBars: async request => { requests.push(request); return [{ time: 60, open: 1, high: 1, low: 1, close: 1 } as Bar]; },
  });

  it('saves each chart variant and reopens it on the same series', async () => {
    const requests: BarsRequest[] = [];
    const grid = makeGrid(feed(requests));
    await flush();
    grid.cells()[1].widget.setDataVariant(extended);
    await flush();
    const payload = grid.getWorkspace();
    expect(payload.panes[0]).not.toHaveProperty('variant');
    expect(payload.panes[1].variant).toEqual(extended);
    const reopened: BarsRequest[] = [];
    const target = makeGrid(feed(reopened));
    await flush();
    expect(target.applyWorkspace(payload)).toEqual({ applied: true });
    await flush();
    expect(target.cells().map(cell => cell.widget.variant())).toEqual([undefined, extended]);
    expect(reopened.filter(request => request.variant !== undefined).map(request => request.variant)).toEqual([extended]);
  });

  it('reopens a chart saved on the default series as the default, whatever the cell showed', async () => {
    const saved = makeGrid(feed([])).getWorkspace();
    expect(saved.panes.some(pane => pane.variant !== undefined)).toBe(false);
    const requests: BarsRequest[] = [];
    const target = makeGrid(feed(requests));
    target.cells()[0].widget.setDataVariant(extended);
    await flush();
    const count = requests.length;
    expect(target.applyWorkspace(saved)).toEqual({ applied: true });
    await flush();
    expect(target.cells().map(cell => cell.widget.variant())).toEqual([undefined, undefined]);
    expect(requests.slice(count).map(request => request.variant)).toEqual([undefined]);
  });

  it('gives a new cell the active chart variant', async () => {
    const grid = makeGrid(feed([]));
    grid.setPreset('1x1');
    grid.cells()[0].widget.setDataVariant(extended);
    grid.setPreset('1x2');
    expect(grid.cells()[1].widget.variant()).toEqual(extended);
  });

  it('refuses a payload whose variant it cannot read, and keeps the charts it had', async () => {
    const grid = makeGrid(feed([]));
    const before = grid.cells().map(cell => cell.widget);
    const payload = grid.getWorkspace();
    (payload.panes[0] as { variant?: unknown }).variant = { session: 'overnight' };
    const report = grid.applyWorkspace(payload);
    expect(report.applied).toBe(false);
    expect(grid.cells().map(cell => cell.widget)).toEqual(before);
  });
});
