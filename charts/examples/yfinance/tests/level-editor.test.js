// The level editor: rows from a ladder, every edit reported as a whole
// list, and the add, remove and reset actions.
import { describe, it, expect, beforeEach } from 'vitest';
import { installDom } from './fake-dom.js';
import { buildLevelEditor, nextRatio, FIB_SEQUENCE } from '../src/level-editor.js';

const LEVELS = [
  { ratio: 0, color: '#787b86' },
  { ratio: 0.5, color: '#4caf50', enabled: false },
  { ratio: 1, label: 'Top' },
];

describe('nextRatio', () => {
  it('walks the conventional ladder, then goes past the largest', () => {
    expect(nextRatio([])).toBe(0);
    expect(nextRatio(LEVELS)).toBe(0.236);
    expect(nextRatio(FIB_SEQUENCE.map((ratio) => ({ ratio })))).toBe(FIB_SEQUENCE[FIB_SEQUENCE.length - 1] + 1);
    expect(nextRatio([{ ratio: 0.2360000001 }, { ratio: 0 }])).toBe(0.382);
  });
});

describe('buildLevelEditor', () => {
  let changes, labels, root;
  const rows = () => root.querySelectorAll('.lved__row');
  const build = (opts = {}) => {
    root = buildLevelEditor({
      levels: LEVELS, defaults: [{ ratio: 0.618, color: '#089981' }], showLabels: true, fallbackColor: '#2962ff',
      onChange: (l) => changes.push(l), onLabels: (on) => labels.push(on), ...opts,
    });
    return root;
  };
  beforeEach(() => { installDom(); changes = []; labels = []; build(); });

  it('names the controls of each row by its level, so no two rows read the same', () => {
    const names = (selector) => rows().map((row) => row.querySelector(selector).getAttribute('aria-label'));
    for (const selector of ['input[type="checkbox"]', 'input[type="number"]', 'input[type="color"]', 'input[type="text"]', '.lved__x']) {
      expect(new Set(names(selector)).size, selector).toBe(3);
    }
    expect(names('.lved__x')[1]).toMatch(/^Remove level /);
    expect(names('input[type="color"]').every((name) => !name.includes('Colour'))).toBe(true);
  });

  it('draws one row per level with its state, and does not touch the list it was given', () => {
    const r = rows();
    expect(r.length).toBe(3);
    expect(r[0].querySelector('input[type="checkbox"]').checked).toBe(true);
    expect(r[1].querySelector('input[type="checkbox"]').checked).toBe(false);
    expect(r[1].classList.contains('is-off')).toBe(true);
    expect(r[0].querySelector('input[type="number"]').value).toBe('0');
    expect(r[1].querySelector('input[type="color"]').value).toBe('#4caf50');
    expect(r[2].querySelector('input[type="color"]').value).toBe('#2962ff');
    expect(r[2].querySelector('input[type="text"]').value).toBe('Top');
    expect(r[0].querySelector('input[type="text"]').placeholder).toBe('0.0%');
    expect(LEVELS[1].enabled).toBe(false);
    expect(LEVELS.length).toBe(3);
  });

  it('reports the whole list on every edit, and re-enabling drops the flag', () => {
    const on = rows()[1].querySelector('input[type="checkbox"]');
    on.checked = true;
    on.fire('change');
    expect(changes[0][1]).toEqual({ ratio: 0.5, color: '#4caf50' });
    expect(rows()[1].classList.contains('is-off')).toBe(false);
    const ratio = rows()[0].querySelector('input[type="number"]');
    ratio.value = '0.25';
    ratio.fire('change');
    expect(changes[1][0].ratio).toBe(0.25);
    expect(rows()[0].querySelector('input[type="text"]').placeholder).toBe('25.0%');
    const color = rows()[2].querySelector('input[type="color"]');
    color.value = '#ff0000';
    color.fire('change');
    expect(changes[2][2].color).toBe('#ff0000');
    const label = rows()[2].querySelector('input[type="text"]');
    label.value = '  ';
    label.fire('change');
    expect(changes[3][2].label).toBeUndefined();
    expect(changes.length).toBe(4);
    expect(LEVELS[0].ratio).toBe(0);
  });

  it('keeps the last good ratio when the box is blank or not a number', () => {
    const ratio = rows()[1].querySelector('input[type="number"]');
    ratio.value = '';
    ratio.fire('change');
    ratio.value = 'abc';
    ratio.fire('change');
    expect(changes).toEqual([]);
    expect(ratio.value).toBe('0.5');
  });

  it('adds the next conventional level in its colour, removes a row, and resets to the defaults', () => {
    const [add] = root.querySelectorAll('.lved__foot button');
    add.click();
    expect(rows().length).toBe(4);
    expect(changes[0][3]).toEqual({ ratio: 0.236, color: '#f23645' });
    rows()[0].querySelector('.lved__x').click();
    expect(rows().length).toBe(3);
    expect(changes[1].map((l) => l.ratio)).toEqual([0.5, 1, 0.236]);
    root.querySelector('.lved__reset').click();
    expect(rows().length).toBe(1);
    expect(changes[2]).toEqual([{ ratio: 0.618, color: '#089981' }]);
    for (const l of rows()) l.querySelector('.lved__x').click();
    expect(root.querySelector('.lved__empty')).not.toBeNull();
    expect(changes[3]).toEqual([]);
  });

  it('carries the labels switch only when the tool has one', () => {
    const sw = root.querySelector('.lved__head input');
    expect(sw.checked).toBe(true);
    sw.checked = false;
    sw.fire('change');
    expect(labels).toEqual([false]);
    build({ showLabels: undefined });
    expect(root.querySelector('.lved__head input')).toBeNull();
  });

  it('uses the tool\'s own label wording for the placeholders', () => {
    build({ labelOf: (r) => `${r}x1` });
    expect(rows()[2].querySelector('input[type="text"]').placeholder).toBe('1x1');
  });
});
