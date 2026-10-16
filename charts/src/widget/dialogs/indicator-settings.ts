/**
 * Settings for one indicator instance: the descriptor's own `inputs` on one
 * tab and the generated per-plot appearance (`indicatorStyleInputs`) on the
 * other. The same two tabs serve MACD, a Bollinger band and a host's own
 * descriptor, because nothing here is specific to any of them: a descriptor
 * declares a key, a type, a label and a default, and that is a form.
 *
 * Edits apply live through `setSettings` (a colour change restyles without
 * a recompute, a period change recomputes), and Cancel puts back the keys
 * this session touched.
 *
 * On a chart that transforms its bars (Renko, Heikin Ashi and the rest) the
 * inputs lead with the bars the study computes on, which is not a setting of
 * the descriptor but of the study (`IndicatorApi.setBarSource`).
 */
import { widgetText } from '../localization';
import { getIndicator, indicatorDefaults, indicatorStyleInputs } from 'openalgo-charts';
import type { Chart, IndicatorApi, IndicatorBarSource, IndicatorDescriptor, IndicatorInput, IndicatorSettings, IndicatorStudySource } from 'openalgo-charts';
import type { WidgetContext } from '../context';
import { mountIndicatorInputControls, type IndicatorInputControlsHandle } from '../indicator-input-controls';
import { studyNames } from '../objects-panel';
import {
  button, controlsFromInputs, declinedPanel as declined, dialogFrame, el, openPanel, renderForm, tabList,
  type FormHandle, type PanelHandle,
} from '../form';

export type IndicatorSettingsTab = 'inputs' | 'style';

/** The row for the study's bar source. Not a descriptor key: no descriptor names one with an at sign. */
const BAR_SOURCE = '@bars';

export interface IndicatorSettingsOptions {
  /**
   * The instance to edit. Without it the dialog reads `data-instance-id` off
   * the anchor (a legend row's gear), and failing that edits the chart's only
   * indicator; with several and no id it declines with a toast.
   */
  instanceId?: string;
  tab?: IndicatorSettingsTab;
  /** Runs after every write, including a revert. */
  onChange?(inst: IndicatorApi): void;
  /** Runs once when the dialog is gone; `committed` is false after Cancel or Escape. */
  onClose?(committed: boolean): void;
}

function studySource(value: unknown): value is IndicatorStudySource {
  if (value === null || typeof value !== 'object') return false;
  const source = value as Partial<IndicatorStudySource>;
  return source.kind === 'indicator' && typeof source.instanceId === 'string' && typeof source.plotKey === 'string';
}

const detached = (settings: Readonly<IndicatorSettings>): IndicatorSettings => Object.fromEntries(
  Object.entries(settings).map(([key, value]) => [key, studySource(value) ? { ...value } : value]),
);

/** The defaults of a list of inputs, as a settings patch. */
function inputDefaults(inputs: readonly IndicatorInput[]): IndicatorSettings {
  const out: IndicatorSettings = Object.fromEntries(inputs.map(input => [input.key, input.default]));
  for (const input of inputs) {
    if (input.type === 'symbol' && input.exchangeKey !== undefined && !Object.prototype.hasOwnProperty.call(out, input.exchangeKey)) {
      Object.defineProperty(out, input.exchangeKey, { value: '', writable: true, configurable: true, enumerable: true });
    }
  }
  return out;
}

/** Which instance a mount call means; null with a reason when it cannot tell. */
export function resolveInstance(
  ctx: WidgetContext, anchor: HTMLElement | undefined, opts: IndicatorSettingsOptions,
): { inst: IndicatorApi | null; why: string | null } {
  const all = ctx.chart.indicators();
  const id = opts.instanceId ?? anchor?.dataset.instanceId;
  if (id !== undefined) {
    const inst = all.find((i) => i.id === id) ?? null;
    return inst === null ? { inst: null, why: widgetText(ctx, 'That indicator is no longer on the chart') } : { inst, why: null };
  }
  if (all.length === 1) return { inst: all[0]!, why: null }; // the one there is
  return { inst: null, why: all.length === 0 ? widgetText(ctx, 'No indicator on the chart to configure') : widgetText(ctx, 'Pick an indicator from the legend first') };
}

/** A handle for a dialog that never opened, so a caller can `close()` it regardless. */
export function mountIndicatorSettings(
  ctx: WidgetContext, anchor?: HTMLElement, opts: IndicatorSettingsOptions = {},
): PanelHandle {
  const doc = ctx.document;
  const resolved = resolveInstance(ctx, anchor, opts);
  if (resolved.inst === null) return declined(ctx, resolved.why ?? widgetText(ctx, 'No indicator to configure'));
  const inst: IndicatorApi = resolved.inst;
  // Every write would be refused, so the dialog says why instead of opening.
  if (inst.policy().configurable === false) return declined(ctx, widgetText(ctx, '{name} settings are protected', { name: inst.name }));
  const descriptor: IndicatorDescriptor = getIndicator(inst.indicatorId);

  const tabs: Array<{ id: IndicatorSettingsTab; label: string; icon: string; inputs: readonly IndicatorInput[] }> = [];
  // Offered only while the chart transforms its bars: on any other chart the two are the same bars.
  const chart: Partial<Chart> = ctx.chart;
  const primary = chart.primarySeries?.() ?? null;
  const bars: IndicatorInput[] = primary === null || (chart.seriesTransform?.(primary) ?? null) === null ? [] : [{
    key: BAR_SOURCE, type: 'select', label: 'Compute on', default: 'chart',
    options: [{ label: 'Chart bars', value: 'chart' }, { label: 'Underlying bars', value: 'underlying' }],
  }];
  const inputs = [...bars, ...descriptor.inputs];
  if (inputs.length > 0) tabs.push({ id: 'inputs', label: widgetText(ctx, 'Inputs'), icon: 'settings', inputs });
  const style = indicatorStyleInputs(descriptor);
  if (style.length > 0) tabs.push({ id: 'style', label: widgetText(ctx, 'Style'), icon: 'brush', inputs: style });
  if (tabs.length === 0) return declined(ctx, widgetText(ctx, '{name} has nothing to configure', { name: inst.name }));

  const before = detached(inst.settings());
  const barsBefore = bars.length > 0 ? inst.barSource() : 'chart';
  const dirty = new Set<string>();
  // Edits preview live, one write per keystroke or colour drag; the session
  // is one step, and a Cancel that restores every key leaves none.
  const endStep = ctx.history?.group('Study settings') ?? ((): void => {});
  // tabs is not empty past the early return above, so tabs[0] is read with `!`.
  let activeTab: IndicatorSettingsTab = tabs.some((t) => t.id === opts.tab) ? (opts.tab as IndicatorSettingsTab) : tabs[0]!.id;
  let form: FormHandle | null = null;
  let inputControls: IndicatorInputControlsHandle | null = null;
  let writeError: string | null = null;
  let committed = false;
  let offRemoved = (): void => {};
  let offDestroy = (): void => {};

  /** What the form shows: the instance's settings over every declared default. */
  const values = (): IndicatorSettings => ({
    ...indicatorDefaults(descriptor), ...inputDefaults(style), ...inst.settings(),
    ...(bars.length > 0 ? { [BAR_SOURCE]: inst.barSource() } : {}),
  });
  const current = (): boolean => !ctx.chart.isDestroyed && ctx.chart.indicators().includes(inst);
  const report = (error: unknown): void => {
    ctx.toast(error instanceof Error ? error.message : widgetText(ctx, 'The study settings could not be applied'), 'error');
  };
  // The host can lock the study while the dialog is open: a refused write
  // changed nothing, so it is reported and never counted as an edit.
  const locked = (): string => widgetText(ctx, '{name} settings are protected', { name: inst.name });
  const write = (patch: IndicatorSettings): boolean => {
    writeError = null;
    if (!current()) { cancel(); return false; }
    try {
      const { [BAR_SOURCE]: source, ...settings } = patch;
      if ((source !== undefined && source !== inst.barSource() && !inst.setBarSource(source as IndicatorBarSource))
        || (Object.keys(settings).length > 0 && inst.setSettings(detached(settings)) === false)) {
        writeError = locked(); ctx.toast(writeError, 'error'); return false;
      }
    } catch (error) {
      writeError = error instanceof Error ? error.message : widgetText(ctx, 'The study settings could not be applied');
      report(error); return false;
    }
    for (const k of Object.keys(patch)) dirty.add(k);
    opts.onChange?.(inst);
    return true;
  };

  const frame = dialogFrame(doc, { translate: ctx.translate, title: widgetText(ctx, '{name} settings', { name: inst.name }), className: 'oac-indset', onClose: () => cancel() });
  const body = el(doc, 'div', 'oac-indset__pane');
  // One tab needs no tab list: the form alone says what it is.
  if (tabs.length > 1) {
    const nav = tabList(doc, tabs.map((t) => ({ id: t.id, label: t.label, icon: t.icon })), activeTab, 'row',
      (id) => {
        if (form && !form.validate()) { nav.setActive(activeTab); return; }
        activeTab = id as IndicatorSettingsTab; renderPane();
      });
    frame.body.appendChild(nav.el);
  }

  function renderPane(): void {
    inputControls?.destroy(); inputControls = null;
    form?.destroy();
    const tab = tabs.find((t) => t.id === activeTab) ?? tabs[0]!;
    body.innerHTML = '';
    const controls = controlsFromInputs(tab.inputs, { translate: ctx.translate, scope: `indicator.${descriptor.id}` }, ctx.intervals);
    const sources = new Map<string, Map<string, IndicatorStudySource>>();
    for (const input of tab.inputs) {
      if (input.type !== 'source') continue;
      const control = controls.find(item => item.key === input.key)!;
      const options = [...(control.options ?? [])], references = new Map<string, IndicatorStudySource>();
      const names = studyNames(ctx.chart);
      if (input.allowStudyOutputs) for (const producer of ctx.chart.indicators()) {
        if (producer.id === inst.id) continue;
        for (const plot of getIndicator(producer.indicatorId).plots) {
          if (plot.ohlc) continue;
          const token = `study-output:${references.size}`;
          references.set(token, { kind: 'indicator', instanceId: producer.id, plotKey: plot.key });
          const title = widgetText(ctx, `schema.indicator.${producer.indicatorId}.plot.${plot.key}`, {}, plot.title ?? plot.key);
          options.push({ value: token, label: `${names.get(producer.id)!} / ${title}` });
        }
      }
      control.options = options;
      sources.set(input.key, references);
    }
    const shown = (): IndicatorSettings => {
      const result = values();
      for (const [key, references] of sources) {
        const value = result[key];
        if (!studySource(value)) continue;
        let token = [...references].find(([, reference]) => reference.instanceId === value.instanceId && reference.plotKey === value.plotKey)?.[0];
        if (token === undefined) {
          token = `study-output:${references.size}`;
          references.set(token, { ...value });
          const control = controls.find(item => item.key === key)!;
          (control.options as { value: string; label: string }[]).push({ value: token,
            label: widgetText(ctx, 'Unavailable study output: {instanceId} / {plotKey}', { instanceId: value.instanceId, plotKey: value.plotKey }) });
        }
        result[key] = token;
      }
      return result;
    };
    form = renderForm(body, controls, {
      values: shown(), translate: ctx.translate, openOverlay: ctx.openOverlay,
      idPrefix: `oac-ind-${inst.id}`,
      live: true,
      onChange: (key, value) => {
        const reference = typeof value === 'string' ? sources.get(key)?.get(value) : undefined;
        if (!write({ [key]: reference ? { ...reference } : value })) {
          if (!current()) return;
          if (tab.inputs.some(input => input.key === key && ['symbol', 'session', 'multiline', 'price', 'timestamp'].includes(input.type))) {
            form?.setError(key, writeError); return;
          }
          const focused = (doc.activeElement as HTMLElement | null)?.id;
          renderPane();
          if (focused) doc.getElementById(focused)?.focus();
          return;
        }
        form?.sync(shown());
        // The sync re-read the descriptor's conditions; a pick or a search
        // beside a field that just went out of play must follow it.
        inputControls?.refresh();
      },
    });
    inputControls = mountIndicatorInputControls(ctx, {
      instance: inst, inputs: tab.inputs, panel: frame.el,
      field: key => Array.from(body.querySelectorAll('input')).find(field =>
        field.id === `oac-ind-${inst.id}-${key.replace(/[^A-Za-z0-9_-]/g, '-')}`) ?? null,
      onPatch: patch => {
        if (!write(patch)) {
          for (const key of Object.keys(patch)) form?.setError(key, writeError);
          return false;
        }
        for (const key of Object.keys(patch)) form?.setError(key, null);
        form?.sync(shown());
        inputControls?.refresh();
        return true;
      },
    });
  }

  frame.body.appendChild(body);
  renderPane();

  frame.lead.appendChild(button(doc, {
    label: widgetText(ctx, 'Defaults'),
    onClick: () => {
      const tab = tabs.find((t) => t.id === activeTab) ?? tabs[0]!;
      if (write(inputDefaults(tab.inputs))) renderPane();
    },
  }));
  frame.actions.appendChild(button(doc, { label: widgetText(ctx, 'Cancel'), onClick: () => cancel() }));
  frame.actions.appendChild(button(doc, { label: widgetText(ctx, 'OK'), variant: 'primary', onClick: () => ok() }));

  // A graph change can make rollback invalid; Escape must follow the same
  // guarded Cancel path before the overlay is removed.
  frame.el.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    event.preventDefault(); event.stopPropagation(); cancel();
  });
  const handle = openPanel(ctx, frame.el, { placement: 'center', modal: true, dismissOnEscape: false,
    onClose: () => { offRemoved(); offDestroy(); inputControls?.destroy(); form?.destroy(); endStep(); },
  }, () => {
    cancel();
    // A host destroying its overlay cannot keep a rejected rollback open.
    if (handle.isOpen()) { form?.destroy(); handle.close(); opts.onClose?.(false); }
  });
  offRemoved = ctx.chart.on('indicatorRemoved', () => {
    if (!current()) cancel();
    else if (form?.validate()) renderPane();
  });
  offDestroy = ctx.chart.on('destroy', cancel);

  function revert(): boolean {
    if (!current()) {
      ctx.toast(widgetText(ctx, 'That indicator is no longer on the chart'), 'info');
      return true;
    }
    if (committed || dirty.size === 0) return true;
    const back: IndicatorSettings = Object.fromEntries([...dirty].filter(key => key !== BAR_SOURCE).map(key => [key, before[key]]));
    try {
      // Locked since the edits: nothing this dialog does can take them back,
      // so it says so and closes rather than holding the user in it.
      if ((dirty.has(BAR_SOURCE) && inst.barSource() !== barsBefore && !inst.setBarSource(barsBefore))
        || (Object.keys(back).length > 0 && inst.setSettings(detached(back)) === false)) ctx.toast(locked(), 'error');
    } catch (error) { report(error); renderPane(); return false; }
    dirty.clear();
    opts.onChange?.(inst);
    return true;
  }
  function cancel(): void {
    if (!handle.isOpen()) return;
    if (!revert()) return;
    inputControls?.destroy(); form?.destroy();
    handle.close();
    opts.onClose?.(false);
  }
  function ok(): void {
    if (!handle.isOpen()) return;
    if (form && !form.validate()) return;
    committed = true;
    inputControls?.destroy(); form?.destroy();
    handle.close();
    opts.onClose?.(true);
  }

  return { el: frame.el, isOpen: handle.isOpen, close: () => ok() };
}
