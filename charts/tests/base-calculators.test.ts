/**
 * The base entry ships a few calculators (ema, rsi, atr, supertrend) that sit
 * in the indicator tier's folder. The ESLint tier ACL guards the base
 * directories, not these files, so an `import { sma } from './calc'` here would
 * pass lint and pull the lazy tier's kernels into openalgo-charts.mjs. This
 * test is that guard: every indicator module the base entry imports may import
 * only base modules and each other.
 */
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

type Glob = { glob(pattern: string, options: { query: string; import: string; eager: true }): Record<string, string> };
const SRC = (import.meta as unknown as Glob).glob('../src/**/*.ts', { query: '?raw', import: 'default', eager: true });
const LAZY_TIERS = ['indicators', 'draw', 'transform', 'profile', 'trade', 'webgl', 'widget', 'workspace'];

/** Every module specifier a file imports or re-exports, dynamic imports included. */
function specifiers(path: string): string[] {
  const text = SRC[`../src/${path}`];
  if (text === undefined) throw new Error(`no source for ${path}`);
  const source = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true);
  const out: string[] = [];
  const visit = (node: ts.Node): void => {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier
      && ts.isStringLiteral(node.moduleSpecifier)) out.push(node.moduleSpecifier.text);
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
      const arg = node.arguments[0];
      out.push(arg !== undefined && ts.isStringLiteral(arg) ? arg.text : '<dynamic>');
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return out;
}

/** A relative specifier from `path`, as a path under src/ without its extension. */
function resolveFrom(path: string, spec: string): string {
  const parts = path.split('/').slice(0, -1);
  for (const part of spec.split('/')) {
    if (part === '..') parts.pop();
    else if (part !== '.') parts.push(part);
  }
  return parts.join('/');
}

/** The indicator modules the base entry pulls in, by path under src/. */
function baseShipped(): string[] {
  return specifiers('index.ts')
    .filter((s) => s.startsWith('./indicators/'))
    .map((s) => `${s.slice(2)}.ts`);
}

describe('base-shipped calculators', () => {
  it('are the four the base entry re-exports', () => {
    expect(baseShipped().sort()).toEqual(['indicators/atr.ts', 'indicators/ema.ts', 'indicators/rsi.ts', 'indicators/supertrend.ts']);
  });

  it('import only base modules and each other', () => {
    const shipped = new Set(baseShipped());
    const leaks: string[] = [];
    for (const file of shipped) {
      for (const spec of specifiers(file)) {
        if (!spec.startsWith('.')) { leaks.push(`${file} -> ${spec}`); continue; }
        const target = resolveFrom(file, spec);
        if (LAZY_TIERS.includes(target.split('/')[0]!) && !shipped.has(`${target}.ts`)) leaks.push(`${file} -> ${spec}`);
      }
    }
    expect(leaks).toEqual([]);
  });
});
