/**
 * Keyboard shortcuts (ARCHITECTURE.md §7). A small, framework-free shortcut
 * manager for the chart: a default keymap wired to real chart actions, combos
 * expressed as physical key codes (layout-independent), rebinding / disabling /
 * custom commands, an alternate preset, hover-vs-global scope, and optional
 * localStorage persistence. Pure and testable - `resolve(event)` and
 * `handleKey(combo)` map input to a command id without needing a real DOM.
 */
import { dispatch } from '../helpers/dispatch';

export type ShortcutScope = 'hover' | 'global';
export type ShortcutPreset = 'default' | 'alt';

export interface KeymapEntry {
  command: string;
  label: string;
  /** Canonical combos that trigger this command. */
  combos: string[];
}

export interface CustomShortcut {
  command: string;
  label?: string;
  combos: string | string[];
  onTrigger: () => void;
}

export interface ShortcutManagerOptions {
  preset?: ShortcutPreset;
  /** Rebind (`string`/`string[]`) or unbind (`null`) a command, still listed. */
  overrides?: Record<string, string | string[] | null>;
  /** Commands to unbind entirely (still listed in `list()`). */
  disabledCommands?: string[];
  customShortcuts?: CustomShortcut[];
  /** `hover` fires while the pointer is over the chart (or it is focused); `global` always. */
  scope?: ShortcutScope;
  /** Persist rebinds/preset to localStorage. */
  persist?: boolean;
  storageKey?: string;
  /** Force platform (⌘ vs Ctrl). Auto-detected when omitted. */
  isMac?: boolean;
}

export interface ShortcutTriggerEvent {
  command: string;
  combo: string;
  isCustom: boolean;
}

interface KeyLike {
  code?: string | undefined;
  key?: string;
  ctrlKey?: boolean | undefined;
  metaKey?: boolean | undefined;
  altKey?: boolean | undefined;
  shiftKey?: boolean | undefined;
}

const MOD_ORDER = ['Mod', 'Ctrl', 'Meta', 'Alt', 'Shift'];
const MOD_SET = new Set(MOD_ORDER);
const MODIFIER_KEYS = new Set([
  'Shift', 'Control', 'Alt', 'Meta', 'OS',
  'ShiftLeft', 'ShiftRight', 'ControlLeft', 'ControlRight',
  'AltLeft', 'AltRight', 'MetaLeft', 'MetaRight', 'OSLeft', 'OSRight',
]);

/** Internal: the chart's key hints read it too. Not part of the package's API. */
export function detectMac(): boolean {
  return typeof navigator !== 'undefined' && /mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent || '');
}

/** Parse a combo string into ordered modifiers + a key code, or null if invalid. */
export function parseCombo(combo: string): { mods: string[]; key: string } | null {
  const parts = combo.split('+').map((p) => p.trim()).filter((p) => p.length > 0);
  if (parts.length === 0) return null;
  const key = parts[parts.length - 1]!; // not empty, checked above
  if (!/^[A-Za-z0-9]+$/.test(key) || MOD_SET.has(key)) return null;
  const mods: string[] = [];
  for (const m of parts.slice(0, -1)) {
    if (!MOD_SET.has(m)) return null;
    if (!mods.includes(m)) mods.push(m);
  }
  mods.sort((a, b) => MOD_ORDER.indexOf(a) - MOD_ORDER.indexOf(b));
  return { mods, key };
}

/** Canonical form of a combo (ordered modifiers), or `''` when invalid. */
export function normalizeCombo(combo: string): string {
  const p = parseCombo(combo);
  return p === null ? '' : [...p.mods, p.key].join('+');
}

export function isValidCombo(combo: string): boolean {
  return normalizeCombo(combo) !== '';
}

const KEY_DISPLAY: Record<string, string> = {
  ArrowLeft: '←', ArrowRight: '→', ArrowUp: '↑', ArrowDown: '↓',
  Equal: '=', Minus: '-', NumpadAdd: '+', NumpadSubtract: '-', Escape: 'Esc', Space: 'Space',
};

function displayKey(key: string): string {
  if (KEY_DISPLAY[key] !== undefined) return KEY_DISPLAY[key];
  if (/^Key[A-Z]$/.test(key)) return key.slice(3);
  if (/^Digit[0-9]$/.test(key)) return key.slice(5);
  return key;
}

/** Platform-aware display string, e.g. `Alt+KeyR` -> `⌥ R` (mac) or `Alt + R`. */
export function formatCombo(combo: string, isMac: boolean = detectMac()): string {
  const p = parseCombo(combo);
  if (p === null) return '';
  const map: Record<string, string> = isMac
    ? { Mod: '⌘', Ctrl: '⌃', Meta: '⌘', Alt: '⌥', Shift: '⇧' }
    : { Mod: 'Ctrl', Ctrl: 'Ctrl', Meta: 'Win', Alt: 'Alt', Shift: 'Shift' };
  const parts = [...p.mods.map((m) => map[m]), displayKey(p.key)];
  return parts.join(isMac ? ' ' : ' + ');
}

/** Build a canonical combo from a keyboard event (`Mod` = ⌘ on mac, Ctrl elsewhere). */
export function eventToCombo(e: KeyLike, isMac: boolean = detectMac()): string {
  const code = e.code ?? e.key ?? '';
  if (code === '' || MODIFIER_KEYS.has(code)) return '';
  const mods: string[] = [];
  if (isMac ? e.metaKey : e.ctrlKey) mods.push('Mod');
  if (isMac && e.ctrlKey) mods.push('Ctrl');
  if (!isMac && e.metaKey) mods.push('Meta');
  if (e.altKey) mods.push('Alt');
  if (e.shiftKey) mods.push('Shift');
  return normalizeCombo([...mods, code].join('+'));
}

// Combos the browser / OS reserve - never bindable.
const RESERVED = new Set([
  'Mod+KeyW', 'Mod+KeyT', 'Mod+KeyN', 'Mod+KeyQ', 'Mod+KeyR', 'Mod+KeyL',
  'Mod+Shift+KeyT', 'Mod+Shift+KeyN', 'Mod+Shift+KeyW',
]);

export function isReservedCombo(combo: string): boolean {
  return RESERVED.has(normalizeCombo(combo));
}

/** The built-in commands and their default bindings. */
export const DEFAULT_KEYMAP: KeymapEntry[] = [
  { command: 'panLeft', label: 'Pan left', combos: ['ArrowLeft'] },
  { command: 'panRight', label: 'Pan right', combos: ['ArrowRight'] },
  { command: 'panLeftFast', label: 'Pan left (fast)', combos: ['Mod+ArrowLeft'] },
  { command: 'panRightFast', label: 'Pan right (fast)', combos: ['Mod+ArrowRight'] },
  { command: 'panUp', label: 'Pan up', combos: ['ArrowUp'] },
  { command: 'panDown', label: 'Pan down', combos: ['ArrowDown'] },
  { command: 'zoomIn', label: 'Zoom in', combos: ['Equal', 'Shift+Equal', 'NumpadAdd'] },
  { command: 'zoomOut', label: 'Zoom out', combos: ['Minus', 'NumpadSubtract'] },
  { command: 'resetScale', label: 'Reset view', combos: ['Home', 'Digit0'] },
  { command: 'fitContent', label: 'Fit all bars', combos: ['Alt+KeyF'] },
  { command: 'screenshot', label: 'Screenshot (PNG)', combos: ['Alt+Shift+KeyS'] },
  { command: 'toggleGridVert', label: 'Toggle vertical grid', combos: ['Alt+KeyV'] },
  { command: 'toggleGridHorz', label: 'Toggle horizontal grid', combos: ['Alt+KeyH'] },
  { command: 'toggleCrosshairMagnet', label: 'Toggle crosshair magnet', combos: ['Alt+KeyM'] },
];

/** Alternate preset - overrides a few default bindings. */
export const ALT_PRESET: Record<string, string[]> = {
  panLeftFast: ['Alt+ArrowLeft'],
  panRightFast: ['Alt+ArrowRight'],
  screenshot: ['Mod+Shift+KeyS'],
};

/** The set of built-in command ids (everything in DEFAULT_KEYMAP). */
export const BUILTIN_COMMANDS: ReadonlySet<string> = new Set(DEFAULT_KEYMAP.map((e) => e.command));

const toArray = (v: string | string[]): string[] => (Array.isArray(v) ? v : [v]);

export interface ShortcutListItem {
  command: string;
  label: string;
  combos: string[];
  isCustom: boolean;
  isDisabled: boolean;
}

export class ShortcutManager {
  public scope: ShortcutScope;
  private readonly _isMac: boolean;
  private readonly _persist: boolean;
  private readonly _storageKey: string;
  private _preset: ShortcutPreset;
  private _overrides: Record<string, string[]> = {};
  private _disabled = new Set<string>();
  private readonly _custom = new Map<string, CustomShortcut>();
  private _entries = new Map<string, KeymapEntry>();
  private _reverse = new Map<string, string>();
  private readonly _listeners = new Set<(e: ShortcutTriggerEvent) => void>();
  private readonly _changes = new Set<() => void>();

  public constructor(options: ShortcutManagerOptions = {}) {
    this.scope = options.scope ?? 'hover';
    this._isMac = options.isMac ?? detectMac();
    this._persist = options.persist ?? false;
    this._storageKey = options.storageKey ?? 'openalgo-charts:shortcuts';
    this._preset = options.preset ?? 'default';

    const applyOverrides = (o: Record<string, string | string[] | null> | undefined): void => {
      for (const [cmd, val] of Object.entries(o ?? {})) {
        if (val === null) { this._disabled.add(cmd); continue; }
        const arr = toArray(val).map(normalizeCombo).filter((c) => c !== '' && !isReservedCombo(c));
        this._overrides[cmd] = arr;
      }
    };
    applyOverrides(options.overrides);
    for (const c of options.disabledCommands ?? []) this._disabled.add(c);
    for (const c of options.customShortcuts ?? []) this._custom.set(c.command, c);

    // Persisted state wins over constructor options for preset/overrides/disabled.
    const saved = this._load();
    if (saved !== null) {
      if (saved.preset !== undefined) this._preset = saved.preset;
      applyOverrides(saved.overrides);
      for (const c of saved.disabled ?? []) this._disabled.add(c);
    }
    this._rebuild();
  }

  private _presetCombos(command: string): string[] | undefined {
    return this._preset === 'alt' ? ALT_PRESET[command] : undefined;
  }

  private _effectiveCombos(command: string, fallback: string[]): string[] {
    if (this._disabled.has(command)) return [];
    if (this._overrides[command] !== undefined) return this._overrides[command];
    return this._presetCombos(command) ?? fallback;
  }

  private _rebuild(): void {
    this._entries = new Map();
    for (const def of DEFAULT_KEYMAP) {
      this._entries.set(def.command, { command: def.command, label: def.label, combos: this._effectiveCombos(def.command, def.combos) });
    }
    for (const c of this._custom.values()) {
      this._entries.set(c.command, {
        command: c.command,
        label: c.label ?? c.command,
        combos: this._effectiveCombos(c.command, toArray(c.combos).map(normalizeCombo).filter((x) => x !== '')),
      });
    }
    this._reverse = new Map();
    for (const entry of this._entries.values()) {
      for (const combo of entry.combos) {
        if (!this._reverse.has(combo)) this._reverse.set(combo, entry.command);
      }
    }
  }

  /** Resolve a keyboard event to a command id (or null). */
  public resolve(event: KeyLike): string | null {
    const combo = eventToCombo(event, this._isMac);
    return combo === '' ? null : (this._reverse.get(combo) ?? null);
  }

  /** Resolve a combo string to a command id (or null). */
  public handleKey(combo: string): string | null {
    return this._reverse.get(normalizeCombo(combo)) ?? null;
  }

  /** Run a custom command's handler (built-ins are executed by the chart). */
  public runCustom(command: string): boolean {
    const c = this._custom.get(command);
    if (c === undefined) return false;
    c.onTrigger();
    this.emitTrigger(command);
    return true;
  }

  public emitTrigger(command: string, combo = ''): void {
    const e: ShortcutTriggerEvent = { command, combo, isCustom: this._custom.has(command) };
    dispatch(this._listeners, e);
  }

  public on(cb: (e: ShortcutTriggerEvent) => void): () => void {
    this._listeners.add(cb);
    return () => this._listeners.delete(cb);
  }

  /**
   * Called after every change to the keymap (a binding set, disabled or reset,
   * a preset, a custom shortcut), so a hint drawn from it can follow. Returns
   * the unsubscriber.
   */
  public onChange(fn: () => void): () => void {
    this._changes.add(fn);
    return () => { this._changes.delete(fn); };
  }

  public setBinding(command: string, combo: string | string[]): boolean {
    const arr = toArray(combo).map(normalizeCombo).filter((c) => c !== '' && !isReservedCombo(c));
    if (arr.length === 0) return false;
    this._overrides[command] = arr;
    this._disabled.delete(command);
    this._after();
    return true;
  }

  public disable(command: string): void {
    this._disabled.add(command);
    delete this._overrides[command];
    this._after();
  }

  public resetBinding(command: string): void {
    delete this._overrides[command];
    this._disabled.delete(command);
    this._after();
  }

  public resetAll(): void {
    this._overrides = {};
    this._disabled.clear();
    this._after();
  }

  public setPreset(preset: ShortcutPreset): void {
    this._preset = preset;
    this._after();
  }

  public addCustom(shortcut: CustomShortcut): void {
    this._custom.set(shortcut.command, shortcut);
    this._after();
  }

  public list(): ShortcutListItem[] {
    return [...this._entries.values()].map((e) => ({
      command: e.command,
      label: e.label,
      combos: e.combos,
      isCustom: this._custom.has(e.command),
      isDisabled: this._disabled.has(e.command),
    }));
  }

  public state(): { preset: ShortcutPreset; overrides: Record<string, string[]>; disabled: string[] } {
    return { preset: this._preset, overrides: this._overrides, disabled: [...this._disabled] };
  }

  private _after(): void {
    this._rebuild();
    this._save();
    for (const fn of [...this._changes]) fn();
  }

  private _save(): void {
    if (!this._persist || typeof localStorage === 'undefined') return;
    try { localStorage.setItem(this._storageKey, JSON.stringify(this.state())); } catch { /* ignore */ }
  }

  private _load(): { preset?: ShortcutPreset; overrides?: Record<string, string[]>; disabled?: string[] } | null {
    if (!this._persist || typeof localStorage === 'undefined') return null;
    try {
      const raw = localStorage.getItem(this._storageKey);
      return raw === null ? null : JSON.parse(raw);
    } catch { return null; }
  }

  /** True when a key event targets a text field and should be ignored. */
  public static shouldIgnore(target: unknown): boolean {
    const t = target as { tagName?: string; isContentEditable?: boolean } | null;
    if (t === null || t === undefined) return false;
    if (t.isContentEditable === true) return true;
    const tag = (t.tagName ?? '').toUpperCase();
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
  }
}
