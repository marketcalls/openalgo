import { describe, expect, it } from 'vitest';
import type { IndicatorState, IndicatorStudySource } from '../src/index';
import {
  parseIndicatorStates, parseIndicatorTemplate, parseWorkspacePayload, planIndicatorTemplate, WorkspaceDocumentError, WorkspaceRepository,
  type WorkspaceCatalog, type WorkspaceStorage,
} from '../src/workspace/index';
import { workspaceFixture } from './helpers/workspace-fixture';

type SavedStudy = IndicatorState & { studyInputs?: readonly string[] };
const ref = (instanceId: string, plotKey = 'ma'): IndicatorStudySource => ({ kind: 'indicator', instanceId, plotKey });
const study = (instanceId: string, patch: Partial<SavedStudy> = {}): SavedStudy => ({
  indicatorId: 'custom-average', instanceId, settings: { length: 2 }, paneIndex: 0, ...patch,
});
const graph = (): SavedStudy[] => [
  study('consumer', { studyInputs: ['source'], settings: { length: 2, source: ref('producer'),
    annotations: { source: ref('opaque-owner') } }, visible: false, priceScaleId: 'left' }),
  study('producer', { paneIndex: 2 }),
];
const document = (indicators: SavedStudy[]) => ({
  kind: 'indicator-template', version: 1, id: 'chain', name: 'Average chain', createdAt: 1, updatedAt: 1, indicators,
});
const available = new Set(['custom-average']);

describe('portable study dependency templates', () => {
  it('preserves graph identity and declared source metadata before template parsing could discard IDs', () => {
    const input = graph();
    const result = parseIndicatorTemplate(JSON.stringify(document(input))).indicators as SavedStudy[];
    expect(result).toEqual(input);
    expect(parseIndicatorTemplate(document(result)).indicators).toEqual(input);
    expect(parseIndicatorStates(input)).toEqual(input);
    (result[0].settings.source as { instanceId: string }).instanceId = 'changed';
    expect(input[0].settings.source).toEqual(ref('producer'));
  });

  it('keeps unresolved state references available for workspace recovery while rejecting external template references', () => {
    const state = [graph()[0]];
    expect(parseIndicatorStates(state)).toEqual(state);
    const workspace: ReturnType<typeof parseWorkspacePayload> = workspaceFixture();
    workspace.panes[0].chart.indicators = state;
    expect(parseWorkspacePayload(JSON.stringify(workspace)).panes[0].chart.indicators).toEqual(state);
    expect(() => parseIndicatorTemplate(document(state))).toThrow(/external|missing/i);
    expect(() => planIndicatorTemplate([study('producer')], state, 'append', available, 1)).toThrow(/external|missing/i);
  });

  it('keeps legacy copies anonymous and does not infer edges from arbitrary settings objects', () => {
    const input = [study('old', { settings: { source: ref('outside'), payload: [ref('also-outside')] } })];
    const result = parseIndicatorTemplate(document(input)).indicators;
    expect(result[0]).not.toHaveProperty('instanceId');
    expect(result[0].settings).toEqual(input[0].settings);
    expect(planIndicatorTemplate([], input, 'replace', available, 1)).toEqual(result);
  });

  it.each([
    { studyInputs: ['source', 'source'] },
    { studyInputs: [''] },
    { studyInputs: ['missing'] },
    { studyInputs: ['source'], settings: { source: 'close' } },
    { studyInputs: ['source'], settings: { source: { kind: 'series', instanceId: 'producer', plotKey: 'ma' } } },
    { studyInputs: ['source'], settings: { source: { kind: 'indicator', instanceId: '', plotKey: 'ma' } } },
    { studyInputs: ['source'], settings: { source: { kind: 'indicator', instanceId: 'producer', plotKey: '' } } },
  ])('rejects malformed portable source metadata before returning a plan (%j)', patch => {
    const input = graph(); Object.assign(input[0], patch);
    expect(() => parseIndicatorStates(input)).toThrow(WorkspaceDocumentError);
    expect(() => parseIndicatorTemplate(document(input))).toThrow(WorkspaceDocumentError);
    expect(() => planIndicatorTemplate([], input, 'replace', available, 1)).toThrow(WorkspaceDocumentError);
  });

  it('rejects self-links, cycles and duplicate graph identities without mutating input', () => {
    const self = [study('self', { studyInputs: ['source'], settings: { source: ref('self') } })];
    const cycle = [study('a', { studyInputs: ['source'], settings: { source: ref('b') } }),
      study('b', { studyInputs: ['source'], settings: { source: ref('a') } })];
    const duplicate = [...graph(), study('producer')];
    for (const input of [self, cycle, duplicate]) {
      const before = structuredClone(input);
      expect(() => parseIndicatorTemplate(document(input))).toThrow(WorkspaceDocumentError);
      expect(() => planIndicatorTemplate([], input, 'replace', available, 1)).toThrow(WorkspaceDocumentError);
      expect(input).toEqual(before);
    }
  });

  it('remaps only declared source keys and preserves reverse display order, styles, scales and pane groups', () => {
    const input = graph(), current = [study('existing', { paneIndex: 1 })];
    const before = structuredClone({ input, current });
    const result = planIndicatorTemplate(current, input, 'append', available, 3) as SavedStudy[];
    expect(result[0]).toEqual(current[0]);
    expect(result[1]).toMatchObject({ visible: false, priceScaleId: 'left', studyInputs: ['source'], paneIndex: 0 });
    expect(result[2].paneIndex).toBe(3);
    expect(result[1].instanceId).toBeTruthy(); expect(result[2].instanceId).toBeTruthy();
    expect(new Set(result.map(item => item.instanceId)).size).toBe(3);
    expect(input.map(item => item.instanceId)).not.toContain(result[1].instanceId);
    expect(input.map(item => item.instanceId)).not.toContain(result[2].instanceId);
    expect(result[1].settings.source).toEqual(ref(result[2].instanceId!));
    expect(result[1].settings.annotations).toEqual({ source: ref('opaque-owner') });
    expect({ input, current }).toEqual(before);
  });

  it('repeated append makes independent graphs and replacement never reuses existing alert anchors', () => {
    const incoming = graph();
    const once = planIndicatorTemplate([], incoming, 'append', available, 1);
    const twice = planIndicatorTemplate(once, incoming, 'append', available, 2);
    expect(twice.slice(0, 2)).toEqual(once);
    expect(new Set(twice.map(item => item.instanceId)).size).toBe(4);
    expect(twice[0].settings.source).toEqual(ref(twice[1].instanceId!));
    expect(twice[2].settings.source).toEqual(ref(twice[3].instanceId!));
    const replaced = planIndicatorTemplate(twice, incoming, 'replace', available, 1);
    for (const item of replaced) expect(twice.map(previous => previous.instanceId)).not.toContain(item.instanceId);
    expect(replaced[0].settings.source).toEqual(ref(replaced[1].instanceId!));
  });

  it('accepts anonymous consumers while requiring an identity for every referenced producer', () => {
    const incoming = graph(); delete incoming[0].instanceId;
    const result = planIndicatorTemplate([], incoming, 'replace', available, 1);
    expect(result[0].instanceId).toBeTruthy();
    expect(result[0].settings.source).toEqual(ref(result[1].instanceId!));
  });

  it('never reuses a removed graph identity when the current chart is empty', () => {
    const first = planIndicatorTemplate([], graph(), 'replace', available, 1);
    const later = planIndicatorTemplate([], graph(), 'replace', available, 1);
    const removed = new Set(first.map(item => item.instanceId));
    expect(later.every(item => !removed.has(item.instanceId))).toBe(true);
    expect(later[0].settings.source).toEqual(ref(later[1].instanceId!));
  });

  it('rewrites all declared inputs without acquiring an unavailable current producer identity', () => {
    const current = [study('retained', { studyInputs: ['source'], settings: { source: ref('template-study-1') } })];
    const incoming = [study('join', { studyInputs: ['first', 'second'],
      settings: { first: ref('left'), second: ref('right', 'signal'), opaque: ref('left') } }),
    study('left'), study('right')];
    const result = planIndicatorTemplate(current, incoming, 'append', available, 1);
    expect(result[0]).toEqual(current[0]);
    expect(result.slice(1).map(item => item.instanceId)).not.toContain('template-study-1');
    expect(result[1].settings.first).toEqual(ref(result[2].instanceId!));
    expect(result[1].settings.second).toEqual(ref(result[3].instanceId!, 'signal'));
    expect(result[1].settings.opaque).toEqual(ref('left'));
  });

  it('does not invoke reference or metadata accessors', () => {
    let calls = 0;
    const input = graph();
    input[0].settings.source = { kind: 'indicator', get instanceId() { calls++; return 'producer'; }, plotKey: 'ma' };
    expect(() => parseIndicatorTemplate(document(input))).toThrow(/accessor/i);
    expect(calls).toBe(0);
    input[0].settings.source = ref('producer');
    Object.defineProperty(input[0], 'studyInputs', { get() { calls++; return ['source']; }, enumerable: true });
    expect(() => planIndicatorTemplate([], input, 'replace', available, 1)).toThrow(/accessor/i);
    expect(calls).toBe(0);
  });

  it('retains graph metadata through create, save, duplicate, export, import and catalog reload', async () => {
    let stored: WorkspaceCatalog | null = null, id = 0;
    const storage: WorkspaceStorage = {
      async read() { return structuredClone(stored); },
      async write(_namespace, next) { stored = structuredClone(next); },
    };
    const repository = new WorkspaceRepository(storage, 'dependency-test', { id: () => `document-${++id}`, now: () => 1 });
    const created = await repository.createTemplate('Chain', graph());
    expect(created.indicators).toEqual(graph());
    await repository.saveTemplate(created.id, graph());
    await repository.duplicate('indicator-template', created.id, 'Copy');
    const text = await repository.exportDocument('indicator-template', created.id);
    await repository.importDocument(text);
    const catalog = await repository.load();
    expect(catalog.templates).toHaveLength(3);
    for (const item of catalog.templates) expect(item.indicators).toEqual(graph());
  });
});
