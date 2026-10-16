/**
 * Every dialog built on the shared frame keeps the same furniture: the title
 * left and one close control top right, which the frame builds. A form dialog
 * closes from the icon button; the two compact list panels, whose rows act
 * through words and which carry no glyph, ask the frame for the word. The
 * alerts list, the alert editor and the objects panel used to rewrite the
 * frame's button after it was built, and the editor, a form, lost its icon.
 */
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import type { Bar } from '../src/index';
import { createWidget, mountObjectsPanel, type Widget } from '../src/widget/index';
import { mountAlertEditor, mountAlertsPanel } from '../src/widget/dialogs/alerts';
import { mountSettingsDialog } from '../src/widget/dialogs/settings';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);
const live: Widget[] = [];
afterEach(() => { for (const w of live.splice(0)) if (!w.isDestroyed) w.destroy(); });

const T0 = 1700000100;
const bars: Bar[] = (() => {
  let seed = 5;
  const next = (): number => { seed = (seed * 16807) % 2147483647; return seed / 2147483647 - 0.5; };
  let close = 870;
  return Array.from({ length: 60 }, (_, i) => {
    const open = close;
    close = Math.round((open + next() * 6) * 20) / 20;
    return { time: T0 + i * 300, open, high: Math.max(open, close) + 2, low: Math.min(open, close) - 2, close, volume: 500 + i };
  });
})();

function make(): Widget {
  const doc = fakeWidgetDocument();
  const w = createWidget(fakeContainer(doc) as unknown as HTMLElement, {
    document: doc as unknown as Document, persist: false, mobile: 'never', pixelRatio: () => 1,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  w.chart.applySize(900, 560);
  w.series.setData(bars);
  live.push(w);
  return w;
}

/** The close control in the head of the dialog with this class, as the shared frame builds it. */
function closeOf(w: Widget, cls: string): FakeElement {
  const head = (w.root as unknown as FakeElement).querySelector(`.${cls} .oac-dialog__head`) as FakeElement;
  const buttons = head.querySelectorAll('button');
  expect(buttons).toHaveLength(1);
  return buttons[0]!;
}

describe('dialog furniture', () => {
  it.each([
    ['oac-settings', (w: Widget) => mountSettingsDialog(w.context)],
    ['oac-alert-editor', (w: Widget) => mountAlertEditor(w.context, undefined, { source: { kind: 'price', price: bars[40]!.close } })],
  ] as const)('the form dialog %s closes from the icon button top right', (cls, open) => {
    const w = make();
    const handle = open(w);
    const close = closeOf(w, cls);
    expect(close.classList.contains('oac-btn--icon')).toBe(true);
    expect(close.getAttribute('aria-label')).toBe('Close');
    expect(close.textContent).toBe('');
    close.click();
    expect(handle.isOpen()).toBe(false);
  });

  it.each([
    ['oac-alerts', (w: Widget) => mountAlertsPanel(w.context)],
    ['oac-objects', (w: Widget) => mountObjectsPanel(w.context)],
  ] as const)('the list panel %s closes from the word, as its rows act', (cls, open) => {
    const w = make();
    const handle = open(w);
    const close = closeOf(w, cls);
    expect(close.classList.contains('oac-btn--icon')).toBe(false);
    expect(close.textContent).toBe('Close');
    expect(close.querySelector('.oac-glyph')).toBeNull();
    close.click();
    expect(handle.isOpen()).toBe(false);
  });
});
