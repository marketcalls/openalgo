import { describe, expect, it } from 'vitest';
import type { IndicatorState } from '../src/index';
import { planIndicatorTemplate } from '../src/workspace/index';

const available = new Set(['ema', 'rsi', 'macd', 'custom-study']);
const study = (patch: Partial<IndicatorState> = {}): IndicatorState => ({
  indicatorId: 'ema', paneIndex: 0, settings: { period: 9, 'plot.ema.color': '#12abcd', 'plot.ema.width': 3 }, ...patch,
});

describe('indicator template planning', () => {
  it('replaces with separate equal instances, detached styles and retained visibility', () => {
    const entry = study({ visible: false });
    const result = planIndicatorTemplate([study({ indicatorId: 'rsi', paneIndex: 1 })], [entry, entry], 'replace', available, 2);
    expect(result).toEqual([entry, entry]);
    expect(result[0]).not.toBe(result[1]);
    result[0].settings.period = 20;
    expect(result[1].settings.period).toBe(9); expect(entry.settings.period).toBe(9);
  });

  it('preserves existing instance identities but never copies incoming alert anchors', () => {
    const current = study({ instanceId: 'existing' });
    const incoming = study({ instanceId: 'existing', settings: { period: 21 } });
    const result = planIndicatorTemplate([current], [incoming], 'append', available, 1);
    expect(result[0].instanceId).toBe('existing'); expect(result[1]).not.toHaveProperty('instanceId');
    expect(incoming.instanceId).toBe('existing');
  });

  it('moves sparse incoming pane groups after existing panes while keeping overlays on pane zero', () => {
    const incoming = [study({ indicatorId: 'rsi', paneIndex: 7 }), study({ indicatorId: 'custom-study', paneIndex: 7 }),
      study(), study({ indicatorId: 'macd', paneIndex: 2 })];
    const result = planIndicatorTemplate([study({ indicatorId: 'rsi', paneIndex: 1 })], incoming, 'append', available, 3);
    expect(result.map(item => item.paneIndex)).toEqual([1, 4, 4, 0, 3]);
    expect(incoming.map(item => item.paneIndex)).toEqual([7, 7, 0, 2]);
  });

  it('keeps incoming pane grouping during replacement and supports empty templates', () => {
    const current = [study({ instanceId: 'old' })];
    const grouped = [study({ indicatorId: 'rsi', paneIndex: 2 }), study({ indicatorId: 'macd', paneIndex: 2 })];
    expect(planIndicatorTemplate(current, grouped, 'replace', available, 1).map(item => item.paneIndex)).toEqual([2, 2]);
    expect(planIndicatorTemplate(current, [], 'replace', available, 1)).toEqual([]);
    expect(planIndicatorTemplate(current, [], 'append', available, 1)).toEqual(current);
  });

  it('reports all missing descriptors before returning a replacement without mutating either input', () => {
    const current = [study()], incoming = [study({ indicatorId: 'missing-a' }), study({ indicatorId: 'missing-b' })];
    const before = structuredClone({ current, incoming });
    expect(() => planIndicatorTemplate(current, incoming, 'replace', available, 1)).toThrow('Missing indicators: missing-a, missing-b');
    expect({ current, incoming }).toEqual(before);
    expect(planIndicatorTemplate([study({ indicatorId: 'old-missing' })], [], 'replace', available, 1)).toEqual([]);
  });

  it.each([0, -1, 1.5, 33, Number.NaN])('rejects invalid append boundaries (%s)', next => {
    expect(() => planIndicatorTemplate([], [study()], 'append', available, next)).toThrow(/pane/);
  });

  it('rejects overlap with existing study panes and pane overflow', () => {
    expect(() => planIndicatorTemplate([study({ paneIndex: 3 })], [study({ paneIndex: 1 })], 'append', available, 3)).toThrow(/pane/);
    expect(() => planIndicatorTemplate([], [study({ paneIndex: 1 })], 'append', available, 32)).toThrow(/pane/);
    expect(planIndicatorTemplate([], [study()], 'append', available, 32)).toHaveLength(1);
  });

  it('enforces the combined study limit and rejects unknown modes', () => {
    const full = Array.from({ length: 256 }, () => study());
    expect(planIndicatorTemplate([], full, 'replace', available, 1)).toHaveLength(256);
    expect(() => planIndicatorTemplate(full, [study()], 'append', available, 1)).toThrow(/256/);
    // @ts-expect-error Verify runtime validation for an untyped host.
    expect(() => planIndicatorTemplate([], [], 'merge', available, 1)).toThrow(/mode/);
  });

  it('rejects malformed settings without invoking accessor input', () => {
    let read = false;
    const incoming = study({ settings: { get period() { read = true; return 9; } } });
    expect(() => planIndicatorTemplate([], [incoming], 'replace', available, 1)).toThrow(/accessor/i);
    expect(read).toBe(false);
  });
});
