/**
 * The widget's sources read from the top: a module's header comment is its
 * first line, and no comment carries a merge note for the agents of a past
 * release ("Hook (chart grid, 2.5.10): ..."), which says where a line came
 * from rather than why it is there, and once reached the API reference.
 */
/// <reference types="vite/client" />
import { describe, expect, it } from 'vitest';

const SOURCES = (import.meta as unknown as {
  glob(pattern: string, options: { query: string; import: string; eager: true }): Record<string, string>;
}).glob('../src/widget/**/*.ts', { query: '?raw', import: 'default', eager: true });

describe('the widget sources', () => {
  it('put a module header before the imports', () => {
    const late = Object.entries(SOURCES).filter(([, text]) => /^import [^\n]*\n\/\*\*/.test(text)).map(([file]) => file);
    expect(late).toEqual([]);
  });

  it('carry no merge notes', () => {
    const noted = Object.entries(SOURCES).filter(([, text]) => /Hook \(|Bottom bar hook/.test(text)).map(([file]) => file);
    expect(noted).toEqual([]);
  });
});
