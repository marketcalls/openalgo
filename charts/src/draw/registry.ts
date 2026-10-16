/**
 * The drawing-tool registry. Same philosophy as the chart-type and indicator
 * registries: a tool is a descriptor, the layer just runs it, and
 * `registerDrawingTool` makes a custom one first-class. The built-ins are
 * listed and registered in tools.ts; everything that only needs to look a
 * tool up imports this module, not the catalogue.
 */
import type { DrawingTool } from './types';
import { type SettingsSchema, LINE_FIELDS, composeSettings } from './schema';

const registry = new Map<string, DrawingTool>();

export function registerDrawingTool(tool: DrawingTool): void {
  registry.set(tool.id, tool);
}

export function getDrawingTool(id: string): DrawingTool {
  const t = registry.get(id);
  if (t === undefined) throw new Error(`openalgo-charts: unknown drawing tool "${id}"`);
  return t;
}

export function hasDrawingTool(id: string): boolean {
  return registry.has(id);
}

/** Whether a registered tool can be anchored to the viewport (`DrawingTool.viewport`). */
export function viewportDrawingTool(id: string): boolean {
  return registry.get(id)?.viewport === true;
}

export function registeredDrawingTools(): DrawingTool[] {
  return Array.from(registry.values());
}

/** Keyboard event fields a shortcut is matched against. */
export interface ShortcutEvent {
  key: string;
  /** The physical key (`KeyT`): under Alt it names the letter when `key` is not one, as macOS Option types a symbol. Since 2.5.10. */
  code?: string;
  altKey?: boolean;
  ctrlKey?: boolean;
  metaKey?: boolean;
  shiftKey?: boolean;
}

/** `'Shift+Alt+F'` -> its parts, for comparison against an event. */
function parseShortcut(spec: string): { key: string; alt: boolean; ctrl: boolean; shift: boolean } {
  const parts = spec.split('+').map((p) => p.trim().toLowerCase());
  const key = parts[parts.length - 1] ?? '';
  return { key, alt: parts.includes('alt'), ctrl: parts.includes('ctrl') || parts.includes('control'), shift: parts.includes('shift') };
}

/**
 * The id of the tool whose `shortcut` matches this key event, or `null`.
 *
 * Pure, so a host can bind one `keydown` listener and decide for itself when
 * shortcuts apply. The library installs no listener, because only the host
 * knows whether the chart has focus, a dialog is open, or the user is typing.
 *
 * Modifiers must match exactly: `Alt+T` will not fire for `Ctrl+Alt+T`, so a
 * tool shortcut cannot shadow a browser or host chord. `metaKey` (Cmd) is
 * treated as Ctrl, which is what a Mac user expects.
 */
export function matchDrawingShortcut(e: ShortcutEvent): string | null {
  // Option+T types a dagger on macOS, where the physical key still says T; a
  // letter typed wins, so a non-QWERTY layout keeps its own letters.
  const typed = e.key ?? '', letter = e.altKey === true && !/^[a-z]$/i.test(typed) ? /^Key([A-Z])$/.exec(e.code ?? '') : null;
  const key = (letter !== null ? letter[1]! : typed).toLowerCase(); // the one group is in every match
  if (key === '') return null;
  const alt = e.altKey === true;
  const ctrl = e.ctrlKey === true || e.metaKey === true;
  const shift = e.shiftKey === true;
  // A bare letter is never a shortcut: it would swallow ordinary typing.
  if (!alt && !ctrl) return null;
  for (const tool of registry.values()) {
    if (tool.shortcut === undefined) continue;
    const want = parseShortcut(tool.shortcut);
    if (want.key === key && want.alt === alt && want.ctrl === ctrl && want.shift === shift) {
      return tool.id;
    }
  }
  return null;
}

/**
 * Every registered tool that has a shortcut, as `id -> shortcut`. Built as
 * entries, so an id such as `__proto__` is a key like any other rather than an
 * assignment to the object's prototype.
 */
export function drawingShortcuts(): Record<string, string> {
  return Object.fromEntries(Array.from(registry.values(), tool => [tool.id, tool.shortcut])
    .filter((entry): entry is [string, string] => entry[1] !== undefined));
}

/** Colour, width and dash: the least any tool drawn through `applyStroke` honours. */
export const LINE_SETTINGS: SettingsSchema = composeSettings([LINE_FIELDS]);

/**
 * The settings a host may show for a tool: the tool's own declaration, else
 * the line fields, which every stroked custom tool reads. This is a registry
 * lookup, which is why it lives here and not in schema.ts: that module stays
 * free of any import that could loop back into this one.
 */
export function drawingSettingsSchema(toolId: string): SettingsSchema {
  return registry.get(toolId)?.settings ?? LINE_SETTINGS;
}
