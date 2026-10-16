import { describe, expect, it } from 'vitest';
import type { IndicatorState, PaneState, PriceScaleState } from '../src/index';
import {
  parseIndicatorTemplate, parseIndicatorTemplatePayload, WorkspaceDocumentError,
} from '../src/workspace/documents';
import { WorkspaceRepository, type WorkspaceStorage } from '../src/workspace/repository';

const scale = (patch: Partial<PriceScaleState> = {}): PriceScaleState => ({
  marginTop: 0.1, marginBottom: 0.2, minMove: 0.01, minPrecision: 3,
  mode: 'linear', inverted: false, autoScale: false,
  range: { min: -20, max: 80 }, fixedRange: null,
  ratioLock: { barSpacing: 8, height: 300 }, placement: { side: 'right', order: 0 }, ...patch,
});

function payload() {
  const indicators: IndicatorState[] = [
    { indicatorId: 'unregistered-source', instanceId: 'source', settings: { length: 5 }, paneIndex: 1,
      priceScaleId: 'left', plotPriceScaleIds: { value: 'left', price: 'overlay:shared' } },
    { indicatorId: 'unregistered-consumer', instanceId: 'consumer', paneIndex: 1, studyInputs: ['source'],
      settings: { source: { kind: 'indicator', instanceId: 'source', plotKey: 'value' } } },
  ];
  const panes: PaneState[] = [
    { weight: 3, priceScale: scale(), scales: {
      left: scale({ placement: { side: 'left', order: 0 } }),
      'overlay:shared': scale({ placement: { side: 'right', order: 1 } }),
    } },
    { weight: 1, priceScale: scale(), scales: {
      left: scale({ placement: { side: 'left', order: 0 }, fixedRange: { min: 0, max: 100 },
        indicatorRange: { instanceId: 'source', manual: true } }),
      '': scale({ placement: { side: 'hidden', order: 0 } }),
    } },
  ];
  return { indicators, layout: { panes, primaryScaleId: 'left' as const, plots: [
    { instanceId: 'source', plotKey: 'value', paneIndex: 1, scaleId: 'left' as const },
    { instanceId: 'source', plotKey: 'price', paneIndex: 0, scaleId: 'overlay:shared' as const },
    { instanceId: 'consumer', plotKey: 'value', paneIndex: 1, scaleId: 'right' as const },
  ] } };
}

const document = (input = payload()) => ({ kind: 'indicator-template', version: 1,
  id: 'layout', name: 'Study layout', createdAt: 1, updatedAt: 1, ...input });

function repository(namespace: string) {
  let saved: string | null = null, next = 0, now = 100, writes = 0;
  const storage: WorkspaceStorage = {
    async read() { return saved === null ? null : JSON.parse(saved); },
    async write(_namespace, catalog) { writes++; saved = JSON.stringify(catalog); },
  };
  return { repo: new WorkspaceRepository(storage, namespace, { id: () => `${namespace}-${++next}`, now: () => now++ }),
    writes: () => writes };
}

describe('indicator template layout documents', () => {
  it('keeps detached pane, scale, ownership and effective plot relationships without a registry', () => {
    const input = payload();
    expect(parseIndicatorTemplate(document(input))).toEqual(document(input));
    const parsed = parseIndicatorTemplatePayload(JSON.stringify(input));
    expect(parsed).toEqual(input);
    input.layout.panes[1].scales!.left!.range!.min = -10;
    input.indicators[0].settings.length = 20;
    input.layout.plots[0].plotKey = 'changed';
    expect(parsed.layout!.panes[1].scales!.left!.range!.min).toBe(-20);
    expect(parsed.indicators[0].settings.length).toBe(5);
    expect(parsed.layout!.plots[0].plotKey).toBe('value');
  });

  it('requires identities for rich independent studies but preserves anonymous legacy copies', () => {
    const input = payload();
    input.indicators[1].studyInputs = [];
    input.indicators[1].settings = {};
    expect(parseIndicatorTemplatePayload(input).indicators.map(item => item.instanceId)).toEqual(['source', 'consumer']);
    for (const legacy of [input.indicators, { indicators: input.indicators }]) {
      expect(parseIndicatorTemplatePayload(legacy).indicators.every(item => item.instanceId === undefined)).toBe(true);
    }
    delete input.indicators[1].instanceId;
    expect(() => parseIndicatorTemplatePayload(input)).toThrow(/instance|identit/i);
  });

  it('retains exact arbitrary plot keys as values and map keys through stored catalogs', async () => {
    const input = payload();
    const keys = ['', ' value ', 'token', 'constructor', '__proto__', 'value\u0000tail'];
    input.indicators[0].plotPriceScaleIds = Object.fromEntries(keys.map(key => [key, 'left']));
    input.layout.plots = keys.map(plotKey => ({ instanceId: 'source', plotKey, paneIndex: 1, scaleId: 'left' }));
    const { repo } = repository('exact');
    const saved = await repo.createTemplate('Exact plots', input);
    const restored = parseIndicatorTemplate(await repo.exportDocument('indicator-template', saved.id));
    expect(restored.layout!.plots.map(binding => binding.plotKey)).toEqual(keys);
    expect(Object.keys(restored.indicators[0].plotPriceScaleIds!)).toEqual(keys);
    expect(Object.getPrototypeOf(restored.indicators[0].plotPriceScaleIds)).toBe(Object.prototype);
  });

  it('accepts primitive-only, empty, shared-scale and unnamed-overlay layouts', () => {
    const input = payload();
    delete input.indicators[0].plotPriceScaleIds;
    input.layout.plots = [];
    expect(parseIndicatorTemplatePayload(input).layout!.plots).toEqual([]);
    expect(parseIndicatorTemplatePayload({ indicators: [], layout: { panes: [input.layout.panes[0]], plots: [] } }))
      .toEqual({ indicators: [], layout: { panes: [input.layout.panes[0]], plots: [] } });
    const shared = payload();
    shared.layout.plots[2].scaleId = 'left';
    expect(parseIndicatorTemplatePayload(shared).layout!.plots[2].scaleId).toBe('left');
    const overlay = { ...input, layout: { ...input.layout, plots: [{ instanceId: 'source', plotKey: 'hidden', paneIndex: 1, scaleId: '' }] } };
    expect(parseIndicatorTemplatePayload(overlay).layout!.plots[0].scaleId).toBe('');
  });

  it('round-trips the pane limit and optional hidden primary relationship without changing plot names', () => {
    const input = payload();
    while (input.layout.panes.length < 32) input.layout.panes.push({ weight: 1, priceScale: scale() });
    input.indicators[1].paneIndex = 31;
    input.layout.plots[2].paneIndex = 31;
    input.layout.panes[31].priceScale.range = { min: -Number.MAX_SAFE_INTEGER, max: Number.MAX_SAFE_INTEGER };
    input.layout.panes[0].scales![''] = scale({ placement: { side: 'hidden', order: 0 } });
    const hidden = { ...input, layout: { ...input.layout, primaryScaleId: '' } };
    expect(parseIndicatorTemplatePayload(JSON.stringify(hidden))).toEqual(hidden);
    const optional = { ...input, layout: { panes: input.layout.panes, plots: input.layout.plots } };
    expect(parseIndicatorTemplatePayload(optional)).toEqual(optional);
  });

  it.each([
    ['duplicate study ID', (value: ReturnType<typeof payload>) => { value.indicators[1].instanceId = 'source'; }],
    ['external dependency', value => { value.indicators[1].settings.source = { kind: 'indicator', instanceId: 'outside', plotKey: 'value' }; }],
    ['self dependency', value => { value.indicators[1].settings.source = { kind: 'indicator', instanceId: 'consumer', plotKey: 'value' }; }],
    ['dependency cycle', value => { value.indicators[0].studyInputs = ['source']; value.indicators[0].settings.source = { kind: 'indicator', instanceId: 'consumer', plotKey: 'value' }; }],
    ['unknown binding study', value => { value.layout.plots[0].instanceId = 'outside'; }],
    ['duplicate binding', value => { value.layout.plots.push({ ...value.layout.plots[0] }); }],
    ['missing plot override binding', value => { value.layout.plots.shift(); }],
    ['mismatched plot override scale', value => { value.indicators[0].plotPriceScaleIds = { value: 'right', price: 'overlay:shared' }; }],
    ['missing binding scale', value => { delete value.layout.panes[0].scales!['overlay:shared']; }],
    ['missing primary scale', value => { delete value.layout.panes[0].scales!.left; }],
    ['unrelated binding pane', value => { value.layout.panes.push({ weight: 1, priceScale: scale() }); value.layout.plots[0].paneIndex = 2; }],
    ['missing study pane', value => { value.indicators[1].paneIndex = 2; }],
    ['dangling range owner', value => { value.layout.panes[1].scales!.left!.indicatorRange!.instanceId = 'outside'; }],
    ['too many panes', value => { value.layout.panes = Array.from({ length: 33 }, () => ({ weight: 1, priceScale: scale() })); }],
    ['zero pane weight', value => { value.layout.panes[0].weight = 0; }],
    ['zero-width range', value => { value.layout.panes[0].priceScale.range = { min: 1, max: 1 }; }],
    ['unbounded range', value => { value.layout.panes[0].priceScale.range = { min: 0, max: Number.MAX_VALUE }; }],
  ] satisfies [string, (value: ReturnType<typeof payload>) => void][])(
    'rejects %s before returning a partial document', (_label, mutate) => {
      const input = payload(); mutate(input);
      expect(() => parseIndicatorTemplatePayload(input)).toThrow(WorkspaceDocumentError);
      expect(() => parseIndicatorTemplate(document(input))).toThrow(WorkspaceDocumentError);
    },
  );

  it.each([null, [], 1, {}, { panes: [], plots: [] }, { panes: [scale()], plots: [] }])(
    'rejects malformed layout structure (%#)', layout => {
      expect(() => parseIndicatorTemplatePayload({ indicators: [], layout })).toThrow(WorkspaceDocumentError);
    },
  );

  it('rejects binding accessors and non-JSON pane state without executing getters', () => {
    const input = payload(); let reads = 0;
    Object.defineProperty(input.layout.plots[0], 'scaleId', { enumerable: true, get() { reads++; return 'left'; } });
    expect(() => parseIndicatorTemplatePayload(input)).toThrow(/accessor/i);
    expect(reads).toBe(0);
    expect(() => parseIndicatorTemplatePayload({ ...payload(), layout: new Date() })).toThrow(/plain/i);
  });

  it('creates, updates, duplicates, exports and imports the complete detached payload', async () => {
    const { repo } = repository('original'), imported = repository('imported').repo;
    const initial = payload();
    const creating = repo.createTemplate('Saved layout', initial);
    initial.layout.panes[1].weight = 99;
    const created = await creating;
    expect(created.layout!.panes[1].weight).toBe(1);
    const next = payload(); next.layout.panes[1].weight = 2;
    const saved = await repo.saveTemplate(created.id, next);
    expect(saved.id).toBe(created.id);
    expect(saved.layout).toEqual(next.layout);
    const copy = await repo.duplicate('indicator-template', saved.id, 'Copy');
    expect(copy.kind).toBe('indicator-template');
    if (copy.kind !== 'indicator-template') throw new Error('Expected an indicator template');
    expect(copy.id).not.toBe(saved.id);
    expect(copy.indicators).toEqual(saved.indicators);
    expect(copy.layout).toEqual(saved.layout);
    const restored = await imported.importDocument(await repo.exportDocument('indicator-template', copy.id));
    if (restored.kind !== 'indicator-template') throw new Error('Expected an indicator template');
    expect(restored.indicators).toEqual(saved.indicators);
    expect(restored.layout).toEqual(saved.layout);
    restored.layout!.panes[1].weight = 100;
    expect((await imported.load()).templates[0].layout!.panes[1].weight).toBe(2);
  });

  it('drops a previous layout when saving legacy independent or dependency arrays', async () => {
    const { repo } = repository('legacy');
    const created = await repo.createTemplate('Saved layout', payload());
    const independent = [{ indicatorId: 'ordinary', instanceId: 'original', settings: {}, paneIndex: 0 }];
    const saved = await repo.saveTemplate(created.id, independent);
    expect(saved).not.toHaveProperty('layout');
    expect(saved.indicators[0]).not.toHaveProperty('instanceId');
    await repo.saveTemplate(created.id, payload());
    const connected = payload().indicators;
    const next = await repo.saveTemplate(created.id, connected);
    expect(next).not.toHaveProperty('layout');
    expect(next.indicators).toEqual(connected);
    expect((await repo.load()).templates[0]).not.toHaveProperty('layout');
  });

  it('leaves stored catalog bytes and revision untouched for invalid saves or imports', async () => {
    const { repo, writes } = repository('rejected');
    const created = await repo.createTemplate('Saved layout', payload());
    const before = await repo.load(), count = writes();
    const invalid = payload(); invalid.layout.plots[0].instanceId = 'outside';
    await expect(repo.saveTemplate(created.id, invalid)).rejects.toThrow(WorkspaceDocumentError);
    await expect(repo.importDocument(document(invalid))).rejects.toThrow(WorkspaceDocumentError);
    expect(writes()).toBe(count);
    expect(await repo.load()).toEqual(before);
  });
});
