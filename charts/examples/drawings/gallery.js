import { createWidget } from '/dist/openalgo-charts.widget.mjs';
import { registeredDrawingTools, getDrawingTool } from '/dist/openalgo-charts.draw.mjs';

const start = 1789357500;
let seed = 22019;
let last = 23800;
const random = () => {
  seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
  return seed / 4294967296;
};
const bars = Array.from({ length: 200 }, (_, i) => {
  const open = last + (i % 75 === 0 ? (random() - .5) * 15 : 0);
  const move = (random() - .49) * 9 + (i % 45 < 20 ? 1.2 : -1.2);
  const close = Math.round((open + move) * 20) / 20;
  last = close;
  return {
    time: start + i * 300, open, close,
    high: Math.max(open, close) + 1 + random() * 7,
    low: Math.min(open, close) - 1 - random() * 7,
    volume: Math.round(400 + random() * 4800 + Math.abs(move) * 380),
  };
});

const widget = createWidget(document.getElementById('chart'), {
  symbol: 'NIFTY SIM', exchange: 'NFO', interval: '5m', intervals: ['5m'],
  topbar: false, statusline: false, persist: false,
  priceScale: { minPrecision: 2, minMove: .05 },
  navigation: { defaultVisibleBars: 210 },
});
widget.series.setData(bars);
const { chart, draw } = widget;
const picker = document.getElementById('tool');
const status = document.getElementById('status');
const tools = registeredDrawingTools();
for (const tool of tools) picker.add(new Option(tool.name, tool.id));

const patternPrices = {
  'xabcd-pattern': [0, 100, 38.2, 69.1, 21.4],
  'abcd-pattern': [100, 38.2, 69.1, 21.4],
  'elliott-impulse': [30, 10, 65, 40, 100],
  'elliott-correction': [10, 70, 0],
  'head-shoulders': [0, 65, 25, 100, 30, 65, 0],
  gartley: [0, 100, 38.2, 69.1, 21.4],
  bat: [0, 100, 55, 82, 11.4],
  butterfly: [0, 100, 21.4, 68.56, -40],
  crab: [0, 100, 50, 94.3, -61.8],
  shark: [0, 100, 50, 115, 0],
  cypher: [0, 100, 50, 130, 27.82],
};

function samplePoints(tool) {
  const n = tool.points || 6;
  const prices = [23805, 23858, 23824, 23848, 23810, 23845, 23818, 23830, 23808];
  let points = Array.from({ length: n }, (_, i) => ({
    time: start + (30 + i * 135 / Math.max(n - 1, 1)) * 300,
    price: prices[i % prices.length],
  }));
  const pattern = patternPrices[tool.id];
  if (pattern) {
    const low = Math.min(...pattern), span = Math.max(...pattern) - low;
    points = points.map((p, i) => ({ ...p, price: 23805 + (pattern[i] - low) / span * 57 }));
  }
  if (tool.freehand || tool.id === 'path' || tool.id === 'polyline') {
    points = Array.from({ length: 40 }, (_, i) => ({
      time: start + (35 + i * 3) * 300,
      price: 23830 + Math.sin(i * .22) * 12 + (i % 5) * 1.5,
    }));
  }
  if (tool.id === 'trend-fib-time') points = [
    { time: start + 30 * 300, price: 23805 },
    { time: start + 55 * 300, price: 23858 },
    { time: start + 80 * 300, price: 23824 },
  ];
  const radial = ['circle', 'fib-circles', 'fib-speed-resistance-arcs', 'fib-spiral'];
  if (radial.includes(tool.id)) {
    const width = Math.max(1, chart.timeScale.width);
    const height = document.getElementById('chart').clientHeight - 22;
    const radius = Math.min(width * .27, height * .3) / (tool.id === 'circle' ? 1 : 2.618);
    points = [
      { time: start + 105 * 300, price: 23835 },
      { time: start + (105 + radius / width * 215) * 300, price: 23835 },
    ];
  }
  if (['sonic', 'supersonic', 'golden-sonic', 'golden-supersonic'].includes(tool.id)) {
    const width = Math.max(1, chart.timeScale.width);
    const height = document.getElementById('chart').clientHeight - 22;
    const lastRatio = tool.id.startsWith('golden') ? 11.09 : 6;
    const radius = Math.min(width * .22, height * .25) / lastRatio;
    points = [
      { time: start + 45 * 300, price: 23835 },
      { time: start + (45 + 2 * radius / width * 215) * 300, price: 23835 },
    ];
  }
  if (tool.expand) points = tool.expand(points, { barSeconds: 300, visibleBars: 210 });
  return points;
}

function instructions(tool) {
  if (tool.freehand) return 'Press, draw, and release.';
  if (tool.points === 0) return 'Click each point, then double-click to finish.';
  return `Click ${tool.points === 1 ? 'once' : tool.points + ' points'} to place it.`;
}

function refresh() {
  const tool = getDrawingTool(picker.value);
  const active = draw.activeTool();
  status.textContent = `${tools.length} tools. ${active ? getDrawingTool(active).name + ': ' + instructions(getDrawingTool(active)) : tool.name + ': drag its body or handles. Right-click a drawing, or use its toolbar, for properties.'} Simulated prices near 23800.`;
  document.getElementById('undo').disabled = !draw.canUndo();
  document.getElementById('redo').disabled = !draw.canRedo();
}

function sample(id = picker.value) {
  picker.value = id;
  const tool = getDrawingTool(id);
  draw.setTool(null);
  draw.fromJSON({ version: 2, drawings: [] });
  draw.add({
    id: 'gallery-sample', tool: tool.id, paneIndex: 0, points: samplePoints(tool),
    style: { ...tool.defaultStyle, color: '#91b5ff', lineWidth: tool.defaultStyle?.lineWidth ?? 1.5 },
    ...(tool.defaultText ? { text: { ...tool.defaultText } } : {}),
  });
  chart.setVisibleLogicalRange({ from: 0, to: 215 });
  chart.setAutoScale(true);
  refresh();
}

picker.addEventListener('change', () => sample());
document.getElementById('sample').addEventListener('click', () => sample());
document.getElementById('draw').addEventListener('click', () => { draw.setTool(picker.value); refresh(); });
document.getElementById('cursor').addEventListener('click', () => { draw.setTool(null); refresh(); });
document.getElementById('undo').addEventListener('click', () => draw.undo());
document.getElementById('redo').addEventListener('click', () => draw.redo());
document.getElementById('clear').addEventListener('click', () => { draw.setTool(null); draw.clear(); refresh(); });
const off = ['draw:tool', 'drawing:select', 'drawing:change'].map(event => chart.on(event, refresh));
window.addEventListener('pagehide', () => { off.forEach(unsubscribe => unsubscribe()); widget.destroy(); }, { once: true });
const requested = new URLSearchParams(location.search).get('tool');
sample(tools.some(tool => tool.id === requested) ? requested : 'trend-line');
window.drawingGallery = { widget, tools, bars, sample, samplePoints };
