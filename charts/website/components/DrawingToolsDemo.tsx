import React from 'react';
import RunnableExample from './RunnableExample';
import { highlight } from './highlight';
import { STOCK_BARS_SOURCE } from './synthetic-market';

// RunnableExample executes this same string; the source panel never has a separate demo implementation.
const code = `${STOCK_BARS_SOURCE}
// In your app: import { createChart } from 'openalgo-charts';
// import { DrawingController, getDrawingTool } from 'openalgo-charts/draw';
// The website supplies these exports as lib and a sized container as el.
const root = document.createElement('div');
root.className = 'oac-draw-playground';
root.innerHTML = \`
  <div class="oac-draw-playground__rail" role="group" aria-label="Drawing tools"></div>
  <div class="oac-draw-playground__main">
    <div class="oac-draw-playground__actions" role="group" aria-label="Drawing actions">
      <select aria-label="Select a drawing"></select>
    </div>
    <div class="oac-draw-playground__plot" tabindex="0" aria-label="Interactive drawing chart"></div>
    <div class="oac-draw-playground__status" role="status" aria-live="polite"></div>
  </div>\`;
el.appendChild(root);
const rail = root.querySelector('.oac-draw-playground__rail');
const actions = root.querySelector('.oac-draw-playground__actions');
const plot = root.querySelector('.oac-draw-playground__plot');
const status = root.querySelector('[role="status"]');
const selection = root.querySelector('select');
const listeners = new AbortController();
const listen = (node, event, handler) => node.addEventListener(event, handler, { signal: listeners.signal });

const chart = lib.createChart(plot);
const bars = stockBars(1700000000, 160, 3600, 100, 631, 0.006, 1800);
chart.addSeries('candlestick').setData(bars);
chart.timeScale.fitContent(bars.length);
const draw = new lib.DrawingController(chart, { magnet: 'weak', stayInDrawingMode: false });
const point = (index, price) => ({ time: bars[index].time, price });

// Seed three editable drawings, then start with an empty undo history.
draw.add({ id: 'demo-trend', tool: 'trend-line', paneIndex: 0,
  points: [point(15, bars[15].low), point(75, bars[75].low)],
  style: { color: '#4f8cff', lineWidth: 2 } });
draw.add({ id: 'demo-zone', tool: 'rectangle', paneIndex: 0,
  points: [point(93, bars[93].high), point(137, bars[137].low)],
  style: { color: '#14b8a6', fill: true, fillOpacity: 0.14, lineWidth: 2 },
  text: { value: 'Supply zone', color: '#14b8a6', position: 'inside', valign: 'top' } });
draw.add({ id: 'demo-level', tool: 'horizontal-line', paneIndex: 0,
  points: [point(0, bars[45].low)],
  style: { color: '#f5a623', lineStyle: 'dashed', lineWidth: 2 } });
const initial = draw.toJSON();
draw.fromJSON(initial);

const quickTools = [
  [null, 'Cursor', 'Click a drawing to select it; drag its body or handles.'],
  ['trend-line', 'Trend line', 'Click a start and end point, or drag across the chart.'],
  ['horizontal-line', 'Horizontal line', 'Click once to mark a price level.'],
  ['ray', 'Ray', 'Click two points to project a line to the right.'],
  ['rectangle', 'Rectangle', 'Click two opposite corners, or drag to mark a zone.'],
  ['fib-retracement', 'Fibonacci', 'Click the swing low and high to place a retracement.'],
  ['long-position', 'Long position', 'Click entry, then target; drag the stop or target to adjust.'],
  ['measure', 'Measure', 'Click two points to measure price, time and volume.'],
  ['anchored-vwap', 'Anchored VWAP', 'Click the candle where the volume-weighted calculation should begin.'],
  ['fixed-range-volume-profile', 'Volume profile', 'Click the beginning and end of a time range. Volume is estimated from candles.'],
  ['brush', 'Brush', 'Press, draw a stroke, and release.'],
];
const tools = [quickTools[0], ...lib.registeredDrawingTools().map(tool => [
  tool.id, tool.name, tool.freehand ? 'Press, draw, and release.' :
    tool.points === 0 ? 'Click each point, then double-click to finish.' :
    'Click ' + tool.points + ' point(s) to place the drawing.',
])];
const catalog = document.createElement('select');
catalog.setAttribute('aria-label', 'All drawing tools');
catalog.add(new Option('All drawing tools...', ''));
for (const [id, name] of tools.slice(1)) catalog.add(new Option(name, id));
actions.prepend(catalog);
listen(catalog, 'change', () => {
  draw.setTool(catalog.value || null);
  plot.focus({ preventScroll: true });
  refresh();
});
const toolButtons = new Map();
function button(parent, label, action) {
  const node = document.createElement('button');
  node.type = 'button';
  node.textContent = label;
  listen(node, 'click', () => { action(); refresh(); });
  parent.appendChild(node);
  return node;
}
for (const [id, label, instruction] of quickTools) {
  const node = button(rail, label, () => { draw.setTool(id); plot.focus({ preventScroll: true }); });
  node.title = instruction;
  toolButtons.set(id, node);
}
const undo = button(actions, 'Undo', () => draw.undo());
const redo = button(actions, 'Redo', () => draw.redo());
const remove = button(actions, 'Delete', () => draw.removeMany(draw.selection()));
button(actions, 'Reset demo', () => {
  draw.setTool(null);
  draw.fromJSON(initial);
  chart.timeScale.fitContent(bars.length);
});

function refresh() {
  const active = draw.activeTool();
  catalog.value = active || '';
  const picked = draw.get(draw.selected());
  const label = drawing => drawing.text?.value || lib.getDrawingTool(drawing.tool).name;
  const rows = draw.drawings();
  selection.replaceChildren(new Option('Select a drawing...', ''));
  rows.forEach(drawing => selection.add(new Option(label(drawing), drawing.id)));
  selection.value = picked?.id || '';
  toolButtons.forEach((node, id) => node.setAttribute('aria-pressed', String(id === active)));
  undo.disabled = !draw.canUndo();
  redo.disabled = !draw.canRedo();
  remove.disabled = draw.selection().length === 0;
  const tool = tools.find(([id]) => id === active);
  status.textContent = rows.length + ' drawings · ' +
    (active ? tool[1] + ': ' + tool[2] : picked ? 'Selected: ' + label(picked) + '. Drag its body or handles.' : tool[2]);
}
listen(selection, 'change', () => {
  const id = selection.value || null;
  draw.setTool(null);
  draw.select(id);
  refresh();
});

// Shortcuts belong to this playground, so another chart or a text field keeps its keys.
listen(root, 'keydown', event => {
  if (event.target.closest('input, textarea, select, [contenteditable="true"]')) return;
  if (event.key === 'Escape') draw.setTool(null);
  else if (event.key === 'Delete' || event.key === 'Backspace') draw.removeMany(draw.selection());
  else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
    event.shiftKey ? draw.redo() : draw.undo();
  } else return;
  event.preventDefault();
  event.stopPropagation();
  refresh();
});
const off = ['draw:tool', 'drawing:select', 'drawing:change'].map(event => chart.on(event, refresh));
refresh();

// Unmounts and site-theme changes release the controller and every host listener.
const destroy = chart.destroy.bind(chart);
chart.destroy = () => {
  listeners.abort();
  off.forEach(unsubscribe => unsubscribe());
  draw.destroy();
  destroy();
  root.remove();
};
return chart;`;

export default function DrawingToolsDemo() {
  return (
    <div className="oac-drawing-demo">
      <RunnableExample
        hideCode
        height={560}
        tiers={['draw']}
        code={code}
        caption="Synthetic hourly bars. Pick a tool, then click to place anchors. Cursor selects and moves drawings; Delete removes a selection, Esc cancels placement, and Ctrl/Cmd+Z undoes. Reset restores the three examples."
      />
      <details className="oac-drawing-demo__source">
        <summary>View the running example source</summary>
        <pre className="oac-example__code" role="region" aria-label="Drawing playground source">
          <code dangerouslySetInnerHTML={{ __html: highlight(code) }} />
        </pre>
      </details>
      <style jsx global>{`
        .oac-drawing-demo { min-width: 0; }
        .oac-drawing-demo .oac-example { margin-bottom: 0; border-radius: 12px 12px 0 0; }
        .oac-drawing-demo .oac-example__badge { top: auto; bottom: 54px; pointer-events: none; }
        .oac-draw-playground { display: grid; grid-template-columns: 144px minmax(0, 1fr); height: 100%; font: 12px/1.45 ui-sans-serif, system-ui, sans-serif; }
        .oac-draw-playground__rail { display: flex; flex-direction: column; gap: 6px; padding: 12px 10px; border-right: 1px solid var(--oac-card-border); background: color-mix(in srgb, var(--oac-accent) 4%, var(--oac-card)); }
        .oac-draw-playground button, .oac-draw-playground select { min-height: 34px; border: 1px solid var(--oac-card-border); border-radius: 6px; background: var(--oac-card); color: inherit; font: inherit; padding: 6px 10px; cursor: pointer; }
        .oac-draw-playground__rail button { text-align: left; }
        .oac-draw-playground button:hover:not(:disabled) { border-color: var(--oac-accent); }
        .oac-draw-playground button[aria-pressed="true"] { background: color-mix(in srgb, var(--oac-accent) 14%, var(--oac-card)); border-color: var(--oac-accent); color: var(--oac-accent); font-weight: 700; }
        .oac-draw-playground button:disabled { opacity: .4; cursor: default; }
        .oac-draw-playground button:focus-visible, .oac-draw-playground select:focus-visible { outline: 2px solid var(--oac-accent); outline-offset: 2px; }
        .oac-draw-playground__main { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
        .oac-draw-playground__actions { display: flex; flex-wrap: wrap; gap: 6px; padding: 10px; border-bottom: 1px solid var(--oac-card-border); }
        .oac-draw-playground__actions select { min-width: 0; max-width: 175px; flex: 1 1 145px; }
        .oac-draw-playground select { appearance: none; padding-right: 24px; background-image: linear-gradient(45deg, transparent 50%, currentColor 50%), linear-gradient(135deg, currentColor 50%, transparent 50%); background-position: calc(100% - 12px) 14px, calc(100% - 8px) 14px; background-size: 4px 4px; background-repeat: no-repeat; }
        .oac-draw-playground__plot { flex: 1; min-height: 220px; min-width: 0; position: relative; }
        .oac-draw-playground__plot:focus-visible { outline: 2px solid var(--oac-accent); outline-offset: -2px; }
        .oac-draw-playground__status { min-height: 50px; border-top: 1px solid var(--oac-card-border); padding: 8px 12px; color: var(--oac-muted); }
        .oac-drawing-demo__source { border: 1px solid var(--oac-card-border); border-top: 0; border-radius: 0 0 12px 12px; overflow: hidden; margin-bottom: 1.5rem; }
        .oac-drawing-demo__source summary { cursor: pointer; padding: 10px 16px; font-size: 13px; font-weight: 600; color: var(--oac-accent); }
        .oac-drawing-demo__source pre { max-height: 400px; margin: 0; border-bottom: 0; }
        @media (max-width: 640px) {
          .oac-draw-playground { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(0, 1fr); }
          .oac-draw-playground__rail { flex-direction: row; flex-wrap: wrap; gap: 5px; padding: 8px; border-right: 0; border-bottom: 1px solid var(--oac-card-border); }
          .oac-draw-playground__rail button { flex: 1 0 auto; padding: 5px 8px; font-size: 11px; }
          .oac-draw-playground__actions { gap: 5px; padding: 8px; }
          .oac-draw-playground__actions button, .oac-draw-playground__actions select { padding: 5px 7px; font-size: 11px; }
          .oac-draw-playground__status { min-height: 58px; font-size: 11px; }
        }
      `}</style>
    </div>
  );
}
