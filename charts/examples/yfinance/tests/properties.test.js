// The properties bar: generated from the schema, editing the selection
// through the controller, and staying out of the chart's way.
import { describe, it, expect, beforeEach } from 'vitest';
import { installDom } from './fake-dom.js';
import { makeApp, line, rect, text, fib, hover, timeToX, priceToY, T0 } from './draw-host.js';

const dist = await import('/dist/openalgo-charts.draw.mjs');
const { BUILTIN_DRAWING_TOOLS, drawingSettingsSchema, readDrawingSetting, DEFAULT_FIB, INTERVAL_FIELDS } = dist;
const { mountPropertiesBar, commonSchema, colorControls, withIntervalFields, PALETTE, PROPBAR_POS_KEY } = await import('../src/properties.js');
const { INTERVALS } = await import('../src/intervals.js');

const paths = (schema) => schema.fields.map((f) => f.path);

describe('commonSchema', () => {
  it('is the tool\'s own schema for a single tool', () => {
    const s = commonSchema(['text']);
    expect(paths(s)).toEqual(paths(drawingSettingsSchema('text')));
    expect(s.textIsContent).toBe(true);
  });

  it('keeps only the fields every selected tool declares, in the first tool\'s order', () => {
    const s = commonSchema(['trend-line', 'rectangle']);
    const both = paths(drawingSettingsSchema('trend-line')).filter((p) => paths(drawingSettingsSchema('rectangle')).includes(p));
    expect(paths(s)).toEqual(both);
    expect(paths(s)).not.toContain('style.extendLeft');
    expect(s.textIsContent).toBeUndefined();
  });

  it('treats the text as content only when every tool does', () => {
    expect(commonSchema(['text', 'note']).textIsContent).toBe(true);
    expect(commonSchema(['text', 'rectangle']).textIsContent).toBeUndefined();
    expect(commonSchema([]).fields).toEqual([]);
  });
});

describe('colorControls', () => {
  it('pairs a fill colour with its switch and opacity, and leaves the stroke colour alone', () => {
    const c = colorControls(drawingSettingsSchema('fib-retracement'));
    const stroke = c.find((x) => x.field.path === 'style.color');
    const fill = c.find((x) => x.field.path === 'style.fillColor');
    expect(stroke.toggle).toBeNull();
    expect(stroke.opacity).toBeNull();
    expect(fill.toggle.path).toBe('style.fill');
    expect(fill.opacity.path).toBe('style.fillOpacity');
  });

  it('finds the text plate and border companions by name', () => {
    const c = colorControls(drawingSettingsSchema('text'));
    const bg = c.find((x) => x.field.path === 'text.backgroundColor');
    const bd = c.find((x) => x.field.path === 'text.borderColor');
    expect(bg.toggle.path).toBe('text.background');
    expect(bg.opacity.path).toBe('text.backgroundOpacity');
    expect(bd.toggle.path).toBe('text.border');
    expect(bd.opacity).toBeNull();
  });
});

describe('the properties bar', () => {
  let dom, app, chart, draw, bar;
  const q = (sel) => bar.el.querySelector(sel);
  const pop = () => bar.popover();
  const open = (sel) => { q(sel).click(); return pop(); };

  beforeEach(() => {
    dom = installDom();
    ({ app, chart, draw } = makeApp());
    bar = mountPropertiesBar(app, dom.stage);
    bar.attach();
  });

  it('mounts hidden inside the anchor, injects its stylesheet once, and hands itself to the app', () => {
    expect(bar.el.hidden).toBe(true);
    expect(bar.el.parentNode).toBe(dom.stage);
    expect(app.props).toBe(bar);
    expect(dom.document.querySelectorAll('#propbar-css').length).toBe(1);
    mountPropertiesBar(app, dom.stage);
    expect(dom.document.querySelectorAll('#propbar-css').length).toBe(1);
  });

  it('shows for a selection with the tool\'s name, and hides when it clears', () => {
    const a = line(draw);
    draw.select(a.id);
    expect(bar.el.hidden).toBe(false);
    expect(q('.pb-name').textContent).toBe('Trend Line');
    draw.select(null);
    expect(bar.el.hidden).toBe(true);
    draw.select([a.id, line(draw).id]);
    expect(q('.pb-name').textContent).toBe('2 drawings');
  });

  it('gives every declared field of every built-in tool a control, and nothing outside the schema', () => {
    for (const tool of BUILTIN_DRAWING_TOOLS) {
      const n = Math.max(tool.points, 1) + (tool.points === 0 ? 2 : 0);
      const points = Array.from({ length: n }, (_, i) => ({ time: T0 + 600 * (i + 1), price: 100 + i * 10 }));
      const d = draw.add({ tool: tool.id, paneIndex: 0, style: {}, points });
      draw.select(d.id);
      // The tool's own fields, and the interval range this page adds to every tool.
      const declared = new Set(paths(withIntervalFields(drawingSettingsSchema(tool.id))));
      const found = new Set();
      const collect = (root) => { for (const n of root.querySelectorAll('[data-path]')) found.add(n.dataset.path); };
      collect(bar.el);
      for (const b of bar.el.querySelectorAll('[data-pop]')) {
        b.click();
        const p = pop();
        expect(p, `${tool.id}: ${b.dataset.pop} opens`).not.toBeNull();
        collect(p);
        b.click();
      }
      for (const p of declared) expect(found.has(p), `${tool.id} shows ${p}`).toBe(true);
      for (const p of found) expect(declared.has(p), `${tool.id} control ${p} is declared`).toBe(true);
      draw.remove(d.id);
    }
  });

  it('recolours every selected drawing from the palette as one undo entry', () => {
    const a = line(draw);
    const b = line(draw);
    draw.select([a.id, b.id]);
    const p = open('[data-path="style.color"][data-pop]');
    expect(p.querySelector('.oac-color')).not.toBeNull();
    const swatches = p.querySelectorAll('.pb-grid button');
    expect(swatches.length).toBe(PALETTE.length);
    swatches.find((s) => s.getAttribute('aria-label') === '#f23645').click();
    expect(draw.get(a.id).style.color).toBe('#f23645');
    expect(draw.get(b.id).style.color).toBe('#f23645');
    expect(pop()).toBeNull();
    expect(q('[data-path="style.color"] .pb-sw').style.background).toBe('#f23645');
    draw.undo();
    expect(draw.get(a.id).style.color).toBeUndefined();
    expect(draw.get(b.id).style.color).toBeUndefined();
  });

  it('offers the four width presets and a stepper held to the field\'s range', () => {
    const a = line(draw);
    draw.select(a.id);
    expect(q('[data-path="style.lineWidth"] .pb-val').textContent).toBe('1.5px');
    let p = open('[data-path="style.lineWidth"]');
    expect(p.querySelectorAll('[data-preset]').map((n) => n.dataset.preset)).toEqual(['1', '2', '3', '4']);
    p.querySelector('[data-preset="3"]').click();
    expect(draw.get(a.id).style.lineWidth).toBe(3);
    expect(q('[data-path="style.lineWidth"] .pb-val').textContent).toBe('3px');
    p = open('[data-path="style.lineWidth"]');
    p.querySelector('[data-act="step-plus"]').click();
    expect(draw.get(a.id).style.lineWidth).toBe(3.5);
    const inp = p.querySelector('[data-act="step-input"]');
    inp.value = '50';
    inp.fire('change');
    expect(draw.get(a.id).style.lineWidth).toBe(12);
    inp.value = '0';
    inp.fire('change');
    expect(draw.get(a.id).style.lineWidth).toBe(1);
    p.querySelector('[data-act="step-minus"]').click();
    expect(draw.get(a.id).style.lineWidth).toBe(1);
  });

  it('picks a dash pattern from the line-style menu and previews it on the button', () => {
    const a = line(draw);
    draw.select(a.id);
    const p = open('[data-path="style.lineStyle"]');
    expect(p.querySelectorAll('[data-value]').map((n) => n.dataset.value)).toEqual(['solid', 'dashed', 'dotted']);
    p.querySelector('[data-value="dotted"]').click();
    expect(draw.get(a.id).style.lineStyle).toBe('dotted');
    expect(q('[data-path="style.lineStyle"] .pb-ls').innerHTML).toContain('stroke-dasharray="1 3"');
  });

  it('flips the extend toggles and shows their state', () => {
    const a = line(draw);
    draw.select(a.id);
    const t = q('[data-path="style.extendLeft"]');
    expect(t.classList.contains('is-on')).toBe(false);
    t.click();
    expect(draw.get(a.id).style.extendLeft).toBe(true);
    expect(t.classList.contains('is-on')).toBe(true);
    t.click();
    expect(draw.get(a.id).style.extendLeft).toBe(false);
  });

  it('runs the fill switch, colour and opacity from one swatch, and a colour pick turns the fill on', () => {
    const a = rect(draw);
    draw.update(a.id, { style: { fill: false } });
    draw.select(a.id);
    const sw = q('[data-path="style.fillColor"]');
    expect(sw.classList.contains('is-off')).toBe(true);
    let p = open('[data-path="style.fillColor"]');
    const cb = p.querySelector('[data-path="style.fill"]');
    expect(cb.checked).toBe(false);
    cb.checked = true;
    cb.fire('change');
    expect(draw.get(a.id).style.fill).toBe(true);
    expect(sw.classList.contains('is-off')).toBe(false);
    const range = p.querySelector('[data-path="style.fillOpacity"]');
    range.value = '40';
    range.fire('input');
    expect(p.querySelector('output').textContent).toBe('40%');
    range.fire('change');
    expect(draw.get(a.id).style.fillOpacity).toBe(0.4);
    expect(pop()).toBe(p);   // a slider commit leaves the popover up
    dom.document.body.fire('keydown', { key: 'Escape' });
    draw.update(a.id, { style: { fill: false } });
    p = open('[data-path="style.fillColor"]');
    p.querySelectorAll('.pb-grid button').find((s) => s.getAttribute('aria-label') === '#4caf50').click();
    expect(draw.get(a.id).style.fillColor).toBe('#4caf50');
    expect(draw.get(a.id).style.fill).toBe(true);
  });

  it('keeps the fields with no place on the bar behind the More button', () => {
    const a = line(draw);
    draw.select(a.id);
    expect(q('[data-path="style.showStats"]')).toBeNull();
    const p = open('[data-pop="more"]');
    const cb = p.querySelector('[data-path="style.showStats"]');
    expect(cb.type).toBe('checkbox');
    cb.checked = true;
    cb.fire('change');
    expect(draw.get(a.id).style.showStats).toBe(true);
  });

  it('limits a drawing to a range of the page intervals from the More button, and says when it is hidden', () => {
    const a = line(draw);
    chart.emit('data:context', { symbol: 'AAPL', interval: '1d' });
    draw.select(a.id);
    const note = q('[data-note="interval"]');
    expect(note.hidden).toBe(true);
    const p = open('[data-pop="more"]');
    const from = p.querySelector('[data-path="intervals.from"]');
    const to = p.querySelector('[data-path="intervals.to"]');
    expect([...to.querySelectorAll('option')].map((o) => o.value)).toEqual([''].concat(INTERVALS));
    expect(to.value).toBe('');
    from.value = '5m';
    from.fire('change');
    to.value = '1h';
    to.fire('change');
    expect(draw.get(a.id).intervals).toEqual({ from: '5m', to: '1h' });
    // The chart is on daily bars, outside the range: the drawing is kept and the bar says so.
    expect(draw.shownOnInterval(a.id)).toBe(false);
    expect(note.hidden).toBe(false);
    expect(note.textContent).toBe('Hidden on 1D');
    to.value = '';
    to.fire('change');
    from.value = '';
    from.fire('change');
    expect(draw.get(a.id).intervals).toBeUndefined();
    expect(note.hidden).toBe(true);
    expect(draw.undo()).toBe(true);
    expect(draw.get(a.id).intervals).toEqual({ from: '5m' });
  });

  it('keeps the hidden note to the interval on screen as it changes under a drawing picked on purpose', () => {
    const a = line(draw, { intervals: { from: '5m', to: '1h' } });
    chart.emit('data:context', { symbol: 'AAPL', interval: '1d' });
    draw.select(a.id);   // from an objects panel: off the chart, and picked all the same
    const note = q('[data-note="interval"]');
    expect(note.textContent).toBe('Hidden on 1D');
    // Still off the chart on weekly bars, so still selected: the note names the new interval.
    chart.emit('data:context', { symbol: 'AAPL', interval: '1wk' });
    expect(draw.selection()).toEqual([a.id]);
    expect(note.hidden).toBe(false);
    expect(note.textContent).toBe('Hidden on 1W');
    // On the chart at 15 minutes: nothing to warn about.
    chart.emit('data:context', { symbol: 'AAPL', interval: '15m' });
    expect(draw.selection()).toEqual([a.id]);
    expect(note.hidden).toBe(true);
  });

  it('locks, hides and reorders through the controller', () => {
    const a = line(draw);
    const b = line(draw);
    draw.select([a.id, b.id]);
    q('[data-act="lock"]').click();
    expect(draw.get(a.id).locked).toBe(true);
    expect(draw.get(b.id).locked).toBe(true);
    expect(q('[data-act="lock"]').innerHTML).toContain(dist.CHROME_ICONS.lock);
    q('[data-act="lock"]').click();
    expect(draw.get(a.id).locked).toBe(false);
    q('[data-act="visible"]').click();
    expect(draw.get(a.id).visible).toBe(false);
    expect(q('[data-act="visible"]').innerHTML).toContain(dist.CHROME_ICONS['eye-off']);
    expect(bar.el.hidden).toBe(false);
    q('[data-act="visible"]').click();
    expect(draw.get(a.id).visible).toBe(true);

    draw.select(a.id);
    let p = open('[data-pop="order"]');
    expect(p.querySelector('[data-act="above"]').classList.contains('is-on')).toBe(true);
    p.querySelector('[data-act="behind"]').click();
    expect(draw.get(a.id).zIndex).toBe(-1);
    p = open('[data-pop="order"]');
    expect(p.querySelector('[data-act="behind"]').classList.contains('is-on')).toBe(true);
    p.querySelector('[data-act="above"]').click();
    expect(draw.get(a.id).zIndex).toBe(0);
    expect(draw.drawings().map((d) => d.id)).toEqual([a.id, b.id]);
    p = open('[data-pop="order"]');
    p.querySelector('[data-act="front"]').click();
    expect(draw.drawings().map((d) => d.id)).toEqual([b.id, a.id]);
    p = open('[data-pop="order"]');
    p.querySelector('[data-act="back"]').click();
    expect(draw.drawings().map((d) => d.id)).toEqual([a.id, b.id]);
  });

  it('duplicates onto the clones and deletes the whole selection', () => {
    const a = line(draw);
    const b = line(draw);
    draw.select([a.id, b.id]);
    q('[data-act="duplicate"]').click();
    expect(draw.drawings().length).toBe(4);
    const clones = draw.selection();
    expect(clones.length).toBe(2);
    expect(clones).not.toContain(a.id);
    expect(bar.selection()).toEqual(clones);
    q('[data-act="delete"]').click();
    expect(draw.drawings().length).toBe(2);
    expect(bar.el.hidden).toBe(true);
  });

  it('stays up for what is still selected after one of the selection is removed', () => {
    const a = line(draw);
    const b = line(draw);
    draw.select([a.id, b.id]);
    draw.remove(a.id);
    expect(bar.el.hidden).toBe(false);
    expect(bar.selection()).toEqual([b.id]);
  });

  it('edits only what a mixed selection shares', () => {
    draw.select([line(draw).id, rect(draw).id]);
    expect(q('[data-path="style.color"]')).not.toBeNull();
    expect(q('[data-path="style.extendLeft"]')).toBeNull();
    expect(q('[data-path="style.fillColor"]')).toBeNull();
  });

  it('parks above the selection, follows a drag, remembers it, and follows the drawing again on a double-click', () => {
    const a = line(draw);
    draw.select(a.id);
    // Anchors at x 80 and 160 (plus the rail's 42), y 300 and 260.
    expect(bar.el.style.left).toBe((timeToX(T0 + 600) + 42) + 'px');
    expect(bar.el.style.top).toBe((priceToY(120) - bar.el.offsetHeight - 10) + 'px');
    const grip = q('.grip');
    grip.fire('pointerdown', { clientX: 10, clientY: 10, button: 0 });
    dom.window.fire('pointermove', { clientX: 60, clientY: 40 });
    expect(bar.el.style.left).toBe((timeToX(T0 + 600) + 42 + 50) + 'px');
    expect(bar.el.style.top).toBe((priceToY(120) - bar.el.offsetHeight - 10 + 30) + 'px');
    dom.window.fire('pointerup', {});
    expect(JSON.parse(dom.store.get(PROPBAR_POS_KEY))).toEqual(bar.pinnedAt());
    draw.select(line(draw, { points: [{ time: T0 + 3000, price: 50 }, { time: T0 + 3600, price: 60 }] }).id);
    expect(bar.el.style.left).toBe(bar.pinnedAt().x + 'px');
    grip.fire('dblclick');
    expect(bar.pinnedAt()).toBeNull();
    expect(dom.store.has(PROPBAR_POS_KEY)).toBe(false);
    expect(bar.el.style.left).toBe((timeToX(T0 + 3000) + 42) + 'px');
  });

  it('never parks over the rail or off the stage', () => {
    const a = line(draw, { points: [{ time: T0, price: 240 }, { time: T0 + 60, price: 250 }] });
    draw.select(a.id);
    expect(bar.el.style.left).toBe('46px');
    expect(bar.el.style.top).toBe((priceToY(240) + 10) + 'px');
  });

  it('closes its popover on a press outside and on Escape, and toggles on its own button', () => {
    draw.select(line(draw).id);
    const btn = q('[data-path="style.color"]');
    btn.click();
    expect(pop()).not.toBeNull();
    btn.click();
    expect(pop()).toBeNull();
    btn.click();
    pop().fire('pointerdown');
    expect(pop()).not.toBeNull();
    dom.chart.fire('pointerdown');
    expect(pop()).toBeNull();
    btn.click();
    dom.document.body.fire('keydown', { key: 'Escape' });
    expect(pop()).toBeNull();
  });

  it('puts the text face on the bar for a text drawing and applies it', () => {
    const t = text(draw);
    draw.select(t.id);
    expect(q('[data-path="text.fontSize"] .pb-val').textContent).toBe('14');
    q('[data-path="text.bold"]').click();
    expect(draw.get(t.id).text.bold).toBe(true);
    const fam = q('[data-path="text.fontFamily"]');
    expect(fam.tagName).toBe('SELECT');
    fam.value = 'ui-serif, Georgia, Times New Roman, serif';
    fam.fire('change');
    expect(draw.get(t.id).text.fontFamily).toBe('ui-serif, Georgia, Times New Roman, serif');
    const p = open('[data-pop="more"]');
    const wrap = p.querySelector('[data-path="text.wrap"]');
    wrap.checked = true;
    wrap.fire('change');
    expect(draw.get(t.id).text.wrap).toBe(true);
    expect(q('[data-path="style.lineWidth"]')).toBeNull();
  });

  it('opens the inline editor on Enter, commits on Ctrl+Enter and cancels on Escape', () => {
    const t = text(draw);
    draw.select(t.id);
    dom.document.body.fire('keydown', { key: 'Enter' });
    let ed = bar.editor();
    expect(ed).not.toBeNull();
    expect(ed.el.textContent).toBe('Hello');
    expect(dom.document.activeElement).toBe(ed.el);
    ed.el.textContent = 'Hi there';
    ed.el.fire('keydown', { key: 'Enter', ctrlKey: true });
    expect(draw.get(t.id).text.value).toBe('Hi there');
    expect(bar.editor()).toBeNull();
    expect(ed.el.isConnected).toBe(false);

    dom.document.body.fire('keydown', { key: 'Enter' });
    ed = bar.editor();
    ed.el.textContent = 'Dropped';
    ed.el.fire('keydown', { key: 'Escape' });
    expect(draw.get(t.id).text.value).toBe('Hi there');
    expect(bar.editor()).toBeNull();

    dom.document.body.fire('keydown', { key: 'Enter' });
    ed = bar.editor();
    ed.el.textContent = 'On blur';
    ed.el.blur();
    expect(draw.get(t.id).text.value).toBe('On blur');
    expect(draw.canUndo()).toBe(true);
  });

  it('leaves Enter alone for a line, a multi-selection, an armed tool, or a form field', () => {
    const a = line(draw);
    draw.select(a.id);
    dom.document.body.fire('keydown', { key: 'Enter' });
    expect(bar.editor()).toBeNull();
    const t = text(draw);
    draw.select([t.id, text(draw).id]);
    dom.document.body.fire('keydown', { key: 'Enter' });
    expect(bar.editor()).toBeNull();
    draw.select(t.id);
    draw.setTool('trend-line');
    dom.document.body.fire('keydown', { key: 'Enter' });
    expect(bar.editor()).toBeNull();
    draw.setTool(null);
    const input = dom.document.createElement('input');
    dom.document.body.appendChild(input);
    input.fire('keydown', { key: 'Enter' });
    expect(bar.editor()).toBeNull();
    q('[data-act="edit-text"]').click();
    expect(bar.editor()).not.toBeNull();
  });

  it('keeps every key typed in the editor from the page\'s chords, even capture-phase ones', () => {
    const t = text(draw);
    draw.select(t.id);
    const seen = [];
    // Registered after the bar, the way the rail's own handler is.
    dom.window.addEventListener('keydown', (e) => seen.push(e.key), true);
    dom.document.body.fire('keydown', { key: 'Enter' });
    const ed = bar.editor();
    ed.el.fire('keydown', { key: 'Backspace' });
    ed.el.fire('keydown', { key: 'Delete' });
    expect(seen).toEqual(['Enter']);
    expect(draw.get(t.id)).toBeDefined();
  });

  it('stops a press on the editor before the chart can capture it', () => {
    const t = text(draw);
    draw.select(t.id);
    dom.document.body.fire('keydown', { key: 'Enter' });
    let captured = 0;
    dom.stage.addEventListener('pointerdown', () => { captured += 1; });
    bar.editor().el.fire('pointerdown');
    expect(captured).toBe(0);
  });

  it('opens on a double-click over a text drawing and keeps the chart from resetting its view', () => {
    const t = text(draw);
    let chartSaw = 0;
    dom.chart.addEventListener('dblclick', () => { chartSaw += 1; });
    const canvas = dom.document.createElement('canvas');
    dom.chart.appendChild(canvas);
    hover(chart, t.id);
    canvas.fire('dblclick');
    expect(bar.editor()).not.toBeNull();
    expect(draw.selected()).toBe(t.id);
    expect(chartSaw).toBe(0);
    bar.editor().cancel();
    hover(chart, null);
    draw.select(line(draw).id);
    canvas.fire('dblclick');
    expect(bar.editor()).toBeNull();
    expect(chartSaw).toBe(1);
  });

  it('lays the editor over the painted frame', () => {
    const t = text(draw, { text: { value: 'ab', fontSize: 10, valign: 'bottom' } });
    draw.select(t.id);
    const ed = bar.editText(t.id);
    // Two characters at 7px plus the pad, one line of 13.5 plus the pad,
    // anchored on the bottom edge; then the chart's 42px offset in the stage.
    expect(ed.frame.width).toBe(2 * 7 + 10);
    expect(ed.frame.height).toBe(13.5 + 10);
    expect(ed.el.style.left).toBe(Math.round(timeToX(T0 + 600) + 42) + 'px');
    expect(ed.el.style.top).toBe(Math.round(priceToY(100) - 23.5) + 'px');
    expect(ed.el.style.minWidth).toBe('24px');
    expect(ed.el.style.whiteSpace).toBe('pre');
    expect(ed.el.style.font).toContain('10px');
    expect(ed.el.getAttribute('contenteditable')).toBe('plaintext-only');
  });

  it('returns nothing for a drawing whose text is only a label', () => {
    const a = rect(draw);
    draw.select(a.id);
    expect(bar.editText(a.id)).toBeNull();
  });

  it('edits a ladder through the level editor', () => {
    const f = fib(draw);
    draw.select(f.id);
    expect(q('[data-path="style.showLabels"]')).toBeNull();
    let p = open('[data-pop="levels"]');
    let rows = p.querySelectorAll('.lved__row');
    expect(rows.length).toBe(DEFAULT_FIB.length);
    const on = rows[1].querySelector('input[type="checkbox"]');
    on.checked = false;
    on.fire('change');
    expect(draw.get(f.id).style.levels[1].enabled).toBe(false);
    const ratio = rows[2].querySelector('input[type="number"]');
    ratio.value = '0.35';
    ratio.fire('change');
    expect(draw.get(f.id).style.levels[2].ratio).toBe(0.35);
    const label = rows[2].querySelector('input[type="text"]');
    label.value = 'Target';
    label.fire('change');
    expect(draw.get(f.id).style.levels[2].label).toBe('Target');
    p.querySelector('.lved__foot button').click();
    expect(draw.get(f.id).style.levels.length).toBe(DEFAULT_FIB.length + 1);
    // 0.382 became 0.35 above, so it is the first conventional ratio missing.
    expect(draw.get(f.id).style.levels[DEFAULT_FIB.length]).toEqual({ ratio: 0.382, color: '#ff9800' });
    p.querySelectorAll('.lved__row')[0].querySelector('.lved__x').click();
    expect(draw.get(f.id).style.levels.length).toBe(DEFAULT_FIB.length);
    expect(draw.get(f.id).style.levels[0].ratio).toBe(0.236);
    p.querySelector('.lved__reset').click();
    expect(draw.get(f.id).style.levels).toEqual(DEFAULT_FIB.map((l) => ({ ...l })));
    const labels = p.querySelector('[data-path="style.showLabels"]');
    expect(labels.checked).toBe(true);
    labels.checked = false;
    labels.fire('change');
    expect(draw.get(f.id).style.showLabels).toBe(false);
    draw.undo();
    expect(draw.get(f.id).style.showLabels).toBe(true);
  });

  it('follows the chart it is attached to and lets go of the old one', () => {
    const before = chart.listenerCount('draw:select');
    bar.attach();
    expect(chart.listenerCount('draw:select')).toBe(before);
    const next = makeApp();
    app.chart = next.chart;
    app.draw = next.draw;
    bar.attach();
    expect(chart.listenerCount('draw:select')).toBe(before - 1);
    const a = line(next.draw);
    next.draw.select(a.id);
    expect(bar.el.hidden).toBe(false);
    bar.destroy();
    expect(bar.el.isConnected).toBe(false);
    expect(app.props).toBeNull();
  });

  it('applies a patch to the selection through the schema, dropping what it does not declare', () => {
    const a = line(draw);
    draw.select(a.id);
    bar.apply({ 'style.color': '#000000', 'style.fillColor': '#111111', 'text.value': 'x' });
    expect(readDrawingSetting(draw.get(a.id), 'style.color')).toBe('#000000');
    expect(draw.get(a.id).style.fillColor).toBeUndefined();
    expect(draw.get(a.id).text).toBeUndefined();
  });
});
