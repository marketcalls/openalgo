/**
 * The widget keymap: the chord grammar, scope resolution, layering, the text
 * field rule, and above all conflict detection, because the draw tier's tool
 * chords and the engine's own keymap collide on two chords and the panel has
 * to say so.
 */
import { describe, it, expect, vi } from 'vitest';
import { ShortcutManager } from '../src/input/shortcuts';
import { drawingShortcuts } from '../src/draw/index';
import {
  Keymap, parseKeyCombo, eventKeyCombo, formatKeyCombo, fromChartCombo, commandChord,
  type KeyEventLike, type KeyScope,
} from '../src/widget/keymap';
import { fakeWidgetDocument, fireKey } from './helpers/fake-dom-widget';

const key = (k: string, extra: Partial<KeyEventLike> = {}): KeyEventLike => ({ key: k, ...extra });

describe('parseKeyCombo', () => {
  it('canonicalises modifier order, case and aliases', () => {
    expect(parseKeyCombo('shift+alt+t')).toBe('Alt+Shift+t');
    expect(parseKeyCombo('Ctrl+Z')).toBe('Mod+z');
    expect(parseKeyCombo('Cmd+Shift+z')).toBe('Mod+Shift+z');
    expect(parseKeyCombo('Meta+ArrowLeft')).toBe('Mod+ArrowLeft');
    expect(parseKeyCombo('Esc')).toBe('Escape');
    expect(parseKeyCombo('Del')).toBe('Delete');
    expect(parseKeyCombo('Left')).toBe('ArrowLeft');
  });

  it('drops Shift from a symbol or digit, since the character already says it', () => {
    expect(parseKeyCombo('Shift+?')).toBe('?');
    expect(parseKeyCombo('?')).toBe('?');
    expect(parseKeyCombo('Shift+1')).toBe('1');
    expect(parseKeyCombo('Ctrl++')).toBe('Mod++');
  });

  it('rejects what is not a chord', () => {
    expect(parseKeyCombo('')).toBe('');
    expect(parseKeyCombo('Foo+x')).toBe('');
    expect(parseKeyCombo('Shift')).toBe('');
    expect(parseKeyCombo('Ctrl+')).toBe('');
  });
});

describe('eventKeyCombo', () => {
  it('reads the event the way a binding is written', () => {
    expect(eventKeyCombo(key('t', { altKey: true }))).toBe('Alt+t');
    expect(eventKeyCombo(key('Z', { shiftKey: true, ctrlKey: true }))).toBe('Mod+Shift+z');
    expect(eventKeyCombo(key('z', { metaKey: true }))).toBe('Mod+z');
    expect(eventKeyCombo(key('?', { shiftKey: true }))).toBe('?');
    expect(eventKeyCombo(key(' '))).toBe('Space');
    expect(eventKeyCombo(key('ArrowLeft', { shiftKey: true }))).toBe('Shift+ArrowLeft');
  });

  it('recovers the letter from the physical key when Alt turned it into a symbol', () => {
    expect(eventKeyCombo(key('†', { altKey: true, code: 'KeyT' }))).toBe('Alt+t');
  });

  it('ignores a bare modifier press', () => {
    expect(eventKeyCombo(key('Shift', { shiftKey: true }))).toBe('');
    expect(eventKeyCombo(key('Control', { ctrlKey: true }))).toBe('');
    expect(eventKeyCombo(key(''))).toBe('');
  });
});

describe('formatKeyCombo and fromChartCombo', () => {
  it('formats for the platform', () => {
    expect(formatKeyCombo('Mod+Shift+z', false)).toBe('Ctrl+Shift+Z');
    expect(formatKeyCombo('Mod+Shift+z', true)).toBe('Cmd+Shift+Z');
    expect(formatKeyCombo('Alt+t', true)).toBe('Opt+T');
    expect(formatKeyCombo('Escape', false)).toBe('Esc');
    expect(formatKeyCombo('?', false)).toBe('?');
    expect(formatKeyCombo('nonsense+', false)).toBe('');
  });

  it('reads the platform as the engine does, so the two never say Cmd and Ctrl side by side', () => {
    // A browser that blanks the platform string still names the machine in its user agent.
    vi.stubGlobal('navigator', { platform: '', userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5)' });
    try {
      expect(new Keymap().isMac).toBe(true);
      expect(formatKeyCombo('Mod+z')).toBe('Cmd+Z');
    } finally { vi.unstubAllGlobals(); }
  });

  it('translates the engine code-based combos into the key form', () => {
    expect(fromChartCombo('Alt+KeyV')).toBe('Alt+v');
    expect(fromChartCombo('Mod+Shift+KeyS')).toBe('Mod+Shift+s');
    expect(fromChartCombo('Shift+Equal')).toBe('+');
    expect(fromChartCombo('Digit0')).toBe('0');
    expect(fromChartCombo('ArrowLeft')).toBe('ArrowLeft');
    expect(fromChartCombo('Ctrl+KeyC')).toBe('Mod+c');
  });
});

describe('Keymap.handle', () => {
  const claimed = (): KeyEventLike & { prevented: boolean; stopped: boolean } => {
    const e = { key: 't', altKey: true, prevented: false, stopped: false } as KeyEventLike & { prevented: boolean; stopped: boolean };
    e.preventDefault = () => { e.prevented = true; };
    e.stopPropagation = () => { e.stopped = true; };
    return e;
  };

  it('runs the binding, prevents and stops the event, and reports the claim', () => {
    const km = new Keymap({ isMac: false });
    const action = vi.fn();
    km.register('Alt+T', action);
    const e = claimed();
    expect(km.handle(e)).toBe(true);
    expect(action).toHaveBeenCalledTimes(1);
    expect(e.prevented).toBe(true);
    expect(e.stopped).toBe(true);
    expect(km.handle(key('t'))).toBe(false);
  });

  it('a declining action leaves the key to the next layered binding, then to nobody', () => {
    const km = new Keymap();
    const order: string[] = [];
    km.register('Escape', () => { order.push('first'); return false; }, 'global', { label: 'first' });
    km.register('Escape', () => { order.push('second'); }, 'global', { label: 'second', layered: true });
    expect(km.handle(key('Escape'))).toBe(true);
    expect(order).toEqual(['first', 'second']);
    expect(km.conflicts()).toEqual([]);
    const lone = new Keymap();
    lone.register('Escape', () => false);
    expect(lone.handle(key('Escape'))).toBe(false);
  });

  it('tries scopes in the order the resolver gives them and skips inactive ones', () => {
    let scopes: KeyScope[] = ['global'];
    const km = new Keymap({ scopes: () => scopes });
    const hits: string[] = [];
    km.register('ArrowDown', () => { hits.push('rail'); }, 'rail');
    km.register('ArrowDown', () => { hits.push('widget'); }, 'widget');
    expect(km.handle(key('ArrowDown'))).toBe(false);
    scopes = ['widget', 'global'];
    km.handle(key('ArrowDown'));
    scopes = ['rail', 'widget', 'global'];
    km.handle(key('ArrowDown'));
    expect(hits).toEqual(['widget', 'rail']);
  });

  it('stays out of text fields unless a binding asks to be let in', () => {
    const km = new Keymap();
    const action = vi.fn();
    const escape = vi.fn();
    km.register('Mod+Z', action);
    km.register('Escape', escape, 'global', { inText: true });
    const input = { tagName: 'INPUT', type: 'text' };
    expect(km.handle(key('z', { ctrlKey: true, target: input }))).toBe(false);
    expect(action).not.toHaveBeenCalled();
    expect(km.handle(key('Escape', { target: input }))).toBe(true);
    expect(escape).toHaveBeenCalled();
    // A checkbox is an input that takes no typing, so chords stay live over it.
    expect(km.handle(key('z', { ctrlKey: true, target: { tagName: 'INPUT', type: 'checkbox' } }))).toBe(true);
  });

  it('honours a when gate without declining for the others', () => {
    const km = new Keymap();
    let open = false;
    const gated = vi.fn();
    const fallback = vi.fn();
    km.register('Enter', gated, 'global', { when: () => open });
    km.register('Enter', fallback, 'global', { layered: true });
    km.handle(key('Enter'));
    expect(gated).not.toHaveBeenCalled();
    expect(fallback).toHaveBeenCalledTimes(1);
    open = true;
    km.handle(key('Enter'));
    expect(gated).toHaveBeenCalledTimes(1);
    expect(fallback).toHaveBeenCalledTimes(1);
  });

  it('throws at registration for a binding that could never fire', () => {
    const km = new Keymap();
    expect(() => km.register('Foo+x', () => {})).toThrow(/not a key binding/);
  });
});

describe('conflicts', () => {
  it('records a second binding on the same chord and scope, and forgets it when either goes', () => {
    const km = new Keymap({ isMac: false });
    const seen = vi.fn();
    km.onConflict(seen);
    km.register('Alt+H', () => {}, 'widget', { label: 'Horizontal Line' });
    const off = km.register('Alt+H', () => {}, 'widget', { label: 'Hide panel' });
    expect(km.conflicts()).toEqual([{ combo: 'Alt+h', scope: 'widget', kept: 'Horizontal Line', shadowed: 'Hide panel', source: 'widget' }]);
    expect(seen).toHaveBeenCalledTimes(1);
    // Different scopes are deliberate layering, not a collision.
    km.register('Alt+H', () => {}, 'rail', { label: 'rail thing' });
    expect(km.conflicts()).toHaveLength(1);
    off();
    expect(km.conflicts()).toEqual([]);
  });

  it('finds the two chords where the draw tier and the engine keymap disagree', () => {
    const km = new Keymap({ isMac: false, chart: new ShortcutManager() });
    for (const [id, chord] of Object.entries(drawingShortcuts())) km.register(chord, () => {}, 'widget', { label: id, group: 'Drawing tools' });
    const chartSide = km.conflicts().filter((c) => c.source === 'chart');
    const shadowed = chartSide.map((c) => `${c.combo}:${c.shadowed}:${c.kept}`).sort();
    expect(shadowed).toEqual(['Alt+h:Toggle horizontal grid:horizontal-line', 'Alt+v:Toggle vertical grid:vertical-line']);
    const chart = km.describe().find((g) => g.group === 'Chart');
    expect(chart).toBeDefined();
    const grid = chart?.rows.find((r) => r.label === 'Toggle vertical grid');
    expect(grid?.shadowedBy).toBe('vertical-line');
    expect(chart?.rows.find((r) => r.label === 'Fit all bars')?.shadowedBy).toBeUndefined();
    // One name per action across the widget: the context menu fits all bars, the navigator resets the view.
    expect(chart?.rows.map((r) => r.label)).toEqual(expect.arrayContaining(['Fit all bars', 'Reset view']));
  });

  it('does not count a rail or overlay binding as shadowing the chart', () => {
    const km = new Keymap({ chart: new ShortcutManager() });
    km.register('ArrowDown', () => {}, 'rail', { label: 'Next tool' });
    km.register('Escape', () => {}, 'overlay');
    expect(km.conflicts()).toEqual([]);
  });
});

describe('attach', () => {
  it('claims in the capture phase so a bubble listener on the document never sees the chord', () => {
    const doc = fakeWidgetDocument();
    const el = doc.createElement('div');
    doc.body.appendChild(el);
    const km = new Keymap();
    const armed = vi.fn();
    km.register('Alt+T', armed);
    const detach = km.attach(doc as unknown as Document);
    const docSaw = vi.fn();
    doc.addEventListener('keydown', docSaw);
    fireKey(el, 't', { altKey: true });
    expect(armed).toHaveBeenCalledTimes(1);
    expect(docSaw).not.toHaveBeenCalled();
    fireKey(el, 'x');
    expect(docSaw).toHaveBeenCalledTimes(1);
    detach();
    fireKey(el, 't', { altKey: true });
    expect(armed).toHaveBeenCalledTimes(1);
  });

  it('describe groups the visible bindings and leaves hidden ones out', () => {
    const km = new Keymap({ isMac: false });
    km.register('Mod+Z', () => {}, 'widget', { label: 'Undo', group: 'Drawing' });
    km.register('Mod+Y', () => {}, 'widget', { label: 'Redo', group: 'Drawing', hidden: true });
    km.register('?', () => {}, 'widget', { label: 'Keyboard shortcuts' });
    expect(km.describe()).toEqual([
      { group: 'Drawing', rows: [{ label: 'Undo', combo: 'Mod+z', display: 'Ctrl+Z' }] },
      { group: 'Widget', rows: [{ label: 'Keyboard shortcuts', combo: '?', display: '?' }] },
    ]);
  });
});

describe('fromChartCombo on a US layout', () => {
  it('reads shifted digits and punctuation as the characters they type', () => {
    expect(fromChartCombo('Shift+Digit1')).toBe('!');
    expect(fromChartCombo('Shift+Slash')).toBe('?');
    expect(fromChartCombo('Alt+Comma')).toBe('Alt+,');
    expect(fromChartCombo('BracketLeft')).toBe('[');
    expect(fromChartCombo('Numpad7')).toBe('7');
    expect(fromChartCombo('NumpadEnter')).toBe('Enter');
  });
});

describe('commands', () => {
  it('names a binding by a command that must be free and outside the chart prefix', () => {
    const km = new Keymap({ isMac: false });
    km.register('Alt+T', () => {}, 'widget', { command: 'tool:trend-line' });
    expect(() => km.register('Alt+Y', () => {}, 'widget', { command: 'tool:trend-line' })).toThrow(/not a free command/);
    expect(() => km.register('Alt+U', () => {}, 'widget', { command: 'chart:zoomIn' })).toThrow(/not a free command/);
    const [b] = km.list();
    expect(b).toMatchObject({ command: 'tool:trend-line', rebindable: true, combo: 'Alt+t', defaultCombo: 'Alt+t' });
    km.register('Escape', () => {}, 'widget', { command: 'leave', rebindable: false });
    km.register('Alt+Q', () => {});
    expect(km.list().map((x) => [x.command, x.rebindable])).toEqual([['tool:trend-line', true], ['leave', false], [null, false]]);
  });
});

describe('rebind', () => {
  const make = (): { km: Keymap; hits: string[] } => {
    const km = new Keymap({ isMac: false, scopes: () => ['widget', 'global'] });
    const hits: string[] = [];
    km.register('Mod+Z', () => { hits.push('undo'); }, 'widget', { command: 'undo', label: 'Undo' });
    km.register('Alt+T', () => { hits.push('trend'); }, 'widget', { command: 'tool:trend-line', label: 'Trend line' });
    km.register('Alt+H', () => { hits.push('hline'); }, 'widget', { command: 'tool:horizontal-line', label: 'Horizontal line' });
    km.register('Escape', () => { hits.push('leave'); }, 'widget', { command: 'leave', label: 'Leave', rebindable: false });
    km.register('ArrowLeft', () => false, 'widget', { command: 'nudge-left', label: 'Nudge', layered: true, rebindable: false });
    return { km, hits };
  };

  it('moves a command: the new chord fires, the old one no longer does, and the override is recorded', () => {
    const { km, hits } = make();
    const seen = vi.fn();
    km.onChange(seen);
    expect(km.rebind('tool:trend-line', 'Alt+Y')).toEqual({ ok: true, conflicts: [] });
    expect(km.handle(key('y', { altKey: true, code: 'KeyY' }))).toBe(true);
    expect(km.handle(key('t', { altKey: true, code: 'KeyT' }))).toBe(false);
    expect(hits).toEqual(['trend']);
    expect(km.chord('tool:trend-line')).toBe('Alt+y');
    expect(km.overrides()).toEqual({ 'tool:trend-line': 'Alt+y' });
    expect(seen).toHaveBeenCalledWith({ commands: ['tool:trend-line'] });
    const row = km.describe().flatMap((g) => g.rows).find((r) => r.command === 'tool:trend-line');
    expect(row).toMatchObject({ combo: 'Alt+y', display: 'Alt+Y', defaultCombo: 'Alt+t', changed: true, rebindable: true });
  });

  it('refuses an unknown or fixed command, an unreadable chord, and one the browser keeps', () => {
    const { km } = make();
    expect(km.rebind('nothing', 'Alt+Y')).toMatchObject({ ok: false, reason: 'unknown' });
    expect(km.rebind('leave', 'Alt+Y')).toMatchObject({ ok: false, reason: 'fixed' });
    expect(km.rebind('undo', 'Foo+x')).toMatchObject({ ok: false, reason: 'invalid' });
    expect(km.rebind('undo', ['Alt+1', 'Alt+2'])).toMatchObject({ ok: false, reason: 'invalid' });
    expect(km.rebind('undo', 'Ctrl+W')).toMatchObject({ ok: false, reason: 'reserved' });
    expect(km.rebind('undo', 'Mod+Shift+T')).toMatchObject({ ok: false, reason: 'reserved' });
    expect(km.overrides()).toEqual({});
  });

  it('will not take a chord another binding holds unless asked to replace, and then unbinds the holder', () => {
    const { km, hits } = make();
    const r = km.rebind('tool:trend-line', 'Alt+H');
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('taken');
    expect(r.conflicts).toEqual([{ command: 'tool:horizontal-line', label: 'Horizontal line', group: 'Widget', source: 'widget', rebindable: true }]);
    expect(km.chord('tool:trend-line')).toBe('Alt+t');
    const seen = vi.fn();
    km.onChange(seen);
    expect(km.rebind('tool:trend-line', 'Alt+H', { replace: true }).ok).toBe(true);
    expect(km.chord('tool:horizontal-line')).toBe('');
    expect(km.overrides()).toEqual({ 'tool:trend-line': 'Alt+h', 'tool:horizontal-line': null });
    expect(seen).toHaveBeenCalledWith({ commands: ['tool:trend-line', 'tool:horizontal-line'] });
    km.handle(key('h', { altKey: true, code: 'KeyH' }));
    expect(hits).toEqual(['trend']);
    expect(km.conflicts()).toEqual([]);
    const hline = km.describe().flatMap((g) => g.rows).find((r) => r.command === 'tool:horizontal-line');
    expect(hline).toMatchObject({ combo: '', display: '', changed: true });
  });

  it('never takes a chord from a fixed binding, replace or not', () => {
    const { km } = make();
    const r = km.rebind('undo', 'Escape', { replace: true });
    expect(r).toMatchObject({ ok: false, reason: 'taken' });
    expect(r.conflicts.map((c) => [c.command, c.rebindable])).toEqual([['leave', false]]);
    // A layered binding still holds its chord against a binding of its own kind.
    expect(km.rebind('undo', 'ArrowLeft', { replace: true })).toMatchObject({ ok: false, reason: 'taken' });
    expect(km.chord('leave')).toBe('Escape');
  });

  it('previews who holds a chord for a scope, with the scopes that are live together', () => {
    const km = new Keymap({ isMac: false, chart: new ShortcutManager() });
    km.register('Alt+O', () => {}, 'global', { label: 'Host orders' });
    km.register('ArrowDown', () => {}, 'rail', { label: 'Next tool' });
    expect(km.conflictsFor('Alt+O', 'widget').map((c) => c.label)).toEqual(['Host orders']);
    expect(km.conflictsFor('Alt+O', 'rail')).toEqual([]);
    expect(km.conflictsFor('ArrowDown', 'widget').map((c) => [c.label, c.source])).toEqual([['Pan down', 'chart']]);
    // The chart's own commands never compete with a rail key.
    expect(km.conflictsFor('ArrowDown', 'rail').map((c) => c.label)).toEqual(['Next tool']);
    expect(km.conflictsFor('Alt+F').map((c) => c.command)).toEqual(['chart:fitContent']);
    expect(km.conflictsFor('not a chord+')).toEqual([]);
  });

  it('resets one command, and asks before taking its default back from another widget binding', () => {
    const { km } = make();
    km.rebind('tool:horizontal-line', 'Alt+J');
    km.rebind('tool:trend-line', 'Alt+H');
    const r = km.reset('tool:horizontal-line');
    expect(r).toMatchObject({ ok: false, reason: 'taken' });
    expect(r.conflicts.map((c) => c.command)).toEqual(['tool:trend-line']);
    expect(km.reset('tool:horizontal-line', { replace: true }).ok).toBe(true);
    expect(km.chord('tool:horizontal-line')).toBe('Alt+h');
    expect(km.chord('tool:trend-line')).toBe('');
    expect(km.reset('tool:trend-line').ok).toBe(true);
    expect(km.overrides()).toEqual({});
  });

  it('resets everything at once, commands not registered yet included, with one change event', () => {
    const { km } = make();
    km.applyOverrides({ 'tool:trend-line': 'Alt+Y', 'tool:later': 'Alt+L' });
    km.rebind('undo', 'Alt+U');
    const seen = vi.fn();
    km.onChange(seen);
    km.resetAll();
    expect(km.overrides()).toEqual({});
    expect(km.chord('tool:trend-line')).toBe('Alt+t');
    expect(km.chord('undo')).toBe('Mod+z');
    expect(seen).toHaveBeenCalledTimes(1);
    expect([...seen.mock.calls[0][0].commands].sort()).toEqual(['tool:later', 'tool:trend-line', 'undo']);
  });
});

describe('overrides and applyOverrides', () => {
  it('round-trips through JSON into a fresh keymap, whenever the command registers', () => {
    const first = new Keymap({ isMac: false });
    first.register('Mod+Z', () => {}, 'widget', { command: 'undo' });
    first.register('Alt+T', () => {}, 'widget', { command: 'tool:trend-line' });
    first.rebind('undo', 'Alt+U');
    first.rebind('tool:trend-line', null);
    const saved = JSON.parse(JSON.stringify(first.overrides()));
    expect(saved).toEqual({ undo: 'Alt+u', 'tool:trend-line': null });

    const next = new Keymap({ isMac: false });
    next.register('Mod+Z', () => {}, 'widget', { command: 'undo' });
    next.applyOverrides(saved);
    expect(next.chord('undo')).toBe('Alt+u');
    // Registered after the saved record arrived: it takes the record at once.
    next.register('Alt+T', () => {}, 'widget', { command: 'tool:trend-line' });
    expect(next.chord('tool:trend-line')).toBe('');
    expect(next.overrides()).toEqual(saved);
  });

  it('replaces rather than merges, and drops what it cannot use', () => {
    const km = new Keymap({ isMac: false });
    km.register('Mod+Z', () => {}, 'widget', { command: 'undo' });
    km.register('Alt+T', () => {}, 'widget', { command: 'tool:trend-line' });
    km.register('Escape', () => {}, 'widget', { command: 'leave', rebindable: false });
    km.rebind('undo', 'Alt+U');
    km.applyOverrides({
      'tool:trend-line': 'Alt+Y', leave: 'Alt+E', broken: 'Foo+x', reserved: 'Ctrl+W', odd: 7, 'chart:': 'KeyA',
    });
    expect(km.chord('undo')).toBe('Mod+z');
    expect(km.chord('tool:trend-line')).toBe('Alt+y');
    expect(km.chord('leave')).toBe('Escape');
    expect(km.overrides()).toEqual({ 'tool:trend-line': 'Alt+y' });
    for (const junk of [null, undefined, 'x', 3, ['Alt+Y']]) {
      km.applyOverrides(junk);
      expect(km.overrides()).toEqual({});
    }
  });

  it('reports a collision a saved chord makes, as a registration would', () => {
    const km = new Keymap({ isMac: false });
    const seen = vi.fn();
    km.onConflict(seen);
    km.register('Alt+O', () => {}, 'widget', { label: 'Host orders' });
    km.register('Alt+T', () => {}, 'widget', { command: 'tool:trend-line', label: 'Trend line' });
    km.applyOverrides({ 'tool:trend-line': 'Alt+O' });
    expect(seen).toHaveBeenCalledWith({ combo: 'Alt+o', scope: 'widget', kept: 'Host orders', shadowed: 'Trend line', source: 'widget' });
  });

  it('says nothing when handed the record it already holds, so keymaps sharing one cannot echo', () => {
    // Two charts that pass each other their record on every change, the way
    // cells of one grid share the user's chords: one change, one round.
    const pair = [new Keymap({ isMac: false, chart: new ShortcutManager({ isMac: false }) }), new Keymap({ isMac: false, chart: new ShortcutManager({ isMac: false }) })];
    const heard = [vi.fn(), vi.fn()];
    pair.forEach((km, i) => {
      km.register('Alt+T', () => {}, 'widget', { command: 'tool:trend-line' });
      km.onChange(heard[i]);
      km.onChange(() => pair[1 - i].applyOverrides(km.overrides()));
    });
    pair[0].rebind('tool:trend-line', 'Alt+Y');
    pair[0].rebind('chart:fitContent', 'Alt+KeyG');
    expect(pair[1].chord('tool:trend-line')).toBe('Alt+y');
    expect(pair[1].overrides()).toEqual(pair[0].overrides());
    expect(heard[0]).toHaveBeenCalledTimes(2);
    expect(heard[1]).toHaveBeenCalledTimes(2);
    pair[1].applyOverrides(pair[1].overrides());
    expect(heard[1]).toHaveBeenCalledTimes(2);
  });
});

describe('commandChord', () => {
  it('shows the chord in force, the fallback for a command nothing registered, and none once unbound', () => {
    const km = new Keymap({ isMac: false });
    km.register('Mod+Z', () => {}, 'widget', { command: 'undo' });
    expect(commandChord(km, 'undo', 'Mod+Y')).toBe('Ctrl+Z');
    km.rebind('undo', 'Alt+U');
    expect(commandChord(km, 'undo')).toBe('Alt+U');
    expect(commandChord(km, 'copy', 'Mod+C')).toBe('Ctrl+C');
    expect(commandChord(km, 'copy')).toBeUndefined();
    km.rebind('undo', null);
    expect(commandChord(km, 'undo', 'Mod+Z')).toBeUndefined();
    expect(commandChord(new Keymap({ isMac: true }), 'copy', 'Mod+C')).toBe('Cmd+C');
  });
});

describe('the chart commands', () => {
  const make = (manager = new ShortcutManager({ isMac: false })): { km: Keymap; sm: ShortcutManager } => {
    const km = new Keymap({ isMac: false, chart: manager });
    km.register('Alt+T', () => {}, 'widget', { command: 'tool:trend-line', label: 'Trend line' });
    km.register('Alt+V', () => {}, 'widget', { command: 'tool:vertical-line', label: 'Vertical line' });
    km.register('ArrowLeft', () => false, 'widget', { command: 'nudge-left', layered: true, rebindable: false });
    return { km, sm: manager };
  };

  it('rebinds through the manager with its code-based combos and refuses what the browser keeps', () => {
    const { km, sm } = make();
    expect(km.rebind('chart:fitContent', 'Alt+KeyG').ok).toBe(true);
    expect(sm.handleKey('Alt+KeyG')).toBe('fitContent');
    expect(sm.handleKey('Alt+KeyF')).toBeNull();
    expect(km.chord('chart:fitContent')).toBe('Alt+g');
    expect(km.overrides()).toEqual({ 'chart:fitContent': ['Alt+KeyG'] });
    expect(km.rebind('chart:fitContent', 'Mod+KeyW')).toMatchObject({ ok: false, reason: 'reserved' });
    expect(km.rebind('chart:fitContent', 'Alt+')).toMatchObject({ ok: false, reason: 'invalid' });
    expect(km.rebind('chart:nothing', 'Alt+KeyG')).toMatchObject({ ok: false, reason: 'unknown' });
    const row = km.describe().find((g) => g.group === 'Chart')?.rows.find((r) => r.command === 'chart:fitContent');
    expect(row).toMatchObject({ combo: 'Alt+g', defaultCombo: 'Alt+f', changed: true, rebindable: true });
  });

  it('asks before taking a chord from a widget binding, and a layered one never stands in the way', () => {
    const { km, sm } = make();
    const r = km.rebind('chart:fitContent', 'Alt+KeyT');
    expect(r).toMatchObject({ ok: false, reason: 'taken' });
    expect(r.conflicts.map((c) => c.command)).toEqual(['tool:trend-line']);
    expect(km.rebind('chart:fitContent', 'Alt+KeyT', { replace: true }).ok).toBe(true);
    expect(km.chord('tool:trend-line')).toBe('');
    expect(sm.handleKey('Alt+KeyT')).toBe('fitContent');
    // The nudge declines with nothing selected, so the pan still runs.
    expect(km.rebind('chart:panRight', 'ArrowLeft', { replace: true }).conflicts.map((c) => c.command)).toEqual(['chart:panLeft']);
    expect(sm.handleKey('ArrowLeft')).toBe('panRight');
    expect(km.chord('chart:panLeft')).toBe('');
  });

  it('takes one chord from a command that has several, and leaves it the rest', () => {
    const { km, sm } = make();
    km.register('Alt+Z', () => {}, 'widget', { command: 'zoom-in-alt', label: 'Mine' });
    expect(km.rebind('zoom-in-alt', '=', { replace: true }).conflicts.map((c) => c.command)).toEqual(['chart:zoomIn']);
    expect(sm.list().find((i) => i.command === 'zoomIn')?.combos).toEqual(['Shift+Equal', 'NumpadAdd']);
  });

  it('a widget chord over a chart command is a conflict to replace, and a reset brings the shadow back as it was', () => {
    const { km, sm } = make();
    // The default Alt+V shadows the grid toggle by design; moving the tool frees it.
    expect(km.rebind('tool:vertical-line', 'Alt+Shift+V').ok).toBe(true);
    expect(km.conflicts().filter((c) => c.source === 'chart')).toEqual([]);
    const r = km.rebind('tool:trend-line', 'Alt+V');
    expect(r.conflicts.map((c) => c.command)).toEqual(['chart:toggleGridVert']);
    km.rebind('tool:trend-line', 'Alt+V', { replace: true });
    expect(sm.list().find((i) => i.command === 'toggleGridVert')?.isDisabled).toBe(true);
    km.reset('tool:trend-line');
    // A reset does not stand aside for a chart command: the default shadows it again.
    expect(km.reset('tool:vertical-line').ok).toBe(true);
    expect(km.reset('chart:toggleGridVert').ok).toBe(true);
    expect(sm.handleKey('Alt+KeyV')).toBe('toggleGridVert');
    expect(km.conflicts().filter((c) => c.source === 'chart').map((c) => c.combo)).toEqual(['Alt+v']);
    expect(km.overrides()).toEqual({});
  });

  it('resets to what the host configured, not to the engine default', () => {
    const { km, sm } = make(new ShortcutManager({ isMac: false, overrides: { fitContent: 'Alt+KeyK' } }));
    km.rebind('chart:fitContent', 'Alt+KeyG');
    km.reset('chart:fitContent');
    expect(sm.handleKey('Alt+KeyK')).toBe('fitContent');
    expect(sm.handleKey('Alt+KeyF')).toBeNull();
    expect(km.overrides()).toEqual({});
    km.applyOverrides({ 'chart:fitContent': 'Alt+KeyG', 'chart:screenshot': null });
    expect(sm.handleKey('Alt+KeyG')).toBe('fitContent');
    expect(sm.list().find((i) => i.command === 'screenshot')?.isDisabled).toBe(true);
    km.applyOverrides({});
    expect(sm.handleKey('Alt+KeyK')).toBe('fitContent');
    expect(sm.list().find((i) => i.command === 'screenshot')?.isDisabled).toBe(false);
  });

  it('lists a chart command the user unbound, so it can be reset, and a plain listing cannot rebind', () => {
    const { km } = make();
    km.rebind('chart:screenshot', null);
    const row = km.describe().find((g) => g.group === 'Chart')?.rows.find((r) => r.command === 'chart:screenshot');
    expect(row).toMatchObject({ combo: '', display: '', changed: true });
    const listOnly = new Keymap({ chart: { list: () => new ShortcutManager().list() } });
    expect(listOnly.rebind('chart:fitContent', 'Alt+KeyG')).toMatchObject({ ok: false, reason: 'fixed' });
    expect(listOnly.describe().find((g) => g.group === 'Chart')?.rows[0].rebindable).toBe(false);
  });
});

describe('capture', () => {
  it('hands every press to the recorder ahead of the bindings, and stops it dead', () => {
    const doc = fakeWidgetDocument();
    const el = doc.createElement('div');
    doc.body.appendChild(el);
    const km = new Keymap();
    const bound = vi.fn();
    km.register('Alt+T', bound);
    km.attach(doc as unknown as Document);
    const later = vi.fn();
    // A listener on the same node after the keymap's: the dialog's own Escape.
    doc.addEventListener('keydown', later, true);
    const seen: string[] = [];
    const release = km.capture((e) => { seen.push(e.key); return e.key === 'Tab' ? false : undefined; });
    expect(km.capturing).toBe(true);
    const t = fireKey(el, 't', { altKey: true });
    const esc = fireKey(el, 'Escape');
    expect(seen).toEqual(['t', 'Escape']);
    expect(bound).not.toHaveBeenCalled();
    expect(later).not.toHaveBeenCalled();
    expect(t.defaultPrevented && esc.immediateStopped).toBe(true);
    // Declined: the key goes on as if nothing recorded it.
    const tab = fireKey(el, 'Tab');
    expect(tab.defaultPrevented).toBe(false);
    expect(later).toHaveBeenCalledTimes(1);
    release();
    expect(km.capturing).toBe(false);
    fireKey(el, 't', { altKey: true });
    expect(bound).toHaveBeenCalledTimes(1);
  });

  it('keeps a neighbour on the same document quiet while one keymap records', () => {
    // Two charts on one page, as in a grid: the first attached sees a key
    // first, so it has to stand aside for the second one's recorder.
    const doc = fakeWidgetDocument();
    const el = doc.createElement('div');
    doc.body.appendChild(el);
    const first = new Keymap();
    const second = new Keymap();
    const picked = vi.fn();
    first.register('Alt+H', picked);
    first.attach(doc as unknown as Document);
    second.attach(doc as unknown as Document);
    const seen: string[] = [];
    const release = second.capture((e) => { seen.push(e.key); });
    fireKey(el, 'h', { altKey: true, code: 'KeyH' });
    expect(seen).toEqual(['h']);
    expect(picked).not.toHaveBeenCalled();
    release();
    fireKey(el, 'h', { altKey: true, code: 'KeyH' });
    expect(picked).toHaveBeenCalledTimes(1);
    // A recorder torn down with its keymap does not leave the neighbour quiet.
    second.capture(() => {});
    second.destroy();
    fireKey(el, 'h', { altKey: true, code: 'KeyH' });
    expect(picked).toHaveBeenCalledTimes(2);
    // A keymap on another document is not a neighbour.
    const other = new Keymap();
    const elsewhere = fakeWidgetDocument();
    other.attach(elsewhere as unknown as Document);
    const offOther = other.capture(() => {});
    fireKey(el, 'h', { altKey: true, code: 'KeyH' });
    expect(picked).toHaveBeenCalledTimes(3);
    offOther();
  });
});
