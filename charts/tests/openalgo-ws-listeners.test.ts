/**
 * A host callback that throws must not stop the feed half way through a state
 * change or starve the other listeners (the chart bus's rule, `dispatch`).
 * The feed's loops used to call each listener bare: a throw during an auth
 * refusal left the socket open and the feed short of its fatal state, and a
 * throw from one tick listener kept the tick from every later one, which in the
 * composed live feed is another pane's chart.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { OpenAlgoWsFeed, type LtpEvent } from '../src/feed/openalgo-ws';

function socket() {
  const s = {
    sent: [] as string[], closed: 0, readyState: 1,
    onopen: null as (() => void) | null, onclose: null as (() => void) | null, onerror: null as (() => void) | null,
    onmessage: null as ((e: { data: string }) => void) | null,
    send(frame: string) { s.sent.push(frame); },
    close() { s.closed++; },
  };
  return s;
}
const frame = (s: ReturnType<typeof socket>, data: unknown): void => s.onmessage?.({ data: JSON.stringify(data) });

afterEach(() => { vi.unstubAllGlobals(); });

describe('OpenAlgoWsFeed listeners that throw', () => {
  it('still drops the socket and goes fatal on a refused key', () => {
    const reported: unknown[] = [];
    vi.stubGlobal('reportError', (error: unknown) => { reported.push(error); });
    const s = socket();
    const ws = new OpenAlgoWsFeed({ url: 'ws://x', apiKey: 'k', socketFactory: () => s, reconnect: { enabled: false } });
    const states: string[] = [];
    const heard: string[] = [];
    ws.onControl(() => { throw new Error('host bug'); });
    ws.onControl((msg) => { heard.push(String((msg as { code?: string; status?: string }).code ?? (msg as { status?: string }).status)); });
    ws.onState((state) => { states.push(state); });
    ws.connect();
    expect(() => frame(s, { type: 'auth', status: 'error', message: 'Invalid API key' })).not.toThrow();
    expect(s.closed).toBe(1);
    expect(states[states.length - 1]).toBe('closed');
    expect(heard).toContain('AUTH_FAILED');
    expect(reported.length).toBeGreaterThan(0);
    ws.close();
  });

  it('delivers a tick to every listener when one throws', () => {
    const s = socket();
    const ws = new OpenAlgoWsFeed({ url: 'ws://x', apiKey: 'k', socketFactory: () => s });
    const ticks: LtpEvent[] = [];
    ws.onLtp(() => { throw new Error('first pane'); });
    ws.onLtp((e) => { ticks.push(e); });
    ws.connect();
    frame(s, { type: 'auth', status: 'success' });
    ws.subscribe('LTP', 'RELIANCE', 'NSE');
    expect(() => frame(s, { type: 'market_data', symbol: 'RELIANCE', exchange: 'NSE', mode: 1, data: { ltp: 1424.5, timestamp: 1756376445123 } }))
      .not.toThrow();
    expect(ticks).toHaveLength(1);
    expect(ticks[0]!.ltp).toBe(1424.5);
    ws.close();
  });
});
