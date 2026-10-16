/** Bounded JSON at the persistence boundary; no callbacks or accessors run. */
import { isPriceScaleId } from '../model/price-axis-layout';

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
const MAX_DOCUMENT_BYTES = 5 * 1024 * 1024;

export class WorkspaceDocumentError extends Error {
  constructor(message: string) { super(message); this.name = 'WorkspaceDocumentError'; }
}

const privateKeys = new Set([
  '__proto__', 'prototype', 'constructor', 'apikey', 'secret', 'clientsecret', 'apisecret',
  'password', 'passwordhash', 'token', 'accesstoken', 'refreshtoken', 'authtoken', 'authorization',
  'credentials', 'credential', 'auth', 'armed', 'oneclick', 'orders', 'positions', 'balances',
  'balance', 'accountbalance', 'accountid', 'account',
]);

export function readJson(input: unknown): Json {
  if (typeof input === 'string') {
    if (input.length > MAX_DOCUMENT_BYTES || new TextEncoder().encode(input).length > MAX_DOCUMENT_BYTES) {
      throw new WorkspaceDocumentError('Document size limit exceeded');
    }
    try { input = JSON.parse(input); }
    catch { throw new WorkspaceDocumentError('Invalid document JSON'); }
  }
  let nodes = 0;
  let characters = 0;
  const ancestors = new Set<object>();
  const visit = (value: unknown, depth: number, opaque = false, plotScales = false): Json => {
    if (++nodes > 100000) throw new WorkspaceDocumentError('Document node limit exceeded');
    if (depth > 32) throw new WorkspaceDocumentError('Document depth limit exceeded');
    if (value === null || typeof value === 'boolean') return value;
    if (typeof value === 'string') {
      characters += value.length;
      if (characters > MAX_DOCUMENT_BYTES) throw new WorkspaceDocumentError('Document size limit exceeded');
      return value;
    }
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value !== 'object') throw new WorkspaceDocumentError('Document values must be finite JSON data');
    if (ancestors.has(value)) throw new WorkspaceDocumentError('Document contains a cycle');
    if (!Array.isArray(value) && ![Object.prototype, null].includes(Object.getPrototypeOf(value))) {
      throw new WorkspaceDocumentError('Document objects must be plain records');
    }
    if (opaque || plotScales) {
      for (const key of Reflect.ownKeys(value)) {
        if (Array.isArray(value) && key === 'length') continue;
        const property = Object.getOwnPropertyDescriptor(value, key)!;
        if (typeof key !== 'string' || !property.enumerable
          || (Array.isArray(value) && (!/^(0|[1-9]\d*)$/.test(key) || Number(key) >= value.length))) {
          throw new WorkspaceDocumentError(`${plotScales ? 'Plot scale map' : 'Opaque payload'} properties must survive JSON`);
        }
      }
    }
    ancestors.add(value);
    let result: Json;
    if (Array.isArray(value)) {
      if (value.length > 100000) throw new WorkspaceDocumentError('Document array limit exceeded');
      const out: Json[] = [];
      for (let i = 0; i < value.length; i++) {
        const descriptor = Object.getOwnPropertyDescriptor(value, String(i));
        if (!descriptor || !('value' in descriptor)) throw new WorkspaceDocumentError('Document arrays must contain data values');
        out.push(visit(descriptor.value, depth + 1, opaque));
      }
      result = out;
    } else {
      const out: Record<string, Json> = {};
      const settings = Object.getOwnPropertyDescriptor(value, 'settings')?.value;
      const indicator = !opaque && typeof Object.getOwnPropertyDescriptor(value, 'indicatorId')?.value === 'string'
        && typeof Object.getOwnPropertyDescriptor(value, 'paneIndex')?.value === 'number'
        && settings !== null && typeof settings === 'object' && !Array.isArray(settings);
      for (const key of Object.keys(value)) {
        const normalized = key.toLowerCase().replace(/[^a-z0-9_]/g, '').replace(/_/g, '');
        if (!plotScales && (privateKeys.has(key) || privateKeys.has(normalized))) {
          if (opaque) throw new WorkspaceDocumentError('Opaque payload contains a private workspace field');
          continue;
        }
        characters += key.length;
        if (characters > MAX_DOCUMENT_BYTES) throw new WorkspaceDocumentError('Document size limit exceeded');
        const descriptor = Object.getOwnPropertyDescriptor(value, key)!;
        if (!('value' in descriptor)) throw new WorkspaceDocumentError('Document accessors are not allowed');
        if (plotScales && !isPriceScaleId(descriptor.value)) {
          throw new WorkspaceDocumentError('Invalid indicator plot priceScaleId');
        }
        // Plot names are descriptor-owned keys, including names also used for private
        // workspace fields. Only this flat, validated scale map keeps those names.
        const copied = visit(descriptor.value, depth + 1, opaque || key === 'payload', indicator && key === 'plotPriceScaleIds');
        if (plotScales) Object.defineProperty(out, key, { value: copied, enumerable: true, configurable: true, writable: true });
        else out[key] = copied;
      }
      result = out;
    }
    ancestors.delete(value);
    return result;
  };
  const result = visit(input, 0);
  if (new TextEncoder().encode(JSON.stringify(result)).length > MAX_DOCUMENT_BYTES) {
    throw new WorkspaceDocumentError('Document size limit exceeded');
  }
  return result;
}

export function record(input: Json | undefined, label: string): Record<string, Json> {
  if (input === null || typeof input !== 'object' || Array.isArray(input)) throw new WorkspaceDocumentError(`${label} must be an object`);
  return input;
}

export function list(input: Json | undefined, label: string, max: number): Json[] {
  if (!Array.isArray(input) || input.length > max) throw new WorkspaceDocumentError(`${label} must be an array within the ${max} item limit`);
  return input;
}

export function string(input: Json | undefined, label: string, max = 200, empty = false): string {
  if (typeof input !== 'string' || (!empty && input.trim().length === 0) || input.length > max || Array.from(input).some(char => char.charCodeAt(0) < 32)) {
    throw new WorkspaceDocumentError(`${label} must be ${empty ? '0' : '1'}-${max} characters`);
  }
  return input.trim();
}

export function number(input: Json | undefined, label: string, min: number, max = Number.MAX_SAFE_INTEGER, integer = false): number {
  if (typeof input !== 'number' || !Number.isFinite(input) || input < min || input > max || (integer && !Number.isInteger(input))) {
    throw new WorkspaceDocumentError(`${label} must be ${integer ? 'an integer' : 'a number'} between ${min} and ${max}`);
  }
  return input;
}

export function boolean(input: Json | undefined, label: string, fallback?: boolean): boolean {
  if (input === undefined && fallback !== undefined) return fallback;
  if (typeof input !== 'boolean') throw new WorkspaceDocumentError(`${label} must be a boolean`);
  return input;
}

export function choice<T extends string>(input: Json | undefined, label: string, values: readonly T[], fallback?: T): T {
  if (input === undefined && fallback !== undefined) return fallback;
  if (typeof input !== 'string' || !values.includes(input as T)) throw new WorkspaceDocumentError(`${label} is not supported`);
  return input as T;
}
