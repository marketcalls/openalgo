/**
 * The function length rule. A file cap (tests/line-caps.test.ts) does not
 * bound what a reader must hold when a module is one long mount closure, so
 * no function in src may run past `maxLines` in scripts/function-caps.json,
 * except the ones listed there, each held to its length on the day it was
 * listed. Like the file caps, the list only shrinks: a listed function that
 * comes under the limit, or is gone, must leave it, and a cap is lowered as
 * its function is split, never raised.
 *
 * Measured from the declaration to its closing brace, comments included:
 * function declarations, methods, constructors, accessors, and function
 * expressions bound to a name. A callback written inline is part of the
 * function around it. A function is named by its class, when it has one,
 * and its own name, so `Pane.paintBase` or `mountRail`.
 */
import ts from 'typescript';
import { describe, expect, it } from 'vitest';
import limits from '../scripts/function-caps.json';

type Sources = Record<string, string>;
/** `import.meta.glob`, typed; the suite carries no Vite client globals. */
type Glob = { glob(pattern: string, options: { query: string; import: string; eager: true }): Sources };
// Keys come back as '../src/...'; the caps name files from the package root.
const SOURCES: Sources = Object.fromEntries(
  Object.entries((import.meta as unknown as Glob).glob('../src/**/*.ts', { query: '?raw', import: 'default', eager: true }))
    .map(([key, text]) => [key.replace(/^\.\.\//, ''), text]),
);

const MAX_LINES = limits.maxLines;
const caps: Record<string, Record<string, number>> = limits.caps;

/** The longest function under each name in a file. */
function lengths(path: string): Map<string, number> {
  const source = ts.createSourceFile(path, SOURCES[path]!, ts.ScriptTarget.Latest, true);
  const out = new Map<string, number>();
  const line = (pos: number): number => source.getLineAndCharacterOfPosition(pos).line;
  const visit = (node: ts.Node, owner: string | null): void => {
    let name: string | null = null;
    if ((ts.isFunctionDeclaration(node) || ts.isMethodDeclaration(node) || ts.isConstructorDeclaration(node)
      || ts.isGetAccessor(node) || ts.isSetAccessor(node)) && node.body !== undefined) {
      name = ts.isConstructorDeclaration(node) ? 'constructor' : node.name?.getText(source) ?? '(anonymous)';
    } else if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer !== undefined
      && (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer))) {
      name = node.name.text;
    }
    if (name !== null) {
      const key = owner === null ? name : `${owner}.${name}`;
      const count = line(node.getEnd()) - line(node.getStart(source)) + 1;
      out.set(key, Math.max(out.get(key) ?? 0, count));
    }
    const next = ts.isClassDeclaration(node) && node.name !== undefined ? node.name.text : owner;
    ts.forEachChild(node, child => visit(child, next));
  };
  visit(source, null);
  return out;
}

const measured = new Map(Object.keys(SOURCES).map(path => [path, lengths(path)]));

describe('function length caps', () => {
  it('lists only functions that are still over the limit, each within its cap', () => {
    for (const [path, listed] of Object.entries(caps)) {
      expect(SOURCES[path], `${path} is listed but missing`).toBeTypeOf('string');
      for (const [name, cap] of Object.entries(listed)) {
        const lines = measured.get(path)!.get(name);
        expect(lines, `${path} ${name} is listed but missing: remove it from scripts/function-caps.json`).toBeTypeOf('number');
        expect(lines, `${path} ${name} is under ${MAX_LINES} lines: remove it from scripts/function-caps.json`).toBeGreaterThan(MAX_LINES);
        expect(lines, `${path} ${name} is over its cap: split it`).toBeLessThanOrEqual(cap);
      }
    }
  });

  it('leaves every other function at or under the limit', () => {
    expect(measured.size).toBeGreaterThan(100);
    const over: string[] = [];
    for (const [path, names] of measured) {
      for (const [name, lines] of names) if (lines > MAX_LINES && caps[path]?.[name] === undefined) over.push(`${path} ${name} (${lines})`);
    }
    expect(over).toEqual([]);
  });
});
