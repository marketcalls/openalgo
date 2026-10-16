import RunnableExample from './RunnableExample';
import { STOCK_BARS_SOURCE } from './synthetic-market';

const code = `${STOCK_BARS_SOURCE}
el.style.display = 'flex';
el.style.flexDirection = 'column';
const controls = document.createElement('div');
controls.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;padding:8px;flex-shrink:0';
const values = document.createElement('output');
values.dataset.alertDragValues = '';
values.style.cssText = 'display:block;padding:0 10px;font:12px/1.7 ui-monospace,monospace;flex-shrink:0';
const status = document.createElement('p');
status.dataset.alertDragStatus = '';
status.setAttribute('role', 'status');
status.style.cssText = 'margin:0;padding:4px 10px 8px;font:12px/1.5 system-ui;flex-shrink:0';
const stage = document.createElement('div');
stage.dataset.alertDragChart = '';
stage.style.cssText = 'flex:1;min-height:260px;position:relative';
el.append(controls, values, status, stage);

lib.registerIndicator({
  id: 'website-alert-drag-study', name: 'Sample study', placement: 'pane', inputs: [],
  plots: [{ key: 'value', type: 'line', title: 'Study units', style: { color: '#a78bfa' } }],
  calc: bars => ({ value: bars.map((bar, i) => {
    if (i < 14) return 50;
    let gains = 0;
    let losses = 0;
    for (let j = i - 13; j <= i; j++) {
      const change = bars[j].close - bars[j - 1].close;
      gains += Math.max(0, change);
      losses += Math.max(0, -change);
    }
    return losses === 0 ? 100 : gains === 0 ? 0 : 100 - 100 / (1 + gains / losses);
  }) }),
});
const chart = lib.createChart(stage, { timeNavigator: false, priceAxisWidth: 72 });
chart.setDataContext({ symbol: 'SYNTHETIC', exchange: 'DEMO', interval: '5m' });
const bars = stockBars(1735689600, 72, 300, 100, 138, 0.006, 1800);
chart.addSeries('candlestick').setData(bars);
let study = chart.addIndicator('website-alert-drag-study');
chart.setVisibleLogicalRange({ from: -2, to: 76 });
chart.panes()[0].priceScale.setOptions({ minMove: 0.25 });
chart.panes()[0].priceScale.setFixedRange({ min: 80, max: 130 });
chart.panes()[study.paneIndex].priceScale.setFixedRange({ min: 0, max: 100 });
const alerts = new lib.AlertController(chart);
const listeners = new AbortController();
let commits = 0;
let paused = false;
let dragging = false;
let commitsBeforeDrag = 0;

function positions() {
  const records = alerts.list();
  stage.dataset.dragX = String(chart.timeToCoordinate(bars[48].time));
  for (const [key, id, field, delta, pane] of [
    ['price', 'demo-price', 'price', 5, 0],
    ['lower', 'demo-range', 'price', 5, 0],
    ['upper', 'demo-range', 'upperPrice', -5, 0],
    ['study', 'demo-study', 'value', 10, study.paneIndex],
  ]) {
    const value = records.find(alert => alert.id === id)?.source[field];
    stage.dataset[key + 'Y'] = Number.isFinite(value) ? String(chart.priceToCoordinate(value, pane)) : '';
    stage.dataset[key + 'TargetY'] = Number.isFinite(value) ? String(chart.priceToCoordinate(value + delta, pane)) : '';
  }
}
function show(message) {
  const records = alerts.list();
  const price = records.find(alert => alert.id === 'demo-price').source;
  const range = records.find(alert => alert.id === 'demo-range').source;
  const indicator = records.find(alert => alert.id === 'demo-study')?.source;
  values.textContent = 'Saved price ' + price.price.toFixed(2)
    + ' | Range ' + range.price.toFixed(2) + ' to ' + range.upperPrice.toFixed(2)
    + ' | Study ' + (indicator ? indicator.value.toFixed(2) : 'unavailable') + ' | Commits ' + commits;
  values.dataset.price = String(price.price);
  values.dataset.lower = String(range.price);
  values.dataset.upper = String(range.upperPrice);
  values.dataset.study = indicator ? String(indicator.value) : '';
  values.dataset.commits = String(commits);
  status.textContent = message;
  positions();
}
function reset() {
  for (const record of alerts.list()) alerts.remove(record.id);
  if (!chart.indicators().some(item => item.id === study.id)) {
    study = chart.addIndicator('website-alert-drag-study');
    chart.panes()[study.paneIndex].priceScale.setFixedRange({ min: 0, max: 100 });
  }
  alerts.add({ id: 'demo-price', title: 'Price level', source: { kind: 'price', price: 110 } });
  alerts.add({ id: 'demo-range', title: 'Price band', condition: 'enteringRange',
    source: { kind: 'price', price: 90, upperPrice: 120 } });
  alerts.add({ id: 'demo-study', title: 'Study level',
    source: { kind: 'indicator', instanceId: study.id, plotKey: 'value', value: 30 } });
  commits = 0;
  show(paused ? 'Alerts paused. Resume to drag a level.' : 'Drag a dashed line or its Alert badge. Press Escape before release to cancel.');
}
function button(label, action, key) {
  const node = document.createElement('button');
  node.type = 'button';
  node.textContent = label;
  node.dataset.alertDragAction = key;
  node.style.cssText = 'min-height:36px;padding:5px 9px;border:1px solid var(--oac-card-border);border-radius:5px;background:var(--oac-card);color:inherit;font:12px system-ui;cursor:pointer';
  node.addEventListener('click', action, { signal: listeners.signal });
  controls.appendChild(node);
  return node;
}
button('Reset thresholds', reset, 'reset');
const pause = button('Pause alerts', () => {
  paused = !paused;
  alerts.setPaused(paused);
  pause.textContent = paused ? 'Resume alerts' : 'Pause alerts';
  pause.setAttribute('aria-pressed', String(paused));
  show(paused ? 'Alerts paused. Dragging is unavailable.' : 'Alerts resumed. Drag a level to preview a change.');
}, 'pause');
pause.setAttribute('aria-pressed', 'false');
reset();
chart.on('drag', () => {
  if (!dragging) { dragging = true; commitsBeforeDrag = commits; }
  show('Preview only. Saved levels and the commit count stay unchanged until release.');
});
chart.on('alert:updated', () => { commits++; show('Threshold committed on release.'); });
chart.on('drag:end', () => {
  dragging = false;
  show(commits > commitsBeforeDrag ? 'Threshold committed on release.' : 'No threshold change.');
});
chart.on('drag:cancel', () => { dragging = false; show('Drag cancelled. Saved levels are unchanged.'); });
chart.on('resize', positions);
el.dataset.alertDragReady = 'true';
return { destroy() { delete el.dataset.alertDragReady; listeners.abort(); alerts.destroy(); chart.destroy(); } };`;

export default function AlertDragDemo() {
  return <div id="alert-drag-demo"><RunnableExample height={560} code={code}
    caption="Synthetic candles and study readings. Drag the price level, either price-band boundary, or the study level in the lower pane. Price previews snap to a 0.25 tick. The saved-value readout changes once on release; Escape cancels. No live feed or external delivery is connected." /></div>;
}
