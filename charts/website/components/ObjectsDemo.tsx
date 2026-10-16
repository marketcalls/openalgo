import RunnableExample from './RunnableExample';
import { STOCK_BARS_SOURCE } from './synthetic-market';

const code = `${STOCK_BARS_SOURCE}
el.style.display = 'flex';
el.style.flexDirection = 'column';
const controls = document.createElement('div');
controls.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;padding:8px;flex-shrink:0';
const stage = document.createElement('div');
stage.style.cssText = 'flex:1;min-height:0;max-width:100%;width:100%';
el.append(controls, stage);
const bars = stockBars(1700000000, 160, 60, 100, 1901, 0.005, 1800);
const widget = lib.createWidget(stage, {
  symbol: 'OBJECTS SIM', interval: '1m', intervals: ['1m'],
  rail: false, statusline: false, topbar: false,
  navigation: { defaultVisibleBars: 100 },
});
widget.series.setData(bars);
function addDrawing() {
  widget.draw.add({ tool: 'trend-line', paneIndex: 0,
    points: [{ time: bars[100].time, price: bars[100].low },
      { time: bars[140].time, price: bars[140].low }],
    style: { color: '#f0a020', lineWidth: 3 },
  });
}
addDrawing();
widget.draw.add({ tool: 'rectangle', paneIndex: 0,
  points: [{ time: bars[159].time + 20 * 60, price: bars[159].high + 2 },
    { time: bars[159].time + 35 * 60, price: bars[159].high + 5 }],
  style: { color: '#4da3ff', lineWidth: 2 },
});
widget.chart.addIndicator('rsi');
const profile = new lib.VolumeProfile(
  lib.computeVolumeProfileSessions(bars, { tickSize: 0.5, session: 'composite' }),
  { width: 60, showValueArea: false, showPocLabel: false },
);
widget.chart.addPrimitive(profile);
let exists = true;
let visible = true;
const unregister = widget.objects.register({
  id: 'session-profile',
  get: () => exists ? { kind: 'profile', name: 'Session profile', paneIndex: 0, visible } : null,
  setVisible(on) {
    if (visible === on) return;
    visible = on;
    if (on) widget.chart.addPrimitive(profile); else widget.chart.removePrimitive(profile);
  },
  remove() { widget.chart.removePrimitive(profile); exists = false; },
});
function button(label, action) {
  const node = document.createElement('button');
  node.textContent = label;
  node.type = 'button';
  node.style.cssText = 'padding:5px 9px;border:1px solid var(--oac-card-border);border-radius:4px;background:var(--oac-card);color:inherit;font:12px system-ui';
  node.addEventListener('click', action);
  controls.appendChild(node);
  return node;
}
button('Open Objects', () => widget.openObjects());
button('Open Data', () => widget.openDataWindow());
button('Add drawing', addDrawing);
button('Add RSI', () => widget.chart.addIndicator('rsi'));
button('Undo drawing action', () => widget.draw.undo());
let compact = false;
const widthButton = button('Width: fit', () => {
  compact = !compact;
  stage.style.width = compact ? '350px' : '100%';
  widthButton.textContent = compact ? 'Width: 350 px' : 'Width: fit';
  widthButton.setAttribute('aria-pressed', String(compact));
});
widthButton.setAttribute('aria-pressed', 'false');
let saved;
const restoreButton = button('Restore layout', () => {
  if (saved) widget.restoreState(saved);
});
restoreButton.disabled = true;
button('Save layout', () => {
  saved = JSON.parse(JSON.stringify(widget.getState()));
  restoreButton.disabled = false;
});
return { destroy() { unregister(); widget.destroy(); } };`;

export default function ObjectsDemo() {
  return <RunnableExample height={500} tiers={['widget', 'profile']} code={code}
    caption="Simulated stock candles with irregular moves, pullbacks and changing volume. Open Data to inspect the dock as you move across the chart. In Objects, select drawings to create a named group, use Earlier/Later to change their order, or move an object to another pane. The rectangle sits beyond the newest bar. Try the 350 px width, then save and restore the layout. The profile offers show/hide and removal; its host-owned state is separate from the saved chart layout." />;
}
