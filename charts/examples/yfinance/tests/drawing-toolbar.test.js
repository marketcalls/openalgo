// The toolbar's draw buttons and the controller wiring in drawing.js, run
// against the real controller on the fake chart: which of Undo, Redo, Del
// and Clear are offered as the drawings and the selection change, what Del
// takes, and the session marks coming back after a rebuild. The rail and
// the clipboard are stubbed, since neither is what these buttons are about.
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { installDom } from './fake-dom.js';
import { fakeChart, line, T0 } from './draw-host.js';

vi.mock('../src/persist.js', () => ({ autosave: vi.fn() }));
vi.mock('../src/rail.js', () => ({
  buildRail: vi.fn(), syncRail: vi.fn(), syncMobileControls: vi.fn(), observeMobileControls: vi.fn(),
  armCursor: vi.fn(), setDrawLock: vi.fn(), magnetMode: () => 'off', stayMode: () => false,
  toolName: (id) => ({ 'trend-line': 'Trend Line' }[id] ?? id),
}));
vi.mock('../src/clipboard.js', () => ({
  clipboardPort: undefined, activeDraw: () => null, canClip: () => false, clipboardAction: vi.fn(),
}));
const { initDrawing, attachDrawing } = await import('../src/drawing.js');
const { addSessionMark, sessionMarks, clearSessionMarks } = await import('../src/session-marks.js');

const BUTTONS = ['drawundo', 'drawredo', 'drawdel', 'drawclear'];
const $ = (id) => document.getElementById(id);
/** Which of Undo, Redo, Del and Clear are greyed, in that order. */
const greyed = () => BUTTONS.map((id) => $(id).disabled);
const second = { points: [{ time: T0 + 2400, price: 90 }, { time: T0 + 3000, price: 95 }] };

let app;

beforeEach(() => {
  const dom = installDom();
  for (const [tag, id] of [['select', 'drawtool'], ...BUTTONS.map((id) => ['button', id]), ['div', 'status']]) {
    const node = dom.document.createElement(tag);
    node.id = id;
    dom.document.body.appendChild(node);
  }
  app = { chart: fakeChart(), draw: null, shortcuts: { ready: true }, req: { symbol: 'AAPL' } };
  initDrawing(app);
  attachDrawing();
});

describe('the toolbar\'s draw buttons', () => {
  it('grey each button until it has something to do, following every change and selection', () => {
    expect(greyed()).toEqual([true, true, true, true]);
    const mine = line(app.draw);
    expect(greyed()).toEqual([false, true, true, false]);
    app.draw.select(mine.id);
    expect(greyed()).toEqual([false, true, false, false]);
    expect($('drawdel').title).toBe('delete selected');
    app.draw.undo();
    expect(greyed()).toEqual([true, false, true, true]);
    app.draw.redo();
    expect(greyed()).toEqual([false, true, true, false]);
  });

  it('grey Del with its reason on a read-only selection, and Clear when only read-only drawings are left', () => {
    const mark = addSessionMark(app.draw, { time: T0 + 600, price: 101 }, 'AAPL');
    app.draw.select(mark.id);
    expect(greyed()).toEqual([true, true, true, true]);
    expect($('drawdel').title).toBe('read-only');
    const mine = line(app.draw);
    app.draw.select([mark.id, mine.id]);
    expect(greyed()).toEqual([false, true, false, false]);
    expect($('drawdel').title).toBe('delete selected');
    clearSessionMarks(app.draw, 'AAPL');
  });

  it('delete the whole selection as one step with Del, and leave the read-only drawings in it', () => {
    const mark = addSessionMark(app.draw, { time: T0 + 600, price: 101 }, 'AAPL');
    const a = line(app.draw);
    const b = line(app.draw, second);
    app.draw.select([a.id, mark.id, b.id]);
    $('drawdel').click();
    expect(app.draw.drawings().map((d) => d.id)).toEqual([mark.id]);
    expect(greyed()).toEqual([false, true, true, true]);
    // One press of Undo brings both back.
    $('drawundo').click();
    expect(app.draw.drawings().map((d) => d.id)).toEqual([mark.id, a.id, b.id]);
    clearSessionMarks(app.draw, 'AAPL');
  });

  it('take every drawing but the read-only ones with Clear', () => {
    const mark = addSessionMark(app.draw, { time: T0 + 600, price: 101 }, 'AAPL');
    line(app.draw);
    $('drawclear').click();
    expect(app.draw.drawings().map((d) => d.id)).toEqual([mark.id]);
    expect(greyed()).toEqual([false, true, true, true]);
    clearSessionMarks(app.draw, 'AAPL');
  });
});

describe('the controller the host attaches', () => {
  it('puts the session marks back after every restore, and after a rebuild', () => {
    const mark = addSessionMark(app.draw, { time: T0 + 600, price: 101 }, 'AAPL');
    const saved = app.draw.toJSON();
    app.chart.emit('drawings:restore', saved);
    expect(sessionMarks(app.draw).map((d) => d.id)).toEqual([mark.id]);
    // A chart-type switch builds a new chart and a new controller, then
    // restores the saved state into them.
    app.chart = fakeChart();
    attachDrawing();
    app.chart.emit('drawings:restore', saved);
    expect(sessionMarks(app.draw).map((d) => d.id)).toEqual([mark.id]);
    // Another instrument's chart has marks of its own, none yet.
    app.req.symbol = 'MSFT';
    app.chart.emit('drawings:restore', saved);
    expect(sessionMarks(app.draw)).toEqual([]);
    app.req.symbol = 'AAPL';
    clearSessionMarks(app.draw, 'AAPL');
  });

  it('says what the user drew, and nothing for a mark the host put back', () => {
    line(app.draw);
    // The tool by its name, not its id.
    expect($('status').textContent).toBe('drew Trend Line');
    $('status').textContent = '';
    addSessionMark(app.draw, { time: T0 + 600, price: 101 }, 'AAPL');
    expect($('status').textContent).toBe('');
    clearSessionMarks(app.draw, 'AAPL');
  });

  it('saves the layout when a setter with no event of its own changes it', async () => {
    const { autosave } = await import('../src/persist.js');
    autosave.mockClear();
    // A grid toggled from the keyboard, say: the chart names the setter.
    app.chart.emit('layout:change', { setter: 'setGridOptions' });
    expect(autosave).toHaveBeenCalledTimes(1);
  });
});
