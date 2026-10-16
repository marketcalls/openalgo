import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fakeDom } from './helpers.js';
import { initGoTo, loadPaneHistory, widerPeriod } from '../src/goto.js';

const DAY = 86400;

describe('reference go-to history', () => {
  it('widens to the shortest period that reaches the requested time', () => {
    // Weekly offers every range, so several longer ones reach each date here.
    expect(widerPeriod('1wk', '1y', 2 * 366 * DAY)).toBe('5y');
    expect(widerPeriod('1wk', '1mo', 40 * DAY)).toBe('6mo');
    expect(widerPeriod('1h', '1mo', 40 * DAY)).toBe('6mo');
    // Daily starts at five years, so its one wider range is the longest.
    expect(widerPeriod('1d', '5y', 6 * 366 * DAY)).toBe('max');
    expect(widerPeriod('1d', '5y', 90 * 366 * DAY)).toBe('max');
    expect(widerPeriod('1d', 'max', 90 * 366 * DAY)).toBeNull();
  });

  it('stops at the longest period an interval can serve', () => {
    expect(widerPeriod('1h', '1mo', 3 * 366 * DAY)).toBe('1y');
    expect(widerPeriod('1h', '1y', 3 * 366 * DAY)).toBeNull();
    expect(widerPeriod('5m', '1mo', 90 * DAY)).toBeNull();
  });
});

describe('reference go-to loading', () => {
  let app;
  /** View listeners the loader holds on either chart, which must not outlive a load. */
  let listening;
  const chart = () => ({ on: (name, cb) => {
    const entry = { name, cb };
    listening.add(entry);
    return () => listening.delete(entry);
  } });
  beforeEach(() => {
    fakeDom({ period: '5y' });
    listening = new Set();
    app = {
      chart: chart(),
      chart2: chart(),
      req: { symbol: 'AAPL', interval: '1d', period: '5y' },
      // An hourly second chart: it widens by its own interval's ranges, not the main chart's.
      p2: { symbol: 'MSFT', interval: '1h', period: '1mo' },
      load: vi.fn(async () => { app.req.period = document.getElementById('period').value; }),
      loadSecondary: vi.fn(async () => true),
    };
    initGoTo(app);
  });

  it('reloads the main chart through its own load path with the wider period', async () => {
    const time = Math.floor(Date.now() / 1000) - 6 * 366 * DAY;
    expect(await loadPaneHistory(1, time)).toBe('loaded');
    expect(document.getElementById('period').value).toBe('max');
    expect(app.load).toHaveBeenCalledTimes(1);
    expect(app.req.period).toBe('max');
    expect(listening.size).toBe(0);
  });

  it('reports exhaustion without loading once the longest period is held', async () => {
    app.req.period = 'max';
    document.getElementById('period').value = 'max';
    expect(await loadPaneHistory(1, 0)).toBe('exhausted');
    expect(app.load).not.toHaveBeenCalled();
  });

  it('surfaces a failed load and never loads during replay', async () => {
    app.load = vi.fn(async () => { app.loadFailed = true; });
    await expect(loadPaneHistory(1, 0)).rejects.toThrow('could not load');
    expect(listening.size).toBe(0);
    app.loadFailed = false;
    app.replay = {};
    expect(await loadPaneHistory(1, 0)).toBe('unavailable');
    expect(app.load).toHaveBeenCalledTimes(1);
  });

  it('widens the second chart through its own loader', async () => {
    const time = Math.floor(Date.now() / 1000) - 100 * DAY;
    expect(await loadPaneHistory(2, time)).toBe('loaded');
    expect(app.p2.period).toBe('6mo');
    expect(app.loadSecondary).toHaveBeenCalledTimes(1);
    expect(app.load).not.toHaveBeenCalled();
    app.loadSecondary = vi.fn(async () => { app.loadFailed2 = true; return false; });
    await expect(loadPaneHistory(2, 0)).rejects.toThrow('could not load');
    expect(listening.size).toBe(0);
  });
});
