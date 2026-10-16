import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fakeDom, flatBar } from './helpers.js';

vi.mock('../src/feed.js', () => ({ fetchBars: vi.fn(), abortFetch: vi.fn() }));
vi.mock('../src/toolbar.js', () => ({ renderToolbar: vi.fn(), ticon: () => '' }));
vi.mock('../src/status.js', async importOriginal => ({ ...await importOriginal(), setLegend: vi.fn(), barStamp: () => '' }));
import { fetchBars, abortFetch } from '../src/feed.js';
import { initReplay, enterReplay, startReplayAt, exitReplay, loadReplaySubBars } from '../src/replay.js';

describe('reference replay transitions', () => {
  let app;
  beforeEach(() => {
    fakeDom();
    document.addEventListener = () => {};
    globalThis.window = { addEventListener() {} };
    app = { chart: { panes: () => [] }, price: { getData: () => [flatBar(1, 10), flatBar(2, 11)] },
      req: { symbol: 'FIRST', interval: '1d', period: '1mo' }, currentBars: [],
      replay: null, replayPicking: false, replayShades: [], alerts: { setPaused: vi.fn() } };
    initReplay(app);
    vi.clearAllMocks();
  });
  afterEach(() => { delete globalThis.window; });

  it('cannot enter or load replay while a workspace switch is pending', async () => {
    app.workspaceLoading = true;
    enterReplay();
    await startReplayAt(0);
    expect(app.replayPicking).toBe(false);
    expect(fetchBars).not.toHaveBeenCalled();
  });

  it('locks before loading and rejects a result after cancellation', async () => {
    let resolve;
    fetchBars.mockReturnValue(new Promise(done => { resolve = done; }));
    const start = startReplayAt(0);
    expect(app.replayLoading).toBe(true);
    expect(app.alerts.setPaused).toHaveBeenLastCalledWith(true);
    exitReplay();
    expect(app.replayLoading).toBe(false);
    expect(abortFetch).toHaveBeenCalledWith('replay:1');
    resolve([flatBar(1, 10), flatBar(2, 11)]);
    await start;
    expect(app.replay).toBeNull();
    expect(app.alerts.setPaused).toHaveBeenLastCalledWith(false);
  });

  it('keys finer history by instrument and period as well as interval', async () => {
    fetchBars.mockResolvedValue([flatBar(1, 10)]);
    await loadReplaySubBars();
    app.req.symbol = 'SECOND';
    await loadReplaySubBars();
    app.req.period = '3mo';
    await loadReplaySubBars();
    expect(fetchBars.mock.calls.map(call => call.slice(0, 3))).toEqual([
      ['FIRST', '60m', '1mo'], ['SECOND', '60m', '1mo'], ['SECOND', '60m', '3mo'],
    ]);
  });

  it('keys finer history by session and asks for it in that session', async () => {
    fetchBars.mockResolvedValue([flatBar(1, 10)]);
    app.req.interval = '1h';
    await loadReplaySubBars();
    // Extended hours are another series: the regular finer bars cannot stand in for them.
    app.req.session = 'extended';
    await loadReplaySubBars();
    expect(fetchBars.mock.calls.map(call => [call[0], call[1], call[3]?.variant])).toEqual([
      ['FIRST', '15m', undefined], ['FIRST', '15m', { session: 'extended' }],
    ]);
  });

  it('captures the selected chart request while focus changes during loading', async () => {
    let resolve;
    fetchBars.mockReturnValue(new Promise(done => { resolve = done; }));
    app.chart2 = { panes: () => [], primarySeries: () => app.price, timezone: () => 'UTC' };
    app.p2 = { symbol: 'SECOND', interval: '1h', period: '1mo' };
    app.focusPane = 2;
    app.alerts2 = { setPaused: vi.fn() };
    const start = startReplayAt(0);
    app.focusPane = 1;
    expect(fetchBars).toHaveBeenCalledWith('SECOND', '15m', '1mo', expect.objectContaining({ timezone: 'UTC' }));
    expect(app.alerts2.setPaused).toHaveBeenLastCalledWith(true);
    exitReplay(1);
    expect(app.replayLoading).toBe(true);
    exitReplay(2);
    resolve([]);
    await start;
    expect(app.replay).toBeNull();
    expect(app.alerts2.setPaused).toHaveBeenLastCalledWith(false);
  });

  it('keys finer history by the captured timezone as well as request', async () => {
    let timezone = 'UTC';
    app.chart.timezone = () => timezone;
    fetchBars.mockResolvedValue([flatBar(1, 10)]);
    await loadReplaySubBars();
    timezone = 'Asia/Kolkata';
    await loadReplaySubBars();
    expect(fetchBars.mock.calls.map(call => call[3]?.timezone)).toEqual(['UTC', 'Asia/Kolkata']);
  });
});
