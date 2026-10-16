import React, { useEffect, useRef, useState } from 'react';
import { highlight } from './highlight';
import { useSiteScheme } from './site-scheme';
import { OF_BAR_SECONDS, OF_TICK, type OrderFlowPrint } from './orderflow-market';

/* eslint-disable @typescript-eslint/no-explicit-any */
/** The base engine and the profile tier, loaded once for every chart on the page. */
export interface OrderFlowLib { core: any; profile: any }
export type Scheme = 'light' | 'dark';

let loading: Promise<OrderFlowLib> | null = null;
export function loadOrderFlowLib(): Promise<OrderFlowLib> {
  // A dozen charts share one download. A failed load is forgotten so the next
  // chart to mount can try again instead of inheriting the rejection.
  loading ??= Promise.all([
    import('../lib/oac/openalgo-charts.mjs'),
    import('../lib/oac/openalgo-charts.profile.mjs'),
  ]).then(([core, profile]) => ({ core, profile }), (error) => { loading = null; throw error; });
  return loading;
}

/** What a chart builder returns: how to apply the latest control state, and how to tear down. */
export interface ChartHandle<S> {
  apply: (state: S) => void;
  destroy: () => void;
}
export type ChartBuilder<S> = (lib: OrderFlowLib, host: HTMLDivElement, scheme: Scheme, state: S) => ChartHandle<S>;

/**
 * Mounts a chart once its frame comes near the viewport, rebuilds it when the
 * site theme or `rebuild` changes, re-applies control state as it changes and
 * destroys it on unmount. Charts far down the page cost nothing until the reader gets there.
 */
export function useOrderFlowChart<S>(build: ChartBuilder<S>, state: S, rebuild: number = 0) {
  const host = useRef<HTMLDivElement>(null);
  const handle = useRef<ChartHandle<S> | null>(null);
  const latest = useRef(state);
  latest.current = state;
  const builder = useRef(build);
  builder.current = build;
  const scheme = useSiteScheme();
  const [near, setNear] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const element = host.current;
    if (!element || near) return;
    if (typeof IntersectionObserver === 'undefined') { setNear(true); return; }
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) { setNear(true); observer.disconnect(); }
    }, { rootMargin: '400px 0px' });
    observer.observe(element);
    return () => observer.disconnect();
  }, [near]);

  useEffect(() => {
    if (!near || !scheme) return;
    let cancelled = false;
    let instance: ChartHandle<S> | null = null;
    setReady(false);
    setError(null);
    loadOrderFlowLib().then(lib => {
      if (cancelled || !host.current) return;
      try {
        instance = builder.current(lib, host.current, scheme, latest.current);
        handle.current = instance;
        setReady(true);
      } catch (cause) {
        instance?.destroy();
        instance = null;
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    }, cause => { if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause)); });
    return () => {
      cancelled = true;
      if (handle.current === instance) handle.current = null;
      try { instance?.destroy(); } catch { /* the chart is going away either way */ }
    };
  }, [near, scheme, rebuild]);

  const key = JSON.stringify(state);
  useEffect(() => {
    if (!ready || !handle.current) return;
    try { handle.current.apply(latest.current); } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  }, [key, ready]);

  return { host, ready, error, scheme };
}

/** Footprint colours that read on the site's own light and dark card backgrounds. */
export function siteColors(scheme: Scheme) {
  return scheme === 'dark'
    ? { buyColor: '#159d87', sellColor: '#cc374b', pocColor: '#ccd5e1', buyTextColor: '#8aefcd', sellTextColor: '#ffb2bd' }
    : { buyColor: '#147e71', sellColor: '#bf4e59', pocColor: '#525d65', buyTextColor: '#075344', sellTextColor: '#8d142c' };
}

/** The engine theme with the card background, so a chart sits in its frame instead of on a slab. */
export function chartTheme(core: any, scheme: Scheme) {
  return scheme === 'dark'
    ? { ...core.darkTheme, background: '#121212', grid: '#1a1a1a', axisLine: '#292929', lastPriceText: '#121212' }
    : { ...core.lightTheme, background: '#ffffff', grid: '#f2f3f5', axisLine: '#e4e4e4' };
}

/** Prints into one-minute footprint bars, the way a host feeds a live tape. */
export function aggregate(profile: any, prints: readonly OrderFlowPrint[], rowTicks = 1, minTradeSize = 0): any[] {
  const aggregator = new profile.FootprintAggregator({ mode: 'interval', seconds: OF_BAR_SECONDS }, OF_TICK, rowTicks, { minTradeSize });
  const bars: any[] = [];
  for (const print of prints) {
    const { bar, isNew } = aggregator.onTick(print);
    if (isNew) bars.push(bar); else bars[bars.length - 1] = bar;
  }
  return bars;
}

export interface Framing { minSpacing?: number; reserveLeft?: number; first?: number }
type Corner = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right';

export interface FootprintView {
  chart: any;
  footprint: any;
  setBars: (bars: readonly any[]) => void;
  /** Frame bars so each column is at least `minSpacing` wide, from `first` or else ending at the newest. */
  fit: (options?: Framing) => void;
  destroy: () => void;
}

/**
 * A chart with a transparent candle series under a footprint. The series gives
 * the time axis and price autoscale real OHLC; the footprint draws its own
 * slim candle beside each column.
 */
export function footprintView(lib: OrderFlowLib, host: HTMLDivElement, scheme: Scheme, options: Record<string, unknown> = {},
  chartOptions: Record<string, unknown> = {}, branding: Corner = 'bottom-left'): FootprintView {
  const { core, profile } = lib;
  const chart = core.createChart(host, {
    theme: chartTheme(core, scheme), priceAxisWidth: 62, timeAxisHeight: 26,
    timeScale: { maxBarSpacing: 260 }, priceScale: { minMove: OF_TICK, marginTop: 0.06, marginBottom: 0.06 },
    ...chartOptions,
  });
  let count = 0;
  let framing: Framing = {};
  try {
    // The mark moves out of the way of a table's labels or a profile on the left.
    if (branding !== 'bottom-left' && chart.brandingOptions()) chart.setBranding({ position: branding });
    const clear = 'rgba(0,0,0,0)';
    const price = chart.addSeries('candlestick', { style: {
      upColor: clear, downColor: clear, wickUpColor: clear, wickDownColor: clear, borderUpColor: clear, borderDownColor: clear,
    } });
    const footprint = new profile.Footprint({
      tickSize: OF_TICK, font: 10, radius: 1, widthFactor: 0.86, pocStyle: 'outline', ...siteColors(scheme), ...options,
    });
    chart.addPrimitive(footprint);
    const fit = (next: Framing = framing) => {
      framing = next;
      const width = chart.timeScale.width;
      if (!count || !(width > 0)) return;
      const { minSpacing = 104, reserveLeft = 0 } = next;
      const available = Math.max(80, width - reserveLeft);
      const visible = Math.max(1, Math.min(count, Math.floor(available / minSpacing - 0.25)));
      // Whole columns only: the oldest one shown starts at the left edge (or at
      // the reserved strip), so no half bar is cut off there.
      if (next.first !== undefined) {
        // An example about particular bars starts at them; nothing older sits in the reserved strip.
        const spacing = Math.max(minSpacing, available / visible);
        const from = Math.max(0, Math.min(next.first, count - visible)) - 0.5 - reserveLeft / spacing;
        chart.timeScale.setVisibleLogicalRange({ from, to: from + width / spacing });
      } else {
        const spacing = Math.max(minSpacing, available / (visible + 0.25));
        const to = count - 0.25;
        chart.timeScale.setVisibleLogicalRange({ from: to - width / spacing, to });
      }
    };
    // The chart measures its host itself; this only re-frames the columns when the width changes.
    let lastWidth = 0;
    const resize = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => {
      if (host.clientWidth !== lastWidth) { lastWidth = host.clientWidth; requestAnimationFrame(() => fit()); }
    });
    resize?.observe(host);
    return {
      chart, footprint, fit,
      setBars(bars) {
        count = bars.length;
        price.setData(bars.map(bar => ({ time: bar.time, open: bar.open, high: bar.high, low: bar.low, close: bar.close })));
        footprint.setBars(bars);
      },
      destroy() { resize?.disconnect(); chart.destroy(); },
    };
  } catch (error) {
    chart.destroy();
    throw error;
  }
}

/* -------------------------------------------------------------------------- */

export function Code({ code }: { code: string }) {
  return (
    <pre className="oac-of__code" aria-label="Key options">
      <code dangerouslySetInnerHTML={{ __html: highlight(code) }} />
    </pre>
  );
}

/** A row of buttons where exactly one is pressed. */
export function Segmented<T extends string | number>({ label, value, options, onChange, disabled }: {
  label: string; value: T; options: readonly (readonly [NoInfer<T>, string])[]; onChange: (value: NoInfer<T>) => void; disabled?: boolean;
}) {
  return (
    <div className="oac-of__group" role="group" aria-label={label}>
      <span className="oac-of__label">{label}</span>
      <div className="oac-of__segmented">
        {options.map(([id, text]) => (
          <button key={String(id)} type="button" aria-pressed={id === value} disabled={disabled} onClick={() => onChange(id)}>{text}</button>
        ))}
      </div>
    </div>
  );
}

/** Independent on and off switches, drawn as chips. */
export function Toggles<T extends string>({ label, value, options, onChange, disabled }: {
  label: string; value: readonly T[]; options: readonly (readonly [NoInfer<T>, string])[]; onChange: (value: NoInfer<T>[]) => void; disabled?: boolean;
}) {
  return (
    <div className="oac-of__group" role="group" aria-label={label}>
      <span className="oac-of__label">{label}</span>
      <div className="oac-of__chips">
        {options.map(([id, text]) => {
          const on = value.includes(id);
          return (
            <button key={id} type="button" aria-pressed={on} disabled={disabled}
              onClick={() => onChange(on ? value.filter(item => item !== id) : [...value, id])}>{text}</button>
          );
        })}
      </div>
    </div>
  );
}

export function Select<T extends string | number>({ label, value, options, onChange, disabled }: {
  label: string; value: T; options: readonly (readonly [NoInfer<T>, string])[]; onChange: (value: NoInfer<T>) => void; disabled?: boolean;
}) {
  return (
    <label className="oac-of__group">
      <span className="oac-of__label">{label}</span>
      <select className="oac-of__select" value={String(value)} disabled={disabled}
        onChange={event => {
          const picked = options.find(([id]) => String(id) === event.target.value);
          if (picked) onChange(picked[0]);
        }}>
        {options.map(([id, text]) => <option key={String(id)} value={String(id)}>{text}</option>)}
      </select>
    </label>
  );
}

/**
 * The frame every example shares: controls, the chart, an optional side panel
 * and the key options. The chart host is handed in from `useOrderFlowChart`.
 */
export function ChartFrame({ chart, height, controls, status, side, code, label }: {
  chart: ReturnType<typeof useOrderFlowChart<any>>;
  height: number;
  controls?: React.ReactNode;
  status?: React.ReactNode;
  side?: React.ReactNode;
  code: string;
  label: string;
}) {
  return (
    <section className="oac-of" aria-label={label}>
      {(controls || status) && (
        <div className="oac-of__bar">
          <div className="oac-of__controls">{controls}</div>
          {status && <div className="oac-of__status">{status}</div>}
        </div>
      )}
      <div className={side ? 'oac-of__body oac-of__body--side' : 'oac-of__body'}>
        <div className="oac-of__stage" style={{ height }}>
          <div className="oac-of__chart" ref={chart.host} role="img" aria-label={label} />
          {!chart.ready && !chart.error && <div className="oac-of__note">Loading live chart</div>}
          {chart.error && <div className="oac-of__note oac-of__note--error" role="alert">Demo error: {chart.error}</div>}
        </div>
        {side}
      </div>
      <Code code={code} />
      <OrderFlowStyles />
    </section>
  );
}

/**
 * One global block for every frame on the page; styled-jsx emits it once
 * however many frames render it. Kept here rather than in the site stylesheet
 * because nothing else on the site uses these classes.
 */
function OrderFlowStyles() {
  return (
    <style jsx global>{`
      .oac-of { margin: 1.1rem 0 2.2rem; min-width: 0; border: 1px solid var(--oac-card-border); border-radius: 12px; background: var(--oac-card); overflow: hidden; box-shadow: 0 4px 24px #00000006; }
      .oac-of__bar { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 10px 18px; padding: 11px 14px; border-bottom: 1px solid var(--oac-card-border); }
      .oac-of__controls { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 10px 16px; min-width: 0; }
      .oac-of__status { color: var(--oac-muted); font-size: 11px; font-variant-numeric: tabular-nums; white-space: nowrap; }
      .oac-of__status b { color: var(--oac-text); font-weight: 600; }
      .oac-of__group { display: grid; gap: 5px; min-width: 0; margin: 0; }
      .oac-of__label { font-size: 9.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--oac-muted); }
      .oac-of__segmented { display: inline-flex; flex-wrap: wrap; border: 1px solid var(--oac-card-border); border-radius: 7px; overflow: hidden; background: var(--oac-elevated); }
      .oac-of__segmented button { border: 0; border-right: 1px solid var(--oac-card-border); background: transparent; color: var(--oac-muted); padding: 5px 10px; font: 500 11.5px/1.35 var(--oac-font); cursor: pointer; white-space: nowrap; }
      .oac-of__segmented button:last-child { border-right: 0; }
      .oac-of__segmented button:hover { color: var(--oac-text); }
      .oac-of__segmented button[aria-pressed='true'] { background: var(--oac-card); color: var(--oac-text); box-shadow: inset 0 -2px 0 var(--oac-accent); }
      .oac-of__chips, .oac-of__actions { display: flex; flex-wrap: wrap; gap: 5px; }
      .oac-of__chips button, .oac-of__button { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--oac-card-border); border-radius: 6px; background: var(--oac-card); color: var(--oac-muted); padding: 4px 9px; font: 500 11.5px/1.35 var(--oac-font); cursor: pointer; white-space: nowrap; }
      .oac-of__chips button::before { content: ''; width: 7px; height: 7px; border-radius: 2px; border: 1px solid currentColor; opacity: .6; }
      .oac-of__chips button[aria-pressed='true'] { color: var(--oac-text); border-color: color-mix(in srgb, var(--oac-text) 35%, var(--oac-card-border)); background: var(--oac-elevated); }
      .oac-of__chips button[aria-pressed='true']::before { background: currentColor; opacity: 1; }
      .oac-of__chips button:hover, .oac-of__button:hover { color: var(--oac-text); border-color: var(--oac-muted); }
      .oac-of__button { min-height: 28px; padding: 4px 11px; color: var(--oac-text); background: var(--oac-elevated); }
      .oac-of__button--primary { min-width: 74px; justify-content: center; background: var(--oac-button-bg); color: var(--oac-button-text); border-color: var(--oac-button-bg); }
      .oac-of__button--primary:hover { background: var(--oac-button-hover); color: var(--oac-button-text); }
      .oac-of__select { appearance: none; -webkit-appearance: none; min-height: 28px; border: 1px solid var(--oac-card-border); border-radius: 6px; padding: 4px 28px 4px 9px; color: var(--oac-text); font: 500 11.5px/1.35 var(--oac-font); cursor: pointer;
        background: var(--oac-card) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%23888' stroke-width='1.4' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") no-repeat right 9px center; }
      .oac-of__select:hover { border-color: var(--oac-muted); }
      .oac-of__select option { background: var(--oac-card); color: var(--oac-text); }
      .oac-of button:disabled, .oac-of__select:disabled { opacity: .5; cursor: wait; }
      .oac-of button:focus-visible, .oac-of__select:focus-visible { outline: 2px solid var(--oac-accent); outline-offset: 1px; }
      .oac-of__body { display: grid; grid-template-columns: minmax(0, 1fr); }
      .oac-of__body--side { grid-template-columns: minmax(0, 1fr) minmax(220px, 27%); }
      .oac-of__stage { position: relative; min-width: 0; }
      .oac-of__chart { position: absolute; inset: 0; }
      .oac-of__note { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; padding: 0 16px; color: var(--oac-muted); font-size: 12px; text-align: center; pointer-events: none; }
      .oac-of__note--error { color: #ef4444; }
      .oac-of__side { display: flex; flex-direction: column; min-width: 0; min-height: 0; border-left: 1px solid var(--oac-card-border); }
      .oac-of__side h4 { margin: 0; padding: 10px 12px; font-size: 9.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--oac-muted); border-bottom: 1px solid var(--oac-card-border); }
      .oac-of__log { flex: 1; margin: 0; padding: 4px 0; list-style: none; overflow: auto; font-size: 11.5px; font-variant-numeric: tabular-nums; scrollbar-width: thin; scrollbar-color: var(--oac-card-border) transparent; }
      .oac-of__log::-webkit-scrollbar { width: 8px; }
      .oac-of__log::-webkit-scrollbar-track { background: transparent; }
      .oac-of__log::-webkit-scrollbar-thumb { background: var(--oac-card-border); border-radius: 4px; }
      .oac-of__log::-webkit-scrollbar-thumb:hover { background: var(--oac-muted); }
      .oac-of__log li { display: grid; grid-template-columns: auto 1fr; gap: 2px 10px; padding: 7px 12px; border-bottom: 1px solid color-mix(in srgb, var(--oac-card-border) 60%, transparent); }
      .oac-of__log time { color: var(--oac-muted); }
      .oac-of__log span { color: var(--oac-text); }
      .oac-of__log small { grid-column: 2; color: var(--oac-muted); font-size: 10.5px; }
      .oac-of__log .oac-of__empty { display: block; color: var(--oac-muted); border: 0; line-height: 1.6; }
      .oac-of__kind { display: inline-block; width: 7px; height: 7px; margin-right: 6px; border-radius: 2px; vertical-align: 1px; }
      .oac-of__code { margin: 0; padding: 13px 16px; border-top: 1px solid var(--oac-card-border); background: var(--oac-code-bg); color: var(--oac-code-text); font: 12px/1.65 var(--oac-mono); white-space: pre; overflow-x: auto; scrollbar-width: thin; scrollbar-color: var(--oac-card-border) transparent; }
      .oac-of__code code { font: inherit; background: none; padding: 0; border: 0; color: inherit; }
      .oac-of__code::-webkit-scrollbar { height: 8px; }
      .oac-of__code::-webkit-scrollbar-thumb { background: var(--oac-card-border); border-radius: 4px; }
      .oac-of-links { display: flex; flex-wrap: wrap; gap: 8px; margin: 18px 0 8px; }
      .oac-of-links a { display: inline-flex; align-items: center; min-height: 32px; padding: 6px 12px; border: 1px solid var(--oac-card-border); border-radius: 7px; background: var(--oac-card); color: var(--oac-text); font-size: 12.5px; font-weight: 500; text-decoration: none; }
      .oac-of-links a:hover { border-color: var(--oac-muted); }
      @media (max-width: 760px) {
        .oac-of__body--side { grid-template-columns: minmax(0, 1fr); }
        .oac-of__side { border-left: 0; border-top: 1px solid var(--oac-card-border); max-height: 220px; }
        .oac-of__status { white-space: normal; }
      }
    `}</style>
  );
}
