import RunnableExample from './RunnableExample';
import { STOCK_BARS_SOURCE } from './synthetic-market';

const code = `${STOCK_BARS_SOURCE}
el.style.display = 'flex';
el.style.flexDirection = 'column';
const controls = document.createElement('div');
controls.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;padding:8px;flex-shrink:0';
const wrap = document.createElement('div');
wrap.style.cssText = 'display:flex;justify-content:center;flex:1;min-height:0;overflow:hidden';
const stage = document.createElement('div');
stage.style.cssText = 'width:100%;max-width:100%;height:100%;min-height:0';
wrap.appendChild(stage);
el.append(controls, wrap);

const bars = stockBars(1700000000, 150, 300, 23800, 173, 0.0015, 2500);
const widget = lib.createWidget(stage, {
  symbol: 'NIFTY SIM', exchange: 'NSE', interval: '5m',
  intervals: ['5m', '15m', '1h'], persist: false,
  feed: { getBars: async () => bars, subscribeBars: () => () => {} },
  navigation: { defaultVisibleBars: 80 },
  rail: { tools: ['trend-line', 'horizontal-line', 'rectangle'] },
});
const listeners = new AbortController();
function button(label, action) {
  const node = document.createElement('button');
  node.type = 'button';
  node.textContent = label;
  node.style.cssText = 'min-height:44px;padding:5px 9px;border:1px solid var(--oac-card-border);border-radius:5px;background:var(--oac-card);color:inherit;font:12px system-ui;cursor:pointer';
  node.addEventListener('click', action, { signal: listeners.signal });
  controls.appendChild(node);
  return node;
}
button('Toggle watermark', () => {
  widget.chart.setWatermarkOptions({ visible: !widget.chart.watermarkOptions().visible });
});
button('Automatic or custom text', () => {
  widget.chart.setWatermarkOptions({ text: widget.chart.watermarkOptions().text ? '' : 'Research' });
});
let brand = true;
const logo = button('Logo: on', () => {
  brand = !brand;
  widget.chart.setBranding(brand);
  logo.textContent = 'Logo: ' + (brand ? 'on' : 'off');
  logo.setAttribute('aria-pressed', String(brand));
});
logo.setAttribute('aria-pressed', 'true');
let narrow = false;
const width = button('Width: desktop', () => {
  narrow = !narrow;
  stage.style.width = narrow ? '360px' : '100%';
  width.textContent = narrow ? 'Width: phone' : 'Width: desktop';
  width.setAttribute('aria-pressed', String(narrow));
});
width.setAttribute('aria-pressed', 'false');
button('Switch theme', () => widget.setTheme(widget.theme() === 'dark' ? 'light' : 'dark'));
button('Chart settings', () => widget.openSettings());
return { destroy() { listeners.abort(); widget.destroy(); } };`;

export default function BrandingWatermarkDemo() {
  return <RunnableExample height={600} tiers={['widget']} code={code}
    caption="Simulated NIFTY bars. The corner logo starts on and the background watermark starts off. Toggle watermark to see the symbol and interval, then try custom text, phone width and both themes. Chart settings offers the same watermark controls under Appearance." />;
}
