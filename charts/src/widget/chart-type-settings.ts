/**
 * The compact settings dialog for a chart type the chart builds from price
 * boxes: point and figure, and Renko. The Price tab of the chart settings
 * already lists every option the transform declares; this is the short form
 * a trader reaches for while looking at the boxes: their colours, a percent
 * preset, the size and how it is measured, the reversal, and which prices
 * move them.
 *
 * Edits are a draft until OK, so Cancel has nothing to put back and one OK is
 * one undo step. The write is the one the Price tab makes: the transform's
 * options through `setSeriesTransform`, an option back at its default left
 * out of the spec, and the colours through `applyChartSettings`, so a saved
 * layout, the undo history and the widget's persistence see the same change
 * whichever surface made it. The colour rows are read from the settings
 * schema rather than named here, so the dialog offers exactly the colours
 * the renderer paints.
 */
import { applyChartSettings, chartSettingsSchema, getSeriesTransform, readChartSettings } from 'openalgo-charts';
import type { ChartSettingsValues, SeriesTransformSpec } from 'openalgo-charts';
import { historyStep, type WidgetContext } from './context';
import { boxChartType } from './chart-type-choice';
import {
  button, controlsFromInputs, declinedPanel, dialogFrame, el, openPanel, renderForm, selectBox, type FormControl, type PanelHandle,
} from './form';
import { widgetText } from './localization';

type BoxType = 'point-figure' | 'renko';
type Mode = 'fixed' | 'percent' | 'atr' | 'atrPercent';
type Draft = Record<string, number | string>;
type Text = (key: string, fallback: string, values?: Record<string, string>) => string;

/** The percent presets each type offers. */
const PRESETS: Readonly<Record<BoxType, readonly number[]>> = {
  'point-figure': [0.05, 0.1, 0.15, 0.25, 0.5, 1, 2, 3],
  renko: [0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5],
};

/**
 * The colour rows each type's renderer reads, by settings key. A Renko brick
 * spans its open and close exactly, so it has no wick to colour.
 */
const COLOR_ROWS: Readonly<Record<BoxType, readonly string[]>> = {
  'point-figure': ['symbol.body'],
  renko: ['symbol.body', 'symbol.borders'],
};

const MODES: readonly Mode[] = ['fixed', 'percent', 'atr', 'atrPercent'];
/** The option the size box edits in each mode: ATR % is a percent of the ATR, so it shares the percent. */
const SIZE_KEY: Readonly<Record<Mode, string>> = { fixed: 'boxSize', percent: 'percent', atr: 'atrMultiplier', atrPercent: 'percent' };
const usesAtr = (mode: Mode): boolean => mode === 'atr' || mode === 'atrPercent';

/** A percent preset as the button shows it: two decimals under one percent, whole above. */
const presetText = (p: number): string => `${p < 1 ? p.toFixed(2) : String(p)}%`;

let sequence = 0;

interface SizeControls {
  presets: HTMLElement;
  size: HTMLElement;
  atrPeriod: HTMLInputElement;
  /** Join each typed box to its row's label and give it an error line, once the form has drawn the rows. */
  attach(form: HTMLElement): void;
  paint(): void;
  /** The box whose typed value would block OK, or null. */
  invalid(): HTMLInputElement | null;
  /** Show a refusal the engine gave, under the size. */
  refuse(message: string): void;
}

/**
 * The presets, the size with its unit and method, and the ATR length. A typed
 * value goes into the draft only once it is valid; until then the box keeps
 * what was typed and says what is wrong with it, and `changed` repaints.
 */
function sizeControls(doc: Document, t: Text, id: string, type: BoxType, draft: Draft, changed: () => void): SizeControls {
  const mode = (): Mode => draft.mode as Mode;
  const errors = new Map<'size' | 'atrPeriod', string>();
  const number = (suffix: string, inputMode: string): HTMLInputElement => {
    // Text, not a number input, so a mistyped draft stays visible to be corrected.
    const input = el(doc, 'input', 'oac-input--num');
    input.type = 'text';
    input.inputMode = inputMode;
    input.id = `${id}-${suffix}`;
    return input;
  };
  const sizeInput = number('size', 'decimal');
  const atrInput = number('atr', 'numeric');
  const unit = el(doc, 'span', 'oac-ctset__unit');
  const { wrap: modeWrap, select: modeSelect } = selectBox(doc);
  modeSelect.setAttribute('aria-label', t('method', 'Sizing method'));
  const labels: Record<Mode, string> = {
    fixed: t('mode.fixed', 'Absolute'), percent: t('mode.percent', 'Percent'), atr: t('mode.atr', 'ATR'), atrPercent: t('mode.atrPercent', 'ATR %'),
  };
  for (const m of MODES) modeSelect.appendChild(Object.assign(el(doc, 'option', undefined, labels[m]), { value: m }));
  const size = el(doc, 'span', 'oac-ctset__size');
  size.append(sizeInput, unit, modeWrap);
  const presets = el(doc, 'div', 'oac-ctset__presets');
  presets.setAttribute('role', 'group');
  presets.setAttribute('aria-label', t('presets', 'Percent presets'));
  const chips = PRESETS[type].map(p => {
    const b = button(doc, { label: presetText(p), onClick: () => {
      draft.mode = 'percent';
      draft.percent = p;
      errors.delete('size');
      changed();
    } });
    b.classList.add('oac-ctset__preset');
    b.dataset.percent = String(p);
    presets.appendChild(b);
    return { b, p };
  });

  /** Why a typed value cannot be used, or null once it is in the draft. Blank in Absolute is the size from history. */
  const read = (key: 'size' | 'atrPeriod'): string | null => {
    const raw = (key === 'size' ? sizeInput : atrInput).value.trim();
    const n = raw === '' ? (key === 'size' && mode() === 'fixed' ? 0 : NaN) : Number(raw);
    if (key === 'atrPeriod') {
      if (!Number.isInteger(n) || n < 1) return t('error.length', 'Enter a whole number, 1 or more');
      draft.atrPeriod = n;
    } else if (!Number.isFinite(n) || (mode() === 'fixed' ? n < 0 : n <= 0)) {
      return mode() === 'fixed' ? t('error.fixed', 'Enter 0 or a positive number') : t('error.positive', 'Enter a number above 0');
    } else {
      draft[SIZE_KEY[mode()]] = n;
    }
    return null;
  };
  const check = (key: 'size' | 'atrPeriod'): void => {
    const message = read(key);
    if (message === null) errors.delete(key); else errors.set(key, message);
    changed();
  };
  sizeInput.addEventListener('input', () => check('size'));
  atrInput.addEventListener('input', () => check('atrPeriod'));
  modeSelect.addEventListener('change', () => {
    draft.mode = modeSelect.value as Mode;
    // A size typed for another method means nothing in this one.
    errors.delete('size');
    changed();
  });

  const lines = new Map<'size' | 'atrPeriod', HTMLElement>();
  return {
    presets, size, atrPeriod: atrInput,
    attach: (form) => {
      for (const [key, input] of [['size', sizeInput], ['atrPeriod', atrInput]] as const) {
        const row = form.querySelector(`[data-key="${key}"]`);
        const label = row?.querySelector('label') as HTMLLabelElement | null | undefined;
        if (label) label.htmlFor = input.id;
        const line = el(doc, 'div', 'oac-input-error');
        line.id = `${input.id}-error`;
        line.setAttribute('role', 'status');
        input.setAttribute('aria-describedby', line.id);
        row?.appendChild(line);
        lines.set(key, line);
      }
    },
    paint: () => {
      const m = mode();
      modeSelect.value = m;
      if (!errors.has('size')) sizeInput.value = m === 'fixed' && draft.boxSize === 0 ? '' : String(draft[SIZE_KEY[m]] ?? '');
      if (!errors.has('atrPeriod')) atrInput.value = String(draft.atrPeriod ?? 14);
      sizeInput.placeholder = m === 'fixed' ? t('auto', 'Auto') : '';
      sizeInput.title = m === 'fixed' ? t('autoHint', 'Blank or 0 sizes it from the loaded history') : '';
      unit.textContent = m === 'percent' || m === 'atrPercent' ? '%' : m === 'atr' ? t('unit.atr', 'x ATR') : '';
      unit.hidden = unit.textContent === '';
      for (const { b, p } of chips) b.setAttribute('aria-pressed', String(m === 'percent' && draft.percent === p && !errors.has('size')));
      for (const [key, line] of lines) {
        const message = errors.get(key) ?? null;
        (key === 'size' ? sizeInput : atrInput).setAttribute('aria-invalid', String(message !== null));
        line.textContent = message ?? '';
        line.hidden = message === null;
      }
    },
    // The ATR length is read by the two ATR methods alone; an error there under any other is not the user's to fix.
    invalid: () => (errors.has('size') ? sizeInput : errors.has('atrPeriod') && usesAtr(mode()) ? atrInput : null),
    refuse: (message) => { errors.set('size', message); changed(); },
  };
}

/** Close only or high and low, as two radios writing the draft's `method`. */
function priceRadios(doc: Document, t: Text, id: string, draft: Draft, changed: () => void): { el: HTMLElement; paint(): void } {
  const group = el(doc, 'div', 'oac-ctset__radios');
  group.setAttribute('role', 'radiogroup');
  group.setAttribute('aria-label', t('prices', 'Prices'));
  const inputs = (['close', 'hl'] as const).map(value => {
    const item = el(doc, 'label', 'oac-ctset__radio');
    const input = Object.assign(el(doc, 'input'), { type: 'radio', name: `${id}-method`, value });
    input.addEventListener('change', () => { if (input.checked) { draft.method = value; changed(); } });
    item.append(input, el(doc, 'span', undefined, value === 'close' ? t('method.close', 'Close only') : t('method.hl', 'High and low')));
    group.appendChild(item);
    return input;
  });
  return { el: group, paint: () => { for (const input of inputs) input.checked = draft.method === input.value; } };
}

/**
 * Write the draft and the colours as one step, the transform options as the
 * Price tab writes them: an option at its default is left out of the spec.
 * Nothing is written when the chart no longer draws `type`. Returns the
 * engine's refusal, or null.
 */
function writeDraft(ctx: WidgetContext, type: BoxType, draft: Draft, colors: ChartSettingsValues, label: string): string | null {
  const { chart } = ctx;
  const primary = chart.primarySeries();
  const now = primary === null ? null : chart.seriesTransform(primary);
  if (primary === null || now?.type !== type) return null;
  const options: Draft = { ...now.options };
  for (const input of getSeriesTransform(type).inputs) {
    const value = draft[input.key];
    if (value === undefined) continue;
    if (value === input.default) delete options[input.key];
    else options[input.key] = value;
  }
  const next: SeriesTransformSpec = Object.keys(options).length > 0 ? { type, options } : { type };
  try {
    historyStep(ctx, label, () => {
      if (JSON.stringify(next) !== JSON.stringify(now)) chart.setSeriesTransform(primary, next);
      if (Object.keys(colors).length > 0) applyChartSettings(chart, colors);
    });
  } catch (error) {
    // The draft was checked against the bounds the transform holds, so this is rare: shown, not thrown.
    return error instanceof Error ? error.message : String(error);
  }
  return null;
}

/**
 * Open the dialog for the chart type in force. The caller checks
 * `boxChartType` first; asked on any other type it says so and opens nothing.
 */
export function openChartTypeSettings(ctx: WidgetContext, anchor?: HTMLElement): PanelHandle {
  const { chart } = ctx;
  const doc = ctx.document;
  const t: Text = (key, fallback, values = {}) => widgetText(ctx, `schema.ui.chartTypeSettings.${key}`, values, fallback);
  const found = boxChartType(chart);
  const series = chart.primarySeries();
  const spec = series === null ? null : chart.seriesTransform(series);
  if (found === null || spec === null) return declinedPanel(ctx, t('unavailable', 'This chart type has no box settings'));
  // Held in a const of its own: the hoisted commit below cannot see the narrowing.
  const type: BoxType = found;
  const transform = getSeriesTransform(type);
  const title = t('title', '{name} settings', { name: widgetText(ctx, `schema.chartType.${type}`, {}, transform.name) });

  // The draft starts from what the chart is drawing: every option the spec
  // gives, else the transform's declared default.
  const draft: Draft = {};
  for (const input of transform.inputs) draft[input.key] = (spec.options?.[input.key] ?? input.default) as number | string;
  if (!MODES.includes(draft.mode as Mode)) draft.mode = 'fixed';
  const colors: ChartSettingsValues = {};
  const id = `oac-ctset-${++sequence}`;
  const size = sizeControls(doc, t, id, type, draft, () => paint());
  const radios = priceRadios(doc, t, id, draft, () => paint());

  // The schema's colour rows, then the rows built here.
  const sizeGroup = type === 'renko' ? t('group.brick', 'Brick size') : t('group.box', 'Box size');
  const buildGroup = t('group.construction', 'Construction');
  const priceTab = chartSettingsSchema(chart).find(tab => tab.id === 'price')?.inputs ?? [];
  const colorInputs = COLOR_ROWS[type].flatMap(key => priceTab.filter(input => input.key === key));
  const controls: FormControl[] = [
    ...controlsFromInputs(colorInputs, { translate: ctx.translate, scope: 'settings' }).map(c => ({ ...c, group: t('group.colors', 'Colors') })),
    { key: 'presets', kind: 'custom', label: t('presetsLabel', 'Presets'), group: sizeGroup },
    { key: 'size', kind: 'custom', label: t('size', 'Size'), group: sizeGroup },
    { key: 'atrPeriod', kind: 'custom', label: t('atrPeriod', 'ATR length'), group: sizeGroup, visibleWhen: { key: 'mode', is: ['atr', 'atrPercent'] } },
    ...(type === 'renko' ? [] : [{
      key: 'reversal', kind: 'select', label: t('reversal', 'Reversal'), group: buildGroup,
      options: Array.from({ length: 10 }, (_, i) => ({ value: String(i + 1), label: i === 0 ? t('box', '1 box') : t('boxes', '{count} boxes', { count: String(i + 1) }) })),
    } satisfies FormControl]),
    { key: 'method', kind: 'custom', label: t('prices', 'Prices'), group: buildGroup },
  ];
  const bodies: Record<string, HTMLElement> = { presets: size.presets, size: size.size, atrPeriod: size.atrPeriod, method: radios.el };

  let closed = false;
  let panel: PanelHandle | null = null;
  const frame = dialogFrame(doc, { translate: ctx.translate, title, className: 'oac-ctset', onClose: close });
  const formHost = el(doc, 'div', 'oac-ctset__form');
  frame.body.appendChild(formHost);
  const form = renderForm(formHost, controls, {
    idPrefix: id, translate: ctx.translate, openOverlay: ctx.openOverlay,
    values: { ...readChartSettings(chart), mode: draft.mode, reversal: String(draft.reversal ?? 3) },
    onChange: (key, value) => {
      if (key === 'reversal') draft.reversal = Number(value);
      else colors[key] = value as ChartSettingsValues[string];
    },
    custom: control => bodies[control.key] ?? null,
  });
  size.attach(formHost);

  /** Show the draft: the size controls, the radios, and the rows the method shows. */
  function paint(): void {
    size.paint();
    radios.paint();
    form.sync({ mode: draft.mode });
  }
  function close(): void {
    if (closed) return;
    closed = true;
    offDestroy();
    form.destroy();
    panel?.close();
  }
  function commit(): void {
    if (closed) return;
    const invalid = size.invalid();
    if (invalid !== null) { invalid.focus(); return; }
    const refused = writeDraft(ctx, type, draft, colors, title);
    if (refused === null) close(); else size.refuse(refused);
  }

  frame.actions.append(
    button(doc, { label: widgetText(ctx, 'Cancel'), onClick: close }),
    button(doc, { label: widgetText(ctx, 'OK'), variant: 'primary', onClick: commit }),
  );
  formHost.addEventListener('keydown', e => { if ((e as KeyboardEvent).key === 'Enter' && (e.target as HTMLElement).classList.contains('oac-input--num')) commit(); });
  const offDestroy = chart.on('destroy', close);
  paint();
  panel = openPanel(ctx, frame.el, { anchor, modal: true, placement: 'center' }, close);
  return { el: frame.el, close, isOpen: () => !closed && panel!.isOpen() };
}
