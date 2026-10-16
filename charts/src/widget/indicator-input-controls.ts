import type { IndicatorApi, IndicatorInput, IndicatorSettings, PickHandle, PickPoint } from 'openalgo-charts';
import { studyInputTarget } from 'openalgo-charts/draw';
import type { WidgetContext } from './context';
import { button, el } from './form';
import { widgetText } from './localization';
import { mountSymbolPicker, type SymbolPickerHandle } from './symbol-picker';

export interface IndicatorInputControlsOptions {
  instance: IndicatorApi;
  inputs: readonly IndicatorInput[];
  panel: HTMLElement;
  field(key: string): HTMLInputElement | HTMLTextAreaElement | null;
  /** Commit one atomic patch. False keeps the existing settings and draft. */
  onPatch(patch: IndicatorSettings): boolean;
  /** A reference host can suspend its own modal instead of the widget stack. */
  suspend?(): () => void;
  current?(): boolean;
}

export interface IndicatorInputControlsHandle {
  cancelPick(): void;
  refresh(): void;
  destroy(): void;
}

/**
 * The form's reason a field cannot act, which its action cannot outrun: a pick
 * or a search would write a value the form is showing as out of play.
 */
const inert = (field: HTMLInputElement | HTMLTextAreaElement): string | null => field.disabled ? field.title : null;

/**
 * Host actions for typed fields. Values remain ordinary settings scalars.
 * Call `refresh` after the form re-reads its conditions, so an action follows
 * its field in and out of play.
 */
export function mountIndicatorInputControls(ctx: WidgetContext, options: IndicatorInputControlsOptions): IndicatorInputControlsHandle {
  let destroyed = false;
  const buttons: HTMLButtonElement[] = [], pickers: SymbolPickerHandle[] = [], refreshers: (() => void)[] = [];
  const disposers: (() => void)[] = [];
  const instance = options.instance;
  const current = (): boolean => !destroyed && !ctx.chart.isDestroyed && ctx.chart.indicators().includes(instance)
    && (options.current?.() ?? true);
  let clearClickGuard = (): void => {};
  const guardCompletionClick = (): void => {
    clearClickGuard();
    // The chart answers on pointerup. Its following browser click must not
    // activate the modal which has just resumed over those plot coordinates.
    const click = (event: MouseEvent): void => {
      if (!(event.detail > 0)) return;
      event.preventDefault(); event.stopImmediatePropagation(); clearClickGuard();
    };
    const clear = (): void => {
      ctx.document.removeEventListener('click', click, true);
      ctx.document.removeEventListener('pointerdown', clear, true);
      ctx.document.removeEventListener('keydown', clear, true);
      if (clearClickGuard === clear) clearClickGuard = () => {};
    };
    clearClickGuard = clear;
    ctx.document.addEventListener('click', click, true);
    ctx.document.addEventListener('pointerdown', clear, true);
    ctx.document.addEventListener('keydown', clear, true);
  };
  let active: { cancel: (() => void) | null; finish: () => void } | null = null;
  const cancelPick = (): void => {
    const pending = active;
    if (!pending) return;
    pending.finish();
    pending.cancel?.();
  };
  const accept = (patch: IndicatorSettings): boolean => {
    if (!current() || !options.onPatch(patch) || !current()) return false;
    for (const [key, value] of Object.entries(patch)) {
      const field = options.field(key);
      if (field) field.value = String(value ?? '');
    }
    return true;
  };

  // A study with two such inputs has two of each button, so each is named with its input.
  const labelOf = (item: IndicatorInput): string => widgetText(ctx, `schema.indicator.${instance.indicatorId}.${item.key}.label`, {}, item.label);
  for (const input of options.inputs) {
    const field = options.field(input.key);
    if (!field) continue;
    if (input.type === 'symbol') {
      const trigger = button(ctx.document, { label: widgetText(ctx, 'Search'), onClick: () => {
        if (current()) picker?.open(field.value);
      } });
      trigger.setAttribute('aria-label', widgetText(ctx, 'Search {label}', { label: labelOf(input) }));
      trigger.dataset.inputAction = input.key;
      field.parentElement?.appendChild(trigger); buttons.push(trigger);
      refreshers.push(() => {
        const why = inert(field) ?? (ctx.symbolSearch === undefined
          ? widgetText(ctx, 'Symbol search is not configured; enter an instrument manually') : null);
        trigger.disabled = why !== null; trigger.title = why ?? '';
      });
      const picker = ctx.symbolSearch === undefined ? null : mountSymbolPicker(ctx, field as HTMLInputElement, {
        search: ctx.symbolSearch,
        context: () => current() ? [instance.id, ctx.symbol(), ctx.interval(), ctx.chart.getDataContext()] : null,
        onSelect: (symbol, exchange) => {
          const patch: IndicatorSettings = input.exchangeKey === undefined ? { [input.key]: symbol }
            : { [input.key]: symbol, [input.exchangeKey]: exchange ?? '' };
          accept(patch);
        },
      });
      if (picker) {
        pickers.push(picker);
        // A result click blurs the query first. Do not publish that query with
        // the previous exchange before the selected pair arrives.
        const change = (event: Event): void => { if (!picker.canCommitRaw()) event.stopImmediatePropagation(); };
        field.addEventListener('change', change, true);
        disposers.push(() => field.removeEventListener('change', change, true));
      }
    }
    if ((input.type !== 'price' && input.type !== 'timestamp') || !input.pick) continue;
    const reason = (): string | null => {
      const off = inert(field);
      if (off !== null) return off;
      if (ctx.draw.activeTool() !== null) return widgetText(ctx, 'Finish or cancel the active drawing before picking');
      if (!options.suspend && !ctx.overlays.suspend) return widgetText(ctx, 'This host cannot suspend the settings dialog');
      if (input.type === 'price' && studyInputTarget(ctx.chart, instance, input.key) === null) {
        return widgetText(ctx, 'Choose an explicit pane and scale for this price input');
      }
      return null;
    };
    // A price paired with a time is one point: its pick captures both halves
    // from one click and commits them in one patch.
    const time = input.type === 'price' && input.timeKey !== undefined
      ? options.inputs.find(item => item.key === input.timeKey && item.type === 'timestamp') : undefined;
    const said = time ? widgetText(ctx, 'Pick {time} and {price} on the chart', { time: labelOf(time), price: labelOf(input) })
      : widgetText(ctx, 'Pick {label} on the chart', { label: labelOf(input) });
    const trigger = button(ctx.document, { label: widgetText(ctx, time ? 'Pick point on chart' : 'Pick on chart'), onClick: () => {
      if (!current()) return;
      const why = reason();
      if (why !== null) { ctx.toast(why, 'info'); return; }
      cancelPick();
      for (const picker of pickers) picker.close();
      const target = input.type === 'price' ? studyInputTarget(ctx.chart, instance, input.key)! : undefined;
      const resume = options.suspend?.() ?? ctx.overlays.suspend!(options.panel);
      const hint = el(ctx.document, 'div', 'oac-input-pick');
      hint.appendChild(el(ctx.document, 'span', undefined, said));
      const cancel = button(ctx.document, { label: widgetText(ctx, 'Cancel pick'), onClick: cancelPick });
      hint.appendChild(cancel);
      hint.addEventListener('pointerdown', event => event.stopPropagation());
      ctx.overlays.layer.appendChild(hint);
      let offEnd = (): void => {};
      const key = (event: KeyboardEvent): void => {
        if (event.key !== 'Escape') return;
        event.preventDefault(); event.stopImmediatePropagation(); cancelPick();
      };
      const pending = { cancel: null as PickHandle | null, finish: (): void => {
        if (active !== pending) return;
        active = null; offEnd(); hint.remove();
        ctx.document.removeEventListener('keydown', key, true);
        resume();
        if (current() && trigger.isConnected) trigger.focus();
      } };
      active = pending;
      let starting = true;
      ctx.document.addEventListener('keydown', key, true);
      offEnd = ctx.chart.on('pick:end', event => {
        // Arming can synchronously cancel an earlier caller's request. The
        // returned handle identifies whether this invocation kept ownership.
        if (starting) return;
        if ((event as { value: number | null }).value === null) pending.finish();
        else queueMicrotask(() => {
          // A newer pick started by an end listener suppresses our callback.
          // Let ordinary success commit first, then release only this modal.
          if (active === pending && pending.cancel && !pending.cancel.active()) {
            guardCompletionClick();
            pending.finish();
          }
        });
      });
      cancel.focus();
      try {
        const done = (patch: IndicatorSettings): void => {
          if (active !== pending) return;
          guardCompletionClick();
          pending.finish();
          accept(patch);
        };
        const stop = time
          ? ctx.chart.beginPick('point', (value: PickPoint) => done({ [input.key]: value.price, [time.key]: value.time }), target)
          : ctx.chart.beginPick(input.type === 'price' ? 'price' : 'time', value => done({ [input.key]: value }), target);
        pending.cancel = stop;
        starting = false;
        if (active !== pending) stop();
        else if (!stop.active()) pending.finish();
      } catch (error) {
        pending.finish();
        ctx.toast(error instanceof Error ? error.message : widgetText(ctx, 'The value could not be picked'), 'error');
      }
    } });
    trigger.setAttribute('aria-label', said);
    trigger.dataset.inputAction = input.key;
    field.parentElement?.appendChild(trigger); buttons.push(trigger);
    refreshers.push(() => { const why = reason(); trigger.disabled = why !== null; trigger.title = why ?? ''; });
  }
  const refresh = (): void => { if (!destroyed) for (const update of refreshers) update(); };
  const offObjects = ctx.chart.on('objects:change', () => { cancelPick(); refresh(); });
  const offTool = ctx.chart.on('draw:tool', () => { cancelPick(); refresh(); });
  const offContext = ctx.chart.on('data:context', () => { cancelPick(); for (const picker of pickers) picker.close(); });
  const offRemoved = ctx.chart.on('indicatorRemoved', () => { if (!current()) cancelPick(); });
  const offRestore = ctx.chart.on('state:restore:start', cancelPick);
  const offDestroy = ctx.chart.on('destroy', cancelPick);
  refresh();
  return { cancelPick, refresh, destroy: () => {
    if (destroyed) return;
    destroyed = true; cancelPick(); clearClickGuard();
    offObjects(); offTool(); offContext(); offRemoved(); offRestore(); offDestroy();
    for (const dispose of disposers) dispose();
    for (const picker of pickers) picker.destroy();
    for (const trigger of buttons) trigger.remove();
  } };
}
