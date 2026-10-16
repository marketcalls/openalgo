import RunnableExample from './RunnableExample';
import { STOCK_BARS_SOURCE } from './synthetic-market';

const code = `${STOCK_BARS_SOURCE}
el.style.display = 'flex';
el.style.flexDirection = 'column';
const controls = document.createElement('div');
controls.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;padding:8px;flex-shrink:0';
const stage = document.createElement('div');
stage.style.cssText = 'flex:1;min-height:220px';
const source = document.createElement('details');
source.hidden = true;
source.style.cssText = 'padding:8px;flex-shrink:0';
const summary = document.createElement('summary');
summary.textContent = 'Indicator source';
const text = document.createElement('pre');
text.style.cssText = 'max-height:130px;overflow:auto;font:11px/1.5 monospace;scrollbar-width:thin;scrollbar-color:var(--oac-card-border) transparent';
source.append(summary, text);
el.append(controls, stage, source);

function descriptor(anchor) {
  return {
    id: 'demo-signal-anchor-' + anchor,
    name: 'Signal anchors', placement: 'onchart', hasSource: true,
    markerAnchor: anchor, inputs: [],
    plots: [
      { key: 'up', type: 'line', title: 'Up', style: { color: '#26a69a' } },
      { key: 'down', type: 'line', title: 'Down', style: { color: '#ef5350' } },
      { key: 'mid', type: 'line', title: 'Helper', style: { color: 'transparent' } },
    ],
    calc(bars) {
      return {
        up: bars.map(bar => bar.close >= bar.open ? bar.close : null),
        down: bars.map(bar => bar.close < bar.open ? bar.close : null),
        mid: bars.map((bar) => (bar.open + bar.close) / 2),
      };
    },
    markers({ bars }) {
      return bars.flatMap((bar, i) => {
        if (i === 0 || i % 12 !== 0) return [];
        const up = bar.close >= bar.open;
        return [{ time: bar.time, position: up ? 'belowBar' : 'aboveBar',
          shape: up ? 'labelUp' : 'labelDown', size: 'small',
          color: up ? '#26a69a' : '#ef5350', text: up ? 'Up' : 'Down' }];
      });
    },
  };
}
for (const anchor of ['price', 'plot']) lib.registerIndicator(descriptor(anchor));
const chart = lib.createChart(stage, { legendIconSize: 20 });
const bars = stockBars(1700000000, 84, 300, 100, 713, 0.008, 1500);
chart.addSeries('candlestick').setData(bars);
let anchor = 'price';
let study = chart.addIndicator('demo-signal-anchor-' + anchor);
chart.fitContent();
const listeners = new AbortController();
function button(label, action) {
  const node = document.createElement('button');
  node.type = 'button';
  node.textContent = label;
  node.style.cssText = 'min-height:36px;padding:5px 9px;border:1px solid var(--oac-card-border);border-radius:5px;background:var(--oac-card);color:inherit;font:12px system-ui;cursor:pointer';
  node.addEventListener('click', action, { signal: listeners.signal });
  controls.appendChild(node);
  return node;
}
const anchorButton = button('Anchor: price', () => {
  anchor = anchor === 'price' ? 'plot' : 'price';
  study.remove();
  study = chart.addIndicator('demo-signal-anchor-' + anchor);
  anchorButton.textContent = 'Anchor: ' + anchor;
});
const sizeButton = button('Buttons: 20 px', () => {
  const size = chart.legendIconSize() === 20 ? 28 : 20;
  chart.setLegendIconSize(size);
  sizeButton.textContent = 'Buttons: ' + size + ' px';
});
chart.on('indicatorSource', ({ instanceId }) => {
  if (instanceId !== study.id) return;
  text.textContent = descriptor.toString();
  source.hidden = false;
  source.open = true;
});
return { destroy() { listeners.abort(); chart.destroy(); } };`;

export default function IndicatorSignalsDemo() {
  return <RunnableExample height={540} code={code}
    caption="Synthetic signals are sampled every twelve bars, with direction derived from each candle. Hover Signal anchors and press its source button to open the code supplied by this host. Switch to plot anchoring to compare line-relative labels with candle-relative labels; the transparent helper has no legend reading." />;
}
