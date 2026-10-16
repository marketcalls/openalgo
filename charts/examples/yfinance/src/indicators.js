import { registeredIndicators, getIndicator, indicatorDefaults, indicatorStyleInputs, INDICATOR_SOURCES } from '/dist/openalgo-charts.mjs';
import { el, esc, currentTheme, chartTheme, toast, closeOverlay, studyNames } from './ui.js';
import { autosave } from './persist.js';
import { capturePaneTarget } from './pane-target.js';
import { historyGroup } from './history.js';
import { createColorPicker, applyTokens, widgetTokens, inputStates } from '/dist/openalgo-charts.widget.mjs';
import { bindTypedField, typedFieldValue, typedFieldError, typedFieldProblem, validateTypedRows, mountReferenceInputControls, outOfPlay } from './indicator-input-controls.js';
import { studyAllows } from './host-study.js';
import { anchoredGrowthSeed } from './anchored-study.js';
import { INTERVALS, intervalLabel } from './intervals.js';

let app;

// ── indicator picker ───────────────────────────────────────────────────
// The picker is built from the registry, not a hardcoded list: anything
// registered (built-in or your own descriptor) shows up here automatically.
export function fillIndicatorPicker() {
  const pick = el('indpick');
  const byCat = new Map();
  for (const d of registeredIndicators().sort((a, b) => a.name.localeCompare(b.name))) {
    const cat = d.category || 'Other';
    if (!byCat.has(cat)) byCat.set(cat, []);
    byCat.get(cat).push(d);
  }
  pick.innerHTML = '';
  for (const [cat, list] of [...byCat].sort((a, b) => a[0].localeCompare(b[0]))) {
    const g = document.createElement('optgroup');
    g.label = cat;
    for (const d of list) {
      const o = document.createElement('option');
      o.value = d.id; o.textContent = d.name;
      g.appendChild(o);
    }
    pick.appendChild(g);
  }
  pick.value = 'macd';
}

// One chip per live instance, reading chart.indicators(), the same handles
// an objects panel would drive.
export function renderIndicatorChips() {
  const host = el('indlist');
  host.innerHTML = '';
  const target = capturePaneTarget(app);
  const chart = target?.chart;
  if (!chart) return;
  // A study its host keeps out of the inventory stays out of the chips too.
  for (const inst of chart.indicators().filter((study) => studyAllows(study, 'listed'))) {
    const chip = document.createElement('span');
    chip.className = 'chip';
    const first = inst.series(Object.keys(inst.values())[0]);
    const color = (inst.settings().color) || '#8892a6';
    chip.innerHTML = `<span class="sw" style="background:${esc(String(color))}"></span><b>${esc(inst.name)}</b>`;
    // No remove button on a study the host keeps; the chip says why instead.
    if (!studyAllows(inst, 'removable')) {
      chip.title = `${inst.name} is protected by the host`;
      chip.classList.add('is-protected');
      host.appendChild(chip);
      continue;
    }
    const x = document.createElement('button');
    x.textContent = '×';
    x.setAttribute('aria-label', `Remove ${inst.name}`);
    x.title = `Remove ${inst.name}`;
    x.addEventListener('click', () => {
      if (!target.current()) return;
      chart.removeIndicator(inst.id);
      renderIndicatorChips();
      el('status').textContent = `removed ${inst.name}`;
    });
    chip.appendChild(x);
    host.appendChild(chip);
    void first;
  }
  if (!chart.indicators().length) host.innerHTML = '<span style="color:var(--faint);font-size:12px">none</span>';
}

/**
 * Why a study stopped drawing, in words that name it once, or null while it
 * draws. Its calculation failed, or the chart refuses its inputs (a
 * timeframe on Renko bricks); either way the error rides on its data status.
 */
function studyErrorText(inst) {
  const status = inst.dataStatus?.();
  if (status?.state !== 'error') return null;
  const why = status.error instanceof Error && status.error.message ? status.error.message : 'its calculation failed';
  return why.startsWith(`${inst.name}: `) ? why : `${inst.name}: ${why}`;
}

/**
 * Say so when a study on `chart` stops drawing: the status line and a toast
 * carry the reason once per new reason, not on every tick that fails again.
 * Returns the call that stops listening.
 */
export function watchStudyStatus(chart) {
  const said = new Map();
  return chart.on('indicator:data-status', ({ id }) => {
    const inst = chart.indicators().find((study) => study.id === id);
    const message = inst ? studyErrorText(inst) : null;
    if (message === null) { said.delete(id); return; }
    if (said.get(id) === message) return;
    said.set(id, message);
    el('status').textContent = message;
    toast('error', message);
  });
}

// A study whose defaults cannot know the loaded history takes its first
// settings from it: an anchor starts where the user can see and grab it.
const SEEDS = { 'anchored-growth-sample': anchoredGrowthSeed };

export function addIndicator(id, target = capturePaneTarget(app)) {
  if (!target?.current()) { el('status').textContent = 'chart changed; open the indicator menu again'; return; }
  if ((target.pane === 2 ? app.loading2 || app.loadFailed2 : app.loading || app.loadFailed)
    || !target.chart.primaryBars().length) { el('status').textContent = 'load chart history before adding a study'; return; }
  const inst = target.chart.addIndicator(id, SEEDS[id]?.(target.chart) ?? {});
  if (target.pane === 1) rememberIndicators();
  renderIndicatorChips();
  autosave();
  el('status').textContent = `added ${inst.name} on chart ${target.pane}`;
  return inst;
}

// ── generated indicator settings ───────────────────────────────────────
// Nothing here is indicator-specific: the descriptor's `inputs` declare a
// key, a type, a label, and a default, which is everything a form needs.
// The same 40 lines render MACD, Bollinger, or your own custom descriptor.
let settingsFor = null; // the IndicatorApi handle being edited
let settingsTarget = null;
let disposeSettings = null;
const formPickers = new WeakMap();
const sourceReferences = new WeakMap();
const formDrafts = new WeakMap();
// Per form: the inputs, the values it opened with, and the rows the
// descriptor's conditions show, hide, enable and disable.
const formRules = new WeakMap();

function studySource(value) {
  return value !== null && typeof value === 'object' && value.kind === 'indicator'
    && typeof value.instanceId === 'string' && typeof value.plotKey === 'string';
}

let settingsTab = 'inputs';
// Each tab switch commits the form and so does OK; the whole session is one
// step on that chart's timeline, and a session that changed nothing is none.
let endSettingsStep = () => {};
function endStudyStep() {
  const end = endSettingsStep;
  endSettingsStep = () => {};
  end();
}

export function openSettings(instanceId, target = capturePaneTarget(app)) {
  if (!target?.current()) return;
  const inst = target.chart.indicators().find((i) => i.id === instanceId);
  if (!inst) return;
  // Every write would be refused, so the dialog says why instead of opening.
  if (!studyAllows(inst, 'configurable')) { el('status').textContent = `${inst.name} settings are protected by the host`; return; }
  disposeSettings?.();
  endStudyStep();
  settingsTarget = target;
  settingsFor = inst;
  endSettingsStep = historyGroup(target.pane, 'Study settings');
  const offDestroy = target.chart.on('destroy', closeSettings);
  const offRemoved = target.chart.on('indicatorRemoved', () => {
    if (currentSettings() && validateTypedRows(el('set-body'))) renderSettingsTab(collectInputRows(el('set-body')));
  });
  disposeSettings = () => { offDestroy(); offRemoved(); };
  el('set-title').textContent = getIndicator(inst.indicatorId).name + ' settings';
  renderSettingsTab();
  el('setmodal').hidden = false;
}

/**
 * The one form renderer. It takes a list of `IndicatorInput`s and the values
 * to seed them with, and knows nothing about where they came from, which is
 * why the chart-settings dialog can hand it `chartSettingsSchema()` output
 * and get the same widgets the indicator dialog has always drawn.
 * `onChange` is optional: the chart dialog previews live, the indicator
 * dialog collects on Apply.
 *
 * `unavailable(key, optionValue)` is optional too, and returns a reason a
 * control (or one option of a select) cannot act in the current context, or
 * null when it can. A control with nothing behind it is drawn disabled with
 * its value still readable rather than left live and inert.
 *
 * An input's `visibleWhen` and `activeWhen` are read against the drafts on
 * every edit, with the same reader the widget uses, and consecutive inputs
 * that share an `inline` id share one row.
 */
export function renderInputRows(host, inputs, values, onChange, unavailable) {
  destroyInputRows(host);
  formPickers.set(host, []);
  formDrafts.set(host, {});
  host.classList.add('oac-widget', 'host-form-widget');
  applyTokens(host, widgetTokens(chartTheme(), currentTheme()));
  host.innerHTML = '';
  const members = [];
  let group = null, head = null, inline = null, box = host;
  for (const input of inputs) {
    if (input.group && input.group !== group) {
      group = input.group;
      head = document.createElement('div');
      head.className = 'set-group';
      head.textContent = group;
      host.appendChild(head);
      // The rows under a heading are a group it names, so a second Up or
      // Color says whose; the box takes no layout of its own.
      head.id = `${host.id}-group-${members.length}`;
      box = document.createElement('div');
      box.className = 'set-rows';
      box.setAttribute('role', 'group');
      box.setAttribute('aria-labelledby', head.id);
      host.appendChild(box);
      inline = null;
    }
    if (inline && (!inlinable(input) || input.inline !== inline.id)) inline = null;
    if (inline) {
      members.push({ ...inlineItem(host, inline, input, values, onChange, unavailable), input, row: inline.row, head });
      continue;
    }
    const lead = inlinable(input);
    const row = input.type === 'colorPair'
      ? colorPairRow(host, input, values, onChange, unavailable)
      : simpleRow(host, input, values, onChange, unavailable, lead);
    box.appendChild(row);
    const fields = [...row.querySelectorAll('[data-key]')];
    const member = { input, row, head, fields, parts: [row], offEl: row, offClass: 'set-row--off', titles: [row],
      offKeys: input.type === 'colorPair' ? [input.up.key, input.down.key] : [input.key] };
    if (lead) {
      row.classList.add('set-row--inline');
      row.dataset.inline = input.inline;
      const label = row.querySelector('label');
      const item = row.querySelector('.set-inline');
      member.parts = item ? [label, item] : [fields[0], label];
      member.titles = item ? [label, item] : [label];
      inline = { id: input.inline, row, ctl: row.querySelector('.set-ctl') };
    }
    members.push(member);
  }
  if (!inputs.some(input => input.activeWhen || input.visibleWhen)) return;
  // Polite and inside the dialog, so the change is read after the edit that
  // caused it without moving focus to announce it.
  const live = document.createElement('div');
  live.className = 'sr-only';
  live.setAttribute('role', 'status');
  live.setAttribute('aria-live', 'polite');
  host.appendChild(live);
  for (const m of members) { m.shown = true; m.enabled = true; }
  // Committed edits only, the way the widget's form reads them: a box counts
  // once it is left, not at every keystroke. Every open renders into the same
  // host, so destroyInputRows takes the listener off again.
  const changed = event => refreshInputRows(host, event.target?.dataset?.key);
  host.addEventListener('change', changed);
  formRules.set(host, { inputs, values, members, live, unavailable, refreshers: [], taken: {},
    detach: () => host.removeEventListener('change', changed) });
  refreshInputRows(host, undefined, false);
}

// A pair is already a row of its own and a multi-line box needs the width.
function inlinable(input) {
  return Boolean(input.inline) && input.type !== 'colorPair' && input.type !== 'multiline';
}

/** A later member of an inline row: its own label and control, dimmed and hidden on their own. */
function inlineItem(host, inline, input, values, onChange, unavailable) {
  const item = document.createElement('span');
  item.className = 'set-inline';
  const label = document.createElement('label');
  label.textContent = input.type === 'timestamp' ? input.label + ' (UTC seconds)' : input.label;
  label.htmlFor = host.id + '_' + input.key;
  if (input.tooltip) label.appendChild(helpMark(input.tooltip));
  const field = inputField(host, input.key, input.type, input, values[input.key], onChange, unavailable);
  describe(field, input);
  if (input.type === 'boolean') item.append(field, label);
  else item.append(label, field._colorPicker?.el || field);
  inline.ctl.appendChild(item);
  bindTypedField(field, input, inline.row);
  return { fields: [field], parts: [item], offEl: item, offClass: 'set-inline--off', titles: [item], offKeys: [input.key] };
}

/**
 * Show, hide, enable and disable the rows of a conditional form from its
 * drafts, and say in the live region what changed. Runs after the first paint
 * and after every edit; a form with no conditions never gets here.
 */
export function refreshInputRows(host, cause, announce = true) {
  const rules = formRules.get(host);
  if (!rules) return;
  const before = document.activeElement;
  // What the widget's form would hold: a number as its last commit left it,
  // and a typed draft it would refuse is no edit, so the last accepted value
  // still decides.
  const draft = { ...rules.values, ...formDrafts.get(host), ...rules.taken };
  for (const m of rules.members) for (const field of m.fields) {
    if (typedFieldProblem(field)) continue;
    draft[field.dataset.key] = rules.taken[field.dataset.key] = field._committed ? field._committed() : fieldValue(field);
  }
  const states = inputStates(rules.inputs, draft);
  const said = { shown: [], hidden: [], on: [], off: [] };
  // A pair's switch and swatches are named by the pair, as the reader counts them.
  const labelOf = key => rules.inputs.find(input => input.key === key
    || [input.enabled, input.up, input.down].some(part => part?.key === key))?.label;
  for (const m of rules.members) {
    const state = states.get(m.input.key);
    const visible = state?.visible ?? true;
    let reason = null;
    if (state && !state.active) {
      const names = state.dependsOn.map(labelOf).filter(Boolean);
      reason = names.length ? `Depends on ${names.join(', ')}` : 'Not used with the current settings';
    }
    for (const part of m.parts) part.hidden = !visible;
    const why = new Map();
    for (const field of m.fields) {
      const r = rules.unavailable?.(field.dataset.key) ?? reason;
      why.set(field.dataset.key, r);
      for (const node of [field, field._colorPicker?.trigger]) {
        if (!node) continue;
        node.disabled = r !== null;
        node.title = field._title(r);
      }
      const error = field._error;
      if (error) error.hidden = !visible || error.textContent === '';
    }
    const off = m.fields.length > 0 && m.offKeys.every(key => why.get(key) !== null);
    m.offEl.classList.toggle(m.offClass, off);
    for (const node of m.titles) node.title = off ? why.get(m.offKeys[0]) ?? '' : '';
    if (m.shown !== visible) said[visible ? 'shown' : 'hidden'].push(m.input.label);
    else if (visible && m.enabled === off) said[off ? 'off' : 'on'].push(m.input.label);
    m.shown = visible;
    m.enabled = !off;
  }
  // A row whose every member left goes too, and a heading with nothing under it.
  for (const outer of ['row', 'head']) {
    const groups = new Map();
    for (const m of rules.members) if (m[outer]) groups.set(m[outer], (groups.get(m[outer]) ?? false) || m.shown);
    for (const [node, any] of groups) node.hidden = !any;
  }
  // Focus inside a row that just left or turned off would fall out of the
  // dialog: give it back to the field that caused this, or the first one left.
  if (before && host.contains(before) && outOfPlay(before, host)) {
    const usable = [...host.querySelectorAll('[data-key]')].filter(field => !outOfPlay(field, host));
    (usable.find(field => field.dataset.key === cause) ?? usable[0])?.focus();
  }
  for (const refresh of rules.refreshers) refresh();
  if (!announce) return;
  const lines = [];
  if (said.shown.length) lines.push('Shown: ' + said.shown.join(', '));
  if (said.hidden.length) lines.push('Hidden: ' + said.hidden.join(', '));
  if (said.on.length) lines.push('Available: ' + said.on.join(', '));
  if (said.off.length) lines.push('Unavailable: ' + said.off.join(', '));
  if (!lines.length) return;
  const message = lines.join('. ');
  // A live region is read when its text changes, so the same words twice in a
  // row differ by a trailing space that is not read out.
  rules.live.textContent = rules.live.textContent === message ? message + '\u00a0' : message;
}

export function destroyInputRows(host) {
  for (const picker of formPickers.get(host) || []) picker.destroy();
  formRules.get(host)?.detach();
  formPickers.delete(host);
  formDrafts.delete(host);
  formRules.delete(host);
}

/**
 * One widget, tagged with the flat key it writes so `collectInputRows` can
 * read the whole form back without knowing which row a field came from. A
 * paired-colour row therefore contributes three ordinary fields, and nothing
 * downstream has to know the pair exists.
 *
 * `spec` carries the widget's own extras: select options, number bounds.
 */
function inputField(host, key, kind, spec, value, onChange, unavailable) {
  const off = unavailable ? unavailable(key) : null;
  let field;
  if (kind === 'select' || kind === 'source' || kind === 'interval') {
    field = document.createElement('select');
    // A timeframe offers the chart's own and the intervals this page serves;
    // a saved code it does not list stays an entry, since a select would
    // otherwise drop it to the chart's own without a word.
    const options = kind === 'interval'
      ? [{ value: '', label: 'Chart' }, ...INTERVALS.concat(value && !INTERVALS.includes(value) ? [value] : [])
        .map(code => ({ value: code, label: intervalLabel(code) }))]
      : [...(kind === 'source' ? INDICATOR_SOURCES : spec.options)];
    const references = new Map();
    if (kind === 'source') {
      for (const output of spec.studyOutputs ?? []) {
        const token = `study-output:${references.size}`;
        references.set(token, { ...output.reference });
        options.push({ value: token, label: output.label });
      }
      if (studySource(value)) {
        let token = [...references].find(([, reference]) => reference.instanceId === value.instanceId && reference.plotKey === value.plotKey)?.[0];
        if (token === undefined) {
          token = `study-output:${references.size}`;
          references.set(token, { ...value });
          options.push({ value: token, label: `Unavailable study output: ${value.instanceId} / ${value.plotKey}` });
        }
        value = token;
      }
      sourceReferences.set(field, references);
    }
    for (const o of options) {
      const opt = document.createElement('option');
      opt.value = o.value; opt.textContent = o.label;
      // One option of a select can be the part with nothing behind it: the
      // title can always show a symbol, and shows a description only when
      // the host has one.
      const why = unavailable ? unavailable(key, o.value) : null;
      if (why) { opt.disabled = true; opt.title = why; }
      field.appendChild(opt);
    }
    field.value = String(value);
  } else if (kind === 'boolean') {
    field = document.createElement('input');
    field.type = 'checkbox';
    field.checked = Boolean(value);
  } else if (kind === 'color') {
    const picker = createColorPicker(document, {
      id: host.id + '_' + key, label: spec.label || key, value,
      disabledReason: off,
      // The chart's overlay layer sits under a modal dialog, so a palette
      // opened there drew behind the card and the card took its clicks. In a
      // dialog the palette opens inline, which the card lets overflow.
      openOverlay: host.closest?.('[aria-modal="true"]') ? undefined
        : app?.['alertUi' + (app.focusPane === 2 ? '2' : '')]?.context.openOverlay,
      // A swatch fires no input event on the form, so a condition that reads
      // a colour has to be told here.
      onChange: next => { onChange?.(key, next); refreshInputRows(host, key); },
    });
    formPickers.get(host).push(picker);
    field = picker.input;
    field._colorPicker = picker;
  } else {
    field = document.createElement(kind === 'multiline' ? 'textarea' : 'input');
    if (kind !== 'multiline') field.type = kind === 'number' ? 'number' : 'text';
    if (kind === 'price' || kind === 'timestamp') field.inputMode = 'decimal';
    if (kind === 'multiline') field.rows = 4;
    if (kind === 'number') {
      if (spec.min !== undefined) field.min = spec.min;
      if (spec.max !== undefined) field.max = spec.max;
      if (spec.step !== undefined) field.step = spec.step;
    }
    field.value = String(value ?? '');
    if (kind === 'number') commitNumber(field, spec, value);
  }
  // Namespaced by host, so both dialogs can exist in the document at once
  // without two fields claiming the same id.
  field.id = host.id + '_' + key;
  field.dataset.key = key;
  field.dataset.kind = kind;
  // The title a field carries for a reason it cannot act, or for none; a
  // swatch keeps its name, since it says nothing about itself.
  field._title = kind === 'color' ? why => why ?? (spec.label || key) : why => why ?? '';
  if (off) { field.disabled = true; field.title = off; }
  if (onChange && kind !== 'color') {
    for (const ev of ['input', 'change']) {
      field.addEventListener(ev, () => onChange(key, fieldValue(field)));
    }
  }
  return field;
}

/**
 * Commit a number box the way the widget's form does, so a condition that
 * reads it answers alike in both: clamped to its bounds, and a blank or
 * unparseable box is no edit and gets the last good value back. Registered
 * before the form's own change listener, so that reads the committed value.
 */
function commitNumber(field, spec, value) {
  let good = value;
  field._committed = () => good;
  field.addEventListener('change', () => {
    const raw = field.value.trim(), n = raw === '' ? NaN : Number(raw);
    if (Number.isFinite(n)) good = Math.min(spec.max ?? Infinity, Math.max(spec.min ?? -Infinity, n));
    if (!Number.isFinite(n) || n !== good) field.value = typeof good === 'number' && Number.isFinite(good) ? String(good) : '';
  });
}

/**
 * The `?` after a label. Attached to the label rather than the row so it stays
 * with the words it explains when a long label wraps. It is for the pointer:
 * inside the label its text would be read as part of the field's name, so the
 * field carries the help as its description instead (describe).
 */
function helpMark(tooltip) {
  const mark = document.createElement('span');
  mark.className = 'set-help';
  mark.textContent = '?';
  mark.title = tooltip;
  mark.setAttribute('aria-hidden', 'true');
  return mark;
}

/** The help text as the field's description. */
function describe(field, input) {
  if (input.tooltip) field.setAttribute('aria-description', input.tooltip);
}

/** A row carrying one control. Booleans sit in the switch column, in front
 *  of their label; everything else sits in the control column on the right.
 *  `lead` starts an inline row: the control column exists for the members
 *  that follow, and the lead's own control sits in an item like theirs, so a
 *  pick button beside it hides with it. */
function simpleRow(host, input, values, onChange, unavailable, lead = false) {
  const row = document.createElement('div');
  row.className = 'set-row';
  const off = unavailable ? unavailable(input.key) : null;
  if (off) { row.classList.add('set-row--off'); row.title = off; }
  const label = document.createElement('label');
  label.textContent = input.type === 'timestamp' ? input.label + ' (UTC seconds)' : input.label;
  label.htmlFor = host.id + '_' + input.key;
  if (input.tooltip) label.appendChild(helpMark(input.tooltip));
  const field = inputField(host, input.key, input.type, input, values[input.key], onChange, unavailable);
  describe(field, input);
  if (input.type === 'boolean') {
    field.classList.add('set-sw');
    row.append(field, label);
    if (lead) {
      const ctl = document.createElement('div');
      ctl.className = 'set-ctl';
      row.appendChild(ctl);
    }
  } else {
    const ctl = document.createElement('div');
    ctl.className = 'set-ctl';
    if (lead) {
      const item = document.createElement('span');
      item.className = 'set-inline';
      item.appendChild(field._colorPicker?.el || field);
      ctl.appendChild(item);
    } else {
      ctl.appendChild(field._colorPicker?.el || field);
    }
    row.append(label, ctl);
  }
  bindTypedField(field, input, row);
  return row;
}

/**
 * A paired-colour row: the property's switch, its label, and both swatches
 * on one line. `enabled` is absent when no flag backs the pair (a candle
 * body is always drawn), and then the switch column is simply left empty
 * rather than filled with a checkbox that would do nothing.
 */
function colorPairRow(host, input, values, onChange, unavailable) {
  const row = document.createElement('div');
  row.className = 'set-row';
  // The row reads as inert only when BOTH halves are: a long position with
  // no short one leaves the pair live and dims the half with nothing to paint.
  const offUp = unavailable ? unavailable(input.up.key) : null;
  const offDown = unavailable ? unavailable(input.down.key) : null;
  if (offUp && offDown) { row.classList.add('set-row--off'); row.title = offUp; }
  if (input.enabled) {
    const sw = inputField(host, input.enabled.key, 'boolean', input.enabled, values[input.enabled.key], onChange, unavailable);
    sw.classList.add('set-sw');
    row.appendChild(sw);
  }
  const label = document.createElement('label');
  label.textContent = input.label;
  label.htmlFor = host.id + '_' + (input.enabled ? input.enabled.key : input.up.key);
  const ctl = document.createElement('div');
  ctl.className = 'set-ctl';
  // A disabled input takes no pointer events, so the reason has to live on
  // the container the hover actually lands on.
  if (offUp || offDown) ctl.title = offUp || offDown;
  for (const half of [input.up, input.down]) {
    const sw = inputField(host, half.key, 'color', half, values[half.key], onChange, unavailable);
    // Which swatch is which is not obvious at 26px, and the pair is too
    // tight for two more labels: the name goes on the control itself, and
    // keeps the reason alongside it when this half has nothing to paint.
    sw.title = sw.disabled ? half.label + ': ' + sw.title : half.label;
    sw._title = why => why === null ? half.label : half.label + ': ' + why;
    // "Body Up", as the widget names it: three rows each have an Up.
    (sw._colorPicker?.trigger || sw).setAttribute('aria-label', `${input.label} ${half.label}`);
    ctl.appendChild(sw._colorPicker?.el || sw);
  }
  row.append(label, ctl);
  return row;
}

/** A field's value in the type its input declared. */
export function fieldValue(field) {
  const reference = sourceReferences.get(field)?.get(field.value);
  if (reference) return { ...reference };
  const kind = field.dataset.kind;
  return kind === 'number' ? Number(field.value) : kind === 'boolean' ? field.checked
    : kind === 'color' && field._colorPicker ? field._colorPicker.read() : typedFieldValue(field);
}

/**
 * Every field in a generated form, as a flat patch keyed by input key. A
 * hidden or disabled field keeps a valid draft, but an invalid one is left out
 * so the stored value stands: nobody can correct what they cannot reach.
 */
export function collectInputRows(host) {
  return { ...formDrafts.get(host), ...Object.fromEntries(
    [...host.querySelectorAll('[data-key]')]
      .filter(field => !(outOfPlay(field, host) && typedFieldProblem(field)))
      .map(field => [field.dataset.key, fieldValue(field)]),
  ) };
}

/** The study's bar source, shown as a row of its inputs; not a descriptor setting. */
const BAR_SOURCE = '@bars';

// Inputs = the descriptor's own `inputs`. Style = `indicatorStyleInputs()`,
// generated per plot (colour, opacity, thickness, line style) so every
// indicator gets the same controls without declaring them.
export function renderSettingsTab(draft) {
  const inst = settingsFor;
  if (!inst) return;
  const descriptor = getIndicator(inst.indicatorId);
  // The bars the study computes on lead its inputs while the chart transforms:
  // on any other chart they are the same bars, and the row would do nothing.
  const primary = settingsTarget.chart.primarySeries?.();
  const bars = settingsTab !== 'style' && primary && settingsTarget.chart.seriesTransform?.(primary) ? [{
    key: BAR_SOURCE, type: 'select', label: 'Compute on', default: 'chart',
    options: [{ label: 'Chart bars', value: 'chart' }, { label: 'Underlying bars', value: 'underlying' }],
  }] : [];
  const inputs = settingsTab === 'style' ? indicatorStyleInputs(descriptor) : [...bars, ...descriptor.inputs.map(input => {
    if (input.type !== 'source' || !input.allowStudyOutputs) return input;
    // Repeated studies are told apart as the widget numbers them, not by an internal id.
    const names = studyNames(settingsTarget.chart);
    const studyOutputs = settingsTarget.chart.indicators().flatMap(producer => producer.id === inst.id ? []
      : getIndicator(producer.indicatorId).plots.filter(plot => !plot.ohlc).map(plot => ({
        reference: { kind: 'indicator', instanceId: producer.id, plotKey: plot.key },
        label: `${names.get(producer.id)} / ${plot.title ?? plot.key}`,
      })));
    return { ...input, studyOutputs };
  })];
  renderInputRows(el('set-body'), inputs, draft ?? { ...inst.settings(), ...(bars.length ? { [BAR_SOURCE]: inst.barSource() } : {}) });
  const target = settingsTarget, host = el('set-body');
  const current = () => settingsFor === inst && settingsTarget === target && target.current()
    && target.chart.indicators().includes(inst);
  const controls = mountReferenceInputControls(app, target, inst, inputs, host, el('setmodal'), patch => {
    if (!current()) return false;
    formDrafts.set(host, { ...formDrafts.get(host), ...patch });
    for (const field of host.querySelectorAll('[data-key]')) {
      if (!Object.prototype.hasOwnProperty.call(patch, field.dataset.key)) continue;
      field.value = String(patch[field.dataset.key]); typedFieldError(field, null);
    }
    refreshInputRows(host);
    return true;
  }, current);
  if (controls) {
    formPickers.get(host).push(controls);
    // A pick or a search beside a field follows it in and out of play.
    formRules.get(host)?.refreshers.push(() => controls.refresh());
  }
}

/** Say that the host locked the study since its settings opened: the write changed nothing. */
function refused(inst) {
  const message = `${inst.name} settings are protected by the host`;
  el('status').textContent = message;
  toast('error', message);
  return false;
}

export function collectSettings() {
  if (!currentSettings()) return false;
  if (!validateTypedRows(el('set-body'))) return false;
  try {
    const { [BAR_SOURCE]: bars, ...settings } = collectInputRows(el('set-body'));
    if (bars !== undefined && bars !== settingsFor.barSource() && !settingsFor.setBarSource(bars)) return refused(settingsFor);
    if (settingsFor.setSettings(settings) === false) return refused(settingsFor);
  } catch (error) {
    const message = error instanceof Error ? error.message : 'The study settings could not be applied';
    el('status').textContent = message;
    toast('error', message);
    for (const field of el('set-body').querySelectorAll('[data-key]')) {
      if (message.includes(`"${field.dataset.key}"`)) typedFieldError(field, message);
    }
    return false;
  }
  rememberSettings();
  return true;
}

function currentSettings() {
  if (settingsTarget?.current() && settingsTarget.chart.indicators().includes(settingsFor)) return true;
  closeSettings();
  el('status').textContent = 'study changed; open its settings again';
  return false;
}

export function rememberIndicators() {
  if (!app.applyingTemplate && app.chart) app.activeIndicators = (app.chart.getState().indicators || [])
    .map(study => ({ ...study, settings: { ...study.settings } }));
}

function rememberSettings() {
  if (settingsTarget?.pane === 1) rememberIndicators();
  autosave();
}

export function applySettings() {
  if (!settingsFor) return;
  const name = settingsFor.name;
  if (!collectSettings()) return;
  renderIndicatorChips();
  el('status').textContent = `${name} updated`;
  closeSettings();
}

export function closeSettings() {
  settingsFor = null;
  settingsTarget = null;
  destroyInputRows(el('set-body'));
  disposeSettings?.();
  disposeSettings = null;
  endStudyStep();
  el('setmodal').hidden = true;
  closeOverlay(el('setmodal'));
  settingsTab = 'inputs';
  for (const t of document.querySelectorAll('.set-tab')) t.classList.toggle('is-on', t.dataset.tab === 'inputs');
}

export function initIndicators(a) {
  app = a;
  document.addEventListener('oac:theme', () => {
    for (const id of ['set-body', 'cset-body']) {
      const host = el(id);
      if (host?.classList.contains('host-form-widget')) applyTokens(host, widgetTokens(chartTheme(), currentTheme()));
    }
  });
  // Add an indicator live: no chart rebuild, no refetch. The handle it returns
  // is what a settings dialog or an objects panel would drive.
  el('indadd').addEventListener('click', () => {
    addIndicator(el('indpick').value);
  });

  for (const tab of document.querySelectorAll('.set-tab')) {
    tab.addEventListener('click', () => {
      if (!settingsFor) return;
      if (!collectSettings()) return;
      settingsTab = tab.dataset.tab;
      for (const t of document.querySelectorAll('.set-tab')) t.classList.toggle('is-on', t === tab);
      renderSettingsTab();
    });
  }
  el('set-ok').addEventListener('click', applySettings);
  el('set-x').addEventListener('click', closeSettings);
  el('set-reset').addEventListener('click', () => {
    if (!currentSettings()) return;
    const d = getIndicator(settingsFor.indicatorId);
    const defaults = indicatorDefaults(d);
    if (settingsFor.setSettings(defaults) === false) { refused(settingsFor); return; }
    rememberSettings();
    renderIndicatorChips();
    closeSettings();
  });
  el('setmodal').addEventListener('click', (e) => { if (e.target.id === 'setmodal') closeSettings(); });
}
