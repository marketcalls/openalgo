import { registerIndicator } from '/dist/openalgo-charts.mjs';
import { el, studyNames } from './ui.js';

/** Self-contained so the viewer can show the exact factory the host registers. */
export function sourceSignalDescriptor() {
  return {
    id: 'source-signal-sample', name: 'Source signal sample', category: 'Examples',
    placement: 'onchart', hasSource: true, markerAnchor: 'price', inputs: [],
    plots: [
      { key: 'up', type: 'line', title: 'Up', style: { color: '#26a69a' } },
      { key: 'down', type: 'line', title: 'Down', style: { color: '#ef5350' } },
      { key: 'helper', type: 'line', title: 'Helper', style: { color: 'transparent' } },
    ],
    calc(bars) {
      return {
        up: bars.map((bar, i) => Math.floor(i / 12) % 2 === 0 ? bar.close : null),
        down: bars.map((bar, i) => Math.floor(i / 12) % 2 === 1 ? bar.close : null),
        helper: bars.map(bar => (bar.open + bar.close) / 2),
      };
    },
    markers({ bars }) {
      return bars.flatMap((bar, i) => {
        if (i === 0 || i % 12 !== 0) return [];
        const up = Math.floor(i / 12) % 2 === 0;
        return [{ time: bar.time, position: up ? 'belowBar' : 'aboveBar',
          shape: up ? 'labelUp' : 'labelDown', size: 'small',
          color: up ? '#26a69a' : '#ef5350', text: up ? 'Up' : 'Down' }];
      });
    },
  };
}

let owner = null;

export function closeIndicatorSource() {
  owner = null;
  el('indsource').hidden = true;
  el('indsource-code').textContent = '';
}

/** The engine emits identity only; this host owns the source text and its UI. */
export function bindIndicatorSource(chart, pane) {
  const offSource = chart.on('indicatorSource', ({ instanceId, indicatorId }) => {
    const instance = chart.indicators().find(item => item.id === instanceId && item.indicatorId === indicatorId);
    if (!instance || indicatorId !== 'source-signal-sample') return;
    owner = { chart, instanceId };
    const context = chart.getDataContext();
    el('indsource-title').textContent = instance.name + ' source';
    el('indsource-owner').textContent = `Chart ${pane}: ${context?.symbol || 'Unknown symbol'}, ${studyNames(chart).get(instance.id)}`;
    el('indsource-code').textContent = sourceSignalDescriptor.toString() + '\n\nregisterIndicator(sourceSignalDescriptor());';
    el('indsource').hidden = false;
  });
  const offRemoved = chart.on('indicatorRemoved', ({ instanceId }) => {
    if (owner?.chart === chart && owner.instanceId === instanceId) closeIndicatorSource();
  });
  const dispose = () => {
    if (owner?.chart === chart) closeIndicatorSource();
    offSource(); offRemoved(); offDestroy();
  };
  const offDestroy = chart.on('destroy', dispose);
  return dispose;
}

export function initIndicatorSource() {
  registerIndicator(sourceSignalDescriptor());
  el('indsource-close').addEventListener('click', closeIndicatorSource);
  el('indsource').addEventListener('click', event => { if (event.target.id === 'indsource') closeIndicatorSource(); });
}
