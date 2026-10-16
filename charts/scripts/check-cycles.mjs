/**
 * The import-cycle gate (CLAUDE.md, Quality gates: Structure).
 *
 *   node scripts/check-cycles.mjs [--verbose]
 *
 * Reads every module under src/ with the repository's own TypeScript and
 * builds the import graph, resolving each specifier the way the compiler does
 * (tsconfig.json paths included, so a tier's `import ... from
 * 'openalgo-charts'` is an edge to src/index.ts). Each import is one of:
 *
 * - runtime: a value import, a re-export, a side-effect import, or an import
 *   whose names are all marked `type` inline. verbatimModuleSyntax emits that
 *   last one as an empty import, which still loads the module, so it can
 *   still close a loop in module evaluation order.
 * - type: `import type`, `export type`, and `import('x').T` in a type. All
 *   are erased.
 * - dynamic: `import()` at run time. Neither graph holds it: the module it
 *   loads runs after the importer has finished loading.
 *
 * Module augmentations (`declare module 'openalgo-charts'`) are not edges.
 *
 * The gate: there is no runtime cycle at all, and the strongly connected
 * components of the graph with type imports added may not grow. Their sizes,
 * largest first, are held in scripts/import-cycles.json; a new component, or
 * a component larger than the one at its rank, fails. So does a list left
 * above what the tree measures, so that it is lowered in the change that
 * breaks a loop and only ever shrinks. An import that does not resolve fails
 * too, because the edge it drops could be the one that closes a loop.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import process from 'node:process';
import { pathToFileURL } from 'node:url';
import ts from 'typescript';

const ROOT = resolve(import.meta.dirname, '..');
const RATCHET = join(ROOT, 'scripts', 'import-cycles.json');

const RUNTIME = new Set(['value', 'inline-type']);
const TYPE_INCLUSIVE = new Set(['value', 'inline-type', 'type']);

const slash = (p) => p.replace(/\\/g, '/');

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else if (/\.m?ts$/.test(name)) out.push(slash(p));
  }
  return out;
}

/** The kind of an import or re-export declaration. */
function declarationKind(node) {
  const isImport = ts.isImportDeclaration(node);
  const clause = isImport ? node.importClause : node;
  if (clause?.isTypeOnly) return 'type';
  const named = isImport ? clause?.namedBindings : node.exportClause;
  const names = named && (ts.isNamedImports(named) || ts.isNamedExports(named)) ? named.elements : [];
  const onlyTypes = names.length > 0 && names.every((e) => e.isTypeOnly) && !(isImport && clause?.name);
  return onlyTypes ? 'inline-type' : 'value';
}

/** Every import edge between modules under `root/dir`, paths relative to `root`. */
function importGraph(root, dir, tsconfig) {
  const config = ts.getParsedCommandLineOfConfigFile(join(root, tsconfig), {}, {
    ...ts.sys,
    onUnRecoverableConfigFileDiagnostic: (d) => { throw new Error(ts.flattenDiagnosticMessageText(d.messageText, '\n')); },
  });
  const files = walk(join(root, dir));
  const known = new Set(files);
  const rel = (p) => slash(relative(root, p));
  const edges = [];
  const unresolved = [];
  for (const file of files) {
    const source = ts.createSourceFile(file, readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true);
    const add = (specifier, kind, node) => {
      const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
      const target = ts.resolveModuleName(specifier, file, config.options, ts.sys).resolvedModule?.resolvedFileName;
      if (target === undefined) unresolved.push(`${rel(file)}:${line} ${specifier}`);
      // A file outside the tree (package.json, a dependency) is no part of a loop.
      else if (known.has(slash(target))) edges.push({ from: rel(file), to: rel(target), kind, line });
    };
    const visit = (node) => {
      if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) {
        add(node.moduleSpecifier.text, declarationKind(node), node);
      } else if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
        const [arg] = node.arguments;
        if (arg && ts.isStringLiteralLike(arg)) add(arg.text, 'dynamic', node);
      } else if (ts.isImportTypeNode(node) && ts.isLiteralTypeNode(node.argument) && ts.isStringLiteral(node.argument.literal)) {
        add(node.argument.literal.text, 'type', node);
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
  }
  return { modules: files.map(rel), edges, unresolved };
}

/** Strongly connected components with more than one module, or a module importing itself (Tarjan). */
function components(modules, edges, kinds) {
  const next = new Map(modules.map((m) => [m, new Set()]));
  for (const e of edges) if (kinds.has(e.kind)) next.get(e.from).add(e.to);
  let counter = 0;
  const index = new Map();
  const low = new Map();
  const stack = [];
  const onStack = new Set();
  const out = [];
  const connect = (v) => {
    index.set(v, counter); low.set(v, counter); counter++;
    stack.push(v); onStack.add(v);
    for (const w of next.get(v)) {
      if (!index.has(w)) { connect(w); low.set(v, Math.min(low.get(v), low.get(w))); }
      else if (onStack.has(w)) low.set(v, Math.min(low.get(v), index.get(w)));
    }
    if (low.get(v) !== index.get(v)) return;
    const component = [];
    let w;
    do { w = stack.pop(); onStack.delete(w); component.push(w); } while (w !== v);
    if (component.length > 1 || next.get(v).has(v)) out.push(component.sort());
  };
  for (const m of modules) if (!index.has(m)) connect(m);
  // Largest first, then by first module, so a report reads the same every run.
  return out.sort((a, b) => b.length - a.length || (a[0] < b[0] ? -1 : 1));
}

/**
 * The modules under `root/dir` and their imports, the runtime and the
 * type-inclusive cycles among them (each a sorted list of paths relative to
 * `root`), and every import that did not resolve, as `file:line specifier`.
 */
export function measureCycles(root, { dir = 'src', tsconfig = 'tsconfig.json' } = {}) {
  const { modules, edges, unresolved } = importGraph(root, dir, tsconfig);
  return {
    modules,
    edges,
    unresolved,
    runtime: components(modules, edges, RUNTIME),
    typeInclusive: components(modules, edges, TYPE_INCLUSIVE),
  };
}

/**
 * What is wrong with the type-inclusive component sizes against the ratchet:
 * a new component, or one larger than the ratchet's at the same rank (largest
 * first), is growth; a ratchet above what was measured has to be lowered.
 */
export function ratchetProblems(sizes, ratchet) {
  const measured = [...sizes].sort((a, b) => b - a);
  const held = [...ratchet].sort((a, b) => b - a);
  const list = (xs) => `[${xs.join(', ')}]`;
  if (measured.length > held.length || measured.some((n, i) => n > held[i])) {
    return [`type-inclusive import cycles grew to ${list(measured)} against the ratchet ${list(held)}. Break the new loop: `
      + 'import the type from the module that declares it, or move it to a module both sides import.'];
  }
  if (measured.length < held.length || measured.some((n, i) => n < held[i])) {
    return [`type-inclusive import cycles shrank to ${list(measured)}: lower "typeInclusive" in scripts/import-cycles.json to match, so they cannot grow back.`];
  }
  return [];
}

function main() {
  const verbose = process.argv.includes('--verbose');
  const started = Date.now();
  const measured = measureCycles(ROOT);
  const { typeInclusive: ratchet } = JSON.parse(readFileSync(RATCHET, 'utf8'));
  const sizes = measured.typeInclusive.map((c) => c.length);
  const inside = (component, kinds) => {
    const set = new Set(component);
    return measured.edges.filter((e) => kinds.has(e.kind) && set.has(e.from) && set.has(e.to))
      .map((e) => `${e.from}:${e.line} -> ${e.to} (${e.kind})`);
  };
  const problems = measured.unresolved.map((u) => `unresolved import ${u}`);
  for (const component of measured.runtime) {
    problems.push(`runtime import cycle through ${component.length} modules:\n    ${inside(component, RUNTIME).join('\n    ')}`);
  }
  problems.push(...ratchetProblems(sizes, ratchet));
  const seconds = ((Date.now() - started) / 1000).toFixed(1);
  console.log(`check-cycles: ${measured.modules.length} modules, ${measured.edges.length} imports; runtime cycles ${measured.runtime.length}; `
    + `type-inclusive components [${sizes.join(', ')}], ratchet [${ratchet.join(', ')}] (${seconds}s)`);
  if (verbose) {
    for (const c of measured.typeInclusive) console.log(`  ${c.length} modules:\n    ${c.length > 12 ? `${c.slice(0, 12).join(', ')}, ...` : c.join(', ')}`);
  }
  if (problems.length > 0) {
    for (const p of problems) console.error(`FAIL: ${p}`);
    process.exit(1);
  }
}

if (process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href) main();
