/**
 * The unused-export gate (CLAUDE.md, Quality gates: Surface).
 *
 *   node scripts/check-unused-exports.mjs [--verbose]
 *
 * An export of a tier entry (the tsconfig.json paths) is public, and so is
 * anything an entry re-exports, through any chain of re-exports. Every other
 * export of a module under src/ has to be used by some file other than its
 * own. A use is any reference the repository's own TypeScript resolves to
 * the exported declaration, from src or from a test: by name, through a
 * namespace or a dynamic import, by destructuring or an object shorthand. A
 * re-export is a door, not a use, and so is an import nothing reads.
 *
 * - An export nothing uses fails. The ones the tree already had when the gate
 *   arrived are listed in scripts/unused-exports.json; a listed one that is
 *   used again or gone fails too, so that list only shrinks.
 * - An export only tests use passes: the test pins behaviour a later change
 *   must keep.
 * - An export used only in its own file passes, and is counted: its export
 *   keyword is surplus, which --verbose lists.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import process from 'node:process';
import { pathToFileURL } from 'node:url';
import ts from 'typescript';

const ROOT = resolve(import.meta.dirname, '..');
const ALLOWLIST = join(ROOT, 'scripts', 'unused-exports.json');
/** Where the tests live that may use a module directly: the unit and e2e suites, the engine integration and the demo's own suite. */
const REFERENCES = ['tests', 'integration', 'examples/yfinance/tests'];

const slash = (p) => p.replace(/\\/g, '/');

function walk(dir, pattern) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p, pattern));
    else if (pattern.test(name)) out.push(slash(p));
  }
  return out;
}

/**
 * The exports of modules under `root/src` that are not public, sorted into
 * those nothing uses, those only a test uses and those only their own file
 * uses, each as `file name`, with the count of all exports and of public ones.
 */
export function findUnusedExports(root, { references = REFERENCES, tsconfig = 'tsconfig.json' } = {}) {
  const config = ts.getParsedCommandLineOfConfigFile(join(root, tsconfig), {}, {
    ...ts.sys,
    onUnRecoverableConfigFileDiagnostic: (d) => { throw new Error(ts.flattenDiagnosticMessageText(d.messageText, '\n')); },
  });
  const sources = walk(join(root, 'src'), /\.m?ts$/);
  const tests = references.flatMap((dir) => walk(join(root, dir), /\.(m?ts|m?js)$/));
  const program = ts.createProgram({
    rootNames: [...sources, ...tests],
    // The demo's suite is JavaScript; it is read for its references only.
    options: { ...config.options, noEmit: true, allowJs: true, checkJs: false, allowImportingTsExtensions: true },
  });
  const checker = program.getTypeChecker();
  const rel = (p) => slash(relative(root, p));
  const origin = (symbol) => {
    let s = symbol;
    for (let i = 0; s && (s.flags & ts.SymbolFlags.Alias) && i < 16; i++) s = checker.getAliasedSymbol(s);
    return s;
  };

  const entries = new Set(Object.values(config.options.paths ?? {}).flat()
    .map((p) => slash(resolve(config.options.pathsBasePath ?? root, p))));
  const publicSymbols = new Set();
  for (const entry of entries) {
    const module = checker.getSymbolAtLocation(program.getSourceFile(entry));
    for (const s of checker.getExportsOfModule(module)) publicSymbols.add(origin(s));
  }

  // Every file that uses each symbol.
  const users = new Map();
  const use = (symbol, file) => {
    const s = origin(symbol);
    if (!s) return;
    if (!users.has(s)) users.set(s, new Set());
    users.get(s).add(file);
  };
  const inTree = new Set([...sources, ...tests]);
  for (const source of program.getSourceFiles()) {
    if (!inTree.has(slash(source.fileName))) continue;
    const file = rel(source.fileName);
    const visit = (node) => {
      // A re-export passes a name on and an import binds one; neither reads it.
      if (ts.isExportSpecifier(node) || ts.isImportClause(node)) return;
      if (ts.isIdentifier(node)) {
        const parent = node.parent;
        if (ts.isBindingElement(parent) && parent.name === node && parent.propertyName === undefined && ts.isObjectBindingPattern(parent.parent)) {
          // `const { name } = await import('./x')`: the name is a local, the property it reads is the export.
          const property = checker.getTypeAtLocation(parent.parent).getProperty(node.text);
          if (property) use(property, file);
        } else if (ts.isShorthandPropertyAssignment(parent)) {
          const value = checker.getShorthandAssignmentValueSymbol(parent);
          if (value) use(value, file);
        } else {
          const symbol = checker.getSymbolAtLocation(node);
          const declares = symbol?.declarations?.some((d) => d.name === node) ?? false;
          if (symbol && !declares) use(symbol, file);
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
  }

  const out = { total: 0, public: 0, unused: [], testOnly: [], localOnly: [] };
  for (const path of sources) {
    if (entries.has(path)) continue;
    const source = program.getSourceFile(path);
    const module = source && checker.getSymbolAtLocation(source);
    if (!module) continue;
    const file = rel(path);
    for (const exported of checker.getExportsOfModule(module)) {
      const s = origin(exported);
      // An export is reported where it is declared, not at every barrel it passes through.
      if (!s?.declarations?.some((d) => slash(d.getSourceFile().fileName) === path)) continue;
      out.total++;
      if (publicSymbols.has(s)) { out.public++; continue; }
      const others = [...(users.get(s) ?? [])].filter((f) => f !== file);
      if (others.some((f) => f.startsWith('src/'))) continue;
      const row = `${file} ${exported.name}`;
      if (others.length > 0) out.testOnly.push(row);
      else if (users.get(s)?.has(file)) out.localOnly.push(row);
      else out.unused.push(row);
    }
  }
  for (const list of [out.unused, out.testOnly, out.localOnly]) list.sort();
  return out;
}

/** An unused export missing from the allowlist, and a listed one that is no longer unused. */
export function allowlistProblems(unused, allowed) {
  const listed = new Set(allowed);
  const found = new Set(unused);
  return [
    ...unused.filter((row) => !listed.has(row)).map((row) => `${row} is exported and nothing uses it: delete it, or drop the export keyword if its own file uses it.`),
    ...allowed.filter((row) => !found.has(row)).map((row) => `${row} is listed in scripts/unused-exports.json but is used or gone now: take it off the list.`),
  ];
}

function main() {
  const verbose = process.argv.includes('--verbose');
  const started = Date.now();
  const found = findUnusedExports(ROOT);
  const { allowed } = JSON.parse(readFileSync(ALLOWLIST, 'utf8'));
  const problems = allowlistProblems(found.unused, allowed);
  const seconds = ((Date.now() - started) / 1000).toFixed(1);
  console.log(`check-unused-exports: ${found.total} exports outside the tier entries, ${found.public} public; `
    + `${found.unused.length} used by nothing (${allowed.length} listed), ${found.testOnly.length} only by tests, `
    + `${found.localOnly.length} only in their own file (${seconds}s)`);
  if (verbose) {
    for (const [label, rows] of [['used by nothing', found.unused], ['only tests', found.testOnly], ['only their own file', found.localOnly]]) {
      console.log(`  ${label}:`);
      for (const row of rows) console.log(`    ${row}`);
    }
  }
  if (problems.length > 0) {
    for (const p of problems) console.error(`FAIL: ${p}`);
    process.exit(1);
  }
}

if (process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href) main();
