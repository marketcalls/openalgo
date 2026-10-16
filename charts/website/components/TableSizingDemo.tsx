import RunnableExample from './RunnableExample';
import { STOCK_BARS_SOURCE } from './synthetic-market';

const code = `${STOCK_BARS_SOURCE}
el.style.display = 'flex';
el.style.flexDirection = 'column';
const controls = document.createElement('div');
controls.style.cssText = 'padding:8px 52px 8px 8px;display:flex;align-items:center;gap:10px;flex-wrap:wrap';
const toggle = document.createElement('button');
toggle.type = 'button';
toggle.dataset.tableSizingToggle = '';
toggle.style.cssText = 'min-height:36px;padding:5px 9px;border:1px solid var(--oac-card-border);border-radius:5px;background:var(--oac-card);color:inherit;font:12px system-ui;cursor:pointer';
const status = document.createElement('output');
status.dataset.tableSizingStatus = '';
status.style.font = '12px system-ui';
const stage = document.createElement('div');
stage.style.cssText = 'flex:1;min-height:230px;position:relative';
controls.append(toggle, status);
el.append(controls, stage);
const chart = lib.createChart(stage);
chart.addSeries('candlestick').setData(stockBars(1700000000, 80, 3600, 100, 811, 0.006));
chart.fitContent();
// The table is drawn on the canvas, so its colours follow the chart's palette.
const dark = chart.theme() === lib.darkTheme;
const table = new lib.ChartTable({
  position: 'top-left', cellWidth: 'auto', cellHeight: 22,
  background: dark ? '#17202e' : '#f8fafc', borderColor: dark ? '#40506a' : '#cbd5e1',
});
table.setRows([
  [{ text: 'Metric', bold: true }, { text: 'Reading', bold: true }],
  [{ text: 'Moving averages', fontSize: 40 }, { text: 'Up', textColor: dark ? '#4ade80' : '#15803d' }],
  [{ text: 'Momentum' }, { text: 'Neutral', textColor: dark ? '#fbbf24' : '#b45309' }],
].map(row => row.map(cell => ({ textColor: dark ? '#e2e8f0' : '#1e293b', ...cell }))));
chart.addPrimitive(table);
let automatic = true;
function show() {
  toggle.textContent = automatic ? 'Use fixed columns' : 'Fit columns to text';
  status.textContent = automatic ? 'Automatic widths fit each column.' : 'Fixed 64 px columns clip long text.';
  el.dataset.tableSizingMode = automatic ? 'auto' : 'fixed';
}
toggle.addEventListener('click', () => {
  automatic = !automatic;
  table.setOptions({ cellWidth: automatic ? 'auto' : 64 });
  show();
});
show();
return chart;`;

export default function TableSizingDemo() {
  return <div id="table-sizing-demo"><RunnableExample height={330} code={code}
    caption="Compare automatic columns with fixed widths. The large requested font is limited by the row height; neighboring readings remain separate in both modes." /></div>;
}
