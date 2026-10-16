import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { downloadSnapshot, initSnapshot, openSnapMenu, snapshotBlob, snapshotName } from '../src/snapshot.js';

vi.mock('../src/toolbar.js', () => ({ ticon: () => '' }));

let app, conversions, downloads, status;
const anchor = { getBoundingClientRect: () => ({ bottom: 30, left: 100 }) };

beforeEach(() => {
  conversions = [];
  downloads = [];
  status = { textContent: '' };
  const menu = { hidden: true, offsetWidth: 180, style: {}, contains: () => false };
  const chart = label => ({ takeScreenshot: vi.fn(() => ({
    toBlob: callback => conversions.push(() => callback(new Blob([label], { type: 'image/png' }))),
  })) });
  app = { chart: chart('primary'), chart2: chart('secondary'), focusPane: 2,
    req: { symbol: 'AAPL', interval: '1d' }, p2: { symbol: 'MSFT', interval: '1h' } };
  vi.stubGlobal('window', { innerWidth: 1000 });
  vi.stubGlobal('document', {
    getElementById: id => id === 'snapmenu' ? menu : id === 'status' ? status : null,
    addEventListener: vi.fn(),
    body: { appendChild: vi.fn() },
    createElement: () => {
      const node = { href: '', download: '', click: () => downloads.push(node.download), remove: vi.fn() };
      return node;
    },
  });
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:preview');
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  vi.useFakeTimers();
  initSnapshot(app);
});

afterEach(() => {
  vi.runAllTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('reference snapshot ownership', () => {
  it('captures the selected chart and names its instrument and interval', async () => {
    const pending = snapshotBlob();
    conversions.shift()();
    expect(await (await pending).text()).toBe('secondary');
    expect(snapshotName()).toMatch(/^MSFT-1h-.*\.png$/);
    expect(app.chart.takeScreenshot).not.toHaveBeenCalled();
  });

  it('retains the original request while image conversion finishes asynchronously', async () => {
    const pending = downloadSnapshot();
    app.focusPane = 1;
    app.p2.symbol = 'CHANGED';
    conversions.shift()();
    await pending;
    expect(downloads).toEqual([expect.stringMatching(/^MSFT-1h-.*\.png$/)]);
    expect(app.chart2.takeScreenshot).toHaveBeenCalledOnce();
    vi.runAllTimers();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview');
  });

  it('keeps an open menu bound to the chart that opened it when focus changes', async () => {
    openSnapMenu(anchor);
    app.focusPane = 1;
    const pending = downloadSnapshot();
    conversions.shift()();
    await pending;
    expect(downloads).toEqual([expect.stringMatching(/^MSFT-1h-.*\.png$/)]);
    expect(app.chart.takeScreenshot).not.toHaveBeenCalled();
  });

  it('refuses an old menu after its chart is rebuilt', async () => {
    openSnapMenu(anchor);
    app.chart2 = { ...app.chart2 };
    const pending = downloadSnapshot();
    conversions.shift()?.();
    await pending;
    expect(downloads).toEqual([]);
    expect(status.textContent).toMatch(/chart changed/i);
  });
});
