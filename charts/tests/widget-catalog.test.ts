/**
 * Every key of the widget's English catalog is shown by some code, or is
 * listed in COMPATIBILITY.md as kept only so host translation catalogs still
 * type-check. A key the UI stopped showing and nobody listed is a translation
 * every host keeps paying for with no date for its removal; 2.5.10 found six
 * such keys from earlier releases and two new ones that nothing ever showed.
 */
/// <reference types="vite/client" />
import ts from 'typescript';
import { describe, expect, it } from 'vitest';
import compatibility from '../COMPATIBILITY.md?raw';

type Sources = Record<string, string>;
const SOURCES = (import.meta as unknown as {
  glob(pattern: string, options: { query: string; import: string; eager: true }): Sources;
}).glob('../src/**/*.ts', { query: '?raw', import: 'default', eager: true });

/** The string members of a union type alias, read with the compiler. */
function members(file: string, alias: string): string[] {
  const source = ts.createSourceFile(file, SOURCES[file], ts.ScriptTarget.Latest, true);
  const decl = source.statements.find((s): s is ts.TypeAliasDeclaration => ts.isTypeAliasDeclaration(s) && s.name.text === alias);
  if (decl === undefined || !ts.isUnionTypeNode(decl.type)) throw new Error(`${alias} is not a union in ${file}`);
  return decl.type.types.flatMap(t => (ts.isLiteralTypeNode(t) && ts.isStringLiteral(t.literal) ? [t.literal.text] : []));
}

/** Every string a source file spells out in code, comments and type positions left out. */
function literals(): Set<string> {
  const out = new Set<string>();
  for (const [file, text] of Object.entries(SOURCES)) {
    const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
    const visit = (node: ts.Node): void => {
      if (ts.isLiteralTypeNode(node)) return;
      if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) out.add(node.text);
      ts.forEachChild(node, visit);
    };
    visit(source);
  }
  return out;
}

describe('the widget message catalog', () => {
  it('holds only keys that some code shows or COMPATIBILITY.md lists as kept for host catalogs', () => {
    const keys = [
      ...members('../src/widget/localization.ts', 'WidgetBuiltinMessage'),
      ...members('../src/widget/grid-text.ts', 'ChartGridMessage'),
    ];
    expect(keys.length).toBeGreaterThan(500);
    const shown = literals();
    const unread = keys.filter(key => !shown.has(key) && !compatibility.includes(`"${key}"`));
    expect(unread).toEqual([]);
  });
});
