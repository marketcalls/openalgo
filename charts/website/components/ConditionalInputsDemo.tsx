import { useEffect, useRef, useState } from 'react';
import { useTheme } from 'next-themes';
import { stockBars } from './synthetic-market';

const START = Date.UTC(2026, 8, 21, 9) / 1000;

/**
 * A windowed mean. The warmup is empty, and a gap in the input empties every
 * window that holds it, so a smoothed line starts where both windows are full.
 */
function mean(values: number[], length: number): number[] {
  return values.map((_, index) => {
    if (index < length - 1) return NaN;
    let sum = 0;
    for (let k = index - length + 1; k <= index; k++) sum += values[k];
    return sum / length;
  });
}

export default function ConditionalInputsDemo() {
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
          id: 'website-conditional-inputs', name: 'Average with bands', placement: 'onchart',
          inputs: [
            { key: 'length', type: 'number', label: 'Length', default: 20, min: 2, max: 100, inline: 'len' },
            { key: 'source', type: 'source', label: 'Source', default: 'close', inline: 'len' },
            { key: 'mode', type: 'select', label: 'Mode', default: 'line',
              options: [{ label: 'Line', value: 'line' }, { label: 'Bands', value: 'bands' }] },
            { key: 'width', type: 'number', label: 'Band width', default: 1.5, min: 0.5, max: 5, step: 0.5,
              visibleWhen: { key: 'mode', is: 'bands' },
              tooltip: 'Distance of each band from the average, in price units.' },
            { key: 'smoothing', type: 'select', label: 'Smoothing', default: 'none', group: 'Smoothing',
              options: [{ label: 'None', value: 'none' }, { label: 'Moving average', value: 'sma' }] },
            { key: 'smoothLength', type: 'number', label: 'Smoothing length', default: 5, min: 2, max: 30,
              group: 'Smoothing', activeWhen: { key: 'smoothing', isNot: 'none' } },
            { key: 'showSignal', type: 'boolean', label: 'Signal', default: false, group: 'Signal', inline: 'signal' },
            { key: 'signalLength', type: 'number', label: 'Length', default: 9, min: 2, max: 50,
              group: 'Signal', inline: 'signal', activeWhen: { key: 'showSignal', is: true } },
            { key: 'signalColor', type: 'color', label: 'Colour', default: '#d97706',
              group: 'Signal', inline: 'signal', activeWhen: { key: 'showSignal', is: true } },
          ],
          plots: [
            { key: 'basis', type: 'line', title: 'Average', style: { color: '#2563eb', lineWidth: 2 } },
            { key: 'upper', type: 'line', title: 'Upper', style: { color: '#64748b', lineWidth: 1 } },
            { key: 'lower', type: 'line', title: 'Lower', style: { color: '#64748b', lineWidth: 1 } },
            { key: 'signal', type: 'line', title: 'Signal', colorKey: 'signalColor', style: { lineWidth: 1.5 } },
          ],
          calc: (bars, settings) => {
            const values = core.sourceValues(bars, settings.source);
            const average = mean(values, settings.length);
            const basis = settings.smoothing === 'sma' ? mean(average, settings.smoothLength) : average;
            const bands = settings.mode === 'bands';
            return {
              basis,
              upper: basis.map(v => (bands ? v + settings.width : NaN)),
              lower: basis.map(v => (bands ? v - settings.width : NaN)),
              signal: settings.showSignal ? mean(values, settings.signalLength) : basis.map(() => NaN),
            };
          },
        });
        const current = host.createWidget(stage.current, {
          symbol: 'SAMPLE-A', exchange: 'DEMO', interval: '1m', timezone: 'UTC',
          theme: resolvedTheme === 'light' ? 'light' : 'dark',
          persist: false, rail: false, topbar: false, statusline: false, panels: false,
          timeNavigator: false, branding: false,
        });
        widget = current;
        // Simulated one-minute prices: a seeded random walk that moves about
        // six points, so the default band width reads against real swings.
        const bars = stockBars(START, 180, 60, 100, 33, 0.0022, 900);
        current.series.setData(bars);
        const study = current.chart.addIndicator('website-conditional-inputs');
        current.chart.setVisibleLogicalRange({ from: -3, to: 185 });
        const refresh = () => {
          if (cancelled) return;
          const s = study.settings();
          const shown = s.mode === 'bands' ? 'Band width is shown' : 'Band width is hidden';
          const smoothing = s.smoothing === 'none' ? 'smoothing length is disabled' : `smoothing over ${s.smoothLength} bars`;
          const signal = s.showSignal ? `signal over ${s.signalLength} bars` : 'signal off, its length and colour disabled';
          setSummary(`Length ${s.length} on ${s.source} | mode ${s.mode} (${shown})\n`
            + `Band width kept at ${s.width} | ${smoothing} | ${signal}`);
        };
        current.chart.on('objects:change', refresh);
        open.current = () => host.mountIndicatorSettings(current.context, undefined, {
          instanceId: study.id, onChange: refresh, onClose: refresh,
        });
        refresh();
        setReady(true);
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      }
    })();
    return () => { cancelled = true; open.current = () => {}; widget?.destroy(); };
  }, [resolvedTheme]);

  return <div className="oac-example" data-conditional-demo="">
    <div style={{ padding: 12 }}>
      <button type="button" disabled={!ready} onClick={() => open.current()}
        style={{ padding: '6px 12px', border: '1px solid #64748b', borderRadius: 5 }}>
        Study inputs
      </button>
      <p style={{ margin: '8px 0', fontSize: 13 }}>
        Switch Mode to Bands to show the band width, choose a smoothing to enable its length,
        and tick Signal to enable the length and colour on its row. Cancel restores the settings.
      </p>
      <output data-conditional-summary="" style={{ display: 'block', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: 12 }}>
        {summary}
      </output>
      {error && <p role="alert">Example error: {error}</p>}
    </div>
    <div ref={stage} style={{ height: 480, position: 'relative' }} />
  </div>;
}
