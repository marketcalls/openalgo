import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { registerIndicator } from '../src/index';
import {
  createWidget, widgetText, controlsFromInputs, mountAlertEditor, mountIndicatorPicker,
  mountIndicatorSettings, mountDrawingProperties, mountLevelEditor, openShortcutsPanel,
  type Widget, type WidgetMessageKey, type WidgetOptions, type WidgetTranslator,
} from '../src/widget/index';
import { errorText } from '../src/widget/localization';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, fire, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);
beforeAll(() => registerIndicator({
  id: 'localization-study', name: 'Chart settings', placement: 'onchart',
  inputs: [{ key: 'period', type: 'number', label: 'Period', default: 2, min: 1, max: 20 }],
  plots: [{ key: 'line', title: 'Value', type: 'line' }],
  calc: bars => ({ line: bars.map(bar => bar.close) }),
}));
const widgets: Widget[] = [];
afterEach(() => { for (const widget of widgets.splice(0)) widget.destroy(); });

function make(options: WidgetOptions = {}) {
  const document = fakeWidgetDocument();
  const widget = createWidget(fakeContainer(document) as unknown as HTMLElement, {
    document: document as unknown as Document, mobile: 'never',
    pixelRatio: () => 1, raf: { schedule: callback => { callback(); return 1; }, cancel: () => {} },
    ...options,
  });
  widget.chart.applySize(800, 600);
  widgets.push(widget);
  return { widget, root: widget.root as unknown as FakeElement };
}

describe('error text', () => {
  it('uses the message of an error, else a fallback, never [object Object] or nothing', () => {
    expect(errorText({}, new Error('quota exceeded'))).toBe('quota exceeded');
    expect(errorText({}, { message: 'x' })).toBe('x');
    expect(errorText({}, 'offline')).toBe('offline');
    expect(errorText({}, {})).toBe('unknown error');
    expect(errorText({}, { code: 1 })).toBe('unknown error');
    expect(errorText({}, new Error(''))).toBe('unknown error');
    expect(errorText({}, undefined)).toBe('unknown error');
    expect(errorText({ translate: (key, fallback) => key === 'unknown error' ? 'erreur inconnue' : fallback }, null)).toBe('erreur inconnue');
  });
});

describe('widget translation contract', () => {
  it('keeps published alert message keys valid in typed host catalogs', () => {
    const messages: Partial<Record<WidgetMessageKey, string>> = {
      'Enter a valid expiry date and time in UTC': 'Fecha UTC no valida',
      'Enter an expiry date and time in UTC': 'Introduzca una fecha UTC',
      'Expires {time} UTC': 'Caduca {time} UTC',
      'Last fired {time} UTC': 'Activada {time} UTC',
      // Retired in 2.5.10 for the active wording, still valid in a typed catalog until 3.0.0.
      'Armed': 'Armada',
      'Keep tool armed': 'Mantener la herramienta',
      'On: the tool stays armed after each drawing': 'Activado',
      'Tools stay armed after each drawing': 'Las herramientas siguen',
      '{group}: chevron for the rest. Double-click keeps it armed': '{group}',
      '{name} stays armed until Escape': '{name}',
    };
    const translate: WidgetTranslator = key => messages[key];
    expect(widgetText({ translate }, 'Expires {time} UTC', { time: '2099-01-02 03:04' })).toBe('Caduca 2099-01-02 03:04 UTC');
    expect(widgetText({ translate }, 'Last fired {time} UTC', { time: '2099-01-01 03:04' })).toBe('Activada 2099-01-01 03:04 UTC');
  });

  it.each(['Asia/Kolkata', 'UTC'])('preserves the translated expiry label and accessible help in %s', timezone => {
    const { widget, root } = make({ timezone, translate: (key, fallback) => {
      if (key === 'schema.alert.expiresAt.label') return 'Caduca <b>';
      if (key === 'schema.alert.expiresAt.tooltip') return 'Vacio para no caducar';
      return fallback;
    } });
    mountAlertEditor(widget.context, undefined, { source: { kind: 'price', price: 100 } });
    const check = (): void => {
      const label = root.querySelector('[data-key="expiresAt"] .oac-row__label')!;
      expect(label.textContent).toContain(`Caduca <b> (${timezone})`);
      expect(label.querySelector('b')).toBeNull();
      const help = label.querySelector('.oac-help');
      expect(help?.title).toBe('Vacio para no caducar');
      // Read as the field's description, not as part of its name.
      expect(root.querySelector('[data-key="expiresAt"] input')!.getAttribute('aria-description')).toBe('Vacio para no caducar');
    };
    check();
    const condition = root.querySelector('[data-key="condition"] select')!;
    condition.value = 'enteringRange';
    fire(condition, 'change');
    check();
  });

  it('translates chrome, accessible names and late dialogs without changing identifiers', () => {
    const seen: string[] = [];
    const { widget, root } = make({ symbol: 'BHEL', interval: '5m', translate: (key, fallback) => {
      seen.push(key); return `Local ${fallback}`;
    } });
    expect(root.querySelector('.oac-topbar')?.getAttribute('aria-label')).toBe('Local Chart toolbar');
    expect(root.querySelector('.oac-sym__input')?.getAttribute('aria-label')).toBe('Local Symbol');
    expect(root.querySelector('.oac-sym__input')?.value).toBe('BHEL');
    expect(root.querySelector('[data-interval="5m"]')?.getAttribute('aria-label')).toBe('Local Interval 5m');
    expect(root.querySelector('.oac-topbar__objects')?.textContent).toBe('Local Objects');
    widget.openSettings();
    expect(root.querySelector('.oac-dialog__title')?.textContent).toBe('Local Chart settings');
    expect(root.querySelector('.oac-settings [aria-label="Local Close"]')).not.toBeNull();
    expect(seen.some(key => key.startsWith('schema.settings.'))).toBe(true);
    widget.context.overlays.closeAll();
    widget.setTheme('light');
    expect(root.querySelector('.oac-topbar__theme')?.getAttribute('aria-label')).toBe('Local Switch to the dark theme');
  });

  it('falls back to English for missing, blank, throwing or invalid translations', () => {
    for (const translate of [undefined, () => undefined, () => null, () => '  ', () => { throw new Error('catalog unavailable'); }]) {
      const { root } = make({ translate });
      expect(root.querySelector('.oac-topbar')?.getAttribute('aria-label')).toBe('Chart toolbar');
    }
    expect(widgetText({ translate: () => 'Interval {unknown}' }, 'Interval {code}', { code: '5m' })).toBe('Interval 5m');
    expect(widgetText({ translate: () => 'Interval' }, 'Interval {code}', { code: '5m' })).toBe('Interval 5m');
  });

  it('interpolates values once and renders translator output as text', () => {
    const payload = '<img src=x onerror=alert(1)>{code}';
    expect(widgetText({ translate: () => '{code}: interval' }, 'Interval {code}', { code: payload })).toBe(`${payload}: interval`);
    const { root } = make({ translate: (key, fallback) => key === 'Objects' ? '<script>bad()</script>' : fallback });
    expect(root.querySelector('.oac-topbar__objects')?.textContent).toBe('<script>bad()</script>');
    expect(root.querySelector('.oac-topbar__objects script')).toBeNull();
  });

  it('keeps host branding and literal messages out of the translator', () => {
    const { widget, root } = make({ translate: (_key, fallback) => `Local ${fallback}` });
    widget.chart.setBranding({ href: 'https://example.test', label: 'Objects' });
    expect(root.querySelector('.oac-topbar__branding')?.textContent).toBe('Objects');
    widget.context.toast('Chart settings');
    expect(root.querySelector('.oac-toast__msg')?.textContent).toBe('Chart settings');
    expect(root.querySelector('.oac-toast [aria-label="Local Dismiss"]')).not.toBeNull();
  });

  it('translates mobile controls and menus opened after mounting', () => {
    const { root } = make({ mobile: 'always', translate: (_key, fallback) => `Local ${fallback}` });
    expect(root.querySelector('.oac-mobile__bar')?.getAttribute('aria-label')).toBe('Local Chart controls');
    const more = root.querySelector('[data-mobile-action="more"]');
    expect(more).not.toBeNull();
    fire(more!, 'click');
    expect(root.querySelector('.oac-mobile-sheet')?.getAttribute('aria-label')).toBe('Local More');
  });

  it('isolates catalogs between widgets in the same document', () => {
    const first = make({ translate: (_key, fallback) => `First ${fallback}` });
    const second = createWidget(fakeContainer(first.widget.context.document as unknown as ReturnType<typeof fakeWidgetDocument>) as unknown as HTMLElement, {
      document: first.widget.context.document, mobile: 'never', translate: (_key, fallback) => `Second ${fallback}`,
      raf: { schedule: callback => { callback(); return 1; }, cancel: () => {} },
    });
    widgets.push(second);
    expect(first.root.querySelector('.oac-topbar__objects')?.textContent).toBe('First Objects');
    expect((second.root as unknown as FakeElement).querySelector('.oac-topbar__objects')?.textContent).toBe('Second Objects');
  });

  it('translates schema metadata while keeping keys, options and numeric values operational', () => {
    const translate: WidgetTranslator = (key, fallback) => key.endsWith('.period.label') ? 'Periodo' : `Local ${fallback}`;
    const { widget, root } = make({ translate });
    const indicator = widget.chart.addIndicator('localization-study');
    mountIndicatorSettings(widget.context, undefined, { instanceId: indicator.id });
    const row = root.querySelector('[data-key="period"]')!;
    expect(row.querySelector('.oac-row__label')?.textContent).toBe('Periodo');
    const input = row.querySelector('input')!;
    expect(input.value).toBe('2');
    input.value = '7';
    fire(input, 'change');
    expect(indicator.settings().period).toBe(7);
    widget.context.overlays.closeAll();
    const converted = controlsFromInputs([{ type: 'select', key: 'mode', label: 'Mode', default: 'fast', options: [
      { label: 'Fast', value: 'fast' }, { label: 'Slow', value: 'slow' },
    ] }], { translate, scope: 'indicator.example' });
    expect(converted[0].options).toEqual([{ label: 'Local Fast', value: 'fast' }, { label: 'Local Slow', value: 'slow' }]);
  });

  it('renders translated drawing properties, levels, rail feedback and shortcuts', () => {
    const { widget, root } = make({ translate: (_key, fallback) => `Local ${fallback}` });
    const drawing = widget.draw.add({ tool: 'fib-retracement', paneIndex: 0, points: [], style: {} });
    mountDrawingProperties(widget.context, undefined, { ids: [drawing.id] });
    expect(root.querySelector('.oac-props [aria-label="Local Drawing actions"]')).not.toBeNull();
    expect(root.querySelector('.oac-props .oac-row__label')?.textContent).toMatch(/^Local /);
    widget.context.overlays.closeAll();
    mountLevelEditor(widget.context, undefined, { ids: [drawing.id] });
    expect(root.querySelector('[aria-label="Local Levels"]')).not.toBeNull();
    expect(root.querySelector('.oac-levels__row input[type="number"]')?.getAttribute('aria-label')).toMatch(/^Local Level .* ratio$/);
    widget.context.overlays.closeAll();
    openShortcutsPanel(widget.context);
    expect(root.querySelector('.oac-keys-dialog')?.getAttribute('aria-label')).toBe('Local Keyboard shortcuts');
    expect(root.querySelector('.oac-keys__row span')?.textContent).toMatch(/^Local /);
    widget.context.overlays.closeAll();
    fire(root.querySelector('.oac-rail__btn--magnet')!, 'click');
    expect(root.querySelector('.oac-statusline__msg')?.textContent).toMatch(/^Local Magnet/);
  });

  it('searches translated study names and preserves an alert title equal to a message key', () => {
    const { widget, root } = make({ translate: (key, fallback) => key === 'schema.indicator.localization-study.name' ? 'Estudio local' : `Local ${fallback}` });
    widget.series.setData([{ time: 1000, open: 100, high: 101, low: 99, close: 100 }]);
    mountIndicatorPicker(widget.context);
    const find = root.querySelector('.oac-pick__find')!;
    find.value = 'Estudio local';
    fire(find, 'input');
    expect(root.querySelector('[data-id="localization-study"]')?.textContent).toBe('Estudio local');
    widget.context.overlays.closeAll();
    mountAlertEditor(widget.context);
    expect(root.querySelector('.oac-alert-editor .oac-dialog__title')?.textContent).toBe('Local Create alert');
    const title = root.querySelector('[data-key="title"] input')!;
    title.value = 'Chart settings';
    fire(title, 'change');
    fire(root.querySelector('[data-action="save-alert"]')!, 'click');
    expect(widget.alerts.list()[0].title).toBe('Chart settings');
    widget.openAlerts();
    expect(root.querySelector('.oac-alerts__summary')?.textContent).toMatch(/^Chart settings\n/);
    expect(root.querySelector('[data-action="toggle-alert"]')?.getAttribute('aria-label')).toBe('Local Disable Chart settings');
  });

  it('translates the event popup it mounts, while host labels still win', () => {
    const words: Record<string, string> = { 'Event details': 'Detalles', 'Close': 'Cerrar', 'Loading details...': 'Cargando...' };
    const { widget, root } = make({ translate: (key, fallback) => words[key] ?? fallback, eventDetails: { labels: { close: 'Salir' } } });
    widget.series.setData(Array.from({ length: 20 }, (_, i) => ({ time: 1700000000 + i * 60, open: 101 + i * 0.3, high: 102 + i * 0.3, low: 100 + i * 0.3, close: 101.5 + i * 0.3 })));
    widget.chart.emit('event:click', { events: [{ id: 'e1', time: 1700000300, label: 'D', title: 'Dividend' }], point: { x: 50, y: 50 } });
    const popup = root.querySelector('.oac-event-details') as FakeElement;
    expect(popup.getAttribute('aria-label')).toBe('Detalles');
    expect(popup.querySelector('.oac-event-details__heading')?.textContent).toBe('Detalles');
    expect(popup.querySelector('[data-action="close-event-details"]')?.textContent).toBe('Salir');
  });

  it('preserves raw provider errors inside translated loading feedback', async () => {
    const { root } = make({ symbol: 'BHEL', interval: '5m', translate: (_key, fallback) => `Local ${fallback}`, feed: {
      getBars: async () => { throw new Error('Chart settings'); }, subscribeBars: () => () => {},
    } });
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(root.querySelector('.oac-toast__msg')?.textContent).toBe('Local Could not load BHEL 5m: Chart settings');
    expect(root.querySelector('.oac-data-status button')?.getAttribute('aria-label')).toBe('Local Retry chart data');
  });
});
