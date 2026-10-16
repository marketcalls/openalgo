import { describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { parsePaneState } from '../src/model/chart-state';
import { parseIndicatorTemplate, parseWorkspaceDocument, WorkspaceDocumentError } from '../src/workspace/index';
import { stripView } from '../src/widget/widget';
import { fakeDocument } from './helpers/fake-dom';
import { workspaceFixture } from './helpers/workspace-fixture';

const scale = (placement?: unknown) => ({
  marginTop: 0.1, marginBottom: 0.2, minMove: 0.05, minPrecision: 4,
  mode: 'logarithmic' as const, inverted: true, autoScale: false,
  range: { min: 10, max: 100 }, fixedRange: { min: 1, max: 200 },
  ratioLock: { barSpacing: 8, height: 578 },
  ...(placement === undefined ? {} : { placement }),
});
const placement = (side = 'right', order = 1) => ({ side, order });
const pane = (value: unknown = placement()) => ({ weight: 1, priceScale: scale(),
  scales: { left: scale({ side: 'left', order: 0 }), 'overlay:volume': scale({ side: 'hidden', order: 0 }),
    'overlay:comparison': scale(value) } });

describe('saved price axis placement', () => {
  it('round-trips detached placement alongside ranges, modes and locks', () => {
    const input = pane();
    const parsed = parsePaneState(input);
    expect(parsed).toEqual(input);
    const value = input.scales['overlay:comparison'].placement as { side: string; order: number };
    value.side = 'left'; value.order = 7;
    expect(parsed.scales?.['overlay:comparison']?.placement).toEqual(placement());
    expect(parsed.scales?.['overlay:comparison']?.ratioLock).toEqual({ barSpacing: 8, height: 578 });
  });

  it('supports primary placement and preserves omission in legacy snapshots', () => {
    const input = { weight: 1, priceScale: scale({ side: 'left', order: 2 }) };
    expect(parsePaneState(input)).toEqual(input);
    expect(parsePaneState({ weight: 1, priceScale: scale() }).priceScale).not.toHaveProperty('placement');
    expect(parsePaneState({ weight: 1, priceScale: {} }, true).priceScale).not.toHaveProperty('placement');
  });

  it('accepts null-prototype placement objects and the existing full native ID range', () => {
    const value = Object.assign(Object.create(null), placement('right', Number.MAX_SAFE_INTEGER));
    const input = { weight: 1, priceScale: scale(), scales: { 'overlay:': scale(value),
      [`overlay:${'x'.repeat(240)}`]: scale({ side: 'hidden', order: 0 }) } };
    const parsed = parsePaneState(input);
    expect(parsed.scales?.['overlay:']?.placement).toEqual(placement('right', Number.MAX_SAFE_INTEGER));
    expect(Object.getPrototypeOf(parsed.scales?.['overlay:']?.placement)).toBe(Object.prototype);
  });

  it.each([
    null, [], {}, { side: 'right' }, { order: 0 }, { side: 'center', order: 0 },
    { side: 'RIGHT', order: 0 }, { side: 'hidden', order: -1 }, { side: 'left', order: 0.5 },
    { side: 'right', order: NaN }, { side: 'right', order: Infinity },
    { side: 'right', order: Number.MAX_SAFE_INTEGER + 1 }, { side: 'right', order: '1' },
  ])('rejects malformed placement without modifying the supplied state (%#)', value => {
    const input = pane(value);
    const before = structuredClone(input);
    expect(() => parsePaneState(input)).toThrow(/placement|side|order|scale/i);
    expect(input).toEqual(before);
  });

  it('rejects inherited placement and accessors without invoking application code', () => {
    expect(() => parsePaneState(pane(Object.create(placement())))).toThrow();
    let reads = 0;
    const value = { get side() { reads++; return 'left'; }, order: 1 };
    expect(() => parsePaneState(pane(value))).toThrow(/accessor/i);
    expect(reads).toBe(0);
  });

  it.each(['side', 'order', 'accessor'])('rejects bad placement %s before actual chart restore mutates any configuration', kind => {
    const document = fakeDocument();
    const chart = new Chart(document.createElement('div'), { document, shortcuts: false,
      raf: { schedule: () => 1, cancel() {} } });
    try {
      chart.applySize(800, 600);
      const series = chart.addSeries('line');
      series.setData([{ time: 1, value: 100 }, { time: 2, value: 120 }]);
      series.priceScale().setPriceFormatter(value => `host:${value}`);
      const before = chart.getState();
      let reads = 0;
      const invalid = kind === 'side' ? { side: 'center', order: 0 }
        : kind === 'order' ? { side: 'right', order: -1 }
          : { get side() { reads++; return 'right'; }, order: 0 };
      const proposed = { ...before, grid: { vertLines: false, horzLines: false },
        panes: [pane(invalid)] };
      expect(chart.restoreState(proposed).applied).toBe(false);
      expect(reads).toBe(0);
      expect(chart.getState()).toEqual(before);
      expect(series.priceScale().format(100)).toBe('host:100');
    } finally { chart.destroy(); }
  });
});

describe('portable placement and old templates', () => {
  function workspace(value: unknown = placement()) {
    const input = workspaceFixture();
    return { ...input, panes: [{ ...input.panes[0], chart: { ...input.panes[0].chart, panes: [pane(value)] } }, input.panes[1]] };
  }

  it('preserves placement through the workspace JSON boundary', () => {
    const input = workspace();
    expect(parseWorkspaceDocument(JSON.stringify(input))).toEqual(input);
  });

  it.each([{ side: 'center', order: 0 }, { side: 'right', order: -1 }, { side: 'left', order: 1.5 }])(
    'rejects invalid workspace placement %j', value => {
      expect(() => parseWorkspaceDocument(workspace(value))).toThrow(WorkspaceDocumentError);
    },
  );

  it('keeps placement when a widget discards dataset-specific ranges and locks', () => {
    const parsed = parsePaneState(pane());
    const input = { version: 1, panes: [parsed], timezone: 'Asia/Kolkata' };
    const stripped = stripView(input);
    const secondary = stripped.panes?.[0].scales?.['overlay:comparison'];
    expect(secondary?.placement).toEqual(placement());
    expect(secondary?.autoScale).toBe(true);
    expect(secondary).not.toHaveProperty('range');
    expect(secondary).not.toHaveProperty('ratioLock');
    expect(secondary?.fixedRange).toEqual({ min: 1, max: 200 });
    expect(input.panes[0].scales?.['overlay:comparison']?.ratioLock).toBeDefined();
  });

  it('does not invent placement for old indicator-only templates', () => {
    const input = { kind: 'indicator-template', version: 1, id: 'legacy', name: 'Legacy', createdAt: 1, updatedAt: 1,
      indicators: [{ indicatorId: 'sma', settings: { length: 3 }, paneIndex: 0, priceScaleId: 'overlay:comparison' }] };
    expect(parseIndicatorTemplate(input)).toEqual(input);
  });
});
