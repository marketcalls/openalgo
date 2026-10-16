import React from 'react';
import RunnableExample from './RunnableExample';
import { STOCK_BARS_SOURCE } from './synthetic-market';

const code = `${STOCK_BARS_SOURCE}
el.style.cssText += ';display:flex;flex-direction:column';
const controls = document.createElement('div');
controls.style.cssText = 'display:flex;gap:8px;flex-wrap:wrap;padding:8px;font:12px system-ui,sans-serif;flex-shrink:0';
const grid = document.createElement('div');
grid.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fit,minmax(min(280px,100%),1fr));grid-auto-rows:minmax(0,1fr);flex:1;min-height:0';
const note = document.createElement('p');
note.style.cssText = 'margin:6px 10px;font:12px system-ui,sans-serif;color:var(--oac-muted);flex-shrink:0';
note.textContent = 'Simulated stock candles. Drawings share time anchors; each chart computes its own volume study.';
el.append(controls, grid, note);
const bars = stockBars(1700000000, 100, 3600, 100, 245, 0.006, 1600);
const hosts = [0, 1].map(() => {
  const host = document.createElement('div');
  host.style.cssText = 'min-width:0;min-height:0;height:100%';
  grid.appendChild(host);
  return host;
});
const charts = hosts.map(host => {
  const widget = lib.createWidget(host, { symbol:'SAMPLE', exchange:'DEMO', interval:'1h',
    persist:false, topbar:false, statusline:false, rail:false, timeNavigator:false,
    navigation:{ defaultVisibleBars:bars.length } });
  widget.series.setData(bars);
  return widget;
});
const first = charts[0];
const drawings = new lib.DrawingLinkGroup({ enabled:true });
const views = lib.createLinkGroup({ crosshair:true, viewport:true });
for (const widget of charts) {
  drawings.add(widget.chart, widget.draw);
  views.add(widget.chart);
}
for (const widget of charts) widget.chart.timeScale.fitContent(bars.length);
function button(label, run) {
  const button = document.createElement('button');
  button.textContent = label;
  button.type = 'button';
  button.style.cssText = 'font:inherit;padding:5px 9px;border:1px solid var(--oac-card-border);border-radius:4px;background:var(--oac-card);color:var(--oac-text)';
  button.addEventListener('pointerdown', e => e.stopPropagation());
  button.addEventListener('click', run);
  controls.appendChild(button);
  return button;
}
button('Anchor VWAP', () => first.draw.setTool('anchored-vwap'));
button('Range profile', () => first.draw.setTool('fixed-range-volume-profile'));
button('Undo', () => first.draw.undo());
let linked = true;
const sync = button('Drawing sync: on', () => {
  linked = !linked; drawings.setOptions({ enabled:linked });
  sync.textContent = 'Drawing sync: ' + (linked ? 'on' : 'off');
});
// Drawing colours reach the canvas as given, labels included, so pick the
// shades that read on the palette the widgets opened with.
const dark = first.theme() === 'dark';
first.draw.add({ tool:'anchored-vwap', paneIndex:0, style:{ color:dark ? '#fbbf24' : '#b45309', lineWidth:2 },
  points:[{ time:bars[20].time, price:bars[20].close }] });
first.draw.add({ tool:'fixed-range-volume-profile', paneIndex:0, style:{ color:dark ? '#60a5fa' : '#2563eb' },
  points:[{ time:bars[45].time, price:bars[45].close }, { time:bars[88].time, price:bars[88].close }] });
return { destroy() { drawings.destroy(); views.destroy(); charts.forEach(widget => widget.destroy());
  controls.remove(); grid.remove(); note.remove(); } };`;

export default function LinkedAnalysisDemo() {
  return <div className="oac-linked-analysis"><RunnableExample code={code} tiers={['widget', 'draw']} height={540}
    caption="Click Anchor VWAP or Range profile, then place anchors on the left chart. Drag a drawing to move it on both charts; crosshair and viewport are linked too. Turn drawing sync off to compare independent edits." /></div>;
}
