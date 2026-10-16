// The inline text editor: the frame maths that lays it over the painted
// text, the contentEditable read-back, and the commit and cancel paths.
import { describe, it, expect, beforeEach } from 'vitest';
import { installDom } from './fake-dom.js';
import {
  fontOf, wrapLines, textFrame, readEditable, openTextEditor, measurer,
  DEFAULT_FONT, TEXT_PAD, LINE_GAP, TEXT_SIZE,
} from '../src/text-editor.js';

const measure7 = (s) => s.length * 7;
const chart = { timeToCoordinate: (t) => t, priceToCoordinate: (p) => p };

describe('fontOf', () => {
  it('builds the shorthand the draw tier paints with', () => {
    expect(fontOf({}, 14)).toBe(`14px ${DEFAULT_FONT}`);
    expect(fontOf({ bold: true, italic: true, fontFamily: 'serif' }, 12)).toBe('italic 700 12px serif');
    expect(fontOf({ fontFamily: '' }, 10)).toBe(`10px ${DEFAULT_FONT}`);
  });
});

describe('wrapLines', () => {
  it('honours explicit newlines and leaves long lines alone without wrap', () => {
    expect(wrapLines(measure7, {}, 'one two\nthree', 20)).toEqual(['one two', 'three']);
  });

  it('soft-wraps each paragraph at the width when wrap is on', () => {
    expect(wrapLines(measure7, { wrap: true }, 'aa bb cc\n\ndd', 6 * 7)).toEqual(['aa bb', 'cc', '', 'dd']);
  });
});

describe('textFrame', () => {
  it('measures the box the way the text tool does, pad and line gap included', () => {
    const d = { points: [{ time: 100, price: 200 }], paneIndex: 0, style: {}, text: { value: 'ab\ncdef', fontSize: 10 } };
    const f = textFrame(chart, d, measure7);
    expect(f.lines).toEqual(['ab', 'cdef']);
    expect(f.width).toBe(4 * 7 + TEXT_PAD * 2);
    expect(f.height).toBe(2 * 10 * LINE_GAP + TEXT_PAD * 2);
    expect(f.x).toBe(100);
    expect(f.y).toBe(200);
    expect(f.lineHeight).toBe(13.5);
    expect(f.font).toBe(`10px ${DEFAULT_FONT}`);
  });

  it('anchors the middle or bottom edge when the block asks', () => {
    const base = { points: [{ time: 0, price: 200 }], paneIndex: 0, style: {} };
    const h = 13.5 + TEXT_PAD * 2;
    expect(textFrame(chart, { ...base, text: { value: 'a', fontSize: 10, valign: 'middle' } }, measure7).y).toBe(200 - h / 2);
    expect(textFrame(chart, { ...base, text: { value: 'a', fontSize: 10, valign: 'bottom' } }, measure7).y).toBe(200 - h);
  });

  it('measures the tool\'s fallback for an empty value and defaults the size', () => {
    const d = { points: [{ time: 0, price: 0 }], paneIndex: 0, style: {}, text: { value: '' } };
    const f = textFrame(chart, d, measure7, 'Note');
    expect(f.lines).toEqual(['Note']);
    expect(f.size).toBe(TEXT_SIZE);
    expect(textFrame(chart, { points: [{ time: 0, price: 0 }], paneIndex: 0, style: {} }, measure7).lines).toEqual(['Text']);
  });

  it('is null when the anchor is off the pane or missing', () => {
    const d = { points: [{ time: 0, price: 0 }], paneIndex: 0, style: {}, text: { value: 'a' } };
    expect(textFrame({ timeToCoordinate: () => NaN, priceToCoordinate: () => 0 }, d, measure7)).toBeNull();
    expect(textFrame({ timeToCoordinate: () => 0, priceToCoordinate: () => null }, d, measure7)).toBeNull();
    expect(textFrame(chart, { points: [], paneIndex: 0, style: {} }, measure7)).toBeNull();
  });
});

describe('readEditable', () => {
  let doc;
  beforeEach(() => { doc = installDom().document; });
  const el = (tag, ...kids) => { const n = doc.createElement(tag); for (const k of kids) n.appendChild(typeof k === 'string' ? doc.createTextNode(k) : k); return n; };

  it('folds br and block wrappers back to newlines', () => {
    expect(readEditable(el('div', 'a', el('br'), 'b'))).toBe('a\nb');
    expect(readEditable(el('div', 'a', el('div', 'b'), el('div', 'c')))).toBe('a\nb\nc');
    expect(readEditable(el('div', el('div', 'a'), el('div', el('br'))))).toBe('a\n');
  });

  it('drops the browser\'s trailing placeholder br only', () => {
    expect(readEditable(el('div', 'a', el('br')))).toBe('a');
    expect(readEditable(el('div', 'a', el('br'), el('br')))).toBe('a\n');
    expect(readEditable(el('div'))).toBe('');
  });
});

describe('measurer', () => {
  it('uses a scratch canvas when one exists and the character estimate otherwise', () => {
    installDom();
    expect(measurer('10px x', 10)('abc')).toBe(21);
    const saved = globalThis.document;
    globalThis.document = undefined;
    expect(measurer('10px x', 10)('abc')).toBe(18);
    globalThis.document = saved;
  });
});

describe('openTextEditor', () => {
  let dom, updates, app;
  beforeEach(() => {
    dom = installDom();
    updates = [];
    const d = { id: 'd1', tool: 'text', points: [{ time: 100, price: 50 }], paneIndex: 0, style: { color: '#abcdef' }, text: { value: 'Hi', fontSize: 10, wrap: true, wrapWidth: 100 } };
    app = {
      chart: { timeToCoordinate: (t) => t, priceToCoordinate: (p) => p },
      draw: { get: (id) => (id === 'd1' ? d : undefined), update: (id, patch) => { updates.push([id, patch]); d.text = { ...d.text, ...patch.text }; return true; } },
    };
  });

  it('sits at the frame, offset by the chart\'s place in the host, in the drawing\'s face', () => {
    const done = [];
    const ed = openTextEditor({ app, id: 'd1', host: dom.stage, chartEl: dom.chart, onDone: (c) => done.push(c) });
    expect(ed.el.parentNode).toBe(dom.stage);
    expect(ed.el.style.left).toBe('142px');
    expect(ed.el.style.top).toBe('50px');
    expect(ed.el.style.color).toBe('#abcdef');
    expect(ed.el.style.lineHeight).toBe('13.5px');
    expect(ed.el.style.whiteSpace).toBe('pre-wrap');
    expect(ed.el.style.width).toBe((2 * 7 + 10) + 'px');
    expect(ed.el.textContent).toBe('Hi');
    ed.el.textContent = 'Hi there friend';
    ed.el.fire('input');
    // Wrapped at 100px: "Hi there" (8 chars) fits, "friend" goes to the next line.
    expect(ed.el.style.width).toBe((8 * 7 + 10) + 'px');
    ed.commit();
    expect(updates).toEqual([['d1', { text: { value: 'Hi there friend' } }]]);
    expect(done).toEqual([true]);
    expect(ed.isOpen()).toBe(false);
    ed.commit();
    expect(updates.length).toBe(1);
  });

  it('writes nothing when the text is unchanged or the edit is cancelled', () => {
    const done = [];
    let ed = openTextEditor({ app, id: 'd1', host: dom.stage, chartEl: dom.chart, onDone: (c) => done.push(c) });
    ed.el.blur();
    expect(updates).toEqual([]);
    ed = openTextEditor({ app, id: 'd1', host: dom.stage, chartEl: dom.chart, onDone: (c) => done.push(c) });
    ed.el.textContent = 'changed';
    ed.el.fire('keydown', { key: 'Escape' });
    expect(updates).toEqual([]);
    expect(done).toEqual([false, false]);
    expect(dom.stage.querySelectorAll('.draw-textedit').length).toBe(0);
  });

  it('returns null for an unknown drawing or a chart with no place for it', () => {
    expect(openTextEditor({ app, id: 'nope', host: dom.stage, chartEl: dom.chart })).toBeNull();
    app.chart.priceToCoordinate = () => null;
    expect(openTextEditor({ app, id: 'd1', host: dom.stage, chartEl: dom.chart })).toBeNull();
  });

  it('stops pointer and key events at the box', () => {
    const ed = openTextEditor({ app, id: 'd1', host: dom.stage, chartEl: dom.chart });
    const seen = [];
    for (const t of ['pointerdown', 'click', 'keydown', 'contextmenu']) dom.stage.addEventListener(t, () => seen.push(t));
    for (const t of ['pointerdown', 'click', 'keydown', 'contextmenu']) ed.el.fire(t, { key: 'a' });
    expect(seen).toEqual([]);
  });
});
