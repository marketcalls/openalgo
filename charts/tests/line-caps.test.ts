/**
 * The file length rule in eslint.config.js lets the files listed in
 * scripts/line-caps.json stay over the limit, each at no more than its cap.
 * That exemption is meant to shrink: a capped file that has come under the
 * limit must leave the list, or it could grow back to its old size without
 * anything failing.
 */
import { describe, expect, it } from 'vitest';
import limits from '../scripts/line-caps.json';

type Sources = Record<string, string>;
/** `import.meta.glob`, typed; the suite carries no Vite client globals. */
type Glob = { glob(pattern: string, options: { query: string; import: string; eager: true }): Sources };
// Keys come back as '../src/...'; the caps name files from the package root.
const SOURCES: Sources = Object.fromEntries(
  Object.entries((import.meta as unknown as Glob).glob('../src/**/*.ts', { query: '?raw', import: 'default', eager: true }))
    .map(([key, text]) => [key.replace(/^\.\.\//, ''), text]),
);

const MAX_LINES = limits.maxLines;
const caps: Record<string, number> = limits.caps;

/** Lines the way the lint rule counts them: a final newline ends a line, it does not start one. */
function lineCount(path: string): number {
  const lines = SOURCES[path].split(/\r\n|\r|\n/);
  return lines.length > 1 && lines[lines.length - 1] === '' ? lines.length - 1 : lines.length;
}

describe('file length caps', () => {
  it('lists only files that are still over the limit, each within its cap', () => {
    for (const [path, cap] of Object.entries(caps)) {
      expect(SOURCES[path], `${path} is listed but missing`).toBeTypeOf('string');
      const lines = lineCount(path);
      expect(lines, `${path} is under ${MAX_LINES} lines: remove it from scripts/line-caps.json`).toBeGreaterThan(MAX_LINES);
      expect(lines, `${path} is over its cap`).toBeLessThanOrEqual(cap);
    }
  });

  it('leaves every other source file at or under the limit', () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(100);
    const over = Object.keys(SOURCES).filter((path) => !(path in caps) && lineCount(path) > MAX_LINES);
    expect(over).toEqual([]);
  });
});
