import { useTheme } from 'next-themes';
import React, { useEffect, useRef, useState } from 'react';

/* eslint-disable @typescript-eslint/no-explicit-any */

async function loadLib(): Promise<any> {
  return import('../lib/oac/openalgo-charts.all.mjs');
}

/** Deterministic random-walk bars (line/area read `close`; O/H/L mirror it). */
function walk(seed: number, n: number, startTime: number, intervalSec: number, start = 100, vol = 1): any[] {
  let s = seed >>> 0;
  let p = start;
  const rnd = (): number => { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; };
  const out: any[] = [];
  for (let i = 0; i < n; i++) {
    p = Math.max(1, p + (rnd() - 0.5) * 2 * vol);
    const v = Math.round(p * 100) / 100;
    out.push({ time: startTime + i * intervalSec, open: v, high: v, low: v, close: v, volume: Math.round(1000 + rnd() * 9000) });
  }
  return out;
}

interface Tab { label: string; key: string; }
type BuildFn = (el: HTMLElement, lib: any, tab: string) => any;

function InteractiveChart({ title, tabs, build, height = 320, code, followSiteTheme = false }: { title: string; tabs?: Tab[]; build: BuildFn; height?: number; code?: string; followSiteTheme?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const [tab, setTab] = useState(tabs?.[0]?.key ?? '');
  const [err, setErr] = useState<string | null>(null);
  const [showCode, setShowCode] = useState(false);
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme !== 'light';

  // A card whose tabs are the palettes opens on the one the page is using, or a
  // light page would open on a dark chart. It is set after mount rather than as
  // the initial state: the static export renders before the theme is known, and
  // hydration does not repair a class that differs from the server's markup.
  useEffect(() => {
    if (followSiteTheme) setTab(dark ? 'dark' : 'light');
  }, [followSiteTheme, dark]);

  useEffect(() => {
    let chart: any;
    let cancelled = false;
    (async () => {
      try {
        const lib = await loadLib();
        if (cancelled || !ref.current) return;
        ref.current.innerHTML = '';
        // Every build calls `createChart` bare, so without this the card renders
        // the library's light default as a white hole in a dark docs page - and
        // the HTML legends layered on top, coloured for the page rather than the
        // canvas, came out invisible against it. Wrap once here instead of asking
        // thirteen builds to remember; a build passing its own `theme` still wins,
        // since caller options spread last.
        // A copy, not `Object.create(lib)`: a module namespace exposes its exports
        // as getter-only accessors, so an override on a child object throws.
        const create = lib.createChart;
        const themed = {
          ...lib,
          createChart: (host: HTMLElement, opts?: Record<string, unknown>) =>
            create(host, { theme: dark ? lib.darkTheme : lib.lightTheme, ...opts }),
        };
        chart = build(ref.current, themed, tab);
      } catch (e: any) {
        setErr(e?.message ?? String(e));
      }
    })();
    return () => { cancelled = true; try { chart?.destroy?.(); } catch { /* ignore */ } };
  }, [tab, build, dark]);

  return (
    <div className="oac-card">
      <div className="oac-card__head">
        <h3>{title}</h3>
        {code && (
          <button className="oac-code-btn" onClick={() => setShowCode((v) => !v)}>
            {showCode ? 'Hide code' : 'Get this chart'}
          </button>
        )}
      </div>
      {tabs && (
        <div className="oac-tabs">
          {tabs.map((t) => (
            <button key={t.key} className={t.key === tab ? 'oac-tab oac-tab--on' : 'oac-tab'} onClick={() => setTab(t.key)}>{t.label}</button>
          ))}
        </div>
      )}
      <div className="oac-card__chart" ref={ref} style={{ height }} />
      {code && showCode && <pre className="oac-card__code"><code>{code}</code></pre>}
      {err && <div className="oac-example__err" style={{ position: 'static', padding: '8px 0' }}>Demo error: {err}</div>}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Range switcher                                                             */
const RANGES: Record<string, { n: number; iv: number }> = {
  '1D': { n: 78, iv: 300 }, '1W': { n: 120, iv: 3600 }, '1M': { n: 160, iv: 14400 }, '1Y': { n: 300, iv: 86400 },
};
const buildRange: BuildFn = (el, lib, tab) => {
  const chart = lib.createChart(el);
  const cfg = RANGES[tab] ?? RANGES['1D'];
  const bars = walk(7, cfg.n, 1700000000, cfg.iv, 26, 0.12);
  chart.addSeries('area', { style: { color: '#4f8cff', lineWidth: 2, areaTopColor: 'rgba(79,140,255,0.45)', areaBottomColor: 'rgba(79,140,255,0)' } }).setData(bars);
  chart.timeScale.fitContent(bars.length);
  return chart;
};
export const RangeSwitcherCard = () => (
  <InteractiveChart title="Range switcher" build={buildRange}
    tabs={[{ label: '1D', key: '1D' }, { label: '1W', key: '1W' }, { label: '1M', key: '1M' }, { label: '1Y', key: '1Y' }]} />
);

/* -------------------------------------------------------------------------- */
/* Legend                                                                     */
const buildLegend: BuildFn = (el, lib, tab) => {
  const chart = lib.createChart(el);
  const bars = walk(11, 170, 1700000000, 86400, 80, 1.1);
  chart.addSeries('area', { style: { color: '#22c1a4', lineWidth: 2, areaTopColor: 'rgba(34,193,164,0.4)', areaBottomColor: 'rgba(34,193,164,0)' } }).setData(bars);
  el.style.position = 'relative';
  const legend = document.createElement('div');
  legend.className = 'oac-legend';
  el.appendChild(legend);
  const fmt = (t: number): string => { const d = new Date(t * 1000); return d.getUTCFullYear() + ' - ' + (d.getUTCMonth() + 1) + ' - ' + d.getUTCDate(); };
  const render = (b: any): void => {
    if (!b) { legend.innerHTML = ''; return; }
    if (tab === '3') {
      legend.innerHTML = '<div class="oac-legend__title">AEROSPACE</div><div class="oac-legend__big">' + b.close.toFixed(2) + '</div><div class="oac-legend__sub">' + fmt(b.time) + '</div>';
    } else {
      legend.innerHTML = '<span class="oac-legend__title">AEROSPACE</span> &nbsp; <span class="oac-legend__big" style="font-size:1.1rem">' + b.close.toFixed(2) + '</span>';
    }
  };
  render(bars[bars.length - 1]);
  chart.subscribeCrosshairMove((e: any) => render(e.bar ?? bars[bars.length - 1]));
  chart.timeScale.fitContent(bars.length);
  return chart;
};
export const LegendCard = () => (
  <InteractiveChart title="Legend" build={buildLegend}
    tabs={[{ label: '1-line legend', key: '1' }, { label: '3-line legend', key: '3' }]} />
);

/* -------------------------------------------------------------------------- */
/* Series compare                                                             */
const COMPARE_COLORS = ['#4f8cff', '#ec407a', '#26a69a', '#f5a623', '#ab47bc'];
const buildCompare: BuildFn = (el, lib, tab) => {
  const n = parseInt(tab, 10) || 2;
  const chart = lib.createChart(el);
  el.style.position = 'relative';
  const legend = document.createElement('div');
  legend.className = 'oac-legend oac-legend--multi';
  el.appendChild(legend);
  let html = '';
  for (let i = 0; i < n; i++) {
    const bars = walk(3 + i * 29, 120, 1700000000, 86400, 25 + i * 12, 1.6);
    chart.addSeries('line', { style: { color: COMPARE_COLORS[i], lineWidth: 2 } }).setData(bars);
    html += '<div><span class="oac-dot" style="background:' + COMPARE_COLORS[i] + '"></span>Series ' + (i + 1) + ' <b>' + bars[bars.length - 1].close.toFixed(2) + '</b></div>';
  }
  legend.innerHTML = html;
  chart.timeScale.fitContent(120);
  return chart;
};
export const SeriesCompareCard = () => (
  <InteractiveChart title="Series compare" build={buildCompare}
    tabs={[{ label: '1 series', key: '1' }, { label: '2 series', key: '2' }, { label: '3 series', key: '3' }, { label: '4 series', key: '4' }, { label: '5 series', key: '5' }]} />
);

/* -------------------------------------------------------------------------- */
/* Indicators & markers                                                       */
const buildIndicators: BuildFn = (el, lib, tab) => {
  const chart = lib.createChart(el);
  const bars = lib.generateBars(1700000000, 140, 86400);
  const price = chart.addSeries('candlestick');
  price.setData(bars);
  if (tab === 'volume') {
    chart.addSeries('histogram', { paneIndex: 1, style: { color: '#3b5168' } })
      .setData(bars.map((b: any) => ({ time: b.time, value: b.volume, close: b.volume })));
  } else if (tab === 'markers') {
    const m = price.createMarkers();
    m.setMarkers([
      { time: bars[34].time, position: 'belowBar', shape: 'arrowUp', size: 'medium', color: '#26a69a', text: 'BUY' },
      { time: bars[96].time, position: 'aboveBar', shape: 'arrowDown', size: 'medium', color: '#ef5350', text: 'SELL' },
    ]);
  } else {
    chart.addSeries('line', { style: { color: '#f5a623', lineWidth: 2 } }).setData(lib.emaSeries(bars, 21));
  }
  chart.timeScale.fitContent(bars.length);
  return chart;
};
export const IndicatorsCard = () => (
  <InteractiveChart title="Indicators & markers" build={buildIndicators}
    tabs={[{ label: 'Volume', key: 'volume' }, { label: 'Series markers', key: 'markers' }, { label: 'Moving average', key: 'ma' }]} />
);

/* -------------------------------------------------------------------------- */
/* Price scale (min / avg / max labelled price lines)                         */
const buildPriceScale: BuildFn = (el, lib, _tab) => {
  const chart = lib.createChart(el);
  const bars = walk(9, 160, 1700000000, 86400, 60, 1.4);
  chart.addSeries('area', { style: { color: '#4f8cff', lineWidth: 2, areaTopColor: 'rgba(79,140,255,0.4)', areaBottomColor: 'rgba(79,140,255,0)' } }).setData(bars);
  const closes = bars.map((b: any) => b.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const avg = closes.reduce((a: number, b: number) => a + b, 0) / closes.length;
  chart.addPriceLine({ price: max, color: '#26a69a', lineWidth: 1, dashed: true, id: 'max', leftLabel: 'maximum price' });
  chart.addPriceLine({ price: avg, color: '#8892a0', lineWidth: 1, dashed: true, id: 'avg', leftLabel: 'average price' });
  chart.addPriceLine({ price: min, color: '#ef5350', lineWidth: 1, dashed: true, id: 'min', leftLabel: 'minimum price' });
  chart.timeScale.fitContent(bars.length);
  return chart;
};
export const PriceScaleCard = () => (
  <InteractiveChart title="Price scale" build={buildPriceScale} />
);

/* -------------------------------------------------------------------------- */
/* Custom chart types (stacked area / HLC area)                               */
const buildCustomTypes: BuildFn = (el, lib, tab) => {
  const chart = lib.createChart(el);
  if (tab === 'hlc') {
    const bars = lib.generateBars(1700000000, 160, 86400);
    chart.addSeries('hlc-area', { style: { color: '#4f8cff', lineWidth: 2, areaTopColor: 'rgba(79,140,255,0.35)', areaBottomColor: 'rgba(79,140,255,0)' } }).setData(bars);
    chart.timeScale.fitContent(bars.length);
    return chart;
  }
  // Stacked area: three positive layers, cumulated so the bands stack.
  const n = 120;
  const a = walk(1, n, 1700000000, 86400, 20, 0.7).map((b: any) => b.close);
  const b = walk(2, n, 1700000000, 86400, 15, 0.6).map((x: any) => x.close);
  const c = walk(3, n, 1700000000, 86400, 10, 0.5).map((x: any) => x.close);
  const stack = (top: number[]): any[] => top.map((v, i) => ({ time: 1700000000 + i * 86400, open: v, high: v, low: v, close: v }));
  const cumC = a.map((v, i) => v + b[i] + c[i]);
  const cumB = a.map((v, i) => v + b[i]);
  const cumA = a.slice();
  // draw largest first so each smaller band paints over the lower part
  chart.addSeries('area', { style: { color: '#4f8cff', lineWidth: 1, areaTopColor: 'rgba(79,140,255,0.5)', areaBottomColor: 'rgba(79,140,255,0.5)' } }).setData(stack(cumC));
  chart.addSeries('area', { style: { color: '#22c1a4', lineWidth: 1, areaTopColor: 'rgba(34,193,164,0.55)', areaBottomColor: 'rgba(34,193,164,0.55)' } }).setData(stack(cumB));
  chart.addSeries('area', { style: { color: '#f5a623', lineWidth: 1, areaTopColor: 'rgba(245,166,35,0.6)', areaBottomColor: 'rgba(245,166,35,0.6)' } }).setData(stack(cumA));
  chart.timeScale.fitContent(n);
  return chart;
};
export const CustomTypesCard = () => (
  <InteractiveChart title="Custom chart types" build={buildCustomTypes}
    tabs={[{ label: 'Stacked area', key: 'stacked' }, { label: 'HLC area', key: 'hlc' }]} />
);

/* -------------------------------------------------------------------------- */
/* Scales formatting (custom price formatter)                                 */
const PRICE_FORMATTERS: Record<string, ((p: number) => string) | undefined> = {
  currency: (p: number) => '$' + p.toFixed(2),
  rupee: (p: number) => 'Rs ' + p.toFixed(2),
  plain: undefined,
};
const buildScalesFormat: BuildFn = (el, lib, tab) => {
  const fmt = PRICE_FORMATTERS[tab];
  const chart = lib.createChart(el, fmt ? { priceFormatter: fmt } : {});
  const bars = walk(5, 160, 1700000000, 86400, 120, 1.3);
  chart.addSeries('area', { style: { color: '#4f8cff', lineWidth: 2, areaTopColor: 'rgba(79,140,255,0.4)', areaBottomColor: 'rgba(79,140,255,0)' } }).setData(bars);
  chart.timeScale.fitContent(bars.length);
  return chart;
};
export const ScalesFormatCard = () => (
  <InteractiveChart title="Scales formatting" build={buildScalesFormat}
    tabs={[{ label: 'Currency ($)', key: 'currency' }, { label: 'Rupee (Rs)', key: 'rupee' }, { label: 'Plain', key: 'plain' }]} />
);

/* -------------------------------------------------------------------------- */
/* Scales config (grid line visibility)                                       */
const GRID_MODES: Record<string, { vertLines: boolean; horzLines: boolean }> = {
  both: { vertLines: true, horzLines: true },
  horizontal: { vertLines: false, horzLines: true },
  none: { vertLines: false, horzLines: false },
};
const buildScalesConfig: BuildFn = (el, lib, tab) => {
  const chart = lib.createChart(el, { grid: GRID_MODES[tab] ?? GRID_MODES.both });
  const bars = lib.generateBars(1700000000, 160, 86400);
  chart.addSeries('candlestick').setData(bars);
  chart.timeScale.fitContent(bars.length);
  return chart;
};
export const ScalesConfigCard = () => (
  <InteractiveChart title="Scales config" build={buildScalesConfig}
    tabs={[{ label: 'Grid: both', key: 'both' }, { label: 'Horizontal', key: 'horizontal' }, { label: 'None', key: 'none' }]} />
);

/* -------------------------------------------------------------------------- */
/* Data (realtime updates / whitespaces)                                      */
const buildData: BuildFn = (el, lib, tab) => {
  const chart = lib.createChart(el);
  if (tab === 'whitespace') {
    const raw = walk(7, 170, 1700000000, 86400, 60, 1.2);
    // Null out OHLC for two stretches -> whitespace items break the line at gaps.
    const data = raw.map((b: any, i: number) => ((i >= 60 && i < 74) || (i >= 120 && i < 130) ? { time: b.time } : b));
    // A line series breaks cleanly at whitespace items ({ time } with no OHLC).
    chart.addSeries('line', { style: { color: '#4f8cff', lineWidth: 2 } }).setData(data);
    chart.timeScale.fitContent(raw.length);
    return chart;
  }
  // Realtime: mutate the last candle a few times, then roll a new one.
  const bars = lib.generateBars(1700000000, 120, 3600);
  const s = chart.addSeries('candlestick');
  s.setData(bars);
  chart.timeScale.fitContent(bars.length);
  let last: any = { ...bars[bars.length - 1] };
  let t = last.time;
  let seed = 99;
  let ticks = 0;
  const rnd = (): number => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
  const id = setInterval(() => {
    const move = (rnd() - 0.5) * 1.6;
    if (ticks >= 5) {
      t += 3600;
      last = { time: t, open: last.close, high: last.close, low: last.close, close: last.close + move };
      ticks = 0;
    } else {
      const c = last.close + move;
      last = { time: last.time, open: last.open, high: Math.max(last.high, c), low: Math.min(last.low, c), close: c };
      ticks += 1;
    }
    s.update(last);
  }, 650);
  const origDestroy = chart.destroy.bind(chart);
  chart.destroy = (): void => { clearInterval(id); origDestroy(); };
  return chart;
};
export const DataCard = () => (
  <InteractiveChart title="Data" build={buildData}
    tabs={[{ label: 'Realtime updates', key: 'realtime' }, { label: 'Whitespaces', key: 'whitespace' }]} />
);

/* -------------------------------------------------------------------------- */
/* Custom plugins (envelope-band IPrimitive + partial price line)             */
const buildPlugins: BuildFn = (el, lib, _tab) => {
  const chart = lib.createChart(el);
  const bars = lib.generateBars(1700000000, 140, 3600);
  chart.addSeries('candlestick').setData(bars);
  // EMA(21) as a numeric array aligned to bar order (fresh series -> logical index i).
  const closes = bars.map((b: any) => b.close);
  const k = 2 / (21 + 1);
  let e = closes[0];
  const ema = closes.map((c: number) => (e = c * k + e * (1 - k)));
  const offset = (Math.max(...closes) - Math.min(...closes)) * 0.06;
  // A minimal IPrimitive: a translucent envelope band around the EMA.
  const band = {
    zOrder: (): string => 'normal',
    autoscaleInfo: (): { min: number; max: number } => ({ min: Math.min(...ema) - offset, max: Math.max(...ema) + offset }),
    draw: (ctx: any, rc: any): void => {
      const yy = (p: number): number => rc.priceScale.priceToY(p) * rc.dpr;
      const xx = (i: number): number => rc.timeScale.indexToX(i) * rc.dpr;
      ctx.save();
      ctx.beginPath();
      for (let i = 0; i < ema.length; i++) { const x = xx(i), y = yy(ema[i] + offset); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
      for (let i = ema.length - 1; i >= 0; i--) ctx.lineTo(xx(i), yy(ema[i] - offset));
      ctx.closePath();
      ctx.fillStyle = 'rgba(79,140,255,0.14)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(79,140,255,0.6)';
      ctx.lineWidth = rc.dpr;
      for (const sign of [1, -1]) {
        ctx.beginPath();
        for (let i = 0; i < ema.length; i++) { const x = xx(i), y = yy(ema[i] + sign * offset); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
        ctx.stroke();
      }
      ctx.restore();
    },
  };
  chart.addPrimitive(band);
  chart.addSeries('line', { style: { color: '#4f8cff', lineWidth: 2 } })
    .setData(ema.map((v: number, i: number) => ({ time: bars[i].time, open: v, high: v, low: v, close: v })));
  // Partial price line: spans only the rightmost 35% of the plot.
  chart.addPriceLine({ price: closes[closes.length - 1], color: '#f5a623', lineWidth: 1, dashed: false, id: 'partial', extentFromRight: 0.35, leftLabel: 'partial line' });
  chart.timeScale.fitContent(bars.length);
  return chart;
};
export const CustomPluginsCard = () => (
  <InteractiveChart title="Custom plugins" build={buildPlugins} />
);

/* -------------------------------------------------------------------------- */
/* Chart type switcher                                                        */
const TYPE_BY_TAB: Record<string, string> = {
  candles: 'candlestick', line: 'line', bars: 'bar', area: 'area', baseline: 'baseline', step: 'step',
};
const buildChartType: BuildFn = (el, lib, tab) => {
  const chart = lib.createChart(el);
  const bars = lib.generateBars(1700000000, 160, 86400);
  const type = TYPE_BY_TAB[tab] ?? 'candlestick';
  const style = type === 'area'
    ? { color: '#4f8cff', lineWidth: 2, areaTopColor: 'rgba(79,140,255,0.4)', areaBottomColor: 'rgba(79,140,255,0)' }
    : (type === 'line' || type === 'step') ? { color: '#4f8cff', lineWidth: 2 }
    : {};
  chart.addSeries(type, { style }).setData(bars);
  chart.timeScale.fitContent(bars.length);
  return chart;
};
const CHART_TYPE_CODE = `const chart = createChart(el);
const bars = generateBars(1700000000, 160, 86400);

// One call, any registered type: candlestick | line | bar | area | baseline | step
chart.addSeries('candlestick').setData(bars);
chart.timeScale.fitContent(bars.length);`;
export const ChartTypeCard = () => (
  <InteractiveChart title="Chart type" build={buildChartType} code={CHART_TYPE_CODE}
    tabs={[{ label: 'Candles', key: 'candles' }, { label: 'Line', key: 'line' }, { label: 'Bars', key: 'bars' }, { label: 'Area', key: 'area' }, { label: 'Baseline', key: 'baseline' }, { label: 'Step', key: 'step' }]} />
);

/* -------------------------------------------------------------------------- */
/* Custom theme switcher (theme drives chrome + series defaults)              */
const buildTheme: BuildFn = (el, lib, tab) => {
  const colorful = {
    ...lib.darkTheme,
    background: '#0b0710', grid: '#1a1030', axisText: '#a99bd6', axisLine: '#33224d', crosshair: '#8b7bb8',
    lineColor: '#8b5cf6', areaTopColor: 'rgba(139,92,246,0.5)', areaBottomColor: 'rgba(139,92,246,0)',
    upColor: '#a855f7', downColor: '#f472b6', wickUpColor: '#a855f7', wickDownColor: '#f472b6',
    lastPriceUp: '#8b5cf6', lastPriceDown: '#f472b6', lastPriceText: '#0b0710',
  };
  const theme = tab === 'light' ? lib.lightTheme : tab === 'colorful' ? colorful : lib.darkTheme;
  const chart = lib.createChart(el, { theme });
  const bars = walk(5, 200, 1700000000, 86400, 45, 1.25);
  // No per-series style -> the area series reads its colors from the active theme.
  chart.addSeries('area').setData(bars);
  chart.timeScale.fitContent(bars.length);
  return chart;
};
const THEME_CODE = `import { createChart, darkTheme, lightTheme } from 'openalgo-charts';

// A theme drives chrome + series defaults. Override any tokens you like.
const colorful = { ...darkTheme, background: '#0b0710', lineColor: '#8b5cf6',
  areaTopColor: 'rgba(139,92,246,0.5)', areaBottomColor: 'rgba(139,92,246,0)' };

const chart = createChart(el, { theme: colorful }); // or darkTheme / lightTheme
chart.addSeries('area').setData(bars); // style-less area inherits theme colors`;
export const ThemeCard = () => (
  <InteractiveChart title="Custom theme" build={buildTheme} code={THEME_CODE} followSiteTheme
    tabs={[{ label: 'Dark', key: 'dark' }, { label: 'Light', key: 'light' }, { label: 'Colorful', key: 'colorful' }]} />
);

/* -------------------------------------------------------------------------- */
/* Data tooltip (floating / tracking / magnifier)                             */
const buildTooltip: BuildFn = (el, lib, tab) => {
  const chart = lib.createChart(el);
  const bars = walk(23, 160, 1551398400, 86400, 78, 0.7);
  chart.addSeries('area', { style: { color: '#ef5350', lineWidth: 2, areaTopColor: 'rgba(239,83,80,0.35)', areaBottomColor: 'rgba(239,83,80,0)' } }).setData(bars);
  el.style.position = 'relative';
  const tip = document.createElement('div');
  tip.style.display = 'none';
  el.appendChild(tip);
  const dot = document.createElement('div');
  dot.className = 'oac-tip-dot';
  dot.style.display = 'none';
  el.appendChild(dot);
  const fmtDate = (t: number): string => { const d = new Date(t * 1000); return d.getUTCFullYear() + '-' + (d.getUTCMonth() + 1) + '-' + d.getUTCDate(); };
  chart.subscribeCrosshairMove((e: any) => {
    if (!e.bar || !e.point) { tip.style.display = 'none'; dot.style.display = 'none'; return; }
    tip.style.display = 'block';
    const y = chart.priceToCoordinate(e.bar.close, 0);
    if (tab === 'magnifier') {
      tip.className = 'oac-tip oac-tip--mag';
      tip.textContent = e.bar.close.toFixed(2);
      tip.style.left = (e.point.x + 18) + 'px'; tip.style.top = (e.point.y - 12) + 'px';
      dot.style.display = 'none';
    } else if (tab === 'tracking') {
      tip.className = 'oac-tip oac-tip--track';
      tip.innerHTML = '<span class="oac-tip__name">Apple Inc.</span> &nbsp; <b class="oac-tip__strong">' + e.bar.close.toFixed(2) + '</b> &nbsp; <span class="oac-tip__date">' + fmtDate(e.bar.time) + '</span>';
      tip.style.left = Math.min(Math.max(e.point.x, 90), el.clientWidth - 90) + 'px'; tip.style.top = '10px';
      dot.style.display = 'none';
    } else {
      tip.className = 'oac-tip';
      tip.innerHTML = '<div class="oac-tip__name">Apple Inc.</div><div class="oac-tip__val">' + e.bar.close.toFixed(2) + '</div><div class="oac-tip__date">' + fmtDate(e.bar.time) + '</div>';
      tip.style.left = e.point.x + 'px'; tip.style.top = (y - tip.offsetHeight - 14) + 'px';
      dot.style.left = e.point.x + 'px'; dot.style.top = y + 'px'; dot.style.display = 'block';
    }
  });
  chart.timeScale.fitContent(bars.length);
  return chart;
};
const TOOLTIP_CODE = `const chart = createChart(el);
chart.addSeries('area', { style: { color: '#ef5350', lineWidth: 2 } }).setData(bars);

// A floating tooltip anchored to the hovered bar, driven by the crosshair.
const tip = document.createElement('div');
el.style.position = 'relative';
el.appendChild(tip);

chart.subscribeCrosshairMove((e) => {
  if (!e.bar || !e.point) { tip.style.display = 'none'; return; }
  const y = chart.priceToCoordinate(e.bar.close, 0);   // price -> container px
  tip.textContent = e.bar.close.toFixed(2);
  tip.style.left = e.point.x + 'px';                    // e.point is the crosshair
  tip.style.top = (y - tip.offsetHeight - 14) + 'px';
  tip.style.display = 'block';
});`;
export const DataTooltipCard = () => (
  <InteractiveChart title="Data tooltip" build={buildTooltip} code={TOOLTIP_CODE}
    tabs={[{ label: 'Floating tooltip', key: 'floating' }, { label: 'Tracking tooltip', key: 'tracking' }, { label: 'Magnifier tooltip', key: 'magnifier' }]} />
);

/* -------------------------------------------------------------------------- */
/* Event markers (dividend / earnings / split / expiry)                       */
const buildEventMarkers: BuildFn = (el, lib, _tab) => {
  const chart = lib.createChart(el);
  const bars = lib.generateBars(1700000000, 160, 86400);
  chart.addSeries('candlestick').setData(bars);
  const em = chart.addEventMarkers(0);
  em.setEvents([
    { time: bars[26].time, type: 'dividend', label: 'D', id: 'div' },
    { time: bars[64].time, type: 'earnings', label: 'E', id: 'ern' },
    { time: bars[104].time, type: 'split', label: 'S', id: 'spl' },
    { time: bars[140].time, type: 'news', label: 'X', color: '#ef5350', id: 'exp' },
  ]);
  el.style.position = 'relative';
  const legend = document.createElement('div');
  legend.className = 'oac-legend oac-legend--multi';
  // One element per entry: the legend is a flex column, so a loose swatch and
  // label became separate rows, each swatch sitting above its own name.
  legend.innerHTML = '<span><span class="oac-dot" style="background:#26a69a"></span>Dividend</span><span><span class="oac-dot" style="background:#f0a020"></span>Earnings</span><span><span class="oac-dot" style="background:#4f8cff"></span>Split</span><span><span class="oac-dot" style="background:#ef5350"></span>Expiry</span>';
  el.appendChild(legend);
  chart.timeScale.fitContent(bars.length);
  return chart;
};
const EVENTS_CODE = `const chart = createChart(el);
chart.addSeries('candlestick').setData(bars);

// Time-anchored badges near the axis (corporate actions, F&O expiry).
const events = chart.addEventMarkers();
events.setEvents([
  { time: t1, type: 'dividend', label: 'D' },
  { time: t2, type: 'earnings', label: 'E' },
  { time: t3, type: 'split',    label: 'S' },
  { time: t4, type: 'news',     label: 'X', color: '#ef5350' }, // expiry
]);`;
export const EventMarkersCard = () => (
  <InteractiveChart title="Event markers" build={buildEventMarkers} code={EVENTS_CODE} />
);

/* -------------------------------------------------------------------------- */
/* Positions & orders (chart.trading)                                         */
const buildPositions: BuildFn = (el, lib, tab) => {
  const chart = lib.createChart(el);
  const bars = lib.generateBars(1700000000, 140, 3600);
  chart.addSeries('candlestick').setData(bars);
  const last = bars[bars.length - 1].close;
  const long = tab !== 'short';
  chart.trading.setPositions([
    { id: 'p1', side: long ? 'long' : 'short', entryPrice: last * (long ? 0.985 : 1.015), size: 1.5, pnlText: long ? '+$1,240' : '-$320', pnlPercent: long ? '+2.4%' : '-0.6%' },
  ]);
  chart.trading.setOrders([
    { id: 'o1', type: 'limit', side: long ? 'buy' : 'sell', price: last * (long ? 0.95 : 1.05), size: 1 },
    { id: 'tp', type: 'limit', side: long ? 'sell' : 'buy', price: last * (long ? 1.04 : 0.96), size: 1.5, parentId: 'p1', bracketRole: 'tp' },
    { id: 'sl', type: 'stop', side: long ? 'sell' : 'buy', price: last * (long ? 0.93 : 1.07), size: 1.5, parentId: 'p1', bracketRole: 'sl' },
  ]);
  chart.timeScale.fitContent(bars.length);
  return chart;
};
export const PositionsCard = () => (
  <InteractiveChart title="Positions & orders" build={buildPositions}
    tabs={[{ label: 'Long', key: 'long' }, { label: 'Short', key: 'short' }]} />
);

/* -------------------------------------------------------------------------- */
/* Trade markers (chart.trading)                                              */
const buildTradeMarkers: BuildFn = (el, lib, tab) => {
  const chart = lib.createChart(el);
  const bars = lib.generateBars(1700000000, 120, 3600);
  chart.addSeries('candlestick').setData(bars);
  const variant = tab; // chevron | bubble | count
  const idxs = [15, 28, 42, 55, 70, 85, 100];
  const trades = idxs.map((i, k) => ({
    id: 'f' + k, side: k % 2 ? 'sell' : 'buy', price: bars[i].close, size: 1 + k, timestamp: bars[i].time * 1000, variant,
  }));
  if (variant === 'count') {
    // extra fills on the same bar+side so the count aggregates
    trades.push({ id: 'fx1', side: 'buy', price: bars[42].close * 1.005, size: 2, timestamp: bars[42].time * 1000, variant: 'count' });
    trades.push({ id: 'fx2', side: 'buy', price: bars[42].close * 0.995, size: 3, timestamp: bars[42].time * 1000, variant: 'count' });
  }
  chart.trading.setTrades(trades);
  chart.timeScale.fitContent(bars.length);
  return chart;
};
export const TradeMarkersCard = () => (
  <InteractiveChart title="Trade markers" build={buildTradeMarkers}
    tabs={[{ label: 'Chevron', key: 'chevron' }, { label: 'Bubble', key: 'bubble' }, { label: 'Count', key: 'count' }]} />
);
