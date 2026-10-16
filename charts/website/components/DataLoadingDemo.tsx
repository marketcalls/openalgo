import RunnableExample from './RunnableExample';
import { STOCK_BARS_SOURCE } from './synthetic-market';

const code = `${STOCK_BARS_SOURCE}
el.style.display = 'flex';
el.style.flexDirection = 'column';
const controls = document.createElement('div');
controls.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;padding:8px;min-height:48px;flex-shrink:0';
const stage = document.createElement('div');
stage.style.cssText = 'flex:1;min-height:0';
el.append(controls, stage);
const now = 1789093800;
const bars = stockBars(now - 359 * 60, 360, 60, 23800, 7133, 0.0005, 6500).map(bar => ({
  ...bar,
  volume: Math.round(bar.volume / 65) * 65,
}));
let failNext = false;
let empty = false;
let requests = 0;
let reconnect;
const counter = document.createElement('span');
counter.style.cssText = 'font:12px system-ui;padding:7px';
const source = {
  async getBars(request) {
    counter.textContent = 'History requests: ' + ++requests;
    await new Promise((resolve, reject) => {
      const stop = () => { clearTimeout(timer); reject(new Error('Cancelled')); };
      const timer = setTimeout(() => {
        request.signal?.removeEventListener('abort', stop);
        resolve();
      }, 700);
      request.signal?.addEventListener('abort', stop, { once: true });
      if (request.signal?.aborted) stop();
    });
    if (failNext) { failNext = false; throw new Error('Simulated connection failure'); }
    if (empty) return [];
    return bars.filter(bar => bar.time >= request.from && bar.time <= request.to);
  },
  async getBarsPage(request) {
    const older = await this.getBars({ ...request, from: bars[0].time });
    return { bars: older.slice(-60), hasMore: older.length > 60 };
  },
  subscribeBars(request, onBar, options) {
    reconnect = options.onResync;
    let seed = 0x31f2c7;
    const random = () => {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return seed / 4294967296;
    };
    const timer = setInterval(() => {
      if (empty) return;
      const last = bars[bars.length - 1];
      const close = Math.round((last.close + (random() - 0.5) * 2) * 20) / 20;
      const live = { ...last, close, high: Math.max(last.high, close),
        low: Math.min(last.low, close), volume: last.volume + (1 + Math.floor(random() * 6)) * 65 };
      bars[bars.length - 1] = live;
      onBar({ ...live });
    }, 800);
    return () => clearInterval(timer);
  },
};
const feed = lib.withBarCache(source, { now: () => now * 1000 });
const widget = lib.createWidget(stage, {
  feed, symbol: 'NIFTY SIM', exchange: 'NFO', interval: '1m', intervals: ['1m'],
  rail: false, indicators: false, lookbackBars: 120, loading: { now: () => now, pageSize: 60 },
  navigation: { defaultVisibleBars: 100 },
});
function button(label, action) {
  const button = document.createElement('button');
  button.textContent = label;
  button.type = 'button';
  button.style.cssText = 'padding:5px 9px;border:1px solid #64748b;border-radius:4px;font:12px system-ui';
  button.addEventListener('click', action);
  controls.appendChild(button);
}
button('Load older', () => void widget.dataController.loadMore());
button('Fail refresh', () => { failNext = true; void widget.reload(); });
button('Reconnect', () => reconnect?.());
button('Pause / resume display', () => {
  widget.dataController.setPaused(!widget.dataController.getState().paused);
});
button('Empty / restore', () => {
  empty = !empty;
  widget.setSymbol(empty ? 'EMPTY SIM' : 'NIFTY SIM', 'NFO');
});
controls.appendChild(counter);
return widget;`;

export default function DataLoadingDemo() {
  return <RunnableExample height={440} tiers={['widget']} code={code}
    caption="Simulated NIFTY around 23,800 with irregular candles, changing volume and live price ticks. Fail a refresh, then use Retry on the chart. Pause holds the display while live data continues; it does not start historical replay." />;
}
