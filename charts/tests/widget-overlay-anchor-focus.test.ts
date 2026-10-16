import { describe, expect, it } from 'vitest';
import { createOverlayStack } from '../src/widget/context';
import { fakeContainer, fakeWidgetDocument, fireKey, type FakeElement } from './helpers/fake-dom-widget';

/**
 * Where focus goes when an overlay closes, for an overlay opened by a tap.
 *
 * WebKit does not focus a button when it is clicked or tapped, so on Safari and
 * every iOS browser nothing outside the overlay holds focus when a control opens
 * it. The stack remembered `document.activeElement` as the place to return to,
 * found the body, and returned nowhere: closing the mobile CSV dialog with Escape
 * left keyboard and screen reader users with no focus at all. The overlay's own
 * anchor is the control that opened it, which is where focus belongs.
 */
function fixture() {
  const doc = fakeWidgetDocument();
  const root = fakeContainer(doc, 390, 820);
  const anchor = doc.createElement('button');
  root.appendChild(anchor);
  const panel = doc.createElement('div');
  const field = doc.createElement('input');
  panel.appendChild(field);
  const stack = createOverlayStack(root as unknown as HTMLElement, doc as unknown as Document);
  return { doc, root, anchor, panel, field, stack };
}

describe('overlay focus return after a tap', () => {
  it('returns focus to the anchor when nothing held focus at open', () => {
    const { doc, anchor, panel, field, stack } = fixture();
    // A tap in WebKit: the anchor was pressed but never focused.
    expect(doc.activeElement).toBe(doc.body);
    stack.open(panel as unknown as HTMLElement, { anchor: anchor as unknown as HTMLElement, modal: true, placement: 'center' });
    field.focus();

    fireKey(doc as unknown as FakeElement, 'Escape');

    expect(doc.activeElement).toBe(anchor);
  });

  it('still prefers the element that really held focus at open', () => {
    const { doc, root, anchor, panel, field, stack } = fixture();
    const other = doc.createElement('button');
    root.appendChild(other);
    other.focus();
    stack.open(panel as unknown as HTMLElement, { anchor: anchor as unknown as HTMLElement, modal: true, placement: 'center' });
    field.focus();

    fireKey(doc as unknown as FakeElement, 'Escape');

    expect(doc.activeElement).toBe(other);
  });

  it('leaves focus alone when the anchor is gone by the time the overlay closes', () => {
    const { doc, anchor, panel, field, stack } = fixture();
    stack.open(panel as unknown as HTMLElement, { anchor: anchor as unknown as HTMLElement, modal: true, placement: 'center' });
    field.focus();
    anchor.remove();

    fireKey(doc as unknown as FakeElement, 'Escape');

    expect(doc.activeElement).not.toBe(anchor);
  });
});
