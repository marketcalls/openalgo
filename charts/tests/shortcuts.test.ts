import { describe, it, expect, vi } from 'vitest';
import {
  ShortcutManager,
  parseCombo,
  normalizeCombo,
  formatCombo,
  isValidCombo,
  isReservedCombo,
  eventToCombo,
} from '../src/input/shortcuts';

describe('combo parsing / formatting', () => {
  it('parses and canonicalizes modifier order', () => {
    expect(normalizeCombo('Shift+Mod+KeyA')).toBe('Mod+Shift+KeyA');
    expect(normalizeCombo('Alt+KeyR')).toBe('Alt+KeyR');
    expect(parseCombo('Alt+KeyR')).toEqual({ mods: ['Alt'], key: 'KeyR' });
  });

  it('rejects invalid combos', () => {
    expect(isValidCombo('Alt+')).toBe(false);
    expect(isValidCombo('Foo+KeyA')).toBe(false);
    expect(isValidCombo('Shift')).toBe(false); // bare modifier
    expect(normalizeCombo('Ctrl+KeyC?')).toBe('');
  });

  it('formats platform-aware labels', () => {
    expect(formatCombo('Alt+KeyR', false)).toBe('Alt + R');
    expect(formatCombo('Alt+KeyR', true)).toBe('⌥ R');
    // The arrow key prints as the arrow on the key; spelled by code point so
    // this file holds none of the characters the writing rules forbid.
    expect(formatCombo('Mod+ArrowLeft', false)).toBe('Ctrl + \u2190');
    expect(formatCombo('Mod+ArrowLeft', true)).toBe('⌘ \u2190');
    expect(formatCombo('Home', false)).toBe('Home');
  });

  it('builds combos from events (Mod = ⌘ on mac, Ctrl elsewhere)', () => {
    expect(eventToCombo({ code: 'ArrowLeft' }, false)).toBe('ArrowLeft');
    expect(eventToCombo({ code: 'KeyF', altKey: true }, false)).toBe('Alt+KeyF');
    expect(eventToCombo({ code: 'KeyS', ctrlKey: true, shiftKey: true }, false)).toBe('Mod+Shift+KeyS');
    expect(eventToCombo({ code: 'KeyS', metaKey: true, shiftKey: true }, true)).toBe('Mod+Shift+KeyS');
    expect(eventToCombo({ code: 'ShiftLeft', shiftKey: true }, false)).toBe(''); // modifier only
  });

  it('flags reserved combos', () => {
    expect(isReservedCombo('Mod+KeyW')).toBe(true);
    expect(isReservedCombo('Alt+KeyR')).toBe(false);
  });
});

describe('ShortcutManager', () => {
  it('resolves the default keymap', () => {
    const m = new ShortcutManager({ isMac: false });
    expect(m.resolve({ code: 'ArrowLeft' })).toBe('panLeft');
    expect(m.resolve({ code: 'KeyF', altKey: true })).toBe('fitContent');
    expect(m.handleKey('Alt+KeyV')).toBe('toggleGridVert');
    expect(m.resolve({ code: 'KeyR', altKey: true })).toBeNull();
  });

  it('applies overrides and disables', () => {
    const m = new ShortcutManager({ isMac: false, overrides: { panLeft: 'Alt+KeyQ' }, disabledCommands: ['panRight'] });
    expect(m.handleKey('Alt+KeyQ')).toBe('panLeft');
    expect(m.handleKey('ArrowLeft')).toBeNull();
    expect(m.handleKey('ArrowRight')).toBeNull();
    expect(m.list().find((e) => e.command === 'panRight')?.isDisabled).toBe(true);
  });

  it('supports the alt preset', () => {
    const m = new ShortcutManager({ isMac: false, preset: 'alt' });
    expect(m.handleKey('Alt+ArrowLeft')).toBe('panLeftFast');
    expect(m.handleKey('Mod+ArrowLeft')).toBeNull();
    expect(m.handleKey('Mod+Shift+KeyS')).toBe('screenshot');
  });

  it('runs custom shortcuts and emits triggers', () => {
    const onTrigger = vi.fn();
    const seen: string[] = [];
    const m = new ShortcutManager({ isMac: false, customShortcuts: [{ command: 'openPanel', label: 'Open panel', combos: 'Alt+KeyO', onTrigger }] });
    m.on((e) => seen.push(e.command));
    expect(m.resolve({ code: 'KeyO', altKey: true })).toBe('openPanel');
    expect(m.runCustom('openPanel')).toBe(true);
    expect(onTrigger).toHaveBeenCalledOnce();
    expect(seen).toContain('openPanel');
  });

  it('rebinds live and rejects reserved combos', () => {
    const m = new ShortcutManager({ isMac: false });
    expect(m.setBinding('panLeft', 'Alt+KeyQ')).toBe(true);
    expect(m.handleKey('Alt+KeyQ')).toBe('panLeft');
    expect(m.setBinding('panLeft', 'Mod+KeyW')).toBe(false); // reserved
    m.resetAll();
    expect(m.handleKey('ArrowLeft')).toBe('panLeft');
  });

  it('ignores key events targeting text fields', () => {
    expect(ShortcutManager.shouldIgnore({ tagName: 'INPUT' })).toBe(true);
    expect(ShortcutManager.shouldIgnore({ isContentEditable: true })).toBe(true);
    expect(ShortcutManager.shouldIgnore({ tagName: 'DIV' })).toBe(false);
    expect(ShortcutManager.shouldIgnore(null)).toBe(false);
  });
});
