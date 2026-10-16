import { createBtcUsdFeed } from '../../website/lib/market-data/btc-usd.mjs';
import { DataLoadingController } from '../../src/feed/data-controller';
import { OpenAlgoLiveDataFeed } from '../../src/feed/openalgo-live';
import type { SocketLike } from '../../src/feed/openalgo-ws';
import type { BarsRequest } from '../../src/feed/types';
import type { Bar } from '../../src/model/bar';
import type { AdapterFixtures, AdapterHarness, AdapterReference, AdapterSnapshot } from './adapter-contract';
import { ControlledTransport } from './controlled-transport';

function candles(start: number, price: number, volume: number): Bar[] {
  return [0, 1, 2].map(index => ({
    time: start + index * 900, open: price + index * 2,
    high: price + index * 2 + 10, low: price + index * 2 - 10,
    close: price + index * 2 + 2, volume: volume * (index + 1),
  }));
}

function repaired(bars: readonly Bar[]): Bar[] {
  return bars.map((bar, index) => index ? { ...bar } : {
    ...bar, open: bar.open + 1, high: bar.high - 2, low: bar.low + 8,
    close: bar.close + 1, volume: bar.volume! / 2,
  });
}

function brokerPayload(bars: readonly Bar[]): unknown {
  return { status: 'success', data: bars.map(bar => ({
    timestamp: bar.time * 1000, open: bar.open, high: bar.high,
    low: bar.low, close: bar.close, volume: bar.volume,
  })) };
}

function cryptoPayload(bars: readonly Bar[]): unknown {
  return bars.map(bar => [bar.time * 1000, bar.open, bar.high, bar.low, bar.close, bar.volume]);
}

function fixtures(kind: 'broker' | 'crypto'): AdapterFixtures {
  const broker = kind === 'broker';
  const start = Date.parse(broker ? '2026-09-18T03:45:00Z' : '2026-09-19T23:45:00Z') / 1000;
  const initialBars = candles(start, broker ? 100 : 60000, broker ? 10 : 0.125);
  const repairedBars = repaired(initialBars);
  const olderDuplicate = { ...initialBars[0], close: initialBars[0].close - 1, volume: initialBars[0].volume! / 2 };
  const encode = broker ? brokerPayload : cryptoPayload;
  // Broker rows keep the last occurrence; the crypto API returns newest first.
  const duplicateRows = broker
    ? [initialBars[2], olderDuplicate, initialBars[1], initialBars[0]]
    : [initialBars[2], initialBars[1], initialBars[0], olderDuplicate];
  return {
    interval: '15m', nextInterval: '1h', initialBars, repairedBars,
    duplicatePayload: encode(duplicateRows),
    repairPayload: encode([...repairedBars].reverse()),
    invalidPayload: encode([{ ...initialBars[0], high: initialBars[0].low - 1 }]),
    providerErrorPayload: broker ? { status: 'error', message: 'Synthetic provider rejection' } : { error: 'Synthetic provider rejection' },
  };
}

export class SyntheticSocket implements SocketLike {
  public readonly frames: Record<string, unknown>[] = [];
  public readyState = 1;
  public onopen: (() => void) | null = null;
  public onclose: (() => void) | null = null;
  public onerror: (() => void) | null = null;
  public onmessage: ((event: { data: string }) => void) | null = null;

  public send(data: string): void { this.frames.push(JSON.parse(data) as Record<string, unknown>); }
  public close(): void { this.readyState = 3; }
  public receive(payload: unknown): void { this.onmessage?.({ data: JSON.stringify(payload) }); }
  public authenticate(): void { this.receive({ type: 'auth', status: 'success' }); }
  public disconnect(): void { this.readyState = 3; this.onclose?.(); }
}

export interface BrokerHarness extends AdapterHarness {
  readonly feed: OpenAlgoLiveDataFeed;
  readonly controller: DataLoadingController;
  readonly sockets: SyntheticSocket[];
  readonly request: BarsRequest;
  quote(time: number, price: number, cumulativeVolume: number): void;
}

export function createBrokerHarness(): BrokerHarness {
  const transport = new ControlledTransport();
  const sample = fixtures('broker');
  const sockets: SyntheticSocket[] = [];
  const feed = new OpenAlgoLiveDataFeed({
    baseUrl: 'https://broker.invalid', wsUrl: 'wss://broker.invalid', apiKey: 'synthetic-placeholder',
    fetchImpl: transport.fetch, volumeMode: 'day-delta',
    reconnect: { baseDelayMs: 10, maxDelayMs: 10, jitter: false },
    heartbeat: { timeoutMs: 0 },
    socketFactory: () => { const socket = new SyntheticSocket(); sockets.push(socket); return socket; },
  });
  const request: BarsRequest = {
    symbol: 'SYNTHETIC', exchange: 'NSE', interval: sample.interval,
    from: sample.initialBars[0].time, to: sample.initialBars[2].time + 899,
  };
  const controller = new DataLoadingController(feed, { now: () => request.to! });
  const publications: AdapterSnapshot[] = [];
  const snapshot = (): AdapterSnapshot => {
    const state = controller.getState();
    return {
      bars: state.bars.map(bar => ({ ...bar })), status: state.status,
      interval: state.request?.interval ?? sample.interval, error: state.error?.message,
    };
  };
  controller.subscribe(() => publications.push(snapshot()));
  sockets[0].authenticate();
  return {
    transport, fixtures: sample, publications, feed, controller, sockets, request, snapshot,
    load: async (interval = sample.interval) => { await controller.load({ ...request, interval }); },
    refresh: async () => { await controller.refresh(); },
    destroy: () => { controller.destroy(); feed.close(); },
    quote: (time, price, cumulativeVolume) => sockets[sockets.length - 1].receive({
      type: 'market_data', mode: 2,
      data: { symbol: request.symbol, exchange: request.exchange, timestamp: time, ltp: price, volume: cumulativeVolume },
    }),
  };
}

export function createCryptoHarness(): AdapterHarness {
  const transport = new ControlledTransport();
  const sample = fixtures('crypto');
  const publications: AdapterSnapshot[] = [];
  let current: AdapterSnapshot = { bars: [], status: 'idle', interval: sample.interval };
  const feed = createBtcUsdFeed({
    fetchImpl: transport.fetch,
    onBars: (bars, interval) => {
      current = { ...current, bars: bars.map(bar => ({ ...bar })), interval };
      publications.push(current);
    },
    onStatus: status => {
      current = {
        ...current, status: status.state === 'connected' ? 'ready' : status.state,
        interval: status.interval, error: status.message,
      };
      publications.push(current);
    },
  });
  return {
    transport, fixtures: sample, publications,
    snapshot: () => ({ ...current, bars: current.bars.map(bar => ({ ...bar })) }),
    load: (interval = sample.interval) => feed.selectInterval(interval),
    refresh: () => feed.refresh(),
    destroy: () => feed.destroy(),
  };
}

export const adapterReferences: readonly AdapterReference[] = [
  { name: 'OpenAlgo broker history and stream', evidence: 'synthetic', create: createBrokerHarness },
  { name: 'Website crypto candle polling', evidence: 'synthetic', create: createCryptoHarness },
];
