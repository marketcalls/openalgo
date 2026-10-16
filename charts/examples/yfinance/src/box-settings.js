// The point and figure and Renko settings dialogs. One card serves both: the
// two transforms size their boxes and bricks the same four ways, so they
// share the size row, the presets and the price choice, and only point and
// figure adds a reversal. Nothing applies until OK: a new box size forms
// other columns, which is a rebuild, so there is no live preview to revert.
import { el } from './ui.js';
import { renderInputRows, collectInputRows, destroyInputRows } from './indicators.js';
import { asStep } from './history.js';
import { autosave } from './persist.js';
import { boxFields, boxOptions, sameType, typeOptions } from './transforms.js';
// The rebuild is the toolbar's changeType, reached through the app the way
// the other modules reach its request changes.
import { chartTypeLabel, shownType } from './toolbar.js';

let app;
let session = null;   // { target, kind, chartType, fields, colors, off }

/** Each transform's dialog: its colours, the style keys they paint, and its presets. */
const KINDS = {
  'point-figure': {
    group: 'Columns', unit: 'column', pair: 'X and O', up: 'X column', down: 'O column', size: 'Box size',
    presets: [0.05, 0.1, 0.15, 0.25, 0.5, 1, 2, 3],
    // The renderer strokes each glyph in the up or down colour and nothing else.
    keys: { up: ['upColor'], down: ['downColor'] },
    defaults: () => ({ up: '#26a69a', down: '#ef5350' }),
  },
  renko: {
    group: 'Bricks', unit: 'brick', pair: 'Up and down', up: 'Up brick', down: 'Down brick', size: 'Brick size',
    presets: [0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5],
    // A brick is a candle body with its border, so both take the colour: a
    // body alone would leave the old colour round every brick.
    keys: { up: ['upColor', 'borderUpColor', 'wickUpColor'], down: ['downColor', 'borderDownColor', 'wickDownColor'] },
    defaults: chart => ({ up: chart.theme().upColor, down: chart.theme().downColor }),
  },
};

const METHODS = [['fixed', 'Absolute'], ['percent', 'Percent'], ['atr', 'ATR'], ['atrPercent', 'ATR %']];
/** What the size box reads under each method, said under it. */
const HINT = {
  fixed: () => 'In price. 0 sizes it from the loaded history.',
  percent: (_, unit) => `Percent of price, sized again as each ${unit} forms.`,
  atr: period => `Multiple of the ${period}-bar ATR.`,
  atrPercent: period => `Percent of the ${period}-bar ATR.`,
};
/** The size a method starts from when the dialog switches to it. */
const START = { fixed: 0, percent: 1, atr: 1, atrPercent: 50 };

/** `0.1` as `0.10%`, the way the presets read: two places under 1, none from 1. */
const presetLabel = value => (value < 1 ? value.toFixed(2) : String(value)) + '%';

function option(select, value, label) {
  const node = document.createElement('option');
  node.value = value;
  node.textContent = label;
  select.appendChild(node);
}

function row(label, forId, ...controls) {
  const node = document.createElement('div');
  node.className = 'set-row';
  const name = document.createElement('label');
  name.textContent = label;
  if (forId) name.htmlFor = forId;
  const ctl = document.createElement('div');
  ctl.className = 'set-ctl';
  ctl.append(...controls);
  node.append(name, ctl);
  return node;
}

function group(text) {
  const node = document.createElement('div');
  node.className = 'set-group';
  node.textContent = text;
  return node;
}

/** The colours the chart draws with now, as the pair the dialog shows. */
function currentColors(target, kind) {
  const style = target.chart.primarySeriesInfo?.()?.style ?? {};
  const fallback = KINDS[kind].defaults(target.chart);
  return { up: style[KINDS[kind].keys.up[0]] ?? fallback.up, down: style[KINDS[kind].keys.down[0]] ?? fallback.down };
}

/** The pair as series style: each colour on every key it paints. */
const styleOf = (kind, colors) => Object.fromEntries(['up', 'down']
  .flatMap(side => KINDS[kind].keys[side].map(key => [key, colors[side]])));

/** Open the dialog for the type `target`'s chart is drawn as. False when that type has none. */
export function openBoxSettings(target) {
  if (!target?.current()) return false;
  if (target.pane === 2 ? app.loading2 || app.loadFailed2 : app.loading || app.loadFailed) {
    el('status').textContent = 'load chart history before changing its settings';
    return false;
  }
  const shown = shownType(target.pane);
  const options = typeOptions(shown);
  if (!options) return false;
  if (session) closeBoxSettings();
  const kind = shown.chartType.slice(2);
  session = { target, kind, chartType: shown.chartType, fields: boxFields(kind, options), colors: null,
    off: target.chart.on('destroy', closeBoxSettings) };
  el('box-title').textContent = chartTypeLabel(shown.chartType) + ' settings';
  renderBody();
  el('box-error').hidden = true;
  el('boxmodal').hidden = false;
  return true;
}

function renderBody() {
  const { target, kind, fields } = session;
  const spec = KINDS[kind];
  const body = el('box-body');
  const colors = currentColors(target, kind);
  // The paired colour row is the generated form's own, with the page's picker.
  renderInputRows(body, [{ type: 'colorPair', key: 'box.colors', label: spec.pair, group: spec.group,
    up: { key: 'box.up', label: spec.up, default: colors.up }, down: { key: 'box.down', label: spec.down, default: colors.down } }],
  { 'box.up': colors.up, 'box.down': colors.down });
  // The picker may spell a colour its own way, so the baseline is what it reads back.
  session.colors = readColors();

  body.appendChild(group('Sizing'));
  const presets = document.createElement('div');
  presets.className = 'box-presets';
  presets.setAttribute('role', 'group');
  presets.setAttribute('aria-label', 'Percent presets');
  for (const value of spec.presets) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'box-preset';
    button.textContent = presetLabel(value);
    button.dataset.value = String(value);
    button.addEventListener('click', () => { method.value = 'percent'; size.value = String(value); refresh(); });
    presets.appendChild(button);
  }
  body.appendChild(presets);

  const size = document.createElement('input');
  size.type = 'number';
  size.id = 'box-size';
  size.min = '0';
  size.value = String(fields.size);
  size.setAttribute('aria-describedby', 'box-hint');
  const method = document.createElement('select');
  method.id = 'box-method';
  method.setAttribute('aria-label', 'Sized by');
  for (const [value, label] of METHODS) option(method, value, label);
  method.value = fields.mode;
  body.appendChild(row(spec.size, size.id, size, method));
  const hint = document.createElement('p');
  hint.id = 'box-hint';
  hint.className = 'box-hint';
  body.appendChild(hint);

  if (kind === 'point-figure') {
    const reversal = document.createElement('select');
    reversal.id = 'box-reversal';
    for (let n = 1; n <= 10; n++) option(reversal, String(n), n === 1 ? '1 box' : `${n} boxes`);
    reversal.value = String(fields.reversal);
    body.appendChild(row('Reversal', reversal.id, reversal));
  }

  body.appendChild(group('Prices'));
  const prices = document.createElement('div');
  prices.className = 'box-radios';
  prices.setAttribute('role', 'radiogroup');
  prices.setAttribute('aria-label', 'Prices');
  for (const [value, label] of [['close', 'Close only'], ['hl', 'High and low']]) {
    const item = document.createElement('label');
    const radio = document.createElement('input');
    radio.type = 'radio';
    radio.name = 'box-prices';
    radio.value = value;
    radio.checked = fields.method === value;
    item.append(radio, label);
    prices.appendChild(item);
  }
  body.appendChild(prices);

  // A method switched to starts from the size it was saved with, or a usual one.
  method.addEventListener('change', () => {
    size.value = String(method.value === fields.mode ? fields.size : START[method.value]);
    refresh();
  });
  size.addEventListener('input', refresh);
  function refresh() {
    hint.textContent = HINT[method.value](fields.atrPeriod, spec.unit);
    size.step = method.value === 'fixed' ? 'any' : '0.01';
    for (const button of presets.children) {
      const on = method.value === 'percent' && Number(size.value) === Number(button.dataset.value);
      button.classList.toggle('is-on', on);
      button.setAttribute('aria-pressed', String(on));
    }
    el('box-error').hidden = true;
  }
  refresh();
}

function readColors() {
  const values = collectInputRows(el('box-body'));
  return { up: values['box.up'], down: values['box.down'] };
}

/** The size typed, or the reason it cannot be used. */
function readSize(mode) {
  const raw = el('box-size').value.trim();
  const value = raw === '' ? NaN : Number(raw);
  if (!Number.isFinite(value) || value < 0) return { error: 'Enter a size of 0 or more' };
  if (mode !== 'fixed' && value === 0) return { error: 'Enter a size above 0' };
  return { value };
}

/** Apply what the dialog holds, then close it. Stays open on a size that cannot be used. */
export function applyBoxSettings() {
  if (!session) return false;
  const { target, kind, chartType, fields } = session;
  if (!target.current()) { closeBoxSettings(); el('status').textContent = 'chart changed; open the settings again'; return false; }
  const mode = el('box-method').value;
  const size = readSize(mode);
  if (size.error) {
    el('box-error').textContent = size.error;
    el('box-error').hidden = false;
    el('box-size').focus();
    return false;
  }
  const checked = [...el('box-body').querySelectorAll('input')].find(input => input.type === 'radio' && input.checked);
  const options = boxOptions(kind, { mode, size: size.value, atrPeriod: fields.atrPeriod,
    reversal: kind === 'point-figure' ? Number(el('box-reversal').value) : undefined, method: checked?.value ?? fields.method });
  const before = session.colors, colors = readColors();
  const recolored = colors.up !== before.up || colors.down !== before.down;
  const shown = shownType(target.pane);
  const next = { chartType, transforms: { ...shown.transforms, [kind]: options } };
  const label = chartTypeLabel(chartType) + ' settings';
  closeBoxSettings();
  if (!sameType(shown, next)) {
    app.changeType(target, next,
      { label, ...(recolored ? { fromColors: styleOf(kind, before), colors: styleOf(kind, colors) } : {}) });
  } else if (recolored) {
    // Colours alone need no rebuild: one step on the chart as it stands.
    asStep(target.pane, () => target.chart.primarySeries()?.applyOptions(styleOf(kind, colors)), label);
    autosave();
  }
  return true;
}

export function closeBoxSettings() {
  if (!session) return;
  const { off } = session;
  session = null;
  off?.();
  destroyInputRows(el('box-body'));
  el('boxmodal').hidden = true;
}

export function initBoxSettings(a) {
  app = a;
  el('box-ok').addEventListener('click', applyBoxSettings);
  el('box-cancel').addEventListener('click', closeBoxSettings);
  el('box-x').addEventListener('click', closeBoxSettings);
  el('boxmodal').addEventListener('click', (e) => { if (e.target.id === 'boxmodal') closeBoxSettings(); });
}
