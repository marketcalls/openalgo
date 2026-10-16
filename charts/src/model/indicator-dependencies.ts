import type { IndicatorDescriptor, IndicatorSettings, IndicatorStudySource } from './indicator-registry';
import { isPlainObject } from '../helpers/validate';

/** A proposed chart state. Input order is display order, not calculation order. */
export interface IndicatorDependencyNode {
  id: string;
  descriptor: IndicatorDescriptor;
  settings: Readonly<IndicatorSettings>;
}

interface IndicatorDependencyEdge {
  inputKey: string;
  source: IndicatorStudySource;
  /** False retains a reference to a producer that is not currently attached. */
  available: boolean;
}

interface IndicatorDependencyPlan {
  order: readonly string[];
  dependencies: ReadonlyMap<string, readonly IndicatorDependencyEdge[]>;
}

function nonemptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

/** Inspect a discriminator without invoking application getters. */
function hasStudyKind(value: unknown): boolean {
  if (typeof value !== 'object' || value === null) return false;
  const kind = Object.getOwnPropertyDescriptor(value, 'kind');
  return kind !== undefined && 'value' in kind && kind.value === 'indicator';
}

function copyReference(value: unknown): IndicatorStudySource {
  if (!isPlainObject(value)) throw new TypeError('Study source reference must be a plain object.');
  const keys = Reflect.ownKeys(value);
  if (keys.length !== 3 || !keys.every(key => key === 'kind' || key === 'instanceId' || key === 'plotKey')) {
    throw new TypeError('Study source reference requires only kind, instanceId and plotKey.');
  }
  const kind = Object.getOwnPropertyDescriptor(value, 'kind');
  const instanceId = Object.getOwnPropertyDescriptor(value, 'instanceId');
  const plotKey = Object.getOwnPropertyDescriptor(value, 'plotKey');
  if (!kind || !instanceId || !plotKey || !('value' in kind) || !('value' in instanceId) || !('value' in plotKey)) {
    throw new TypeError('Study source reference fields must be own data properties.');
  }
  if (kind.value !== 'indicator' || !nonemptyString(instanceId.value) || !nonemptyString(plotKey.value)) {
    throw new TypeError('Study source reference requires nonempty instanceId and plotKey strings.');
  }
  return { kind: 'indicator', instanceId: instanceId.value, plotKey: plotKey.value };
}

/**
 * Copy ordinary enumerable settings and detach direct study references. Other
 * application values retain their ordinary shallow-copy semantics. Accessors
 * are rejected without executing them. Returned references remain mutable.
 */
export function cloneIndicatorSettings(settings: Readonly<IndicatorSettings>): IndicatorSettings {
  if (!isPlainObject(settings)) throw new TypeError('Indicator settings must be a plain object.');
  const result: IndicatorSettings = {};
  for (const key of Object.keys(settings)) {
    const property = Object.getOwnPropertyDescriptor(settings, key)!;
    if (!('value' in property)) throw new TypeError(`Indicator settings property "${key}" must be a data property.`);
    const value: unknown = property.value;
    Object.defineProperty(result, key, {
      value: hasStudyKind(value) ? copyReference(value) : value,
      writable: true, configurable: true, enumerable: true,
    });
  }
  return result;
}

/**
 * A min-heap keeps ready nodes in display order without repeated full scans.
 * Parents and children are read only below the heap's length.
 */
function enqueue(heap: number[], value: number): void {
  let index = heap.length;
  heap.push(value);
  while (index > 0) {
    const parent = (index - 1) >>> 1;
    if (heap[parent]! <= value) break;
    heap[index] = heap[parent]!;
    index = parent;
  }
  heap[index] = value;
}

/** The least node; the caller dequeues only from a heap that holds one. */
function dequeue(heap: number[]): number {
  const first = heap[0]!, last = heap.pop()!;
  if (heap.length === 0) return first;
  let index = 0;
  while (index * 2 + 1 < heap.length) {
    let child = index * 2 + 1;
    if (child + 1 < heap.length && heap[child + 1]! < heap[child]!) child++;
    if (heap[child]! >= last) break;
    heap[index] = heap[child]!;
    index = child;
  }
  heap[index] = last;
  return first;
}

/**
 * Validate a complete proposed graph before the caller mutates chart state.
 * Only opted-in source inputs create edges. Missing producers stay unavailable;
 * known producers must expose the selected scalar plot. Among ready nodes,
 * display order breaks ties. Neither nodes nor accepted settings are mutated.
 */
export function planIndicatorDependencies(nodes: readonly IndicatorDependencyNode[]): IndicatorDependencyPlan {
  const positions = new Map<string, number>();
  for (let i = 0; i < nodes.length; i++) {
    const id = nodes[i]!.id;
    if (!nonemptyString(id)) throw new TypeError('Indicator instance id must be a nonempty string.');
    if (positions.has(id)) throw new TypeError(`Duplicate indicator instance id "${id}".`);
    positions.set(id, i);
  }

  const dependencies = new Map<string, readonly IndicatorDependencyEdge[]>();
  const dependents = nodes.map(() => [] as number[]);
  const pending = nodes.map(() => 0);
  // `dependents`, `pending` and every position are indices into `nodes`.
  for (let i = 0; i < nodes.length; i++) {
    const node = nodes[i]!, settings = cloneIndicatorSettings(node.settings);
    for (const key of Object.keys(settings)) {
      if (hasStudyKind(settings[key]) && !node.descriptor.inputs.some(input =>
        input.key === key && input.type === 'source' && input.allowStudyOutputs === true)) {
        throw new TypeError(`Indicator "${node.id}" input "${key}" does not support study sources.`);
      }
    }
    const edges: IndicatorDependencyEdge[] = [], producers = new Set<number>();
    for (const input of node.descriptor.inputs) {
      if (input.type !== 'source') continue;
      const own = Object.getOwnPropertyDescriptor(settings, input.key);
      const value: unknown = own ? own.value : input.default;
      // Legacy strings retain their existing calculation fallback semantics.
      if (typeof value === 'string') continue;
      const source = copyReference(value);
      if (input.allowStudyOutputs !== true) {
        throw new TypeError(`Indicator "${node.id}" input "${input.key}" does not support study sources.`);
      }
      if (source.instanceId === node.id) throw new TypeError(`Indicator "${node.id}" cannot reference itself (self dependency).`);
      const producer = positions.get(source.instanceId);
      if (producer !== undefined) {
        const plots = nodes[producer]!.descriptor.plots.filter(plot => plot.key === source.plotKey);
        if (plots.length !== 1) throw new TypeError(`Study source plot "${source.plotKey}" must identify one declared plot on "${source.instanceId}".`);
        if (plots[0]!.ohlc !== undefined) throw new TypeError(`Study source plot "${source.plotKey}" must be scalar, without an OHLC mapping.`);
        producers.add(producer);
      }
      edges.push({ inputKey: input.key, source, available: producer !== undefined });
    }
    dependencies.set(node.id, edges);
    pending[i] = producers.size;
    for (const producer of producers) dependents[producer]!.push(i);
  }

  const ready: number[] = [], order: string[] = [];
  for (let i = 0; i < nodes.length; i++) if (pending[i] === 0) enqueue(ready, i);
  while (ready.length > 0) {
    const index = dequeue(ready);
    order.push(nodes[index]!.id);
    for (const dependent of dependents[index]!) {
      pending[dependent]!--;
      if (pending[dependent] === 0) enqueue(ready, dependent);
    }
  }
  if (order.length !== nodes.length) throw new TypeError('Study source references contain a dependency cycle.');
  return { order, dependencies };
}
