import { describe, expect, it } from 'vitest';
import type { IndicatorState, PriceScaleId } from '../src/index';
import {
  parseIndicatorStates, parseIndicatorTemplate, parseWorkspaceDocument, planIndicatorTemplate,
  WorkspaceDocumentError, WorkspaceRepository,
} from '../src/workspace/index';
import { workspaceFixture } from './helpers/workspace-fixture';

const study = (patch: Partial<IndicatorState> = {}): IndicatorState => ({
  indicatorId: 'ema', instanceId: 'original', settings: { period: 9 }, paneIndex: 0, visible: false, ...patch,
});

function template(indicators: unknown[]) {
  return { kind: 'indicator-template', version: 1, id: 'scales', name: 'Study scales', createdAt: 1, updatedAt: 1, indicators };
}

function workspace(indicators: unknown[]) {
  const input = workspaceFixture();
  return { ...input, panes: [{ ...input.panes[0], chart: { ...input.panes[0].chart, indicators } }, input.panes[1]] };
}

describe('portable indicator scale overrides', () => {
  it.each<PriceScaleId>(['right', 'left', '', 'overlay:', 'overlay:momentum', 'overlay: spaced '])(
    'retains the exact native scale ID %j in states, workspaces and templates', priceScaleId => {
      const input = study({ priceScaleId });
      expect(parseIndicatorStates([input])).toEqual([input]);
      expect(parseWorkspaceDocument(JSON.stringify(workspace([input]))).panes[0].chart.indicators).toEqual([input]);
      const copied = parseIndicatorTemplate(JSON.stringify(template([input]))).indicators;
      expect(copied).toEqual([{ indicatorId: 'ema', settings: { period: 9 }, paneIndex: 0, visible: false, priceScaleId }]);
      expect(copied[0]).not.toHaveProperty('instanceId');
      expect(input.instanceId).toBe('original');
    },
  );

  it('keeps legacy omission distinct from an explicit right-scale override', () => {
    const input = study();
    const state = parseIndicatorStates([input])[0];
    const saved = parseWorkspaceDocument(workspace([input])).panes[0].chart.indicators![0];
    const copied = parseIndicatorTemplate(template([input])).indicators[0];
    for (const item of [state, saved, copied]) expect(item).not.toHaveProperty('priceScaleId');
    expect(state).toEqual(input);
  });

  it('detaches the override and settings from the source state', () => {
    const input = study({ priceScaleId: 'left' });
    const parsed = parseIndicatorStates([input])[0];
    input.priceScaleId = 'right';
    input.settings.period = 99;
    expect(parsed).toMatchObject({ priceScaleId: 'left', settings: { period: 9 } });
  });

  it.each([null, 0, true, [], {}, 'center', 'RIGHT', ' left ', 'overlay', 'Overlay:study'].map(priceScaleId => ({ priceScaleId })))(
    'rejects malformed scale ID $priceScaleId at every document boundary without changing input', ({ priceScaleId }) => {
      const input = [{ ...study(), priceScaleId }];
      const before = structuredClone(input);
      expect(() => parseIndicatorStates(input)).toThrow(WorkspaceDocumentError);
      expect(() => parseWorkspaceDocument(workspace(input))).toThrow(WorkspaceDocumentError);
      expect(() => parseIndicatorTemplate(template(input))).toThrow(WorkspaceDocumentError);
      expect(input).toEqual(before);
    },
  );

  it.each(['replace', 'append'] as const)('keeps scale overrides while %s planning removes incoming instance identities', mode => {
    const current = [study({ priceScaleId: 'left' })];
    const incoming = [study({ instanceId: 'copied', paneIndex: 2, priceScaleId: 'overlay:signals' })];
    const result = planIndicatorTemplate(current, incoming, mode, new Set(['ema']), 1);
    expect(result[result.length - 1]).toEqual({ indicatorId: 'ema', paneIndex: mode === 'append' ? 1 : 2,
      settings: { period: 9 }, visible: false, priceScaleId: 'overlay:signals' });
    if (mode === 'append') expect(result[0]).toEqual(current[0]);
    expect(incoming[0].instanceId).toBe('copied');
    expect(incoming[0].paneIndex).toBe(2);
  });

  it('rejects an invalid template override before any repository storage operation', async () => {
    const calls: string[] = [];
    const repo = new WorkspaceRepository({
      async read() { calls.push('read'); return null; },
      async write() { calls.push('write'); },
    }, 'scale-test', { now: () => 1, id: () => 'template' });
    const malformed = [{ ...study(), priceScaleId: null }] as unknown as IndicatorState[];
    await expect(repo.createTemplate('Invalid', malformed)).rejects.toThrow(WorkspaceDocumentError);
    await expect(repo.saveTemplate('template', malformed)).rejects.toThrow(WorkspaceDocumentError);
    expect(calls).toEqual([]);
  });
});
