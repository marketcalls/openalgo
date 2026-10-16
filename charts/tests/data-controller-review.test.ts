import { afterEach, describe, expect, it, vi } from 'vitest';
import { DataLoadingController } from '../src/feed/data-controller';
import type { Bar } from '../src/model/bar';

const bar = (time: number, close = 10): Bar => ({ time, open: 10, high: Math.max(10, close), low: Math.min(10, close), close });
const req = { symbol: 'AAA', exchange: 'NSE', interval: '1m', from: 100, to: 300 };
const controllers: DataLoadingController[] = [];
afterEach(() => { controllers.splice(0).forEach(controller => controller.destroy()); });

describe('controller independent lifecycle review', () => {
  it('lets authoritative refresh replace a live close observed before the request', async () => {
    let calls = 0;
    const controller = new DataLoadingController({ getBars: async () => [bar(200, ++calls === 1 ? 10 : 20)] }, { now: () => 300 });
    controllers.push(controller);
    await controller.load(req);
    controller.pushBar(bar(200, 15));
    await controller.refresh();
    expect(controller.bars()[0].close).toBe(20);
  });

  it('coalesces pagination invoked reentrantly by a loading listener', async () => {
    const getBarsPage = vi.fn(async () => ({ bars: [bar(50)], hasMore: true }));
    const controller = new DataLoadingController({ getBars: async () => [bar(100)], getBarsPage });
    controllers.push(controller);
    await controller.load(req);
    let nested: Promise<readonly Bar[]> | undefined;
    let invoked = false;
    let prepends = 0;
    controller.subscribe(state => {
      if (state.reason === 'prepend') prepends++;
      if (state.historyStatus === 'loading' && !invoked) {
        invoked = true;
        nested = controller.loadMore();
      }
    });
    const outer = controller.loadMore();
    await Promise.all([nested, outer]);
    expect(prepends).toBe(1);
    expect(nested).toBe(outer);
    expect(getBarsPage).toHaveBeenCalledTimes(1);
    expect(controller.bars().map(value => value.time)).toEqual([50, 100]);
  });

  it('honors a newer context requested by an old subscription cleanup', async () => {
    let redirected = false;
    let replacement: Promise<readonly Bar[]> | undefined;
    const controller = new DataLoadingController({
      getBars: async request => [bar(200, request.symbol === 'CCC' ? 30 : request.symbol === 'BBB' ? 20 : 10)],
      subscribeBars: () => () => {
        if (!redirected) {
          redirected = true;
          replacement = controller.load({ ...req, symbol: 'CCC' });
        }
      },
    });
    controllers.push(controller);
    await controller.load(req);
    await controller.load({ ...req, symbol: 'BBB' });
    await replacement;
    expect(controller.getState().request?.symbol).toBe('CCC');
    expect(controller.bars()[0].close).toBe(30);
  });


  it('keeps a paused display stable across concurrent paging, repair and retention', async () => {
    let resolveRefresh!: (bars: Bar[]) => void;
    let resolvePage!: (page: { bars: Bar[]; hasMore: boolean }) => void;
    let calls = 0;
    const controller = new DataLoadingController({
      getBars: () => ++calls === 1 ? Promise.resolve([bar(200), bar(300)])
        : new Promise<Bar[]>(resolve => { resolveRefresh = resolve; }),
      getBarsPage: () => new Promise(resolve => { resolvePage = resolve; }),
    }, { now: () => 300, maxBars: 4 });
    controllers.push(controller);
    await controller.load({ ...req, from: 200 });
    const page = controller.loadMore();
    controller.setPaused(true);
    const repair = controller.refresh();
    controller.pushBar(bar(400, 40));
    resolvePage({ bars: [bar(50), bar(100)], hasMore: true });
    await page;
    resolveRefresh([bar(200, 20), bar(300, 30)]);
    await repair;
    expect(controller.getState().bars.map(value => value.time)).toEqual([200, 300]);
    expect(controller.getState()).toMatchObject({ hasMore: true, historyStatus: 'limited' });
    controller.setPaused(false);
    expect(controller.getState().bars.map(value => [value.time, value.close])).toEqual([[100, 10], [200, 20], [300, 30], [400, 40]]);
  });


  it('does not resume an obsolete refresh after its abort callback changes context', async () => {
    let refreshCalls = 0;
    let replacement: Promise<readonly Bar[]> | undefined;
    const controller = new DataLoadingController({
      getBars: request => {
        if (request.symbol === 'CCC') return Promise.resolve([bar(200, 30)]);
        if (!request.noCache) return Promise.resolve([bar(200)]);
        if (++refreshCalls === 1) {
          request.signal?.addEventListener('abort', () => {
            replacement = controller.load({ ...req, symbol: 'CCC' });
          }, { once: true });
          return new Promise(() => {});
        }
        return Promise.resolve([bar(200, 20)]);
      },
    }, { now: () => 300 });
    controllers.push(controller);
    await controller.load(req);
    const first = controller.refresh();
    const second = controller.refresh();
    await Promise.all([first, second, replacement]);
    expect(controller.getState()).toMatchObject({ request: { symbol: 'CCC' }, status: 'ready' });
    expect(controller.getState().bars).toEqual([bar(200, 30)]);
  });

});
