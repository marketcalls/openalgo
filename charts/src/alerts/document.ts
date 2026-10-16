import { CONDITIONS } from './conditions';
import { normalizeDataVariant } from '../feed/data-variant';
import type { Alert, AlertsDocument } from './types';

const text = (value: unknown): boolean => typeof value === 'string' && value.trim().length > 0;

/** Runtime validation deliberately leaves the opaque host payload alone. */
export function validateAlert(alert: Alert): void {
  if (!text(alert.id)) throw new Error('Alert id must be nonempty');
  const source = alert.source;
  if (!source || !['price', 'indicator', 'barCondition', 'drawing'].includes(source.kind)) throw new Error('Unknown alert source');
  if (source.kind === 'barCondition' && !text(source.id)) throw new Error('Invalid bar condition id');
  if (source.kind === 'indicator' && (!text(source.instanceId) || !text(source.plotKey))) throw new Error('Invalid indicator source');
  if (source.kind === 'drawing' && (!text(source.drawingId) || (source.level !== undefined && !text(source.level))
    || (source.input !== undefined && (!source.input || !text(source.input.instanceId) || !text(source.input.plotKey))))) {
    throw new Error('Invalid drawing source');
  }
  if (source.kind === 'barCondition' ? alert.condition !== 'matches' : !CONDITIONS.includes(alert.condition)) throw new Error('Invalid source condition');
  if (source.kind === 'price' || source.kind === 'indicator') {
    const lower = source.kind === 'price' ? source.price : source.value;
    const upper = source.kind === 'price' ? source.upperPrice : source.upperValue;
    if (!Number.isFinite(lower) || (upper !== undefined && !Number.isFinite(upper))) throw new Error('Alert bounds must be finite');
    if ((alert.condition === 'enteringRange' || alert.condition === 'leavingRange') && (upper === undefined || upper < lower)) {
      throw new Error('Alert range requires ordered finite bounds');
    }
  }
  if (alert.policy !== 'onBarClose' && alert.policy !== 'onTouch') throw new Error('Unknown alert policy');
  if (alert.repeat !== 'once' && alert.repeat !== 'everyTime') throw new Error('Unknown alert repeat');
  if (!['armed', 'triggered', 'disabled', 'expired'].includes(alert.state)) throw new Error('Unknown alert state');
  if (!Number.isFinite(alert.cooldownSeconds) || alert.cooldownSeconds < 0) throw new Error('Invalid alert cooldown');
  if (typeof alert.title !== 'string' || (alert.message !== undefined && typeof alert.message !== 'string')) {
    throw new Error('Alert title and message must be text');
  }
  const scope = dataRecord(alert.scope);
  for (const key of ['symbol', 'exchange', 'interval']) {
    if (scope[key] !== undefined && typeof scope[key] !== 'string') throw new Error('Invalid alert scope');
  }
  // A variant this build cannot name would evaluate on some other series.
  if (scope.variant !== undefined) {
    try { normalizeDataVariant(dataRecord(scope.variant)); }
    catch { throw new Error('Invalid alert scope variant'); }
  }
  for (const key of ['expiresAt', 'lastTriggeredAt', 'lastTriggeredTime', 'lastClosedTime', 'lastTouchedTime'] as const) {
    if (alert[key] !== undefined && !Number.isFinite(alert[key])) throw new Error(`Invalid alert ${key}`);
  }
}

/** Detached configuration, retaining the runtime payload's identity. */
export function copyAlert(alert: Alert): Alert {
  return { ...alert, source: alert.source.kind === 'drawing'
    ? { ...alert.source, ...(alert.source.input ? { input: { ...alert.source.input } } : {}) }
    : { ...alert.source }, scope: { ...alert.scope, ...(alert.scope.variant ? { variant: { ...alert.scope.variant } } : {}) } };
}

function dataRecord(input: unknown): Record<string, unknown> {
  if (input === null || typeof input !== 'object' || Array.isArray(input)
    || ![Object.prototype, null].includes(Object.getPrototypeOf(input))) throw new Error('Alert document needs plain JSON records');
  for (const key of Reflect.ownKeys(input)) {
    const descriptor = Object.getOwnPropertyDescriptor(input, key)!;
    if (typeof key !== 'string' || !('value' in descriptor) || !descriptor.enumerable) throw new Error('Alert document needs JSON data properties');
  }
  return input as Record<string, unknown>;
}

function dataArray(input: unknown): unknown[] {
  if (!Array.isArray(input) || input.length > 100000 || Reflect.ownKeys(input).length !== input.length + 1) {
    throw new Error('Alert document array is not JSON data');
  }
  return Array.from({ length: input.length }, (_, i) => {
    const item = Object.getOwnPropertyDescriptor(input, String(i));
    if (!item || !('value' in item)) throw new Error('Alert document array needs JSON data values');
    return item.value;
  });
}

/** Validate before copying: JSON.stringify alone silently deletes or changes data. */
function jsonPayload(input: unknown): unknown {
  const ancestors = new Set<object>();
  let nodes = 0;
  let characters = 0;
  const visit = (value: unknown, depth: number): unknown => {
    if (++nodes > 100000 || depth > 32) throw new Error('Alert payload exceeds JSON limits');
    if (value === null || typeof value === 'boolean') return value;
    if (typeof value === 'string') {
      characters += value.length;
      if (characters > 5 * 1024 * 1024) throw new Error('Alert payload exceeds JSON size limit');
      return value;
    }
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value !== 'object') throw new Error('Alert payload must be finite JSON data');
    if (ancestors.has(value)) throw new Error('Alert payload contains a cycle');
    ancestors.add(value);
    let result: unknown;
    if (Array.isArray(value)) {
      result = dataArray(value).map(item => visit(item, depth + 1));
    } else {
      const record = dataRecord(value);
      const copy: Record<string, unknown> = {};
      for (const key of Object.keys(record)) {
        characters += key.length;
        if (characters > 5 * 1024 * 1024) throw new Error('Alert payload exceeds JSON size limit');
        Object.defineProperty(copy, key, { value: visit(record[key], depth + 1), enumerable: true, writable: true, configurable: true });
      }
      result = copy;
    }
    ancestors.delete(value);
    return result;
  };
  return visit(input, 0);
}

/** Validate and detach a version-1 document, or migrate a legacy bare list. */
export function parseAlertsDocument(input: unknown): AlertsDocument {
  if (typeof input === 'string') {
    if (input.length > 5 * 1024 * 1024) throw new Error('Alert document exceeds JSON size limit');
    input = JSON.parse(input);
  }
  const document = Array.isArray(input) ? { version: 1, alerts: input } : dataRecord(input);
  if (document.version !== 1 || !Array.isArray(document.alerts) || document.alerts.length > 10000) throw new Error('Unsupported alert document');
  const ids = new Set<string>();
  const alerts = dataArray(document.alerts).map(item => {
    const record = dataRecord(item);
    const source = dataRecord(record.source);
    if (source.input !== undefined) dataRecord(source.input);
    const fallback = (key: string, value: unknown): unknown => record[key] === undefined ? value : record[key];
    const scope = dataRecord(fallback('scope', {}));
    const alert = {
      id: record.id, source: { ...source }, condition: fallback('condition', source.kind === 'barCondition' ? 'matches' : 'crossing'),
      policy: fallback('policy', 'onBarClose'), repeat: fallback('repeat', 'once'), state: fallback('state', 'armed'),
      title: fallback('title', 'Chart alert'), cooldownSeconds: fallback('cooldownSeconds', 0),
      scope: jsonPayload(Object.fromEntries(Object.entries(scope).filter(([, value]) => value !== undefined))),
    } as unknown as Alert;
    for (const key of ['message', 'expiresAt', 'lastTriggeredAt', 'lastTriggeredTime', 'lastClosedTime', 'lastTouchedTime'] as const) {
      if (record[key] !== undefined) Object.assign(alert, { [key]: record[key] });
    }
    validateAlert(alert);
    if (ids.has(alert.id)) throw new Error(`Duplicate alert id: ${alert.id}`);
    ids.add(alert.id);
    // Optional configuration fields may be omitted; payload fields may never be lost.
    alert.source = jsonPayload(Object.fromEntries(Object.entries(alert.source).filter(([, value]) => value !== undefined))) as Alert['source'];
    if (record.payload !== undefined) alert.payload = jsonPayload(record.payload);
    return alert;
  });
  return { version: 1, alerts };
}
