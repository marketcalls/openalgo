import { tryResolveInterval } from 'openalgo-charts';
import { h, type WidgetContext } from './context';
import { eventKeyCombo, fromChartCombo } from './keymap';
import { widgetText } from './localization';
import { mountSymbolPicker, type SymbolPickerHandle, type SymbolSearch } from './symbol-picker';

export interface QuickEntryOptions {
  /** The host decides whether this chart currently owns direct typing. */
  enabled(): boolean;
  onSymbol(symbol: string, exchange?: string): void;
  onInterval(code: string): void;
  search?: SymbolSearch | undefined;
}

export interface QuickEntryHandle { close(): void; destroy(): void }

function editable(target: EventTarget | null): boolean {
  for (let node = target as HTMLElement | null; node !== null; node = node.parentElement) {
    if (node.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(node.tagName)) return true;
  }
  return false;
}

/** Start a symbol or interval box from an unclaimed plain key on the focused chart. */
export function mountQuickEntry(ctx: WidgetContext, options: QuickEntryOptions): QuickEntryHandle {
  const doc = ctx.document;
  let destroyed = false;
  let closer: (() => void) | null = null;
  let panel: HTMLElement | null = null;
  let input: HTMLInputElement | null = null;
  let picker: SymbolPickerHandle | null = null;
  const close = (): void => {
    const current = closer;
    closer = null;
    picker?.destroy();
    picker = null;
    panel = null;
    input = null;
    current?.();
  };
  const open = (mode: 'symbol' | 'interval', initial: string): void => {
    close();
    panel = h(doc, 'section', 'oac-quick-entry', { role: 'dialog', 'aria-label': widgetText(ctx, mode === 'symbol' ? 'schema.ui.enterSymbol' : 'schema.ui.enterInterval', {}, mode === 'symbol' ? 'Enter symbol' : 'Enter interval') });
    input = h(doc, 'input', 'oac-quick-entry__input', {
      type: 'text', autocomplete: 'off', spellcheck: 'false',
      'aria-label': widgetText(ctx, mode === 'symbol' ? 'schema.ui.symbol' : 'schema.ui.interval', {}, mode === 'symbol' ? 'Symbol' : 'Interval'),
    });
    input.value = initial;
    const message = h(doc, 'div', 'oac-quick-entry__message', { role: 'alert' });
    panel.append(input, message);
    const field = input;
    field.addEventListener('input', () => { message.textContent = ''; });
    const onFieldKey = (event: KeyboardEvent): void => {
      if (event.key !== 'Enter' || (event as KeyboardEvent).isComposing) return;
      event.preventDefault();
      event.stopPropagation();
      const value = field.value.trim();
      if (mode === 'symbol') {
        if (picker !== null && !picker.canCommitRaw()) return;
        if (value === '') { message.textContent = widgetText(ctx, 'schema.ui.symbolRequired', {}, 'Enter a symbol'); return; }
        close();
        options.onSymbol(value.toUpperCase());
      } else {
        const found = tryResolveInterval(value) ?? (/^[0-9]+$/.test(value) ? tryResolveInterval(`${value}m`) : null);
        if (found === null) {
          message.textContent = widgetText(ctx, 'schema.ui.invalidInterval', {}, 'Enter a recognized interval');
          return;
        }
        close();
        options.onInterval(found.code);
      }
    };
    const currentPanel = panel;
    closer = ctx.openOverlay(panel, { placement: 'center', initialFocus: field, onClose: () => { if (panel === currentPanel) close(); } });
    if (mode === 'symbol' && options.search) {
      picker = mountSymbolPicker(ctx, field, {
        search: options.search,
        onSelect: (symbol, exchange) => { close(); options.onSymbol(symbol, exchange); },
        context: () => `${ctx.symbol().exchange}:${ctx.symbol().symbol}:${ctx.interval()}`,
      });
      picker.open(initial);
    }
    field.addEventListener('keydown', onFieldKey);
  };
  const onKey = (event: KeyboardEvent): void => {
    if (destroyed || event.defaultPrevented || event.isComposing || event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
    if (!/^[a-zA-Z0-9]$/.test(event.key)) return;
    const target = event.target;
    const focused = doc.activeElement;
    if (target === null || !ctx.root.contains(target as Node) || focused === null || !ctx.root.contains(focused) || editable(target)) return;
    if (ctx.overlays.size() > 0 || ctx.draw.activeTool() !== null || !options.enabled()) return;
    const combo = eventKeyCombo(event);
    if (ctx.keymap.list().some(binding => binding.combo === combo && ctx.keymap.activeScopes().includes(binding.scope))) return;
    if (ctx.chart.shortcuts?.list().some(binding => !binding.isDisabled && binding.combos.some(chord => fromChartCombo(chord) === combo))) return;
    event.preventDefault();
    event.stopPropagation();
    open(/[0-9]/.test(event.key) ? 'interval' : 'symbol', event.key);
  };
  doc.addEventListener('keydown', onKey, true);
  const offSymbol = ctx.bus.on('symbol', close);
  const offInterval = ctx.bus.on('interval', close);
  return { close, destroy: () => { if (destroyed) return; destroyed = true; close(); offSymbol(); offInterval(); doc.removeEventListener('keydown', onKey, true); } };
}

export const QUICK_ENTRY_CSS = `
.oac-widget .oac-quick-entry{width:min(330px,calc(100vw - 32px));padding:12px}
.oac-widget .oac-quick-entry__input{width:100%;box-sizing:border-box;background:var(--oac-panel);color:var(--oac-tx);border:1px solid var(--oac-bd);border-radius:4px;padding:9px;font:inherit}
.oac-widget .oac-quick-entry__message{min-height:20px;padding-top:5px;color:var(--oac-danger)}
`;
