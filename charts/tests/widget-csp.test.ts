import { describe, expect, it } from 'vitest';
import { injectWidgetStyles, WIDGET_CSS, WIDGET_STYLE_ID } from '../src/widget/styles';
import { fakeWidgetDocument } from './helpers/fake-dom-widget';

describe('widget stylesheet CSP support', () => {
  it('applies the requested nonce to the injected stylesheet', () => {
    const doc = fakeWidgetDocument() as unknown as Document;
    const sheet = injectWidgetStyles(doc, '.extra { color: red; }', 'request-nonce');

    expect(sheet.nonce).toBe('request-nonce');
    expect(sheet.textContent).toBe(WIDGET_CSS + '.extra { color: red; }');
    expect(doc.getElementById(WIDGET_STYLE_ID)).toBe(sheet);
  });

  it('keeps the two-argument API and shares the first populated sheet', () => {
    const doc = fakeWidgetDocument() as unknown as Document;
    const sheet = injectWidgetStyles(doc, '.first { color: red; }');
    const second = injectWidgetStyles(doc, '.later { color: blue; }', 'later-nonce');

    expect(second).toBe(sheet);
    expect(sheet.nonce || '').toBe('');
    expect(sheet.textContent).toBe(WIDGET_CSS + '.first { color: red; }');
    expect(doc.head.children).toHaveLength(1);
  });

  it.each(['', '\n  '])('fills an empty server-rendered placeholder with content %j', (content) => {
    const doc = fakeWidgetDocument() as unknown as Document;
    const placeholder = doc.createElement('style');
    placeholder.id = WIDGET_STYLE_ID;
    placeholder.textContent = content;
    doc.head.appendChild(placeholder);

    const sheet = injectWidgetStyles(doc, '.dialog { display: flex; }', 'request-nonce');

    expect(sheet).toBe(placeholder);
    expect(sheet.nonce).toBe('request-nonce');
    expect(sheet.textContent).toBe(WIDGET_CSS + '.dialog { display: flex; }');
    expect(doc.head.children).toHaveLength(1);
  });

  it.each([undefined, 'different-nonce'])('preserves a placeholder nonce when called with %j', (nonce) => {
    const doc = fakeWidgetDocument() as unknown as Document;
    const placeholder = doc.createElement('style');
    placeholder.id = WIDGET_STYLE_ID;
    placeholder.nonce = 'host-nonce';
    doc.head.appendChild(placeholder);

    const sheet = injectWidgetStyles(doc, '.dialog { display: flex; }', nonce);

    expect(sheet).toBe(placeholder);
    expect(sheet.nonce).toBe('host-nonce');
    expect(sheet.textContent).toBe(WIDGET_CSS + '.dialog { display: flex; }');
  });

  it.each(['', 'host-nonce'])('preserves populated host CSS and its nonce %j', (nonce) => {
    const doc = fakeWidgetDocument() as unknown as Document;
    const host = doc.createElement('style');
    host.id = WIDGET_STYLE_ID;
    host.nonce = nonce;
    host.textContent = '.oac-widget { display: grid; } /* host overrides */';
    doc.head.appendChild(host);

    const sheet = injectWidgetStyles(doc, '.extra { color: red; }', 'different-nonce');

    expect(sheet).toBe(host);
    expect(sheet.nonce).toBe(nonce);
    expect(sheet.textContent).toBe('.oac-widget { display: grid; } /* host overrides */');
    expect(doc.head.children).toHaveLength(1);
  });
});
