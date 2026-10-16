// The level editor: a popover listing a ladder tool's levels (retracement,
// extension, channel, fan, time zone, the Gann pair) one row each, with the
// enable switch, the ratio, the colour and the label the tier's `FibLevel`
// carries, plus add, remove and reset to the tool's own defaults.
//
// Pure DOM building: the caller (properties.js) owns the popover, hands in
// the list and gets every edited list back through `onChange`, so the
// writes go through the controller as one undo entry each and this module
// never touches the drawing.
import { formatRatio, levelColor, LEVEL_NEUTRAL } from '/dist/openalgo-charts.draw.mjs';

/** The stylesheet the editor needs; properties.js injects it with its own. */
export const LEVEL_CSS = `
.lved { min-width: 318px; }
.lved__head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.lved__head b { font-weight: 650; color: var(--tx); }
.lved__head label { display: inline-flex; align-items: center; gap: 6px; color: var(--mut); cursor: pointer; }
.lved__rows { max-height: 46vh; overflow: auto; display: grid; gap: 3px; }
.lved__row { display: grid; grid-template-columns: 15px 68px 26px 1fr 22px; align-items: center; gap: 6px; min-height: 28px; }
.lved__row input[type=number], .lved__row input[type=text] { width: 100%; }
.lved__row input[type=color].swatch { width: 26px; height: 26px; }
.lved__row.is-off input[type=number], .lved__row.is-off input[type=text], .lved__row.is-off input[type=color] { opacity: .45; }
.lved__x { width: 22px; height: 22px; display: grid; place-items: center; background: transparent; border: 0;
  border-radius: 5px; color: var(--faint); cursor: pointer; padding: 0; }
.lved__x:hover { background: var(--elev-3, #2a3348); color: #ff9b9b; }
.lved__x svg { width: 12px; height: 12px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; }
.lved__foot { display: flex; gap: 6px; margin-top: 8px; }
.lved__foot button { height: 26px; padding: 0 10px; background: var(--elev); border: 1px solid var(--bd); border-radius: 6px;
  color: var(--tx); font: inherit; font-size: 12px; cursor: pointer; }
.lved__foot button:hover { border-color: var(--bd-hover, #3a4761); }
.lved__reset { margin-left: auto; color: var(--mut); }
.lved__empty { color: var(--faint); padding: 6px 0; }
`;

/** The ladder a new level is drawn from: the conventional ratios, in order. */
export const FIB_SEQUENCE = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.272, 1.414, 1.618, 2, 2.618, 3.618, 4.236];

const RATIO_EPS = 1e-6;
const has = (levels, ratio) => levels.some((l) => Math.abs(l.ratio - ratio) <= RATIO_EPS);

/**
 * The ratio for an added level: the first conventional ratio the ladder does
 * not have, else one past its largest, so "add" always adds something new.
 */
export function nextRatio(levels) {
  for (const r of FIB_SEQUENCE) if (!has(levels, r)) return r;
  let max = 0;
  for (const l of levels) if (Number.isFinite(l.ratio)) max = Math.max(max, l.ratio);
  return max + 1;
}

const clone = (levels) => levels.map((l) => ({ ...l }));

/** A hex colour an `<input type=color>` will take, or the neutral level colour. */
const hexOf = (c) => (typeof c === 'string' && /^#[0-9a-f]{6}$/i.test(c) ? c.toLowerCase() : null);

const CLOSE = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 3l10 10M13 3 3 13"/></svg>';

/**
 * Build the editor.
 *
 * - `levels`: the drawing's list (copied; the caller's array is not touched).
 * - `defaults`: what Reset restores.
 * - `showLabels`: the drawing's flag, or undefined when the tool has no such
 *   field, in which case the switch is not drawn.
 * - `fallbackColor`: what a level with no colour of its own is stroked in.
 * - `labelOf(ratio)`: what the tool prints for an unlabelled level, shown as
 *   the label box's placeholder.
 * - `onChange(levels)`: every edit, with the whole list.
 * - `onLabels(on)`: the labels switch.
 */
export function buildLevelEditor({ levels, defaults, showLabels, fallbackColor, labelOf, onChange, onLabels }) {
  let list = clone(levels || []);
  const fmt = labelOf || formatRatio;
  const root = document.createElement('div');
  root.className = 'lved';

  const head = document.createElement('div');
  head.className = 'lved__head';
  const title = document.createElement('b');
  title.textContent = 'Levels';
  head.appendChild(title);
  if (showLabels !== undefined) {
    const lab = document.createElement('label');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = showLabels === true;
    cb.addEventListener('change', () => { if (onLabels) onLabels(cb.checked); });
    const txt = document.createElement('span');
    txt.textContent = 'Show labels';
    lab.appendChild(cb);
    lab.appendChild(txt);
    head.appendChild(lab);
  }
  root.appendChild(head);

  const rows = document.createElement('div');
  rows.className = 'lved__rows';
  root.appendChild(rows);

  const emit = () => { if (onChange) onChange(clone(list)); };

  function row(lv, i) {
    const r = document.createElement('div');
    r.className = 'lved__row' + (lv.enabled === false ? ' is-off' : '');

    const on = document.createElement('input');
    on.type = 'checkbox';
    on.checked = lv.enabled !== false;
    on.addEventListener('change', () => {
      // `true` is the default, so an enabled level carries no flag at all.
      if (on.checked) delete list[i].enabled; else list[i].enabled = false;
      r.classList.toggle('is-off', !on.checked);
      emit();
    });
    r.appendChild(on);

    const ratio = document.createElement('input');
    ratio.type = 'number';
    ratio.step = '0.001';
    ratio.value = String(lv.ratio);
    ratio.addEventListener('change', () => {
      const n = Number(ratio.value);
      // A blank or unparseable ratio would drop the level on coercion; keep
      // the last good value on screen instead.
      if (ratio.value.trim() === '' || !Number.isFinite(n)) { ratio.value = String(list[i].ratio); return; }
      list[i].ratio = n;
      if (!list[i].label) label.placeholder = fmt(n);
      name();
      emit();
    });
    r.appendChild(ratio);

    const color = document.createElement('input');
    color.type = 'color';
    color.className = 'swatch';
    color.value = hexOf(lv.color) || hexOf(fallbackColor) || hexOf(levelColor(lv.ratio)) || LEVEL_NEUTRAL;
    color.addEventListener('change', () => { list[i].color = color.value; emit(); });
    r.appendChild(color);

    const label = document.createElement('input');
    label.type = 'text';
    label.value = lv.label || '';
    label.placeholder = fmt(lv.ratio);
    label.addEventListener('change', () => {
      const v = label.value.trim();
      if (v === '') delete list[i].label; else list[i].label = v;
      emit();
    });
    r.appendChild(label);

    const x = document.createElement('button');
    x.className = 'lved__x';
    x.type = 'button';
    x.innerHTML = CLOSE;
    x.addEventListener('click', () => { list.splice(i, 1); paint(); emit(); });
    r.appendChild(x);
    // Every control names its level, or seven rows would read the same.
    function name() {
      const level = fmt(list[i].ratio);
      on.setAttribute('aria-label', `Level ${level} enabled`);
      ratio.setAttribute('aria-label', `Level ${level} ratio`);
      color.setAttribute('aria-label', `Level ${level} color`);
      label.setAttribute('aria-label', `Level ${level} label`);
      x.setAttribute('aria-label', `Remove level ${level}`);
    }
    name();
    return r;
  }

  function paint() {
    rows.innerHTML = '';
    if (list.length === 0) {
      const e = document.createElement('div');
      e.className = 'lved__empty';
      e.textContent = 'No levels. Add one, or reset to the defaults.';
      rows.appendChild(e);
      return;
    }
    list.forEach((lv, i) => rows.appendChild(row(lv, i)));
  }
  paint();

  const foot = document.createElement('div');
  foot.className = 'lved__foot';
  const add = document.createElement('button');
  add.type = 'button';
  add.textContent = 'Add level';
  add.addEventListener('click', () => {
    const r = nextRatio(list);
    const lv = { ratio: r };
    const c = levelColor(r);
    if (c !== LEVEL_NEUTRAL) lv.color = c;
    list.push(lv);
    paint();
    emit();
  });
  foot.appendChild(add);
  const reset = document.createElement('button');
  reset.type = 'button';
  reset.className = 'lved__reset';
  reset.textContent = 'Reset';
  reset.addEventListener('click', () => { list = clone(defaults || []); paint(); emit(); });
  foot.appendChild(reset);
  root.appendChild(foot);

  return root;
}
