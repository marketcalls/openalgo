import { useEffect, useRef, useState } from 'react';
import { useTheme } from 'next-themes';
import { stockBars } from './synthetic-market';

const START = Date.UTC(2026, 8, 21, 9) / 1000;

export default function TypedInputsDemo() {
  const stage = useRef<HTMLDivElement>(null);
  const open = useRef<() => void>(() => {});
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const [summary, setSummary] = useState('');
  const { resolvedTheme } = useTheme();

  useEffect(() => {
    let cancelled = false;
    let widget: { destroy(): void } | undefined;
    setReady(false);
    setError('');
    void (async () => {
      try {
        // Register on the same base module that the widget imports.
        const [core, host] = await Promise.all([
          import('../lib/oac/openalgo-charts.mjs'),
          import('../lib/oac/openalgo-charts.widget.mjs'),
        ]);
        if (cancelled || !stage.current) return;
        core.registerIndicator({
          id: 'website-typed-inputs', name: 'Session threshold', placement: 'onchart',
          inputs: [
            { key: 'instrument', type: 'symbol', label: 'Watch instrument', default: 'SAMPLE-A', exchangeKey: 'venue' },
            { key: 'session', type: 'session', label: 'Active session (UTC)', default: '0900-1700:23456' },
            { key: 'note', type: 'multiline', label: 'Notes', default: 'Review this threshold\nAfter the opening range' },
            { key: 'level', type: 'price', label: 'Threshold', default: 104, pick: true },
            { key: 'start', type: 'timestamp', label: 'Start at', default: START + 1200, pick: true },
          ],
          plots: [{ key: 'level', type: 'line', title: 'Threshold', style: { color: '#d97706', lineWidth: 2 } }],
          calc: (bars, settings) => {
            const session = core.parseSessionSpec(settings.session);
            return { level: bars.map(bar => session && bar.time >= settings.start
              && core.inSessionAt(bar.time, session, 'UTC') ? settings.level : NaN) };
          },
        });
        const current = host.createWidget(stage.current, {
          symbol: 'SAMPLE-A', exchange: 'DEMO', interval: '1m', timezone: 'UTC',
          theme: resolvedTheme === 'light' ? 'light' : 'dark',
          persist: false, rail: false, topbar: false, statusline: false, panels: false,
          timeNavigator: false, branding: false,
          symbolSearch: query => ['SAMPLE-A', 'SAMPLE-B', 'SAMPLE-C']
            .filter(symbol => symbol.includes(query.toUpperCase()))
            .map(symbol => ({ symbol, exchange: 'DEMO', name: `Sample instrument ${symbol.slice(-1)}` })),
        });
        widget = current;
        // Simulated one-minute prices: a seeded random walk from 100 that trades
        // through the default threshold of 104, so the level sits among the bars.
        const bars = stockBars(START, 180, 60, 100, 9, 0.002, 1000);
        current.series.setData(bars);
        const study = current.chart.addIndicator('website-typed-inputs');
        current.chart.setVisibleLogicalRange({ from: -3, to: 185 });
        const refresh = () => {
          if (cancelled) return;
          const settings = study.settings();
          const session = core.parseSessionSpec(settings.session);
          const count = bars.filter(bar => session && bar.time >= settings.start
            && core.inSessionAt(bar.time, session, 'UTC')).length;
          const date = new Date(settings.start * 1000);
          const instant = Number.isFinite(date.getTime()) ? date.toISOString() : 'outside calendar display range';
          setSummary(`${settings.instrument}${settings.venue ? ` (${settings.venue})` : ''}`
            + ` | Threshold ${settings.level} | ${count} active bars\n`
            + `From ${settings.start} UTC seconds (${instant}) | Session ${settings.session}\n${settings.note}`);
        };
        current.chart.on('objects:change', refresh);
        open.current = () => host.mountIndicatorSettings(current.context, undefined, { instanceId: study.id });
        refresh();
        setReady(true);
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      }
    })();
    return () => { cancelled = true; open.current = () => {}; widget?.destroy(); };
  }, [resolvedTheme]);

  return <div className="oac-example" data-typed-demo="">
    <div style={{ padding: 12 }}>
      <button type="button" disabled={!ready} onClick={() => open.current()}
        style={{ padding: '6px 12px', border: '1px solid #64748b', borderRadius: 5 }}>
        Study inputs
      </button>
      <p style={{ margin: '8px 0', fontSize: 13 }}>
        Edit the session, pick a threshold or start bar, and keep a watch instrument with notes.
        Session hours and displayed times use UTC.
      </p>
      <output data-typed-summary="" style={{ display: 'block', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: 12 }}>
        {summary}
      </output>
      {error && <p role="alert">Example error: {error}</p>}
    </div>
    <div ref={stage} style={{ height: 360, position: 'relative' }} />
  </div>;
}
