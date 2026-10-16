import { expect } from 'vitest';
import type { Bar } from '../../src/model/bar';
import type { ControlledTransport } from './controlled-transport';

export interface AdapterSnapshot {
  readonly bars: readonly Bar[];
  readonly status: 'idle' | 'loading' | 'ready' | 'empty' | 'refreshing' | 'stale' | 'error' | 'unsupported';
  readonly interval: string;
  readonly error?: string;
}

export interface AdapterFixtures {
  readonly interval: string;
  readonly nextInterval: string;
  readonly initialBars: readonly Bar[];
  readonly repairedBars: readonly Bar[];
  readonly duplicatePayload: unknown;
  readonly repairPayload: unknown;
  readonly invalidPayload: unknown;
  readonly providerErrorPayload: unknown;
}

export interface AdapterHarness {
  readonly transport: ControlledTransport;
  readonly fixtures: AdapterFixtures;
  readonly publications: AdapterSnapshot[];
  load(interval?: string): Promise<void>;
  refresh(): Promise<void>;
  snapshot(): AdapterSnapshot;
  destroy(): void;
}

export interface AdapterReference {
  readonly name: string;
  readonly evidence: 'synthetic';
  create(): AdapterHarness;
}

export async function loadInitial(harness: AdapterHarness): Promise<void> {
  const work = harness.load();
  (await harness.transport.request(0)).reply(harness.fixtures.duplicatePayload);
  await work;
}

export async function duplicateHistory(harness: AdapterHarness): Promise<void> {
  await loadInitial(harness);
  const snapshot = harness.snapshot();
  expect(snapshot.status).toBe('ready');
  expect(snapshot.interval).toBe(harness.fixtures.interval);
  expect(snapshot.bars, 'history must be sorted, unique and preserve the winning values').toEqual(harness.fixtures.initialBars);
  expect(new Set(snapshot.bars.map(bar => bar.time)).size).toBe(snapshot.bars.length);
  for (const bar of snapshot.bars) expect(Number.isSafeInteger(bar.time)).toBe(true);
}

export async function authoritativeRepair(harness: AdapterHarness): Promise<void> {
  await loadInitial(harness);
  const work = harness.refresh();
  (await harness.transport.request(1)).reply(harness.fixtures.repairPayload);
  await work;
  expect(harness.snapshot().status).toBe('ready');
  expect(harness.snapshot().bars, 'an authoritative closed-bar repair must replace stale values').toEqual(harness.fixtures.repairedBars);
}

export const adapterContractChecks: ReadonlyArray<{
  name: string;
  run(harness: AdapterHarness): Promise<void>;
}> = [
  { name: 'normalizes duplicate history to ascending UTC-second candles', run: duplicateHistory },
  { name: 'replaces closed candles with authoritative repairs', run: authoritativeRepair },
  {
    name: 'rejects an initial HTTP failure without fabricating history',
    async run(harness) {
      const work = harness.load();
      (await harness.transport.request(0)).reply({}, 503);
      await work;
      expect(harness.snapshot()).toMatchObject({ status: 'error', bars: [] });
      expect(harness.snapshot().error).toContain('503');
    },
  },
  ...(['network', 'http', 'provider', 'invalid-candle'] as const).map(failure => ({
    name: `keeps history stale after ${failure} failure and clears the error on retry`,
    async run(harness: AdapterHarness) {
      await loadInitial(harness);
      const before = harness.snapshot().bars.map(bar => ({ ...bar }));
      const work = harness.refresh();
      const request = await harness.transport.request(1);
      if (failure === 'network') request.fail(new Error('Synthetic transport offline'));
      else if (failure === 'http') request.reply({}, 429);
      else request.reply(failure === 'provider' ? harness.fixtures.providerErrorPayload : harness.fixtures.invalidPayload);
      await work;
      expect(harness.snapshot().status).toBe('stale');
      expect(harness.snapshot().error).toBeTruthy();
      expect(harness.snapshot().bars).toEqual(before);
      const retry = harness.refresh();
      (await harness.transport.request(2)).reply(harness.fixtures.repairPayload);
      await retry;
      expect(harness.snapshot()).toMatchObject({ status: 'ready', bars: harness.fixtures.repairedBars });
      expect(harness.snapshot().error).toBeUndefined();
    },
  })),
  {
    name: 'aborts an obsolete interval request and ignores its late response',
    async run(harness) {
      const first = harness.load();
      const obsolete = await harness.transport.request(0);
      const second = harness.load(harness.fixtures.nextInterval);
      const current = await harness.transport.request(1);
      expect(obsolete.init.signal?.aborted, 'context change must reach the transport signal').toBe(true);
      current.reply(harness.fixtures.repairPayload);
      await second;
      const before = harness.snapshot();
      const publications = harness.publications.length;
      obsolete.reply(harness.fixtures.duplicatePayload);
      await first;
      expect(harness.snapshot()).toEqual(before);
      expect(harness.snapshot().interval).toBe(harness.fixtures.nextInterval);
      expect(harness.snapshot().bars).toEqual(harness.fixtures.repairedBars);
      expect(harness.publications).toHaveLength(publications);
    },
  },
  {
    name: 'aborts an obsolete repair without replacing the newly selected interval',
    async run(harness) {
      await loadInitial(harness);
      const repair = harness.refresh();
      const obsolete = await harness.transport.request(1);
      const second = harness.load(harness.fixtures.nextInterval);
      const current = await harness.transport.request(2);
      expect(obsolete.init.signal?.aborted).toBe(true);
      current.reply(harness.fixtures.duplicatePayload);
      await second;
      const before = harness.snapshot();
      const publications = harness.publications.length;
      obsolete.reply(harness.fixtures.repairPayload);
      await repair;
      expect(harness.snapshot()).toEqual(before);
      expect(harness.snapshot().interval).toBe(harness.fixtures.nextInterval);
      expect(harness.publications).toHaveLength(publications);
    },
  },
  {
    name: 'destroy aborts an in-flight load and suppresses late publications',
    async run(harness) {
      const work = harness.load();
      const request = await harness.transport.request(0);
      harness.destroy();
      harness.destroy();
      const publications = harness.publications.length;
      expect(request.init.signal?.aborted).toBe(true);
      request.reply(harness.fixtures.duplicatePayload);
      await work;
      expect(harness.publications).toHaveLength(publications);
      const requests = harness.transport.requests.length;
      await harness.load();
      await harness.refresh();
      expect(harness.transport.requests).toHaveLength(requests);
    },
  },
  {
    name: 'destroy aborts a repair and preserves the last delivered snapshot',
    async run(harness) {
      await loadInitial(harness);
      const work = harness.refresh();
      const request = await harness.transport.request(1);
      harness.destroy();
      const publications = harness.publications.length;
      const before = harness.snapshot();
      expect(request.init.signal?.aborted).toBe(true);
      request.reply(harness.fixtures.repairPayload);
      await work;
      expect(harness.publications).toHaveLength(publications);
      expect(harness.snapshot()).toEqual(before);
    },
  },
];
