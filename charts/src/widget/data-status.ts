import { IndicatorInputError } from 'openalgo-charts';
import type { DataAdjustment, DataLoadingController, DataLoadingSnapshot, DataSession, DataVariant, DataVariantDimension } from 'openalgo-charts';
import { errorText, widgetText, type WidgetTranslationOptions } from './localization';
import { h, type WidgetContext } from './context';

/**
 * A variant in words: the session and the adjustment in the host's language,
 * the currency and the unit as the provider names them. With `only`, just
 * that field, for saying which part a provider does not serve. Empty for the
 * default series.
 */
export function dataVariantLabel(ctx: WidgetTranslationOptions, variant: Readonly<DataVariant> | undefined, only?: DataVariantDimension): string {
  if (variant === undefined) return '';
  const words: Record<DataSession | DataAdjustment, string> = {
    regular: widgetText(ctx, 'Regular hours'), extended: widgetText(ctx, 'Extended hours'),
    adjusted: widgetText(ctx, 'Adjusted prices'), raw: widgetText(ctx, 'Raw prices'),
  };
  const parts: string[] = [];
  for (const key of ['session', 'adjustment', 'currency', 'unit'] as const) {
    const value = variant[key];
    if (value === undefined || (only !== undefined && only !== key)) continue;
    parts.push(key === 'session' || key === 'adjustment' ? words[value as DataSession | DataAdjustment] : value);
  }
  return parts.join(' ');
}

export interface DataStatusHandle {
  readonly el: HTMLElement;
  update(state: DataLoadingSnapshot): void;
  destroy(): void;
}

/** Compact status furniture shares the widget palette and leaves the canvas reachable. */
export function mountDataStatus(
  ctx: WidgetContext, stage: HTMLElement, controller: DataLoadingController | null, retry: () => void,
): DataStatusHandle {
  const el = h(ctx.document, 'div', 'oac-data-status');
  el.setAttribute('role', 'status');
  el.setAttribute('aria-live', 'polite');
  el.setAttribute('aria-atomic', 'true');
  el.hidden = true;
  stage.appendChild(el);
  let state = controller?.getState() ?? null;
  let signature = '';
  let destroyed = false;
  const stop = (event: Event): void => event.stopPropagation();
  for (const event of ['pointerdown', 'wheel', 'keydown']) el.addEventListener(event, stop);
  const render = (): void => {
    if (destroyed) return;
    const rows: { text: string; label?: string; retry?: (() => void) | undefined }[] = [];
    if (state !== null) {
      const symbol = state.request?.symbol ?? '';
      const interval = state.request?.interval ?? '';
      switch (state.status) {
        case 'loading': rows.push({ text: widgetText(ctx, 'Loading {symbol} {interval}', { symbol, interval }) }); break;
        case 'refreshing': rows.push({ text: widgetText(ctx, 'Refreshing {symbol} {interval}', { symbol, interval }) }); break;
        case 'empty': rows.push({ text: widgetText(ctx, 'No bars for {symbol} {interval}', { symbol, interval }), label: widgetText(ctx, 'Retry chart data'), retry }); break;
        case 'stale': rows.push({ text: widgetText(ctx, 'History is stale for {symbol} {interval}', { symbol, interval }), label: widgetText(ctx, 'Retry chart data'), retry }); break;
        case 'error': rows.push({ text: widgetText(ctx, 'Could not load {symbol} {interval}', { symbol, interval }), label: widgetText(ctx, 'Retry chart data'), retry }); break;
        // No retry: the same provider would give the same answer. The way out is another variant.
        case 'unsupported': rows.push({ text: widgetText(ctx, 'Not available from this source: {variant}',
          { variant: dataVariantLabel(ctx, state.request?.variant, state.unsupported) }) }); break;
      }
      if (state.historyStatus === 'limited') rows.push({ text: widgetText(ctx, 'History retention limit reached') });
      else if (state.historyStatus === 'loading') rows.push({ text: widgetText(ctx, 'Loading older history') });
      else if (state.historyStatus === 'error') rows.push({ text: widgetText(ctx, 'Could not load older history'),
        label: widgetText(ctx, 'Retry older history'), retry: () => { void controller?.loadMore(); } });
    }
    for (const indicator of ctx.chart.indicators()) {
      const status = indicator.dataStatus();
      if (status === null || status.state === 'ready') continue;
      // A study its inputs refuse (a timeframe on transformed bars) says why and
      // offers no retry: the same inputs are refused the same way.
      if (status.state === 'error' && status.error instanceof IndicatorInputError) {
        const why = errorText(ctx, status.error);
        rows.push({ text: why.startsWith(`${indicator.name}: `) ? why : widgetText(ctx, '{name}: {error}', { name: indicator.name, error: why }) });
        continue;
      }
      const label = { loading: widgetText(ctx, 'Loading'), empty: widgetText(ctx, 'No data'), unsupported: widgetText(ctx, 'Unsupported'), error: widgetText(ctx, 'Could not load') }[status.state];
      rows.push({ text: `${indicator.name}: ${label}`, label: widgetText(ctx, 'Retry {name}', { name: indicator.name }),
        retry: status.state === 'loading' ? undefined : () => indicator.retryData() });
    }
    const next = JSON.stringify(rows.map(row => [row.text, row.label, !!row.retry]));
    if (signature === next) return;
    signature = next;
    el.textContent = '';
    el.hidden = rows.length === 0;
    for (const row of rows) {
      const line = h(ctx.document, 'div', 'oac-data-status__row');
      const text = h(ctx.document, 'span', 'oac-data-status__text');
      text.textContent = row.text;
      line.appendChild(text);
      if (row.retry) {
        const button = h(ctx.document, 'button', 'oac-btn');
        button.textContent = widgetText(ctx, 'Retry');
        button.type = 'button';
        button.setAttribute('aria-label', row.label!);
        button.addEventListener('click', row.retry);
        line.appendChild(button);
      }
      el.appendChild(line);
    }
  };
  // An indicator can publish its first status inside its constructor, before
  // Chart has added the instance to its public collection.
  const changed = (): void => { render(); queueMicrotask(render); };
  const cleanups = (['indicator:data-status', 'indicatorRemoved'] as const).map(event => ctx.chart.on(event, changed));
  render();
  return {
    el,
    update: snapshot => { state = snapshot; render(); },
    destroy: () => {
      destroyed = true;
      for (const cleanup of cleanups) cleanup();
      for (const event of ['pointerdown', 'wheel', 'keydown']) el.removeEventListener(event, stop);
      el.remove();
    },
  };
}
