// Hover labels for the controls the chart paints on its canvas: a legend
// row's eye, gear and cross, and the close box on an order or position line.
// They have no element to carry a name, so the chart's hover id raises the
// shared tip (hover.js) at the pointer and says what a press does.
import { showCanvasTip, hideCanvasTip } from './hover.js';
import { comparisonState } from './compare.js';
import { volumeShown } from './volume.js';

/** What a press on the canvas control `id` does on chart `pane`, or null for anything else. */
export function canvasControlWords(chart, pane, id) {
  const sep = id.lastIndexOf('::');
  if (sep < 0) return null;
  const owner = id.slice(0, sep), action = id.slice(sep + 2);
  if (owner === 'position') return action === 'close' ? 'Close position' : null;
  if (owner.startsWith('order:')) return action === 'close' ? 'Cancel order' : null;
  let name = null, hidden = false;
  if (owner.startsWith('indicator:')) {
    const study = chart.indicators().find((item) => item.id === owner.slice('indicator:'.length));
    if (study) { name = study.name; hidden = !study.visible(); }
  } else if (owner.startsWith('cmp:')) {
    const spec = comparisonState(pane).items.find((item) => item.symbol === owner.slice('cmp:'.length));
    if (spec) { name = spec.symbol; hidden = spec.hidden === true; }
  } else if (owner === 'volume') {
    name = 'volume'; hidden = !volumeShown(pane);
  }
  if (name === null) return null;
  if (action === 'hide') return (hidden ? 'Show ' : 'Hide ') + name;
  if (action === 'settings') return 'Settings for ' + name;
  if (action === 'close') return 'Remove ' + name;
  return null;
}

/** Follow `chart`'s hover id over `host` (the chart's element) and label its canvas controls. */
export function attachCanvasTips(chart, host, pane) {
  let at = { x: 0, y: 0 };
  const move = (e) => { at = { x: e.clientX, y: e.clientY }; };
  const leave = () => hideCanvasTip();
  host.addEventListener('pointermove', move);
  host.addEventListener('pointerleave', leave);
  const off = chart.on('hover', ({ id }) => {
    const said = id ? canvasControlWords(chart, pane, id) : null;
    if (said) showCanvasTip(said, at);
    else hideCanvasTip();
  });
  return () => { off(); host.removeEventListener('pointermove', move); host.removeEventListener('pointerleave', leave); hideCanvasTip(); };
}
