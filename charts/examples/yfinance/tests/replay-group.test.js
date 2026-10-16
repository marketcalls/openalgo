import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fakeDom, flatBar } from './helpers.js';

vi.mock('../src/feed.js', () => ({ fetchBars: vi.fn(), abortFetch: vi.fn() }));
vi.mock('../src/toolbar.js', () => ({ renderToolbar: vi.fn(), ticon: () => '' }));
vi.mock('../src/hover.js', () => ({ attachTip: vi.fn() }));
vi.mock('../src/volume.js', () => ({ setLegend: vi.fn() }));
import { fetchBars, abortFetch } from '../src/feed.js';
import { initReplay, attachReplay, enterReplay, startReplayAt, exitReplay,
  setReplayScope, setShadeIndex, replayBarEndTime, lastBar } from '../src/replay.js';

const T = Date.UTC(2024, 0, 2) / 1000;
const history = (seconds, count, start = T) => Array.from({ length: count }, (_, i) => flatBar(start + i * seconds, 100 + i, 10));
function host(bars) {
  const listeners = new Map();
  let data = bars;
  const series = { getData: () => data, setData: value => { data = value; } };
  const chart = {
    primarySeries: () => series, primaryBars: () => data, timezone: () => 'UTC',
    panes: () => [{}], addPrimitive: vi.fn(), removePrimitive: vi.fn(),
    timeScale: { barSpacing: 7, rightOffset: 3, getVisibleLogicalRange: () => ({ from: 0, to: 12 }),
      setBarSpacing(value) { this.barSpacing = value; }, setRightOffset(value) { this.rightOffset = value; } },
    on(event, callback) {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event).add(callback);
      return () => listeners.get(event).delete(callback);
    },
    emit(event, value) { for (const callback of [...(listeners.get(event) || [])]) callback(value); },
    destroy() { this.isDestroyed = true; this.emit('destroy'); },
  };
  return chart;
}

describe('reference shared replay', () => {
  let app, dom, firstReadout, secondReadout;
  beforeEach(() => {
    dom = fakeDom();
    const get = document.getElementById;
    document.getElementById = id => { const node = get(id); node.dataset ??= {}; return node; };
    const create = document.createElement;
    document.createElement = tag => { const node = create(tag); node.dataset = {}; return node; };
    document.addEventListener = () => {};
    globalThis.window = { addEventListener() {} };
    app = { chart: host(history(300, 12)), chart2: host(history(3600, 4)), focusPane: 1,
      req: { symbol: 'FIRST', interval: '5m', period: '1mo' },
      p2: { symbol: 'SECOND', interval: '1h', period: '1mo' }, currentBars: history(300, 12),
      alerts: { setPaused: vi.fn() }, alerts2: { setPaused: vi.fn() }, replay: null };
    app.price = app.chart.primarySeries();
    initReplay(app);
    firstReadout = vi.fn(); secondReadout = vi.fn();
    attachReplay(app.chart, 1, firstReadout); attachReplay(app.chart2, 2, secondReadout);
    vi.clearAllMocks(); fetchBars.mockResolvedValue([]);
  });
  afterEach(() => { exitReplay(); vi.useRealTimers(); delete globalThis.window; });

  it('aligns all charts by close time and clears a later chart readout', async () => {
    enterReplay(); setReplayScope('all');
    await startReplayAt(1);
    expect(app.replay, dom.get('status').textContent).not.toBeNull();
    expect(app.replay.state()).toMatchObject({ scope: 'all', time: T + 600 });
    expect(app.chart.primaryBars()).toHaveLength(2);
    expect(app.chart2.primaryBars()).toEqual([]);
    expect(secondReadout).toHaveBeenLastCalledWith(null);
    expect(app.alerts2.setPaused).toHaveBeenLastCalledWith(true);
    app.replay.seekTime(T + 3600);
    expect(app.chart2.primaryBars()).toHaveLength(1);
    exitReplay();
    expect(app.chart.primaryBars()).toHaveLength(12);
    expect(app.chart2.primaryBars()).toHaveLength(4);
    expect(app.alerts2.setPaused).toHaveBeenLastCalledWith(false);
  });

  it('keeps one playing clock and UTC time across scope and toolbar focus changes', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'performance'] });
    await startReplayAt(1);
    app.replay.play(); app.focusPane = 2;
    setReplayScope('all');
    expect(app.replay.state()).toMatchObject({ focusedId: '1', time: T + 600, playing: true });
    expect(vi.getTimerCount()).toBe(1);
    vi.advanceTimersByTime(1000);
    // No finer bars arrive here, so the next 5-minute candle forms over five
    // simulated steps a minute apart: one played step is one minute.
    expect(app.replay.state().time).toBe(T + 660);
    setReplayScope('focused');
    expect(app.chart2.primaryBars()).toHaveLength(4);
    expect(app.replay.state().time).toBe(T + 660);
    exitReplay(); expect(vi.getTimerCount()).toBe(0);
  });

  it('uses separate history slots and discards every late response after cancellation', async () => {
    const resolve = [];
    fetchBars.mockImplementation(() => new Promise(done => resolve.push(done)));
    enterReplay(); setReplayScope('all');
    const start = startReplayAt(1);
    expect(fetchBars.mock.calls.map(call => call[3].slot)).toEqual(['replay:1', 'replay:2']);
    expect(app.replayLoading).toBe(true);
    exitReplay();
    expect(abortFetch).toHaveBeenCalledWith('replay:1');
    expect(abortFetch).toHaveBeenCalledWith('replay:2');
    resolve.forEach(done => done(history(60, 3)));
    await start;
    expect(app.replay).toBeNull();
    expect(app.chart.primaryBars()).toHaveLength(12);
  });

  it('forms candles along a simulated path, and says so, when finer history fails', async () => {
    fetchBars.mockRejectedValue(new Error('offline'));
    enterReplay(); setReplayScope('all');
    await startReplayAt(1);
    expect(app.replay.state().active).toBe(true);
    expect(dom.get('status').textContent).toMatch(/simulated path/i);
    expect(dom.get('status').textContent).toMatch(/Chart 1.*Chart 2/);
    app.replay.step();
    expect(app.replay.state().members.find(m => m.id === '1').state).toMatchObject({ subSteps: 5, simulated: true });
    expect(dom.get('rp-sim').hidden).toBe(false);
  });

  it('labels only simulated steps as simulated', async () => {
    // Real 1-minute bars under the 5-minute chart: its candles form from them.
    fetchBars.mockImplementation((symbol, interval) => Promise.resolve(interval === '1m' ? history(60, 60) : []));
    await startReplayAt(1);
    app.replay.step();
    expect(app.replay.state().members.find(m => m.id === '1').state).toMatchObject({ subSteps: 5, simulated: false });
    expect(dom.get('rp-sim').hidden).toBe(true);
  });

  it('restores every survivor when an active participant is destroyed', async () => {
    enterReplay(); setReplayScope('all'); await startReplayAt(1);
    app.chart2.destroy();
    expect(app.replay).toBeNull();
    expect(app.chart.primaryBars()).toHaveLength(12);
    expect(app.chart.timeScale.barSpacing).toBe(7);
    expect(dom.get('replaybar').hidden).toBe(true);
  });

  it('keeps focused replay when an inactive chart closes', async () => {
    await startReplayAt(1);
    app.chart2.destroy();
    expect(app.replay.state()).toMatchObject({ active: true, destroyed: false });
    expect(app.chart.primaryBars()).toHaveLength(2);
  });

  it('rejects an all-chart transition onto a changed source without disturbing playback', async () => {
    await startReplayAt(1);
    app.p2.symbol = 'THIRD';
    setReplayScope('all');
    expect(app.replay.state()).toMatchObject({ scope: 'focused', time: T + 600 });
    expect(dom.get('status').textContent).toMatch(/new replay/i);
  });

  it('rejects stale all-chart history and unlocks after a participant changes context', async () => {
    const resolve = [];
    fetchBars.mockImplementation(() => new Promise(done => resolve.push(done)));
    enterReplay(); setReplayScope('all');
    const start = startReplayAt(1);
    app.p2.interval = '15m';
    resolve.forEach(done => done([])); await start;
    expect(app.replay).toBeNull();
    expect(app.replayLoading).toBe(false);
    expect(app.chart.primaryBars()).toHaveLength(12);
    expect(app.alerts.setPaused).toHaveBeenLastCalledWith(false);
  });

  it('does not replace an empty replay reading with the latest live price', async () => {
    await startReplayAt(1); app.replay.seekTime(T - 1);
    expect(lastBar()).toBeNull();
    expect(firstReadout).toHaveBeenLastCalledWith(null);
  });

  it('releases loading and leaves all charts unchanged when timing is invalid', async () => {
    app.chart2.primarySeries().setData(history(60, 3));
    enterReplay(); setReplayScope('all'); await startReplayAt(1);
    expect(app.replay).toBeNull(); expect(app.replayLoading).toBe(false);
    expect(app.chart.primaryBars()).toHaveLength(12);
    expect(dom.get('status').textContent).toMatch(/replay.*could not start/i);
  });

  it('keeps focused replay usable when the inactive chart cannot be aligned', async () => {
    app.chart2.primarySeries().setData(history(60, 3));
    await startReplayAt(1);
    expect(app.replay, dom.get('status').textContent).not.toBeNull();
    setReplayScope('all');
    expect(app.replay.state().scope).toBe('focused');
    expect(dom.get('status').textContent).toMatch(/Chart 2.*time/i);
  });

  it('clears transport and guards even when restoration reports a host failure', async () => {
    await startReplayAt(1);
    const controller = app.replay, destroy = controller.destroy.bind(controller);
    vi.spyOn(controller, 'destroy').mockImplementation(() => { destroy(); throw new Error('host callback failed'); });
    expect(() => exitReplay()).not.toThrow();
    expect(app.replay).toBeNull(); expect(app.replayLoading).toBe(false);
    expect(app.alerts.setPaused).toHaveBeenLastCalledWith(false);
    expect(dom.get('replaybar').hidden).toBe(true);
    expect(dom.get('status').textContent).toMatch(/restoration error/);
  });

  it('passes each chart its own finer bars without disclosing final volume or OI', async () => {
    fetchBars.mockImplementation(async symbol => history(symbol === 'FIRST' ? 60 : 900, 60)
      .map((bar, index) => ({ ...bar, oi: (symbol === 'FIRST' ? 100 : 500) + index })));
    enterReplay(); setReplayScope('all'); await startReplayAt(0);
    app.replay.seekTime(T + 360);
    expect(app.chart.primaryBars().at(-1)).toMatchObject({ time: T + 300, volume: 10, oi: 105 });
    expect(app.chart2.primaryBars()).toEqual([]);
    app.replay.seekTime(T + 900);
    expect(app.chart2.primaryBars()).toEqual([{ ...flatBar(T, 100, 10), oi: 500 }]);
  });

  it('leaves visible only what the closed bars of a transformed chart formed, whatever its interval', () => {
    // Chart 2 draws two bricks on each hourly bar, the second dated a second later.
    const bricks = history(3600, 4).flatMap(bar => [bar, { ...bar, time: bar.time + 1 }]);
    app.chart2.primaryBars = () => bricks;
    app.chart2.seriesTransform = () => ({ type: 'renko' });
    enterReplay(); setReplayScope('all');
    const shade = app.chart2.addPrimitive.mock.calls[0][0], set = vi.spyOn(shade, 'setOptions');
    const cut = index => { setShadeIndex(index); return set.mock.lastCall[0].index; };
    // Picked 5-minute bars close at 10 and 55 minutes: the first hourly bar is still open, so none of its bricks shows.
    expect(cut(1)).toBe(-1);
    expect(cut(10)).toBe(-1);
    // At the hour it has closed, and both bricks it formed are in view.
    expect(cut(11)).toBe(1);
  });

  it('ends an active group when a captured source context changes', async () => {
    enterReplay(); setReplayScope('all'); await startReplayAt(1);
    app.p2.symbol = 'THIRD'; app.chart2.emit('data:context');
    expect(app.replay).toBeNull();
    expect(app.chart.primaryBars()).toHaveLength(12);
  });
});

describe('reference replay availability', () => {
  it('uses local calendar days across daylight changes and never waits for the next trading day', () => {
    const close = replayBarEndTime('1d', 'America/New_York');
    expect(close(flatBar(Date.parse('2024-03-10T05:00:00Z') / 1000, 1))).toBe(Date.parse('2024-03-11T04:00:00Z') / 1000);
    expect(close(flatBar(Date.parse('2024-11-03T04:00:00Z') / 1000, 1))).toBe(Date.parse('2024-11-04T05:00:00Z') / 1000);
    expect(close(flatBar(Date.parse('2024-01-05T05:00:00Z') / 1000, 1))).toBe(Date.parse('2024-01-06T05:00:00Z') / 1000);
  });
  it('uses exact calendar month ends and rejects unknown timing', () => {
    expect(replayBarEndTime('1mo', 'UTC')(flatBar(Date.UTC(2024, 1, 1) / 1000, 1))).toBe(Date.UTC(2024, 2, 1) / 1000);
    expect(() => replayBarEndTime('unknown', 'UTC')(flatBar(T, 1))).toThrow(/interval/i);
  });
});

describe('the finer period replay asks for', async () => {
  const { finerPeriod } = await import('../src/replay.js');
  it('keeps a period the finer interval can serve', () => {
    expect(finerPeriod('5m', '1mo')).toBe('1mo');
    expect(finerPeriod('1d', '5y')).toBe('5y');
  });
  it('asks for the longest period the source keeps when the chart period is longer', () => {
    // The source refuses a month of 1-minute bars outright; five days it serves.
    expect(finerPeriod('1m', '1mo')).toBe('5d');
    expect(finerPeriod('15m', '1y')).toBe('1mo');
    expect(finerPeriod('60m', '5y')).toBe('1y');
  });
});
