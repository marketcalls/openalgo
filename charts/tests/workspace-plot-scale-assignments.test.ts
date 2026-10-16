import { describe, expect, it } from 'vitest';
import type { IndicatorState, PriceScaleId } from '../src/index';
import {
  parseIndicatorStates, parseIndicatorTemplate, parseWorkspaceDocument, planIndicatorTemplate,
  WorkspaceRepository, WorkspaceDocumentError, type WorkspaceStorage,
} from '../src/workspace/index';
import { readJson } from '../src/workspace/json';
import { workspaceFixture } from './helpers/workspace-fixture';

type SavedStudy = IndicatorState & { plotPriceScaleIds?: Readonly<Record<string, PriceScaleId>> };
const study = (patch: Partial<SavedStudy> = {}): SavedStudy => ({
  indicatorId: 'unregistered-mixed-study', instanceId: 'source-study', settings: { length: 3 },
  paneIndex: 1, priceScaleId: 'left', ...patch,
});
const document = (indicators: SavedStudy[]) => ({ kind: 'indicator-template', version: 1,
  id: 'mixed', name: 'Mixed scales', createdAt: 1, updatedAt: 1, indicators });
const available = new Set(['unregistered-mixed-study']);

function repository(namespace: string) {
  let saved: string | null = null, next = 0, now = 100;
  const storage: WorkspaceStorage = {
    async read() { return saved === null ? null : JSON.parse(saved); },
    async write(_namespace, catalog) { saved = JSON.stringify(catalog); },
  };
  return new WorkspaceRepository(storage, namespace, { id: () => `copy-${namespace}-${++next}`, now: () => now++ });
}

describe('workspace per-plot scale assignments', () => {
  it('keeps exact arbitrary plot keys and valid scale IDs without a registry', () => {
    const assignments = Object.fromEntries([
      ['ordinary', 'right'], [' price overlay ', 'left'], ['', ''], ['ratio/band.1', 'overlay:'],
      ['token', 'overlay:token-scale'], ['account', 'overlay:account-scale'],
      ['constructor', 'overlay:constructor-scale'], ['__proto__', 'overlay:prototype-scale'],
    ]) as Record<string, PriceScaleId>;
    const input = study({ plotPriceScaleIds: assignments });
    const parsed = parseIndicatorStates([input])[0] as SavedStudy;
    expect(parsed.plotPriceScaleIds).toEqual(assignments);
    expect(parsed.priceScaleId).toBe('left');
    expect(Object.getPrototypeOf(parsed.plotPriceScaleIds)).toBe(Object.prototype);
    assignments.ordinary = 'left';
    expect(parsed.plotPriceScaleIds?.ordinary).toBe('right');
    expect(Object.prototype).not.toHaveProperty('polluted');
  });

  it('normalizes empty maps to omission and accepts null-prototype input records', () => {
    const entries = [study(), study({ instanceId: 'empty', plotPriceScaleIds: {} })];
    for (const entry of parseIndicatorStates(entries)) expect(entry).not.toHaveProperty('plotPriceScaleIds');
    const assignments = Object.assign(Object.create(null), { value: 'overlay:manual' }) as Record<string, PriceScaleId>;
    expect((parseIndicatorStates([study({ plotPriceScaleIds: assignments })])[0] as SavedStudy).plotPriceScaleIds)
      .toEqual({ value: 'overlay:manual' });
  });

  it.each([null, [], 'left', 1, true, { value: null }, { value: 1 }, { value: false },
    { value: {} }, { value: [] }, { value: 'center' }, { value: 'overlay' }, { value: ' right' }])(
    'rejects a malformed map or scale ID before returning a partial study (%#)', assignments => {
      const input = { ...study(), plotPriceScaleIds: assignments };
      expect(() => parseIndicatorStates([input])).toThrow(WorkspaceDocumentError);
      expect(() => parseIndicatorTemplate({ ...document([]), indicators: [input] })).toThrow(WorkspaceDocumentError);
    },
  );

  it('rejects prototypes and accessors without evaluating application code', () => {
    let reads = 0;
    const accessor = { get value() { reads++; return 'left'; } };
    const outer = { ...study(), get plotPriceScaleIds() { reads++; return { value: 'left' }; } };
    expect(() => parseIndicatorStates([{ ...study(), plotPriceScaleIds: accessor }])).toThrow(/accessor/i);
    expect(() => parseIndicatorStates([outer])).toThrow(/accessor/i);
    expect(() => parseIndicatorStates([{ ...study(), plotPriceScaleIds: Object.create({ value: 'left' }) }])).toThrow(/plain/i);
    expect(reads).toBe(0);
  });

  it('rejects map properties that cannot survive JSON without widening private-field retention', () => {
    const hidden = Object.defineProperty({ value: 'right' }, 'extra', { value: 'left' });
    const symbol = { value: 'right', [Symbol('plot')]: 'left' };
    for (const assignments of [hidden, symbol]) {
      expect(() => parseIndicatorStates([{ ...study(), plotPriceScaleIds: assignments }])).toThrow(/survive JSON/i);
    }
    expect(readJson({ ...study({ plotPriceScaleIds: { token: 'left' } }), token: 'private',
      settings: { token: 'private', nested: { plotPriceScaleIds: { token: 'left', value: 'right' } } },
    })).toEqual({ ...study({ plotPriceScaleIds: { token: 'left' } }),
      settings: { nested: { plotPriceScaleIds: { value: 'right' } } },
    });
    expect(() => readJson({ payload: study({ plotPriceScaleIds: { token: 'left' } }) })).toThrow(/private workspace field/i);
  });

  it('preserves detached maps through full workspace JSON and legacy templates', () => {
    const input = study({ plotPriceScaleIds: { line: 'left', candle: 'overlay:price' } });
    const workspace: ReturnType<typeof parseWorkspaceDocument> = workspaceFixture();
    workspace.panes[0].chart.indicators = [input];
    const parsed = parseWorkspaceDocument(JSON.stringify(workspace));
    expect(parsed.panes[0].chart.indicators?.[0]).toEqual(input);
    const template = parseIndicatorTemplate(JSON.stringify(document([input])));
    expect(template.indicators[0]).not.toHaveProperty('instanceId');
    expect((template.indicators[0] as SavedStudy).plotPriceScaleIds).toEqual(input.plotPriceScaleIds);
    const map = (parsed.panes[0].chart.indicators![0] as SavedStudy).plotPriceScaleIds as Record<string, PriceScaleId>;
    map.line = 'right';
    expect(input.plotPriceScaleIds?.line).toBe('left');
    expect((template.indicators[0] as SavedStudy).plotPriceScaleIds?.line).toBe('left');
  });

  it('keeps scale maps untouched while dependency templates remap study IDs and panes', () => {
    const incoming = [study({ instanceId: 'consumer', studyInputs: ['source'],
      settings: { source: { kind: 'indicator', instanceId: 'producer', plotKey: 'value' } },
      plotPriceScaleIds: { value: 'overlay:producer', price: 'right' } }),
    study({ instanceId: 'producer', paneIndex: 2, plotPriceScaleIds: { value: 'left' } })];
    const current = [study({ instanceId: 'existing', paneIndex: 0, plotPriceScaleIds: { value: '' } })];
    const parsed = parseIndicatorTemplate(document(incoming));
    const planned = planIndicatorTemplate(current, parsed.indicators, 'append', available, 1) as SavedStudy[];
    expect(planned.map(item => item.plotPriceScaleIds)).toEqual([current[0].plotPriceScaleIds, ...incoming.map(item => item.plotPriceScaleIds)]);
    expect(planned.map(item => item.paneIndex)).toEqual([0, 1, 2]);
    expect(planned[1].instanceId).not.toBe('consumer');
    expect(planned[2].instanceId).not.toBe('producer');
    expect(planned[1].settings.source).toEqual({ kind: 'indicator', instanceId: planned[2].instanceId, plotKey: 'value' });
    expect(planned[1].plotPriceScaleIds?.value).toBe('overlay:producer');
    (planned[1].plotPriceScaleIds as Record<string, PriceScaleId>).value = 'right';
    expect(incoming[0].plotPriceScaleIds?.value).toBe('overlay:producer');
  });

  it('round-trips real repository create, save, duplicate, export and import for templates and workspaces', async () => {
    const repo = repository('original'), importedRepo = repository('imported');
    const initial = study({ plotPriceScaleIds: { value: 'right' } });
    const created = await repo.createTemplate('Mixed', [initial]);
    expect((created.indicators[0] as SavedStudy).plotPriceScaleIds).toEqual(initial.plotPriceScaleIds);
    const expected = Object.fromEntries([
      ['value', 'overlay:manual'], ['token', 'left'], ['constructor', 'right'], ['__proto__', 'overlay:prototype'],
    ]) as Record<string, PriceScaleId>;
    const assignments = { ...expected };
    const updating = repo.saveTemplate(created.id, [study({ plotPriceScaleIds: assignments })]);
    assignments.value = 'right';
    const updated = await updating;
    expect((updated.indicators[0] as SavedStudy).plotPriceScaleIds).toEqual(expected);
    const copy = await repo.duplicate('indicator-template', created.id, 'Copy');
    const imported = await importedRepo.importDocument(await repo.exportDocument('indicator-template', copy.id));
    expect(imported.kind).toBe('indicator-template');
    if (imported.kind !== 'indicator-template') throw new Error('Expected a template document');
    expect(imported.indicators).toEqual(updated.indicators);

    const workspace: ReturnType<typeof parseWorkspaceDocument> = workspaceFixture(); workspace.panes[0].chart.indicators = [initial];
    const savedWorkspace = await repo.createWorkspace('Desk', workspace);
    workspace.panes[0].chart.indicators = [study({ plotPriceScaleIds: { value: '', price: 'overlay:external' } })];
    await repo.saveWorkspace(savedWorkspace.id, workspace);
    const importedWorkspace = await importedRepo.importDocument(await repo.exportDocument('workspace', savedWorkspace.id));
    if (importedWorkspace.kind !== 'workspace') throw new Error('Expected a workspace document');
    expect(importedWorkspace.panes[0].chart.indicators).toEqual(workspace.panes[0].chart.indicators);
    expect((await importedRepo.load()).workspaces[0].panes[0].chart.indicators).toEqual(workspace.panes[0].chart.indicators);
  });

  it('rejects a private-looking plot accessor before catalog writes without reading it', async () => {
    const repo = repository('accessors');
    const created = await repo.createTemplate('Original', [study({ plotPriceScaleIds: { value: 'left' } })]);
    const before = await repo.load();
    let reads = 0;
    const assignments = { get token(): PriceScaleId { reads++; return 'right'; } };
    await expect(repo.saveTemplate(created.id, [study({ plotPriceScaleIds: assignments })])).rejects.toThrow(/accessor/i);
    expect(reads).toBe(0);
    expect(await repo.load()).toEqual(before);
  });
});
