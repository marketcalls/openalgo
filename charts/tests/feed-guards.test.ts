import { describe, it, expect } from 'vitest';
import { OpenAlgoTradeFeed } from '../src/feed/openalgo-trade';
import type { OrderConstraints } from '../src/trade/validation';

/**
 * These guarantees are tested against the FEED, not the engine, on purpose.
 *
 * OpenAlgo's terminal calls `trade.place` directly and never constructs an
 * `OrderEngine`, so anything enforced only in the engine is not enforced for the
 * largest consumer of this library. A guarantee you can bypass by calling one
 * layer down is not a guarantee.
 */
function feedFor(
  opts: {
    onPost?: (body: Record<string, unknown>) => unknown;
    constraints?: (symbol: string, exchange: string) => OrderConstraints | undefined;
  } = {},
) {
  const calls: Record<string, unknown>[] = [];
  const fetchImpl = (async (url: string, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    if (String(url).includes('/analyzer/')) {
      return { ok: true, status: 200, json: async () => ({ data: { mode: 'live' } }) } as Response;
    }
    calls.push(body);
    const out = opts.onPost ? opts.onPost(body) : { orderid: 'OA' + calls.length };
    if (out instanceof Error) throw out;
    return { ok: true, status: 200, json: async () => out } as Response;
  }) as unknown as typeof fetch;
  const feed = new OpenAlgoTradeFeed({
    baseUrl: 'http://x', apiKey: 'k', fetchImpl, constraints: opts.constraints,
  });
  return { feed, calls };
}

const order = (over: Record<string, unknown> = {}) =>
  ({ symbol: 'SBIN', exchange: 'NSE', side: 'BUY', type: 'MARKET', qty: 10, mode: 'live', ...over }) as never;

describe('feed-level quantity guard (reaches a caller that skips OrderEngine)', () => {
  it('refuses a non-finite quantity with no constraints configured', async () => {
    const { feed, calls } = feedFor();
    await expect(feed.place(order({ qty: Number.NaN }))).rejects.toThrow(/finite/);
    expect(calls).toHaveLength(0);
  });

  it('refuses a negative and a zero quantity', async () => {
    const { feed, calls } = feedFor();
    await expect(feed.place(order({ qty: -5 }))).rejects.toThrow(/positive/);
    await expect(feed.place(order({ qty: 0 }))).rejects.toThrow(/positive/);
    expect(calls).toHaveLength(0);
  });

  it('refuses a fractional quantity, which no Indian instrument trades', async () => {
    const { feed, calls } = feedFor();
    await expect(feed.place(order({ qty: 2.5 }))).rejects.toThrow();
    expect(calls).toHaveLength(0);
  });

  it('applies the freeze limit to a MARKET order, the one that cannot be taken back', async () => {
    const { feed, calls } = feedFor({ constraints: () => ({ tickSize: 0.05, freezeQty: 1000 }) });
    await expect(feed.place(order({ type: 'MARKET', qty: 5000 }))).rejects.toThrow(/freeze/i);
    expect(calls).toHaveLength(0);
    // and still lets a legal one through
    await feed.place(order({ type: 'MARKET', qty: 900 }));
    expect(calls).toHaveLength(1);
  });

  it('applies the lot grid when the instrument has one', async () => {
    const { feed } = feedFor({ constraints: () => ({ tickSize: 0.05, lotSize: 75 }) });
    await expect(feed.place(order({ qty: 100 }))).rejects.toThrow();
    await expect(feed.place(order({ qty: 150 }))).resolves.toBeTruthy();
  });

  it('rejects large fractional grid violations before delivery and preserves valid adapter units', async () => {
    const { feed, calls } = feedFor({ constraints: () => ({ tickSize: 0.01, lotSize: 0.001, allowFractionalQty: true }) });
    await expect(feed.place(order({ qty: 1000.0005, clientToken: 'large-grid' }))).rejects.toMatchObject({ preflight: true });
    expect(calls).toHaveLength(0);
    expect(feed.tokenState('large-grid')).toBe('unknown');
    await feed.place(order({ qty: 1000.001, clientToken: 'large-grid' }));
    expect(calls).toHaveLength(1);
    expect(calls[0].quantity).toBe(1000.001);
  });

  it('a refusal is pre-flight, so the caller knows nothing was sent', async () => {
    const { feed } = feedFor();
    await expect(feed.place(order({ qty: -1 }))).rejects.toMatchObject({ preflight: true });
  });
});

describe('feed-level idempotency (reaches a caller that skips OrderEngine)', () => {
  it('a repeated clientToken is refused and never reaches the broker twice', async () => {
    const { feed, calls } = feedFor();
    await feed.place(order({ clientToken: 't1' }));
    await expect(feed.place(order({ clientToken: 't1' }))).rejects.toThrow(/duplicate/);
    expect(calls).toHaveLength(1);
  });

  it('two concurrent places with one token produce exactly one order', async () => {
    // The double-click case: both calls start before either resolves.
    let release: (v: unknown) => void = () => {};
    const gate = new Promise((r) => { release = r; });
    const { feed, calls } = feedFor({ onPost: () => ({ orderid: 'OA1' }) });
    const a = feed.place(order({ clientToken: 'dbl' }));
    const b = feed.place(order({ clientToken: 'dbl' })).catch((e: Error) => e);
    release(null);
    await gate;
    await expect(a).resolves.toBeTruthy();
    expect(await b).toBeInstanceOf(Error);
    expect(calls).toHaveLength(1);
  });

  it('a failure AFTER the request leaves keeps the claim and reports it ambiguous', async () => {
    const { feed, calls } = feedFor({ onPost: () => new Error('gateway timeout') });
    await expect(feed.place(order({ clientToken: 'amb' }))).rejects.toThrow(/timeout/);
    expect(feed.tokenState('amb')).toBe('ambiguous');
    // The retry is refused, and says why rather than silently resending.
    await expect(feed.place(order({ clientToken: 'amb' }))).rejects.toThrow(/may already be live/);
    expect(calls).toHaveLength(1);
  });

  it('the host can release a claim once it has established the truth', async () => {
    const { feed, calls } = feedFor({ onPost: () => new Error('boom') });
    await expect(feed.place(order({ clientToken: 'r1' }))).rejects.toThrow();
    feed.releaseToken('r1');
    expect(feed.tokenState('r1')).toBe('unknown');
    const ok = feedFor();
    await ok.feed.place(order({ clientToken: 'r1' }));
    expect(ok.calls).toHaveLength(1);
    expect(calls).toHaveLength(1);
  });

  it('places without a token are unaffected, so existing callers keep working', async () => {
    const { feed, calls } = feedFor();
    await feed.place(order());
    await feed.place(order());
    expect(calls).toHaveLength(2);
  });
});
