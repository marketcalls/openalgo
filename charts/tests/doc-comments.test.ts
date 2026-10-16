/**
 * A doc comment sits on the declaration it describes. Two doc blocks in a row
 * attach both to the declaration below them, and the API reference and an
 * editor's hover show only the last, so the first is lost to its own
 * declaration: 2.5.10 slid a helper between commandChord and its doc, and six
 * more had drifted the same way across the tiers. Held over all of src; a
 * file's opening block may precede its first doc.
 */
/// <reference types="vite/client" />
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

type Glob = { glob(pattern: string, options: { query: string; import: string; eager: true }): Record<string, string> };
const SRC = (import.meta as unknown as Glob).glob('../src/**/*.ts', { query: '?raw', import: 'default', eager: true });

function stacked(file: string, text: string): string[] {
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
  const found: string[] = [];
  const visit = (node: ts.Node): void => {
    const docs = (node as { jsDoc?: readonly ts.JSDoc[] }).jsDoc ?? [];
    if (docs.length > 1 && !(node.parent === source && source.statements[0] === node)) {
      found.push(`${file.replace(/^\.\.\//, '')}:${source.getLineAndCharacterOfPosition(node.getStart()).line + 1}`);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

describe('doc comments', () => {
  it('keeps each doc block on its own declaration across src', () => {
    expect(Object.keys(SRC).length).toBeGreaterThan(300);
    expect(Object.entries(SRC).flatMap(([file, text]) => stacked(file, text))).toEqual([]);
  });
});
