import { describe, expect, it } from 'vitest';
import {
  cloneIndicatorSettings, planIndicatorDependencies, type IndicatorDependencyNode,
} from '../src/model/indicator-dependencies';
import type { IndicatorDescriptor, IndicatorSettings, IndicatorStudySource } from '../src/model/indicator-registry';

type MutableStudySource = { -readonly [Key in keyof IndicatorStudySource]: IndicatorStudySource[Key] };
const reference = (instanceId: string, plotKey = 'value'): MutableStudySource => ({ kind: 'indicator', instanceId, plotKey });
function descriptor(allowStudyOutputs = true): IndicatorDescriptor {
  return {
    id: 'average', name: 'Average', placement: 'pane',
    inputs: [{ key: 'source', type: 'source', label: 'Source', default: 'close', allowStudyOutputs }],
    plots: [{ key: 'value', title: 'Value', type: 'line' }],
    calc: bars => ({ value: bars.map(bar => bar.close) }),
  };
}
const node = (id: string, source: unknown = 'close', d = descriptor()): IndicatorDependencyNode => ({ id, descriptor: d, settings: { source } });

describe('study dependency ordering', () => {
  it('keeps independent calculations in display order without changing its inputs', () => {
    const nodes = [node('c'), node('a'), node('b')];
    const result = planIndicatorDependencies(nodes);
    expect(result.order).toEqual(['c', 'a', 'b']);
    expect(nodes.map(item => item.id)).toEqual(['c', 'a', 'b']);
    expect([...result.dependencies]).toEqual([['c', []], ['a', []], ['b', []]]);
    expect(planIndicatorDependencies([]).order).toEqual([]);
  });

  it('orders a reversed chain by dependency and returns declared input references', () => {
    const result = planIndicatorDependencies([node('c', reference('b')), node('b', reference('a')), node('a')]);
    expect(result.order).toEqual(['a', 'b', 'c']);
    expect(result.dependencies.get('c')).toEqual([{ inputKey: 'source', source: reference('b'), available: true }]);
  });

  it('uses display order to break readiness ties in a diamond and schedules each producer once', () => {
    const d = descriptor();
    d.inputs = [...d.inputs, { key: 'other', type: 'source', label: 'Other', default: 'close', allowStudyOutputs: true }];
    const diamond = node('d', reference('b'), d); diamond.settings = { source: reference('b'), other: reference('c') };
    const result = planIndicatorDependencies([diamond, node('c', reference('a')), node('a'), node('b', reference('a'))]);
    expect(result.order).toEqual(['a', 'c', 'b', 'd']);
    expect(result.dependencies.get('d')?.map(edge => edge.source.instanceId)).toEqual(['b', 'c']);
  });

  it('does not double-count a producer selected by multiple inputs', () => {
    const d = descriptor(); d.inputs = [...d.inputs, { key: 'other', type: 'source', label: 'Other', default: 'close', allowStudyOutputs: true }];
    const consumer = node('b', reference('a'), d); consumer.settings = { source: reference('a'), other: reference('a') };
    const result = planIndicatorDependencies([consumer, node('a')]);
    expect(result.order).toEqual(['a', 'b']); expect(result.dependencies.get('b')).toHaveLength(2);
  });

  it('keeps missing producers as unavailable references without retargeting or blocking order', () => {
    const result = planIndicatorDependencies([node('consumer', reference('missing')), node('unrelated')]);
    expect(result.order).toEqual(['consumer', 'unrelated']);
    expect(result.dependencies.get('consumer')).toEqual([{ inputKey: 'source', source: reference('missing'), available: false }]);
    expect(planIndicatorDependencies([node('consumer', reference('missing')), node('missing')]).order).toEqual(['missing', 'consumer']);
  });

  it('supports a long chain without recursive graph traversal', () => {
    const nodes = Array.from({ length: 2_000 }, (_, i) => node(String(i), i === 0 ? 'close' : reference(String(i - 1))));
    const result = planIndicatorDependencies(nodes.slice().reverse());
    expect(result.order).toEqual(nodes.map(item => item.id));
  });
});

describe('study dependency validation', () => {
  it.each(['', ' '])('rejects an empty node identity (%j)', id => {
    expect(() => planIndicatorDependencies([node(id)])).toThrow(/id|identity/i);
  });

  it('rejects duplicate node identities before returning a graph', () => {
    expect(() => planIndicatorDependencies([node('a'), node('a')])).toThrow(/duplicate|unique/i);
  });

  it('rejects self references, two-node cycles and longer cycles with outgoing dependents', () => {
    expect(() => planIndicatorDependencies([node('a', reference('a'))])).toThrow(/self/i);
    expect(() => planIndicatorDependencies([node('a', reference('b')), node('b', reference('a'))])).toThrow(/cycle/i);
    expect(() => planIndicatorDependencies([
      node('tail', reference('a')), node('a', reference('b')), node('b', reference('c')), node('c', reference('a')), node('independent'),
    ])).toThrow(/cycle/i);
  });

  it('rejects references on inputs that did not opt in', () => {
    expect(() => planIndicatorDependencies([node('a'), node('b', reference('a'), descriptor(false))])).toThrow(/allow|support|source/i);
    const d = descriptor(); d.inputs = [{ key: 'source', type: 'text', label: 'Text', default: '' }];
    expect(() => planIndicatorDependencies([node('b', reference('missing'), d)])).toThrow(/allow|support|source/i);
    expect(() => planIndicatorDependencies([{ ...node('b'), settings: { undeclared: reference('missing') } }])).toThrow(/allow|support|source/i);
  });

  it.each([
    null, [], {}, { kind: 'other', instanceId: 'a', plotKey: 'value' },
    { kind: 'indicator', instanceId: '', plotKey: 'value' },
    { kind: 'indicator', instanceId: 'a', plotKey: ' ' },
    { kind: 'indicator', instanceId: 3, plotKey: 'value' },
    { kind: 'indicator', instanceId: 'a' },
    { kind: 'indicator', instanceId: 'a', plotKey: 'value', extra: true },
    { kind: 'indicator', instanceId: 'a', plotKey: 'value', [Symbol('hidden')]: true },
  ])('rejects malformed declared source references (%#)', source => {
    expect(() => planIndicatorDependencies([node('consumer', source)])).toThrow(/source|reference/i);
  });

  it('rejects missing and bar-shaped plots on known producers but accepts a separate scalar plot', () => {
    const producer = node('a'); producer.descriptor.plots = [
      { key: 'candle', title: 'Candle', type: 'candlestick', ohlc: { open: 'o', high: 'h', low: 'l', close: 'c' } },
      { key: 'scalar', title: 'Scalar', type: 'line', offset: 10, overlay: true },
    ];
    expect(() => planIndicatorDependencies([producer, node('b', reference('a', 'missing'))])).toThrow(/plot/i);
    expect(() => planIndicatorDependencies([producer, node('b', reference('a', 'candle'))])).toThrow(/scalar|ohlc|bar/i);
    expect(planIndicatorDependencies([node('b', reference('a', 'scalar')), producer]).order).toEqual(['a', 'b']);
  });

  it('preserves source defaults, legacy strings and unrelated settings objects', () => {
    const metadata = { kind: 'custom', value: 3 };
    const legacy = { ...node('a', 'legacy-source'), settings: { source: 'legacy-source', length: 2, metadata } };
    const missing = { ...node('b'), settings: {} };
    const result = planIndicatorDependencies([legacy, missing]);
    expect(result.order).toEqual(['a', 'b']);
    expect(result.dependencies.get('a')).toEqual([]); expect(result.dependencies.get('b')).toEqual([]);
    expect(cloneIndicatorSettings(legacy.settings).metadata).toBe(metadata);
  });

  it('does not partially mutate settings or a former plan when a proposed cycle is rejected', () => {
    const original = reference('a'); const first = [node('b', original), node('a')];
    const before = planIndicatorDependencies(first);
    expect(() => planIndicatorDependencies([first[0], node('a', reference('b'))])).toThrow(/cycle/i);
    expect(first[0].settings.source).toBe(original); expect(original).toEqual(reference('a'));
    expect(before.order).toEqual(['a', 'b']); expect(before.dependencies.get('b')?.[0].source).toEqual(reference('a'));
  });
});

describe('study reference ownership', () => {
  it('detaches accepted, planned and returned reference objects', () => {
    const source = reference('a'), incoming = { source };
    const accepted = cloneIndicatorSettings(incoming);
    const result = planIndicatorDependencies([node('a'), { ...node('b'), settings: accepted }]);
    const returned = cloneIndicatorSettings(accepted);
    source.instanceId = 'outside'; (returned.source as MutableStudySource).plotKey = 'outside';
    expect(accepted.source).toEqual(reference('a'));
    (accepted.source as MutableStudySource).instanceId = 'later';
    expect(result.dependencies.get('b')?.[0].source).toEqual(reference('a'));
    expect(returned.source).toEqual(reference('a', 'outside'));
  });

  it('handles special own property names and null prototypes as ordinary data', () => {
    const settings = Object.create(null) as IndicatorSettings;
    settings.__proto__ = reference('constructor', '__proto__');
    const producer = node('constructor'); producer.descriptor.plots = [{ key: '__proto__', title: 'Value', type: 'line' }];
    const consumer = node('__proto__'); consumer.settings = settings;
    consumer.descriptor.inputs = [{ key: '__proto__', type: 'source', label: 'Source', default: 'close', allowStudyOutputs: true }];
    const result = planIndicatorDependencies([consumer, producer]);
    expect(result.order).toEqual(['constructor', '__proto__']);
    const copy = cloneIndicatorSettings(settings);
    expect(Object.getPrototypeOf(copy)).toBe(Object.prototype);
    expect(Object.prototype.hasOwnProperty.call(copy, '__proto__')).toBe(true);
    expect(copy.__proto__).toEqual(reference('constructor', '__proto__'));
    const nullReference = Object.assign(Object.create(null), reference('constructor', '__proto__')) as IndicatorStudySource;
    expect(planIndicatorDependencies([producer, node('b', nullReference)]).dependencies.get('b')?.[0].available).toBe(true);
  });

  it('rejects inherited reference fields and settings prototypes instead of creating hidden edges', () => {
    expect(() => planIndicatorDependencies([node('b', Object.create(reference('missing')))])).toThrow(/source|reference|prototype/i);
    const settings = Object.create({ source: reference('missing') }) as IndicatorSettings;
    expect(() => cloneIndicatorSettings(settings)).toThrow(/settings|prototype/i);
  });

  it('rejects getters without executing them', () => {
    let reads = 0;
    const source = { kind: 'indicator', get instanceId() { reads++; return 'a'; }, plotKey: 'value' };
    expect(() => planIndicatorDependencies([node('b', source)])).toThrow(/data|accessor|reference/i);
    expect(() => cloneIndicatorSettings({ get source() { reads++; return reference('a'); } })).toThrow(/data|accessor|settings/i);
    expect(reads).toBe(0);
  });
});
