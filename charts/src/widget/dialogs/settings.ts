/**
 * The chart settings dialog, generated from `chartSettingsSchema`.
 *
 * Nothing here names a control. The engine describes its tabs and inputs,
 * `readChartSettings` reports what the chart is drawing now, and
 * `applyChartSettings` takes a one-key patch back, so a control the engine
 * adds appears here on its own and a control the engine has no backing for
 * cannot appear at all. Edits apply live, which is the only honest preview of
 * a colour; Cancel and Escape put back the keys this session touched, and
 * only those, so an axis the user dragged while the dialog was open stays
 * where they left it.
 */
import { widgetText } from '../localization';
import { applyChartSettings, chartSettingsSchema, readChartSettings } from 'openalgo-charts';
import type { ChartSettingsTab, ChartSettingsTabId, ChartSettingsValues } from 'openalgo-charts';
import { historyStep, type WidgetContext } from '../context';
import {
  button, controlsFromInputs, dialogFrame, el, openPanel, renderForm, tabList,
  type FormHandle, type PanelHandle,
} from '../form';

/**
 * The chrome glyph beside each settings tab, keyed by the schema's tab id
 * rather than by position, so a reordering in the engine cannot shuffle the
 * pictures. Typed on the full id union: a tab the engine adds fails the build
 * here until it has a picture.
 */
const SETTINGS_TAB_ICONS: Readonly<Record<ChartSettingsTabId, string>> = {
  price: 'chart-candlestick', readout: 'legend', axes: 'axes', appearance: 'panels', trading: 'trading',
};

export interface SettingsDialogOptions {
  /** The tab to open on. Default: the first tab with a control in it. */
  tab?: ChartSettingsTabId;
  /**
   * Why a control, or one option of a select, cannot act in this host right
   * now, or null. A host that draws its own trade chrome knows whether there
   * is a position to recolour; the engine does not.
   */
  unavailable?(key: string, option?: string): string | null;
  /** Runs after every write, including a revert, for state a host keeps outside the schema. */
  onApply?(patch: Readonly<Partial<ChartSettingsValues>>): void;
  /** Runs once when the dialog is gone; `committed` is false after Cancel or Escape. */
  onClose?(committed: boolean): void;
}

/** The defaults of one tab as a patch: both halves and the switch of a paired colour included. */
export function tabDefaults(tab: ChartSettingsTab): ChartSettingsValues {
  const patch: ChartSettingsValues = {};
  for (const input of tab.inputs) {
    if (input.type === 'colorPair') {
      patch[input.up.key] = input.up.default;
      patch[input.down.key] = input.down.default;
      if (input.enabled !== undefined) patch[input.enabled.key] = input.enabled.default;
    } else {
      patch[input.key] = input.default;
    }
  }
  return patch;
}

/**
 * Open the chart settings dialog, centred over the widget. `anchor` is
 * accepted for the registry's uniform signature and not used: a dialog this
 * size is not a popover.
 */
export function mountSettingsDialog(
  ctx: WidgetContext, _anchor?: HTMLElement, opts: SettingsDialogOptions = {},
): PanelHandle {
  const { chart } = ctx;
  const doc = ctx.document;
  // An empty tab is hidden rather than shown bare: the Price tab has no
  // controls before a series exists, and a tab of nothing reads as broken.
  const tabs = chartSettingsSchema(chart).filter((t) => t.inputs.length > 0);
  const before = readChartSettings(chart);
  const dirty = new Set<string>();
  let activeTab: string = tabs.some((t) => t.id === opts.tab) ? (opts.tab as string) : (tabs[0]?.id ?? 'price');
  let form: FormHandle | null = null;
  let committed = false;

  // The whole session is one step on the chart's timeline, and a Cancel that
  // puts everything back leaves none. Settings are not announced by the
  // chart, so each write is a transaction the history can measure.
  const endStep = ctx.history?.group('Chart settings') ?? ((): void => {});
  const applyNow = (patch: ChartSettingsValues): void => { historyStep(ctx, undefined, () => applyChartSettings(chart, patch)); };
  const write = (patch: ChartSettingsValues): void => {
    for (const k of Object.keys(patch)) dirty.add(k);
    applyNow(patch);
    opts.onApply?.(patch);
  };

  const frame = dialogFrame(doc, { translate: ctx.translate, title: widgetText(ctx, 'Chart settings'), className: 'oac-settings', onClose: () => cancel() });
  const main = el(doc, 'div', 'oac-settings__main');
  const pane = el(doc, 'div', 'oac-settings__pane');
  frame.body.appendChild(main);
  const nav = tabList(doc, tabs.map((t) => ({ id: t.id, label: widgetText(ctx, `schema.settings.tab.${t.id}`, {}, t.label), icon: SETTINGS_TAB_ICONS[t.id] })),
    activeTab, 'rail', (id) => { activeTab = id; renderPane(); });
  main.appendChild(nav.el);

  function renderPane(): void {
    form?.destroy();
    const tab = tabs.find((t) => t.id === activeTab);
    pane.innerHTML = '';
    form = null;
    if (tab === undefined) {
      pane.appendChild(el(doc, 'div', 'oac-empty', widgetText(ctx, 'Nothing to configure on this chart yet.')));
      return;
    }
    // Re-read on every paint: edits apply live, so a tab left and returned to
    // has to show what the chart is drawing now, not what it drew when opened.
    form = renderForm(pane, controlsFromInputs(tab.inputs, { translate: ctx.translate, scope: 'settings' }), {
      values: readChartSettings(chart), translate: ctx.translate, openOverlay: ctx.openOverlay,
      idPrefix: 'oac-cset',
      live: true,
      unavailable: (key, option) => key === 'statusLine.openInterest' && chart.hasOpenInterest === false
        ? widgetText(ctx, 'Open interest is unavailable for this instrument.') : opts.unavailable?.(key, option) ?? null,
      onChange: (key, value) => {
        write({ [key]: value as ChartSettingsValues[string] });
        // One write can move a neighbour (a scale mode changes what auto-fit
        // reads), so every other control re-reads the chart.
        form?.sync(readChartSettings(chart));
      },
    });
  }

  main.appendChild(pane);
  renderPane();

  frame.lead.appendChild(button(doc, {
    label: widgetText(ctx, 'Restore this tab'),
    onClick: () => {
      const tab = tabs.find((t) => t.id === activeTab);
      if (tab === undefined) return;
      // Marked dirty like any edit, so Cancel still undoes a restore. A value
      // the widget starts at itself wins over the engine's default.
      const defaults = tabDefaults(tab);
      for (const key of Object.keys(defaults)) {
        const own = ctx.settingsDefaults?.[key];
        if (own !== undefined) defaults[key] = own;
      }
      write(defaults);
      renderPane();
    },
  }));
  frame.actions.appendChild(button(doc, { label: widgetText(ctx, 'Cancel'), onClick: () => cancel() }));
  frame.actions.appendChild(button(doc, { label: widgetText(ctx, 'OK'), variant: 'primary', onClick: () => ok() }));

  // Escape and the scrim are the shell's, and both mean Cancel.
  const offContext = chart.on('data:context', renderPane);
  const handle = openPanel(ctx, frame.el, { placement: 'center', modal: true, onClose: () => { offContext(); form?.destroy(); endStep(); } }, () => cancel());

  function revert(): void {
    if (committed || dirty.size === 0) return;
    const back: ChartSettingsValues = {};
    for (const key of dirty) {
      const v = before[key];
      if (v !== undefined) back[key] = v;
    }
    dirty.clear();
    applyNow(back);
    opts.onApply?.(back);
  }
  function cancel(): void {
    if (!handle.isOpen()) return;
    revert();
    form?.destroy();
    handle.close();
    opts.onClose?.(false);
  }
  function ok(): void {
    if (!handle.isOpen()) return;
    committed = true;
    form?.destroy();
    handle.close();
    opts.onClose?.(true);
  }

  return {
    el: frame.el,
    isOpen: handle.isOpen,
    // A programmatic close (the widget being destroyed) keeps what was applied,
    // the way OK does: the edits are already on the chart.
    close: () => ok(),
  };
}
