import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('/dist/openalgo-charts.mjs', () => ({ exportChartDataCsv: vi.fn(chart => chart.csv) }));
vi.mock('../src/ui.js', () => ({ el: () => status, toast: vi.fn() }));
import { chartDataFile, chartDataUnavailableReason, downloadChartData } from '../src/chart-data.js';
import { capturePaneTarget } from '../src/pane-target.js';

let app, status, downloads, anchor;
beforeEach(() => {
  const chart = csv => ({ csv, primaryBars: () => [{ time: 60 }], primarySeriesInfo: () => ({ type: 'candlestick' }) });
  app = { chart: chart('primary'), chart2: chart('secondary'), focusPane: 2,
    req: { symbol: 'AAPL', interval: '1d' }, p2: { symbol: 'MSFT', interval: '1h' } };
  status = { textContent: '' }; downloads = [];
  anchor = { href: '', download: '', click: () => downloads.push(anchor.download), remove: vi.fn() };
  vi.stubGlobal('document', { createElement: () => anchor, body: { appendChild: vi.fn() } });
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:csv');
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  vi.useFakeTimers();
});
afterEach(() => { vi.runAllTimers(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('reference chart data download', () => {
  it('captures the selected chart and retains its filename when focus changes', () => {
    const target = capturePaneTarget(app); app.focusPane = 1;
    expect(chartDataFile(app, target)).toMatchObject({ text: 'secondary', rows: 1,
      filename: expect.stringMatching(/^MSFT-1h-candlestick-.*\.csv$/) });
    expect(downloadChartData(app, target)).toBe(true);
    expect(downloads).toEqual([expect.stringMatching(/^MSFT-1h-candlestick-.*\.csv$/)]);
  });

  it('refuses a rebuilt chart or changed source before creating a file', () => {
    const target = capturePaneTarget(app); app.p2.symbol = 'OTHER';
    expect(downloadChartData(app, target)).toBe(false);
    expect(status.textContent).toMatch(/changed/); expect(URL.createObjectURL).not.toHaveBeenCalled();
    app.p2.symbol = 'MSFT'; app.chart2 = { ...app.chart2 };
    expect(chartDataUnavailableReason(app, target)).toMatch(/changed/);
  });

  it('blocks only the captured source loading/error and shared transitions', () => {
    const target = capturePaneTarget(app); app.loading = true;
    expect(chartDataUnavailableReason(app, target)).toBeNull();
    for (const flag of ['loading2', 'loadFailed2', 'workspaceLoading', 'applyingTemplate', 'replayLoading', 'replayPicking', 'chartSettingsEditing']) {
      app[flag] = true;
      expect(() => chartDataFile(app, target)).toThrow(); app[flag] = false;
    }
    app.chart2.primaryBars = () => [];
    expect(() => chartDataFile(app, target)).toThrow(/no bars/i);
  });

  it('permits the installed active replay prefix and labels the file', () => {
    app.replay = {}; app.replayTarget = capturePaneTarget(app);
    expect(chartDataFile(app)).toMatchObject({ text: 'secondary', rows: 1, filename: expect.stringContaining('-replay-') });
  });

  it('names a transform rather than its underlying candle renderer', () => {
    app.p2.chartType = 't:heikin-ashi';
    expect(chartDataFile(app).filename).toMatch(/^MSFT-1h-heikin-ashi-/);
  });

  it('cleans up the object URL after handing off the download', () => {
    expect(downloadChartData(app)).toBe(true);
    expect(anchor.remove).toHaveBeenCalledOnce(); expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    vi.runAllTimers(); expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:csv');
  });

  it('reports a failed browser download and still releases its resources', () => {
    anchor.click = () => { throw new Error('Download refused'); };
    expect(downloadChartData(app)).toBe(false);
    expect(status.textContent).toMatch(/Download refused/);
    expect(anchor.remove).toHaveBeenCalledOnce();
    vi.runAllTimers(); expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:csv');
  });
});
