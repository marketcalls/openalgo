// The floating properties bar for the selected drawing. Host UI: the engine
// draws on canvas and ships no DOM, so this bar belongs to the page and
// reaches the model only through the controller's public API.
//
// Every control is generated from the tool's settings schema
// (`drawingSettingsSchema`), which declares only the fields the tool's
// `draw` reads. That is the rule the bar leans on: a field in the schema is
// a control with something behind it, and a field absent from it is a
// control that is not shown. With several drawings selected the bar edits
// the fields their schemas share, and writes through `updateMany` so one
// edit is one undo entry.
import {
  drawingSettingsSchema, readDrawingSettings, applyDrawingSettings, getDrawingTool, chromeIconSvg, CHROME_ICON_STROKE,
  formatRatio, gannLabel, cloneLevels, DEFAULT_FIB, INTERVAL_FIELDS,
} from '/dist/openalgo-charts.draw.mjs';
import { el, inTextField, toast, MOD } from './ui.js';
import { attachTip } from './hover.js';
import { openTextEditor, EDITOR_CSS } from './text-editor.js';
import { buildLevelEditor, LEVEL_CSS } from './level-editor.js';
import { createColorPicker, applyTokens, widgetTokens } from '/dist/openalgo-charts.widget.mjs';
import { currentTheme, chartTheme } from './ui.js';
import { INTERVALS, intervalLabel } from './intervals.js';

/** Where the bar's dragged position is kept between sessions. */
export const PROPBAR_POS_KEY = 'oa-charts-propbar';

/** The palette behind every colour swatch: greys, saturated, tints, shades. */
export const PALETTE = [
  '#ffffff', '#d1d4dc', '#b2b5be', '#9598a1', '#787b86', '#5d606b', '#434651', '#2a2e39', '#1e222d', '#000000',
  '#f23645', '#ff9800', '#ffe100', '#4caf50', '#089981', '#00bcd4', '#2962ff', '#673ab7', '#9c27b0', '#e91e63',
  '#faa1a4', '#ffcc80', '#fff176', '#a5d6a7', '#80cbc4', '#80deea', '#90caf9', '#b39ddb', '#ce93d8', '#f48fb1',
  '#b22833', '#e65100', '#fbc02d', '#388e3c', '#00695c', '#0097a7', '#1565c0', '#4527a0', '#6a1b9a', '#ad1457',
];
export const WIDTH_PRESETS = [1, 2, 3, 4];
export const FONT_SIZE_PRESETS = [10, 12, 14, 16, 20, 24, 32];
/** What the layer strokes with when a drawing sets no width. */
const DEFAULT_LINE_WIDTH = 1.5;
const DEFAULT_COLOR = '#2962ff';

// The bar's stylesheet, injected once on mount. It travels with the module
// so the bar renders wherever it is mounted; the page may move the block
// into styles.css and drop the injection.
export const PROPERTIES_CSS = `
.propbar { position: absolute; z-index: 40; display: flex; align-items: center; gap: 2px; padding: 4px 6px;
  background: var(--panel); border: 1px solid var(--bd); border-radius: 9px;
  box-shadow: var(--shadow, 0 10px 30px rgba(0,0,0,.5)); user-select: none; white-space: nowrap; }
.propbar[hidden] { display: none; }
.propbar .grip { display: grid; place-items: center; width: 14px; height: 28px; cursor: grab; color: var(--faint); flex: none; }
.propbar .grip:active { cursor: grabbing; }
.propbar .pb-name { color: var(--mut); font-size: 11px; padding: 0 6px 0 2px; max-width: 110px;
  overflow: hidden; text-overflow: ellipsis; }
.propbar .pb-note, .propbar .pb-off { color: var(--faint); font-size: 11px; text-transform: uppercase; padding: 0 6px; }
.propbar button { height: 28px; min-width: 28px; display: inline-flex; align-items: center; justify-content: center;
  gap: 4px; padding: 0 4px; background: transparent; border: 1px solid transparent; border-radius: 6px;
  color: var(--mut); cursor: pointer; font: inherit; font-size: 12px; flex: none; }
.propbar button:hover { background: var(--elev-2); color: var(--tx); }
.propbar button.is-on { background: var(--on-bg, rgba(34,193,164,.16)); border-color: var(--on-bd, #1d6b5e); color: var(--acc-2); }
.propbar button.danger:hover { color: var(--danger-tx, #ff8b8b); }
.propbar button b { font-weight: 700; }
.propbar button i { font-style: italic; }
.propbar svg { width: 16px; height: 16px; flex: none; }
.propbar .pb-chev svg { width: 11px; height: 11px; opacity: .7; }
.propbar .vsep { width: 1px; height: 18px; background: var(--bd-soft); margin: 0 3px; flex: none; }
.pb-sw { width: 26px; height: 26px; border-radius: 6px; border: 1px solid var(--swatch-bd, rgba(0,0,0,.45)); flex: none;
  box-shadow: inset 0 0 0 1px rgba(255,255,255,.08); }
.propbar button.is-off .pb-sw { opacity: .35; }
.propbar .pb-val { color: var(--tx); font-variant-numeric: tabular-nums; }
.propbar select.pb-select { height: 26px; background-color: var(--elev); color: var(--tx); border: 1px solid var(--bd);
  border-radius: 6px; padding: 0 22px 0 7px; font: inherit; font-size: 12px; outline: none; cursor: pointer; max-width: 96px; }
.propbar select.pb-select:focus { border-color: var(--acc); }
.pb-pop { position: absolute; z-index: 41; min-width: 160px; padding: 8px; background: var(--panel);
  border: 1px solid var(--bd); border-radius: 10px; box-shadow: var(--shadow, 0 14px 40px rgba(0,0,0,.55));
  font-size: 12px; color: var(--tx); }
.pb-pop .pb-grid { display: grid; grid-template-columns: repeat(10, 22px); gap: 4px; }
.pb-pop .pb-grid button { width: 22px; height: 22px; border-radius: 5px; border: 1px solid var(--swatch-bd, rgba(0,0,0,.45));
  padding: 0; cursor: pointer; }
.pb-pop .pb-grid button.is-on { outline: 2px solid var(--acc-2); outline-offset: 1px; }
.pb-pop .pb-row { display: flex; align-items: center; gap: 8px; min-height: 26px; }
.pb-pop .pb-row + .pb-row { margin-top: 4px; }
.pb-pop .pb-row > label { flex: 1 1 auto; color: var(--mut); cursor: pointer; }
.pb-pop .pb-group { color: var(--faint); font-size: 10px; font-weight: 700; text-transform: uppercase;
  letter-spacing: .8px; margin: 8px 0 2px; }
.pb-pop .pb-group:first-child { margin-top: 0; }
.pb-pop input[type=number], .pb-pop input[type=text], .pb-pop select, .pb-pop textarea { height: 24px;
  background: var(--elev); color: var(--tx); border: 1px solid var(--bd); border-radius: 6px; padding: 0 7px;
  font: inherit; font-size: 12px; outline: none; }
.pb-pop input[type=number] { width: 64px; }
.pb-pop input[type=text] { width: 130px; }
.pb-pop select { padding-right: 22px; cursor: pointer; max-width: 150px; }
.pb-pop textarea { width: 100%; height: auto; min-height: 56px; padding: 6px 7px; resize: vertical; display: block; }
.pb-pop input:focus, .pb-pop select:focus, .pb-pop textarea:focus { border-color: var(--acc); }
.pb-pop input[type=range] { width: 130px; accent-color: var(--acc); }
.pb-pop output { min-width: 36px; text-align: right; color: var(--mut); font-variant-numeric: tabular-nums; }
.pb-pop .pb-item { display: flex; align-items: center; gap: 10px; width: 100%; padding: 5px 8px; background: transparent;
  border: 0; border-radius: 6px; color: var(--tx); font: inherit; font-size: 12px; text-align: left; cursor: pointer; }
.pb-pop .pb-item:hover { background: var(--elev-2); }
.pb-pop .pb-item.is-on { background: var(--on-bg, rgba(34,193,164,.16)); color: var(--acc-2); }
.pb-pop .pb-item svg { flex: none; }
.pb-pop .pb-item .pb-key { margin-left: auto; color: var(--faint); font-size: 11px; }
.pb-pop .pb-step { display: inline-flex; align-items: center; gap: 4px; }
.pb-pop .pb-step button { width: 24px; height: 24px; display: grid; place-items: center; background: var(--elev);
  border: 1px solid var(--bd); border-radius: 6px; color: var(--mut); cursor: pointer; padding: 0; }
.pb-pop .pb-step button:hover { color: var(--tx); border-color: var(--bd-hover, #3a4761); }
.pb-pop .pb-step svg { width: 14px; height: 14px; }
.pb-pop input[type=color].swatch { width: 26px; height: 26px; }
.pb-pop hr { border: 0; border-top: 1px solid var(--bd-soft); margin: 7px 0; }
`;

// Glyphs the tier's chrome set does not carry, on the same 16 grid and stroke.
const GLYPH = {
  grip: 'M6 3.5h.01M10 3.5h.01M6 8h.01M10 8h.01M6 12.5h.01M10 12.5h.01',
  extendLeft: 'M14 8H3M6 5 3 8l3 3',
  extendRight: 'M2 8h11M10 5l3 3-3 3',
  levels: 'M2 4h12M2 8h12M2 12h12',
  opacity: 'M3 3h10v10H3zM3 8h10M8 3v10',
  order: 'M2 10h7v4H2zM7 2h7v7H7z',
  // The arrow stops a pixel short of its bar: at the 2px chrome line a tip
  // one stroke away from the bar joins it.
  behind: 'M3 13h10M8 2v7M5 6l3 3 3-3',
  above: 'M3 3h10M8 14V7M5 10l3-3 3 3',
  // A pushpin: the drawing is fixed to the screen.
  pin: 'M6 2h4M7 2v4L5 9h6L9 6V2M8 9v5',
};
const XMLNS = 'http://www.w3.org/2000/svg';
const glyph = (id, stroke = CHROME_ICON_STROKE) =>
  `<svg xmlns="${XMLNS}" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor"`
  + ` stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${GLYPH[id]}"/></svg>`;
const chrome = (id) => chromeIconSvg(id, { size: 16 });
const DASH = { solid: '', dashed: '6 4', dotted: '1 3' };
/** A stroke sample: the line as it will be drawn, at `width` px and `style`. */
const linePreview = (width, style, long = false) => {
  const w = long ? 56 : 28;
  return `<svg xmlns="${XMLNS}" viewBox="0 0 ${w} 16" width="${w}" height="16" fill="none" stroke="currentColor"`
    + ` stroke-linecap="round" aria-hidden="true"><path d="M2 8h${w - 4}" stroke-width="${width}"`
    + (DASH[style] ? ` stroke-dasharray="${DASH[style]}"` : '') + '/></svg>';
};

/** A drawing whose policy keeps the user from editing it. */
const isReadOnly = (d) => d.policy?.editable === false;

/**
 * The fields every one of `toolIds` declares, with the same kind, in the
 * first tool's order. A multi-selection edits this intersection: a field one
 * tool lacks would be a control doing nothing for that drawing.
 */
export function commonSchema(toolIds) {
  const schemas = toolIds.map((t) => drawingSettingsSchema(t));
  if (schemas.length === 0) return { fields: [] };
  const [first, ...rest] = schemas;
  const fields = first.fields.filter((f) => rest.every((s) => s.fields.some((g) => g.path === f.path && g.kind === f.kind)));
  return schemas.every((s) => s.textIsContent === true) ? { fields, textIsContent: true } : { fields };
}

/**
 * `schema` with the intervals a drawing is shown on added: every tool can be
 * limited to a range of intervals, and it is this page that lists them, so
 * the tier declares the pair and the host puts it in.
 */
export function withIntervalFields(schema) {
  return { ...schema, fields: schema.fields.concat(INTERVAL_FIELDS) };
}

/**
 * The colour fields of a schema with their companions: the switch that turns
 * the paint on (`style.fill`, `text.background`, `text.border`) and the
 * opacity it is laid at, found by name so a tool that declares a colour
 * alone gets a plain swatch and one that declares all three gets the popover
 * with the switch and the slider in it.
 */
export function colorControls(schema) {
  const byPath = new Map(schema.fields.map((f) => [f.path, f]));
  const out = [];
  for (const f of schema.fields) {
    if (f.kind !== 'color') continue;
    const stem = f.path.endsWith('Color') ? f.path.slice(0, -'Color'.length) : null;
    const toggle = stem ? byPath.get(stem) : undefined;
    const opacity = stem ? byPath.get(stem + 'Opacity') : undefined;
    out.push({
      field: f,
      toggle: toggle && toggle.kind === 'boolean' ? toggle : null,
      opacity: opacity && opacity.kind === 'opacity' ? opacity : null,
    });
  }
  return out;
}

/** A 6-digit hex an `<input type=color>` accepts, else null. */
const hexOf = (c) => (typeof c === 'string' && /^#[0-9a-f]{6}$/i.test(c) ? c.toLowerCase() : null);
const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));
/** Round to the field's step so 1.5 + 0.5 does not print as 2.0000000000000004. */
const snap = (n, step) => (step ? Math.round(n / step) * step : n);
const fmtNum = (n) => (Number.isInteger(n) ? String(n) : String(Math.round(n * 100) / 100));

function ensureStyle(id, css) {
  if (typeof document === 'undefined' || document.getElementById(id)) return;
  const s = document.createElement('style');
  s.id = id;
  s.textContent = css;
  (document.head || document.body).appendChild(s);
}

/** What the tool prints beside an unlabelled level, for the editor's placeholders. */
function levelLabeller(toolId) {
  if (toolId === 'gann-fan') return gannLabel;
  if (toolId === 'fib-time-zone') return (r) => String(r);
  return formatRatio;
}

/**
 * Mount the bar inside `anchorEl`, the positioned element the chart container
 * sits in (the stage). Call `attach()` after every chart rebuild, once the
 * drawing controller exists: the bar follows `app.draw` and `app.chart`, and
 * subscribes to the chart that is live at that moment. The handle is also
 * stored as `app.props`.
 */
export function mountPropertiesBar(app, anchorEl) {
  const host = anchorEl || el('chart').parentElement;
  const chartEl = () => el('chart');
  ensureStyle('propbar-css', PROPERTIES_CSS + EDITOR_CSS + LEVEL_CSS);

  const bar = document.createElement('div');
  bar.className = 'propbar';
  bar.id = 'propbar';
  bar.hidden = true;
  bar.setAttribute('role', 'toolbar');
  bar.setAttribute('aria-label', 'Drawing properties');
  // A press on the bar is the bar's: window listeners that close menus on
  // any press outside their own box must not see it as "outside".
  bar.addEventListener('pointerdown', (e) => { e.stopPropagation(); });
  host.appendChild(bar);

  let ids = [];        // the selection the bar edits, primary first
  let shownReadOnly = false;   // whether the bar was built in its read-only form
  let schema = null;   // the fields shared by every selected tool
  let pinned = loadPos();
  let pop = null;      // { el, for } while a popover is open
  let colorPickerHandle = null;
  let editor = null;   // the inline text editor while one is open
  let off = [];        // unsubscribers on the chart the bar last attached to
  let syncers = [];    // refresh each control's state from the model

  // ── model access ───────────────────────────────────────────────────────
  const drawingsOf = () => ids.map((id) => (app.draw ? app.draw.get(id) : undefined)).filter(Boolean);
  const primary = () => drawingsOf()[0];
  const values = () => { const d = primary(); return d && schema ? readDrawingSettings(d, schema) : {}; };
  const toolOf = (d) => { try { return getDrawingTool(d.tool); } catch (_) { return null; } };
  const toolName = (d) => { const t = toolOf(d); return t ? t.name : d.tool; };
  /** A boolean field as drawn: the value, else the tool's own default for it. */
  function boolOf(path) {
    const v = values()[path];
    if (v !== undefined) return v === true;
    const d = primary();
    const t = d && toolOf(d);
    if (!t) return false;
    const [root, key] = path.split('.');
    const bag = root === 'style' ? t.defaultStyle : root === 'text' ? t.defaultText : undefined;
    return !!(bag && bag[key] === true);
  }

  /** Write `{ path: value }` to every selected drawing as one undo entry. */
  function apply(patch) {
    if (!app.draw || !schema) return;
    const patches = [];
    for (const d of drawingsOf()) {
      const p = applyDrawingSettings(d, patch, schema);
      if (Object.keys(p).length) patches.push({ id: d.id, patch: p });
    }
    if (patches.length) app.draw.updateMany(patches);
  }

  // ── position ───────────────────────────────────────────────────────────
  function loadPos() {
    try {
      const raw = localStorage.getItem(PROPBAR_POS_KEY);
      const p = raw ? JSON.parse(raw) : null;
      return p && Number.isFinite(p.x) && Number.isFinite(p.y) ? { x: p.x, y: p.y } : null;
    } catch (_) { return null; }
  }
  function savePos() {
    try {
      if (pinned) localStorage.setItem(PROPBAR_POS_KEY, JSON.stringify(pinned));
      else localStorage.removeItem(PROPBAR_POS_KEY);
    } catch (_) { /* storage is a convenience */ }
  }
  /** The chart container's offset inside the host: the rail sits to its left. */
  function chartOffset() {
    const c = chartEl();
    if (!c) return { x: 0, y: 0 };
    const hr = host.getBoundingClientRect();
    const cr = c.getBoundingClientRect();
    return { x: cr.left - hr.left, y: cr.top - hr.top };
  }
  function clampPos(x, y) {
    const hr = host.getBoundingClientRect();
    const o = chartOffset();
    return {
      x: clamp(x, o.x + 4, Math.max(o.x + 4, hr.width - bar.offsetWidth - 4)),
      y: clamp(y, 4, Math.max(4, hr.height - bar.offsetHeight - 4)),
    };
  }
  function place(x, y) {
    const p = clampPos(x, y);
    bar.style.left = p.x + 'px';
    bar.style.top = p.y + 'px';
  }
  /** The selection's anchors on screen, in host px, or null when none is. */
  function bounds(live) {
    const chart = app.chart;
    if (!chart) return null;
    const o = chartOffset();
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const d of live) {
      // The controller knows where a drawing pinned to the screen is; the
      // chart can only map the time and price of one that is not.
      const pinned = d.space === 'viewport' && typeof app.draw.screenPoints === 'function' ? app.draw.screenPoints(d.id) : null;
      const at = pinned || d.points.map((p) => ({ x: chart.timeToCoordinate(p.time), y: chart.priceToCoordinate(p.price, d.paneIndex) }));
      for (const { x: cx, y: cy } of at) {
        if (!Number.isFinite(cx) || cy === null || !Number.isFinite(cy)) continue;
        x0 = Math.min(x0, cx + o.x); x1 = Math.max(x1, cx + o.x);
        y0 = Math.min(y0, cy + o.y); y1 = Math.max(y1, cy + o.y);
      }
    }
    return Number.isFinite(x0) && Number.isFinite(y0) ? { x0, y0, x1, y1 } : null;
  }
  /** Above the selection, below it when there is no room, or where it was dragged. */
  function reposition() {
    if (bar.hidden) return;
    if (pinned) { place(pinned.x, pinned.y); return; }
    const b = bounds(drawingsOf());
    const h = bar.offsetHeight || 36;
    let x = b ? b.x0 : 60;
    let y = b ? b.y0 - h - 10 : 60;
    if (b && y < 4) y = b.y1 + 10;
    place(x, y);
  }

  // ── popovers ───────────────────────────────────────────────────────────
  function closePop() {
    if (!pop) return;
    colorPickerHandle?.destroy();
    colorPickerHandle = null;
    pop.el.remove();
    pop = null;
  }
  /** One popover at a time, under its button (above the bar when that runs off the host). */
  function openPop(btn, build) {
    closePop();
    const p = document.createElement('div');
    p.className = 'pb-pop';
    p.addEventListener('pointerdown', (e) => { e.stopPropagation(); });
    // The page's chords (Delete, Backspace, Escape) stay out of a form.
    p.addEventListener('keydown', (e) => { if (e.key !== 'Escape') e.stopPropagation(); });
    build(p);
    host.appendChild(p);
    const hr = host.getBoundingClientRect();
    const br = btn.getBoundingClientRect();
    const w = p.offsetWidth || 200;
    const hgt = p.offsetHeight || 100;
    let x = br.left - hr.left;
    let y = bar.offsetTop + bar.offsetHeight + 6;
    if (y + hgt > hr.height - 4) y = Math.max(4, bar.offsetTop - hgt - 6);
    p.style.left = clamp(x, 4, Math.max(4, hr.width - w - 4)) + 'px';
    p.style.top = y + 'px';
    pop = { el: p, for: btn };
  }
  // A popover the page's overlay stack already took down (its Escape removes
  // the node) is not open, whatever this module last recorded.
  const popOpen = () => !!pop && pop.el.isConnected !== false;
  const togglePop = (btn, build) => { if (popOpen() && pop.for === btn) closePop(); else openPop(btn, build); };

  // ── control kit ────────────────────────────────────────────────────────
  function button(html, tip, onClick, cls) {
    const b = document.createElement('button');
    b.type = 'button';
    b.innerHTML = html;
    if (cls) b.className = cls;
    // A string is the title alone; a spec or a function passes through, or
    // its chord and sub line are lost and the name reads "[object Object]".
    attachTip(b, typeof tip === 'string' ? { title: tip, side: 'top' } : tip);
    if (onClick) b.addEventListener('click', (e) => { e.stopPropagation(); onClick(e); });
    bar.appendChild(b);
    return b;
  }
  const span = (cls, parent) => { const s = document.createElement('span'); s.className = cls; parent.appendChild(s); return s; };
  const vsep = () => span('vsep', bar);

  function toggleBtn(field, html, tip) {
    const b = button(html, tip, () => apply({ [field.path]: !boolOf(field.path) }));
    b.dataset.path = field.path;
    const paint = () => { b.classList.toggle('is-on', boolOf(field.path)); b.setAttribute('aria-pressed', String(boolOf(field.path))); };
    paint();
    syncers.push(paint);
    return b;
  }

  /** A 26px swatch opening the palette, with the field's switch and opacity when it has them. */
  function colorBtn(ctl, opts = {}) {
    const { field, toggle, opacity } = ctl;
    const b = document.createElement('button');
    b.type = 'button';
    const sw = document.createElement('span');
    sw.className = 'pb-sw';
    b.appendChild(sw);
    b.dataset.path = field.path;
    b.dataset.pop = 'color';
    attachTip(b, { title: opts.tip || field.label, side: 'top' });
    const current = () => values()[field.path] || (opts.fallback ? opts.fallback() : null) || DEFAULT_COLOR;
    const paint = () => {
      sw.style.background = current();
      if (toggle) b.classList.toggle('is-off', !boolOf(toggle.path));
    };
    paint();
    syncers.push(paint);
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      togglePop(b, (p) => {
        if (toggle) {
          const row = document.createElement('div');
          row.className = 'pb-row';
          const cb = document.createElement('input');
          cb.type = 'checkbox';
          cb.dataset.path = toggle.path;
          cb.id = 'pb-' + toggle.path.replace('.', '-');
          cb.checked = boolOf(toggle.path);
          cb.addEventListener('change', () => apply({ [toggle.path]: cb.checked }));
          const lab = document.createElement('label');
          lab.htmlFor = cb.id;
          lab.textContent = toggle.label;
          row.appendChild(cb);
          row.appendChild(lab);
          p.appendChild(row);
          syncers.push(() => { cb.checked = boolOf(toggle.path); });
        }
        const grid = document.createElement('div');
        grid.className = 'pb-grid';
        const cur = String(current()).toLowerCase();
        for (const c of PALETTE) {
          const s = document.createElement('button');
          s.type = 'button';
          s.style.background = c;
          s.setAttribute('aria-label', c);
          s.setAttribute('aria-pressed', String(c === cur));
          if (c === cur) s.classList.add('is-on');
          // Picking a colour for a switched-off paint switches it on: the
          // pick has to show, or it is a control that did nothing.
          s.addEventListener('click', () => {
            apply(toggle ? { [field.path]: c, [toggle.path]: true } : { [field.path]: c });
            closePop();
          });
          grid.appendChild(s);
        }
        p.appendChild(grid);
        p.classList.add('oac-widget', 'host-drawing-widget');
        applyTokens(p, widgetTokens(chartTheme(), currentTheme()));
        colorPickerHandle = createColorPicker(document, {
          id: `pb-shared-${field.path.replace(/[^a-z0-9]/gi, '-')}`,
          label: `${opts.tip || field.label} picker`, value: current(),
          openOverlay: app.alertUi?.context.openOverlay,
          onChange: next => apply(toggle ? { [field.path]: next, [toggle.path]: true } : { [field.path]: next }),
        });
        const shared = document.createElement('div');
        shared.className = 'pb-row pb-shared-color';
        const sharedLabel = document.createElement('span');
        sharedLabel.textContent = 'Palette, recent and custom';
        shared.append(sharedLabel, colorPickerHandle.el);
        p.appendChild(shared);
        const custom = document.createElement('div');
        custom.className = 'pb-row';
        const inp = document.createElement('input');
        inp.type = 'color';
        inp.className = 'swatch';
        inp.value = hexOf(current()) || DEFAULT_COLOR;
        inp.setAttribute('aria-label', 'Custom color');
        inp.addEventListener('change', () => apply(toggle ? { [field.path]: inp.value, [toggle.path]: true } : { [field.path]: inp.value }));
        const lab = document.createElement('label');
        lab.textContent = 'Custom';
        custom.appendChild(inp);
        custom.appendChild(lab);
        p.appendChild(custom);
        if (opacity) p.appendChild(opacityRow(opacity, toggle));
      });
    });
    bar.appendChild(b);
    return b;
  }

  /**
   * Opacity as a slider. It commits on release so a drag is one undo entry;
   * the readout tracks the thumb meanwhile. With a switch alongside, a
   * non-zero opacity turns the paint on, so the slider always shows.
   */
  function opacityRow(field, toggle) {
    const row = document.createElement('div');
    row.className = 'pb-row';
    const lab = document.createElement('label');
    lab.textContent = field.label;
    const range = document.createElement('input');
    range.type = 'range';
    // The label beside it is not tied to it, so the slider carries the name.
    range.setAttribute('aria-label', field.label);
    range.dataset.path = field.path;
    range.min = '0'; range.max = '100'; range.step = '1';
    const out = document.createElement('output');
    const cur = () => { const v = values()[field.path]; return Math.round((v === undefined ? 0.12 : v) * 100); };
    const paint = () => { range.value = String(cur()); out.textContent = cur() + '%'; };
    paint();
    syncers.push(paint);
    range.addEventListener('input', () => { out.textContent = range.value + '%'; });
    range.addEventListener('change', () => {
      const v = Number(range.value) / 100;
      apply(toggle ? { [field.path]: v, [toggle.path]: v > 0 } : { [field.path]: v });
    });
    row.appendChild(lab);
    row.appendChild(range);
    row.appendChild(out);
    return row;
  }

  /** A translucent tool's one opacity (a highlighter) as a bar button. */
  function opacityBtn(field) {
    const b = button(glyph('opacity'), field.label, null);
    b.dataset.path = field.path;
    b.dataset.pop = 'opacity';
    const val = span('pb-val', b);
    const paint = () => { const v = values()[field.path]; val.textContent = Math.round((v === undefined ? 0.12 : v) * 100) + '%'; };
    paint();
    syncers.push(paint);
    b.addEventListener('click', (e) => { e.stopPropagation(); togglePop(b, (p) => p.appendChild(opacityRow(field, null))); });
    return b;
  }

  /** A number as a readout button: presets in the popover, then a stepper bound to the field's range. */
  function numberBtn(field, presets, opts) {
    const unit = opts.unit || '';
    const cur = () => { const v = values()[field.path]; return v === undefined ? opts.fallback : v; };
    const b = button(opts.icon || '', opts.tip || field.label, null);
    b.dataset.path = field.path;
    b.dataset.pop = 'number';
    const val = span('pb-val', b);
    span('pb-chev', b).innerHTML = chrome('chevron-down');
    const paint = () => { val.textContent = fmtNum(cur()) + unit; };
    paint();
    syncers.push(paint);
    const min = field.min === undefined ? -Infinity : field.min;
    const max = field.max === undefined ? Infinity : field.max;
    const step = field.step || 1;
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      togglePop(b, (p) => {
        for (const v of presets) {
          if (v < min || v > max) continue;
          const it = document.createElement('button');
          it.type = 'button';
          it.className = 'pb-item' + (cur() === v ? ' is-on' : '');
          it.setAttribute('aria-pressed', String(cur() === v));
          it.dataset.preset = String(v);
          it.innerHTML = (opts.preview ? opts.preview(v) : '') + '<span>' + fmtNum(v) + unit + '</span>';
          it.addEventListener('click', () => { apply({ [field.path]: v }); closePop(); });
          p.appendChild(it);
        }
        const hr = document.createElement('hr');
        p.appendChild(hr);
        const row = document.createElement('div');
        row.className = 'pb-row pb-step';
        const minus = document.createElement('button');
        minus.type = 'button';
        minus.innerHTML = chrome('minus');
        minus.dataset.act = 'step-minus';
        minus.setAttribute('aria-label', 'Decrease');
        const inp = document.createElement('input');
        inp.type = 'number';
        inp.dataset.act = 'step-input';
        if (field.min !== undefined) inp.min = String(field.min);
        if (field.max !== undefined) inp.max = String(field.max);
        inp.step = String(step);
        inp.value = fmtNum(cur());
        inp.setAttribute('aria-label', field.label);
        const plus = document.createElement('button');
        plus.type = 'button';
        plus.innerHTML = chrome('plus');
        plus.dataset.act = 'step-plus';
        plus.setAttribute('aria-label', 'Increase');
        const set = (n) => { if (Number.isFinite(n)) { apply({ [field.path]: clamp(snap(n, step), min, max) }); inp.value = fmtNum(cur()); } else inp.value = fmtNum(cur()); };
        minus.addEventListener('click', () => set(cur() - step));
        plus.addEventListener('click', () => set(cur() + step));
        inp.addEventListener('change', () => set(inp.value.trim() === '' ? NaN : Number(inp.value)));
        row.appendChild(minus);
        row.appendChild(inp);
        row.appendChild(plus);
        p.appendChild(row);
        syncers.push(() => { if (document.activeElement !== inp) inp.value = fmtNum(cur()); });
      });
    });
    return b;
  }

  /** The dash pattern as a select with the stroke drawn in each row. */
  function lineStyleBtn(field) {
    const cur = () => values()[field.path] || 'solid';
    const b = button('', field.label, null);
    b.dataset.path = field.path;
    b.dataset.pop = 'lineStyle';
    const sample = span('pb-ls', b);
    span('pb-chev', b).innerHTML = chrome('chevron-down');
    const paint = () => { sample.innerHTML = linePreview(2, cur()); };
    paint();
    syncers.push(paint);
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      togglePop(b, (p) => {
        for (const o of field.options || []) {
          const it = document.createElement('button');
          it.type = 'button';
          it.className = 'pb-item' + (cur() === o.value ? ' is-on' : '');
          it.setAttribute('aria-pressed', String(cur() === o.value));
          it.dataset.value = o.value;
          it.innerHTML = linePreview(2, o.value, true) + '<span>' + o.label + '</span>';
          it.addEventListener('click', () => { apply({ [field.path]: o.value }); closePop(); });
          p.appendChild(it);
        }
      });
    });
    return b;
  }

  /** A select, on the bar or in a popover. A value outside the list (a typed font stack) is kept as its own option. */
  function selectFor(field, parent, cls) {
    const sel = document.createElement('select');
    if (cls) sel.className = cls;
    sel.dataset.path = field.path;
    sel.setAttribute('aria-label', field.label);
    const fill = () => {
      sel.innerHTML = '';
      const v = values()[field.path];
      const opts = (field.options || []).slice();
      if (v !== undefined && v !== '' && !opts.some((o) => o.value === v)) opts.push({ value: v, label: 'Custom' });
      for (const o of opts) {
        const op = document.createElement('option');
        op.value = o.value;
        op.textContent = o.label;
        sel.appendChild(op);
      }
      sel.value = v === undefined || v === '' ? (opts[0] ? opts[0].value : '') : v;
    };
    fill();
    syncers.push(() => { if (document.activeElement !== sel) fill(); });
    sel.addEventListener('change', () => apply({ [field.path]: sel.value }));
    sel.addEventListener('pointerdown', (e) => { e.stopPropagation(); });
    parent.appendChild(sel);
    return sel;
  }

  /** A labelled row for any field, for the overflow popovers. */
  function fieldRow(field, parent) {
    const row = document.createElement('div');
    row.className = 'pb-row';
    const lab = document.createElement('label');
    lab.textContent = field.label;
    const id = 'pb-' + field.path.replace('.', '-');
    lab.htmlFor = id;
    let ctl;
    const val = () => values()[field.path];
    switch (field.kind) {
      case 'boolean': {
        ctl = document.createElement('input');
        ctl.type = 'checkbox';
        ctl.checked = boolOf(field.path);
        ctl.addEventListener('change', () => apply({ [field.path]: ctl.checked }));
        syncers.push(() => { ctl.checked = boolOf(field.path); });
        break;
      }
      case 'color': {
        ctl = document.createElement('input');
        ctl.type = 'color';
        ctl.className = 'swatch';
        const paint = () => { ctl.value = hexOf(val()) || hexOf(values()['style.color']) || DEFAULT_COLOR; };
        paint();
        ctl.addEventListener('change', () => apply({ [field.path]: ctl.value }));
        syncers.push(() => { if (document.activeElement !== ctl) paint(); });
        break;
      }
      case 'number': {
        ctl = document.createElement('input');
        ctl.type = 'number';
        if (field.min !== undefined) ctl.min = String(field.min);
        if (field.max !== undefined) ctl.max = String(field.max);
        if (field.step !== undefined) ctl.step = String(field.step);
        const paint = () => { const v = val(); ctl.value = v === undefined ? '' : fmtNum(v); };
        paint();
        ctl.addEventListener('change', () => { if (ctl.value.trim() !== '') apply({ [field.path]: Number(ctl.value) }); else paint(); });
        syncers.push(() => { if (document.activeElement !== ctl) paint(); });
        break;
      }
      case 'opacity': {
        row.appendChild(opacityRow(field, null));
        parent.appendChild(row);
        return row;
      }
      case 'select':
      case 'lineStyle': {
        ctl = selectFor(field, row);
        break;
      }
      case 'interval': {
        // This page's own intervals, and an empty choice for no limit that side.
        const options = [{ value: '', label: 'Any' }].concat(INTERVALS.map((iv) => ({ value: iv, label: intervalLabel(iv) })));
        ctl = selectFor({ ...field, options }, row);
        break;
      }
      case 'text':
      default: {
        const multi = field.path === 'text.value';
        ctl = document.createElement(multi ? 'textarea' : 'input');
        if (!multi) ctl.type = 'text';
        ctl.setAttribute('spellcheck', 'false');
        const paint = () => { const v = val(); ctl.value = v === undefined ? '' : String(v); };
        paint();
        ctl.addEventListener('change', () => apply({ [field.path]: ctl.value }));
        syncers.push(() => { if (document.activeElement !== ctl) paint(); });
        if (multi) {
          ctl.dataset.path = field.path;
          ctl.id = id;
          row.style.display = 'block';
          row.appendChild(lab);
          row.appendChild(ctl);
          parent.appendChild(row);
          return row;
        }
        break;
      }
    }
    ctl.dataset.path = field.path;
    ctl.id = id;
    row.appendChild(lab);
    row.appendChild(ctl);
    parent.appendChild(row);
    return row;
  }

  /** Rows for `fields`, under small uppercase headers per group. */
  function fieldRows(fields, parent) {
    const GROUPS = { line: 'Line', fill: 'Fill', text: 'Text', levels: 'Levels', behavior: 'Behavior', visibility: 'Visibility' };
    let last = null;
    for (const f of fields) {
      const g = f.group || 'behavior';
      if (g !== last) {
        const h = document.createElement('div');
        h.className = 'pb-group';
        h.textContent = GROUPS[g] || g;
        parent.appendChild(h);
        last = g;
      }
      fieldRow(f, parent);
    }
  }

  // ── building the bar ───────────────────────────────────────────────────
  function build(live) {
    bar.innerHTML = '';
    syncers = [];
    const d0 = live[0];
    const byPath = new Map(schema.fields.map((f) => [f.path, f]));
    const shown = new Set();
    const take = (path) => { const f = byPath.get(path); if (f) shown.add(path); return f; };

    // Grip, then what is selected.
    const grip = document.createElement('span');
    grip.className = 'grip';
    grip.innerHTML = glyph('grip', 2.2);
    attachTip(grip, { title: 'Drag to move', sub: 'Double-click to follow the drawing again', side: 'top' });
    startDrag(grip);
    bar.appendChild(grip);
    const name = document.createElement('span');
    name.className = 'pb-name';
    name.textContent = live.length === 1 ? toolName(d0) : `${live.length} drawings`;
    bar.appendChild(name);
    // Its interval range leaves out the one on screen: nothing of it is drawn,
    // so the bar says why rather than editing a shape the user cannot see.
    const off = span('pb-off', bar);
    off.dataset.note = 'interval';
    const paintOff = () => {
      const d = primary();
      const hidden = !!(d && app.draw.shownOnInterval && !app.draw.shownOnInterval(d.id));
      off.hidden = !hidden;
      off.textContent = hidden ? 'Hidden on ' + intervalLabel(app.draw.interval()) : '';
    };
    paintOff();
    syncers.push(paintOff);

    // A selection the user may not edit (the host's session marks, say) gets
    // no control the controller would refuse: it says what it is and offers
    // a copy, which is the user's own drawing and edits normally.
    shownReadOnly = live.every(isReadOnly);
    if (shownReadOnly) {
      span('pb-note', bar).textContent = 'Read-only';
      const copy = button(chrome('duplicate'), { title: 'Duplicate as your own drawing', chord: `${MOD}+D`, side: 'top' }, () => { app.draw.duplicate(ids.slice()); });
      copy.dataset.act = 'duplicate';
      return;
    }

    // Line: colour, width, dash.
    const colours = colorControls(schema);
    const ctlFor = (path) => colours.find((c) => c.field.path === path);
    const strokeC = ctlFor('style.color');
    if (strokeC) { take('style.color'); colorBtn(strokeC, { tip: 'Color' }); }
    const widthF = take('style.lineWidth');
    if (widthF) numberBtn(widthF, WIDTH_PRESETS, { unit: 'px', fallback: DEFAULT_LINE_WIDTH, tip: 'Line width', preview: (w) => linePreview(w, 'solid', true) });
    const styleF = take('style.lineStyle');
    if (styleF) lineStyleBtn(styleF);

    // Fill: the swatch carries the switch and the opacity in its popover; a
    // tool with an opacity and no fill colour (a highlighter) gets the slider alone.
    const fillC = ctlFor('style.fillColor');
    if (fillC) {
      take('style.fillColor');
      if (fillC.toggle) shown.add(fillC.toggle.path);
      if (fillC.opacity) shown.add(fillC.opacity.path);
      colorBtn(fillC, { tip: 'Fill', fallback: () => values()['style.color'] });
    } else {
      const opF = byPath.get('style.fillOpacity');
      if (opF && opF.kind === 'opacity') { take(opF.path); opacityBtn(opF); }
    }

    // Text. When the text is the drawing its face sits on the bar and the
    // content is edited in place; a shape's label gets one button with the
    // whole text group behind it.
    const hasTextValue = byPath.has('text.value');
    if (schema.textIsContent) {
      take('text.value');
      const textC = ctlFor('text.color');
      if (textC) { take('text.color'); colorBtn(textC, { tip: 'Text color', fallback: () => values()['style.color'] }); }
      const sizeF = take('text.fontSize');
      if (sizeF) numberBtn(sizeF, FONT_SIZE_PRESETS, { fallback: 14, tip: 'Font size' });
      const famF = take('text.fontFamily');
      if (famF) selectFor(famF, bar, 'pb-select');
      const boldF = take('text.bold');
      if (boldF) toggleBtn(boldF, '<b>B</b>', 'Bold');
      const italF = take('text.italic');
      if (italF) toggleBtn(italF, '<i>I</i>', 'Italic');
      if (live.length === 1) {
        const eb = button(chrome('text'), { title: 'Edit text', chord: 'Enter', sub: 'Double-click the text also opens it', side: 'top' }, () => editText(d0.id));
        eb.dataset.path = 'text.value';
        eb.dataset.act = 'edit-text';
      }
    } else if (hasTextValue) {
      const textFields = schema.fields.filter((f) => f.path.startsWith('text.'));
      for (const f of textFields) shown.add(f.path);
      const b = button(chrome('text'), () => ({ title: values()['text.value'] ? 'Edit label' : 'Add label', side: 'top' }), null);
      b.dataset.path = 'text.value';
      b.dataset.pop = 'text';
      b.addEventListener('click', (e) => { e.stopPropagation(); togglePop(b, (p) => fieldRows(textFields, p)); });
      // The name follows at once, not on the next hover.
      const paint = () => {
        b.classList.toggle('is-on', !!values()['text.value']);
        b.setAttribute('aria-label', values()['text.value'] ? 'Edit label' : 'Add label');
      };
      paint();
      syncers.push(paint);
    }

    // Pinned to the screen or following the bars: one toggle, since the
    // schema offers the two spaces and nothing between them. Writing the
    // space converts the anchors at the view on screen, so the drawing stays
    // exactly where it is and only stops following the chart.
    const spaceF = take('space');
    if (spaceF) {
      // One name; the pressed state says pinned.
      const pin = button(glyph('pin'), () => ({
        title: 'Pin to the screen',
        sub: values().space === 'viewport' ? 'Click to follow the bars again' : 'Stays put when the chart pans or zooms',
        side: 'top',
      }), () => {
        const want = values().space === 'viewport' ? 'data' : 'viewport';
        apply({ space: want });
        // The controller converts nothing on a pane folded to its strip or
        // hidden behind a maximized one, and the toggle reads the model back,
        // so a click that changed nothing says why.
        if (drawingsOf().some((d) => (d.space || 'data') !== want)) {
          toast('info', `A drawing can be ${want === 'viewport' ? 'pinned' : 'unpinned'} only while its pane is on screen`);
        }
      });
      pin.dataset.path = 'space';
      const paint = () => {
        const on = values().space === 'viewport';
        pin.classList.toggle('is-on', on);
        pin.setAttribute('aria-pressed', String(on));
      };
      paint();
      syncers.push(paint);
    }

    // Extending past the anchors, as two toggles.
    const exL = take('style.extendLeft');
    if (exL) toggleBtn(exL, glyph('extendLeft'), exL.label);
    const exR = take('style.extendRight');
    if (exR) toggleBtn(exR, glyph('extendRight'), exR.label);

    // Levels: the ladder editor, with the labels switch inside it.
    const levelsF = schema.fields.find((f) => f.kind === 'levels');
    if (levelsF) {
      take(levelsF.path);
      const labelsF = take('style.showLabels');
      const b = button(glyph('levels'), 'Levels', null);
      b.dataset.path = levelsF.path;
      b.dataset.pop = 'levels';
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        togglePop(b, (p) => {
          const d = primary();
          const tool = d && toolOf(d);
          const defaults = tool && tool.defaultStyle && tool.defaultStyle.levels ? tool.defaultStyle.levels : DEFAULT_FIB;
          p.appendChild(buildLevelEditor({
            levels: values()[levelsF.path] || cloneLevels(defaults),
            defaults: cloneLevels(defaults),
            showLabels: labelsF ? boolOf(labelsF.path) : undefined,
            fallbackColor: values()['style.color'],
            labelOf: levelLabeller(d ? d.tool : ''),
            onChange: (levels) => apply({ [levelsF.path]: levels }),
            onLabels: (on) => apply({ [labelsF.path]: on }),
          }));
          const labels = labelsF ? p.querySelector('.lved__head input') : null;
          if (labels) labels.dataset.path = labelsF.path;
        });
      });
    }

    // Whatever the schema declares that has no home above.
    const rest = schema.fields.filter((f) => !shown.has(f.path));
    if (rest.length) {
      const b = button(chrome('settings'), 'More settings', null);
      b.dataset.pop = 'more';
      b.addEventListener('click', (e) => { e.stopPropagation(); togglePop(b, (p) => fieldRows(rest, p)); });
    }

    vsep();

    // Lock, visibility, order, duplicate, delete: not schema fields, since
    // every drawing has them.
    // Lock and the eye keep one name each; the pressed state and the glyph
    // say locked or hidden, and follow a keyboard press with no hover.
    const lock = button('', { title: 'Lock', side: 'top' }, () => {
      const on = !(primary() && primary().locked === true);
      app.draw.updateMany(drawingsOf().map((d) => ({ id: d.id, patch: { locked: on } })));
    });
    lock.dataset.act = 'lock';
    const paintLock = () => {
      const on = !!(primary() && primary().locked);
      lock.innerHTML = chrome(on ? 'lock' : 'unlock');
      lock.classList.toggle('is-on', on);
      lock.setAttribute('aria-pressed', String(on));
    };
    paintLock();
    syncers.push(paintLock);

    const eye = button('', { title: 'Hide', side: 'top' }, () => {
      const hidden = !!(primary() && primary().visible === false);
      app.draw.updateMany(drawingsOf().map((d) => ({ id: d.id, patch: { visible: hidden } })));
    });
    eye.dataset.act = 'visible';
    const paintEye = () => {
      const hidden = !!(primary() && primary().visible === false);
      eye.innerHTML = chrome(hidden ? 'eye-off' : 'eye');
      eye.classList.toggle('is-on', hidden);
      eye.setAttribute('aria-pressed', String(hidden));
    };
    paintEye();
    syncers.push(paintEye);

    const order = button(glyph('order'), 'Order', null);
    order.dataset.pop = 'order';
    order.addEventListener('click', (e) => {
      e.stopPropagation();
      togglePop(order, (p) => {
        // Placed between studies (Objects dock) it is on neither side of the series.
        const d = primary();
        const between = !!(d?.stackAbove && app.chart.seriesStack?.(d.paneIndex).includes(d.stackAbove));
        const behind = !between && !!(d && d.zIndex < 0);
        const rows = [
          { act: 'front', icon: chrome('front'), label: 'Bring to front', run: (id) => app.draw.bringToFront(id) },
          { act: 'back', icon: chrome('back'), label: 'Send to back', run: (id) => app.draw.sendToBack(id) },
          { act: 'above', icon: glyph('above'), label: 'In front of the series', on: !behind && !between, run: (id) => app.draw.bringAboveSeries(id) },
          { act: 'behind', icon: glyph('behind'), label: 'Behind the series', on: behind, run: (id) => app.draw.sendBehindSeries(id) },
        ];
        for (const r of rows) {
          const it = document.createElement('button');
          it.type = 'button';
          it.className = 'pb-item' + (r.on ? ' is-on' : '');
          if (r.on !== undefined) it.setAttribute('aria-pressed', String(r.on));
          it.dataset.act = r.act;
          it.innerHTML = r.icon + '<span>' + r.label + '</span>';
          // The controller reorders one drawing at a time (the list position
          // is part of the order), so a multi-selection is several entries.
          it.addEventListener('click', () => { for (const id of ids.slice()) r.run(id); closePop(); });
          p.appendChild(it);
        }
      });
    });

    const dup = button(chrome('duplicate'), { title: 'Duplicate', chord: `${MOD}+D`, side: 'top' }, () => { app.draw.duplicate(ids.slice()); });
    dup.dataset.act = 'duplicate';
    const del = button(chrome('trash'), { title: 'Delete', chord: 'Del', side: 'top' }, () => {
      if (typeof app.draw.removeMany === 'function') app.draw.removeMany(ids.slice());
      else for (const id of ids.slice()) app.draw.remove(id);
    }, 'danger');
    del.dataset.act = 'delete';
  }

  function startDrag(grip) {
    grip.addEventListener('pointerdown', (e) => {
      if (e.button !== undefined && e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();
      closePop();
      const start = { x: e.clientX, y: e.clientY, left: bar.offsetLeft, top: bar.offsetTop };
      const move = (ev) => {
        pinned = clampPos(start.left + (ev.clientX - start.x), start.top + (ev.clientY - start.y));
        place(pinned.x, pinned.y);
      };
      const up = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        savePos();
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    });
    grip.addEventListener('dblclick', (e) => { e.stopPropagation(); pinned = null; savePos(); reposition(); });
  }

  // ── inline text ────────────────────────────────────────────────────────
  // A read-only text drawing is not text the editor could commit.
  const isTextContent = (d) => !!d && !isReadOnly(d) && drawingSettingsSchema(d.tool).textIsContent === true;
  function editText(id) {
    const d = app.draw ? app.draw.get(id) : undefined;
    if (!d || !isTextContent(d)) return null;
    if (editor && editor.isOpen()) editor.commit();
    closePop();
    const tool = toolOf(d);
    editor = openTextEditor({
      app, id, host, chartEl: chartEl(),
      fallback: tool && tool.defaultText && tool.defaultText.value ? tool.defaultText.value : 'Text',
      onDone: () => { editor = null; },
    });
    return editor;
  }
  function settleEditor(commit) {
    if (editor && editor.isOpen()) { if (commit) editor.commit(); else editor.cancel(); }
    editor = null;
  }
  const dialogOpen = () => ['setmodal', 'chartset', 'cmpmodal', 'textmodal'].some((id) => { const n = el(id); return !!n && n.hidden === false; });

  // Double-click on a text drawing opens the editor, and the chart must not
  // also read the double-click as "reset the view": this runs in the capture
  // phase, ahead of the chart's own listener on the same element.
  const onDblClick = (e) => {
    if (!app.draw || app.draw.activeTool()) return;
    const id = app.draw.hovered() || app.draw.selected();
    const d = id ? app.draw.get(id) : undefined;
    if (!isTextContent(d)) return;
    e.stopPropagation();
    e.preventDefault();
    if (app.draw.selected() !== id) app.draw.select(id);
    editText(id);
  };
  // Enter with one text drawing selected. The chords module owns Enter only
  // while a tool is armed, so this cannot collide with "finish the shape".
  const onKey = (e) => {
    if (e.key === 'Escape') {
      if (pop) { closePop(); return; }
      // Nothing of the bar's own to close: Escape then closes the bar the
      // way it closes every floating control, by clearing the selection it
      // belongs to. A press something else already used (the rail marks its
      // placement cancel defaultPrevented), or one meant for a dialog or a
      // text field, is left alone.
      if (e.defaultPrevented || bar.hidden || !app.draw || app.draw.activeTool() || dialogOpen() || inTextField(e)) return;
      app.draw.select(null);
      return;
    }
    if (e.key !== 'Enter' || e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
    if (inTextField(e) || (e.target && e.target.isContentEditable)) return;
    if (!app.draw || app.draw.activeTool() || pop || dialogOpen()) return;
    const sel = app.draw.selection ? app.draw.selection() : [app.draw.selected()].filter(Boolean);
    if (sel.length !== 1) return;
    const d = app.draw.get(sel[0]);
    if (!isTextContent(d)) return;
    e.preventDefault();
    editText(sel[0]);
  };
  const onWindowDown = (e) => {
    if (popOpen() && !pop.el.contains(e.target) && !bar.contains(e.target)) closePop();
  };
  // Keys typed into the editor are the editor's alone. The page's chord
  // handlers listen on the window in the capture phase and only step aside
  // for form controls, so a Backspace in a contentEditable would delete
  // the very drawing being edited; this runs ahead of them (registered
  // first, on the same target and phase) and ends the event's travel.
  const onEditorKey = (e) => {
    if (!editor || !editor.isOpen()) return;
    const box = editor.el;
    if (!(e.target === box || (box.contains && box.contains(e.target)))) return;
    if (e.key === 'Escape') { e.preventDefault(); editor.cancel(); }
    else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); editor.commit(); }
    e.stopImmediatePropagation();
  };
  const chartBox = chartEl();
  if (chartBox) chartBox.addEventListener('dblclick', onDblClick, true);
  window.addEventListener('keydown', onEditorKey, true);
  window.addEventListener('keydown', onKey);
  window.addEventListener('pointerdown', onWindowDown, true);

  // ── lifecycle ──────────────────────────────────────────────────────────
  /**
   * Show the bar for the controller's selection (`id`, when given, is only
   * a hint that it is in there). The same selection shown again refreshes
   * the controls in place rather than rebuilding them, so the rail's
   * forwarded call and the bar's own subscription can both fire on one
   * select without the bar flickering.
   */
  function show(id) {
    if (!app.draw) { hide(); return; }
    const next = app.draw.selection ? app.draw.selection().slice() : [app.draw.selected()].filter(Boolean);
    if (id && !next.includes(id) && app.draw.get(id)) next.unshift(id);
    const same = !bar.hidden && next.length === ids.length && next.every((x, i) => x === ids[i]);
    ids = next;
    const live = drawingsOf();
    if (!live.length) { hide(); return; }
    if (same) { sync(); return; }
    closePop();
    schema = withIntervalFields(commonSchema(live.map((d) => d.tool)));
    build(live);
    bar.hidden = false;
    reposition();
  }
  /** Refresh every control from the model, then park the bar. */
  function sync() {
    if (bar.hidden) return;
    const live = drawingsOf();
    if (!live.length) { hide(); return; }
    // The host made the selection read-only, or lifted that: the controls
    // on the bar are the wrong set, so it is built again rather than synced.
    if (live.every(isReadOnly) !== shownReadOnly) { ids = []; show(); return; }
    for (const s of syncers) s();
    reposition();
  }
  function hide() {
    settleEditor(true);
    closePop();
    ids = [];
    schema = null;
    bar.hidden = true;
  }
  function attach() {
    for (const f of off) f();
    off = [];
    settleEditor(false);
    const chart = app.chart;
    if (!chart || !app.draw) { hide(); return; }
    off.push(chart.on('draw:select', () => show()));
    off.push(chart.on('draw:update', sync));
    // A new interval leaves a drawing picked from the objects panel selected
    // while it is still off the chart, and its note must name the new one.
    off.push(chart.on('data:context', sync));
    // A removal filters the selection without a select event of its own.
    off.push(chart.on('draw:remove', () => { if (!bar.hidden) show(); }));
    off.push(chart.on('viewport', reposition));
    off.push(chart.on('resize', reposition));
    show();
  }
  function destroy() {
    for (const f of off) f();
    off = [];
    settleEditor(false);
    closePop();
    if (chartBox) chartBox.removeEventListener('dblclick', onDblClick, true);
    window.removeEventListener('keydown', onEditorKey, true);
    window.removeEventListener('keydown', onKey);
    window.removeEventListener('pointerdown', onWindowDown, true);
    bar.remove();
    if (app.props === api) app.props = null;
  }

  // `reposition` is what the drawing module forwards on every `draw:update`,
  // and an update is also when a control's state goes stale, so the two
  // are one call.
  const api = {
    el: bar,
    attach, show, sync, reposition: sync, hide, destroy, editText, apply,
    selection: () => ids.slice(),
    schema: () => schema,
    popover: () => (pop ? pop.el : null),
    editor: () => (editor && editor.isOpen() ? editor : null),
    pinnedAt: () => (pinned ? { ...pinned } : null),
  };
  app.props = api;
  return api;
}
