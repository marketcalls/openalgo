/**
 * The package's two doors besides `import`, held to the ESM build they mirror.
 * Runs after `build` in `npm run verify`.
 *
 * The script-tag build (rollup.config.js) is nine classic scripts that fill
 * one `OpenAlgoCharts` global, a key per tier. Nothing else ties their names
 * to the declarations a host reads, so this runs them in page order in a
 * fresh global and requires each tier's keys to equal the runtime exports its
 * `.d.ts` declares. It then requires the registries they filled to hold what
 * the ESM tiers register, which fails if a tier file carried a private base
 * of its own, and runs a tier ahead of what it needs to see it refuse by name.
 *
 * There is no CommonJS build: a second copy of the code would carry a second
 * registry of chart types, indicators, drawing tools, render backends and
 * widget dialogs. Each export's `default` condition points `require()` at the
 * same ESM file, so on a Node that can require ESM, `require()` must return
 * the very module `import` returns, and on one that cannot, it must fail with
 * Node's ERR_REQUIRE_ESM, whose message names `import()`, rather than with
 * "not exported".
 */
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import ts from 'typescript';

const PKG = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
const at = (rel) => new URL(`../${rel.replace(/^\.\//, '')}`, import.meta.url);
const path = (rel) => decodeURIComponent(at(rel).pathname).replace(/^\/([A-Za-z]:)/, '$1');

/** Each tier, from package.json exports: its specifier, key, declarations, ESM and script files. */
const TIERS = Object.entries(PKG.exports).map(([sub, entry]) => ({
  specifier: sub === '.' ? PKG.name : `${PKG.name}/${sub.slice(2)}`,
  key: sub === '.' ? null : sub.slice(2),
  types: entry.types,
  esm: entry.import,
  script: entry.import.replace(/\.mjs$/, '.standalone.js'),
}));

/**
 * Names a tier's `.d.ts` declares as values although its source exports them
 * with `export type`, so no build has them at run time: the declaration
 * bundler drops the `type` modifier from a class. A host's `new DataLayer()`
 * therefore type-checks and then fails. Listed so the check can hold the rest
 * exactly; an entry that stops being true fails, so the list only shrinks.
 */
const DECLARED_NOT_EXPORTED = {
  [PKG.name]: ['DataLayer'],
  [`${PKG.name}/webgl`]: ['ColorCache', 'VertexBatch'],
};

const failures = [];
const fail = (message) => failures.push(message);

/** The value exports of every tier's `.d.ts`, resolving re-exports through to what they name. */
function declaredValues() {
  const files = TIERS.map((t) => path(t.types));
  const program = ts.createProgram(files, {
    noEmit: true,
    types: [],
    module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler,
    // A tier's declarations import the others by specifier; resolve them to dist.
    paths: { [PKG.name]: [path('dist/index.d.ts')], [`${PKG.name}/*`]: [path('dist/*/index.d.ts')] },
  });
  const checker = program.getTypeChecker();
  const out = new Map();
  TIERS.forEach((tier, i) => {
    const source = program.getSourceFile(files[i]);
    if (!source) { fail(`${tier.types} is missing. Did the build run?`); return; }
    const names = [];
    for (const symbol of checker.getExportsOfModule(checker.getSymbolAtLocation(source))) {
      const decl = symbol.declarations?.[0];
      if (decl && ts.isExportSpecifier(decl) && (decl.isTypeOnly || decl.parent.parent.isTypeOnly)) continue;
      const target = symbol.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(symbol) : symbol;
      if (target.flags & ts.SymbolFlags.Value) names.push(symbol.name);
    }
    out.set(tier.specifier, names);
  });
  return out;
}

/** A fresh global, the way a page starts, with the one platform object a tier reads while loading. */
const freshPage = () => vm.createContext({ crypto: globalThis.crypto });
const runScript = (page, tier) => vm.runInContext(readFileSync(at(tier.script), 'utf8'), page, { filename: tier.script });

function sameSet(label, actual, expected) {
  const have = new Set(actual);
  const want = new Set(expected);
  const missing = expected.filter((k) => !have.has(k));
  const extra = actual.filter((k) => !want.has(k));
  if (missing.length) fail(`${label} lacks ${missing.length} declared export(s): ${missing.join(', ')}`);
  if (extra.length) fail(`${label} has ${extra.length} undeclared key(s): ${extra.join(', ')}`);
}

// 1. Each global key set equals its tier's declared runtime exports.
const declared = declaredValues();
const page = freshPage();
for (const tier of TIERS) {
  try { runScript(page, tier); } catch (error) { fail(`${tier.script} did not load in page order: ${error.message}`); }
}
const onPage = page.OpenAlgoCharts;
const tierKeys = TIERS.filter((t) => t.key).map((t) => t.key);
const complete = onPage !== undefined && tierKeys.every((k) => onPage[k] !== undefined);
let names = 0;
if (onPage === undefined) fail('the base script defined no OpenAlgoCharts global');
else {
  for (const tier of TIERS) {
    const known = DECLARED_NOT_EXPORTED[tier.specifier] ?? [];
    const values = declared.get(tier.specifier) ?? [];
    for (const name of known) {
      if (!values.includes(name)) fail(`${tier.types} no longer declares ${name} as a value: drop it from DECLARED_NOT_EXPORTED`);
    }
    const expected = values.filter((name) => !known.includes(name));
    const object = tier.key ? onPage[tier.key] : onPage;
    if (object === undefined) { fail(`OpenAlgoCharts.${tier.key} is missing after ${tier.script}`); continue; }
    const keys = Object.keys(object).filter((k) => tier.key || !tierKeys.includes(k));
    for (const name of known) {
      if (keys.includes(name)) fail(`${tier.script} now exports ${name}: drop it from DECLARED_NOT_EXPORTED`);
    }
    sameSet(tier.key ? `OpenAlgoCharts.${tier.key}` : 'OpenAlgoCharts', keys, expected);
    names += keys.length;
  }
  // A base export named like a tier would be overwritten when that tier loads.
  const shadowed = tierKeys.filter((k) => (declared.get(PKG.name) ?? []).includes(k));
  if (shadowed.length) fail(`the base exports ${shadowed.join(', ')}, which the tier files of that name overwrite on the global`);
}

// 2. The registries the script-tag tiers filled are the base's own.
const esm = Object.fromEntries(await Promise.all(TIERS.map(async (t) => [t.key ?? 'base', await import(at(t.esm).href)])));
if (complete) {
  const counts = (base, draw, widget) => ({
    indicators: base.registeredIndicators().length,
    chartTypes: base.registeredChartTypes().length,
    renderBackends: base.registeredRenderBackends().join(' '),
    drawingTools: draw.registeredDrawingTools().length,
    widgetDialogs: widget.registeredWidgetDialogs().length,
  });
  const fromModules = counts(esm.base, esm.draw, esm.widget);
  const fromScripts = counts(onPage, onPage.draw, onPage.widget);
  for (const [what, want] of Object.entries(fromModules)) {
    if (fromScripts[what] !== want) fail(`the script-tag build registers ${fromScripts[what]} ${what}, the ESM build ${want}`);
  }
  if (onPage.trade.TradingCapabilityError !== onPage.TradingCapabilityError) {
    fail('OpenAlgoCharts.trade.TradingCapabilityError is not the base constructor');
  }
}

// 3. A tier loaded before what it reads refuses, naming the files to load first.
const refusal = (loaded, tier) => {
  const early = freshPage();
  try { for (const t of [...loaded, tier]) runScript(early, t); return null; } catch (error) { return error.message; }
};
const byKey = (key) => TIERS.find((t) => t.key === key);
const base = TIERS.find((t) => !t.key);
const refusals = [
  [[], byKey('indicators'), 'openalgo-charts.indicators.standalone.js needs openalgo-charts.standalone.js loaded before it'],
  [[base], byKey('widget'), 'openalgo-charts.widget.standalone.js needs openalgo-charts.standalone.js and openalgo-charts.draw.standalone.js loaded before it'],
];
for (const [loaded, tier, message] of refusals) {
  const got = refusal(loaded, tier);
  if (got !== message) fail(`${tier.script} out of order said ${JSON.stringify(got)}, not ${JSON.stringify(message)}`);
}

// 4. require() returns the import instance, or fails the way Node documents.
const require = createRequire(import.meta.url);
const canRequireEsm = process.features.require_module === true;
for (const tier of TIERS) {
  let viaRequire;
  try { viaRequire = require(tier.specifier); } catch (error) {
    if (!canRequireEsm && error.code === 'ERR_REQUIRE_ESM') continue;
    fail(`require('${tier.specifier}') failed: ${error.code ?? ''} ${error.message.split('\n')[0]}`);
    continue;
  }
  if (viaRequire !== await import(tier.specifier) || viaRequire !== esm[tier.key ?? 'base']) {
    fail(`require('${tier.specifier}') returned another module than import`);
  }
}

if (failures.length) {
  for (const message of failures) console.error(`check-exports: ${message}`);
  process.exit(1);
}
console.log(`check-exports: ${TIERS.length} script-tag files carry the ${names} declared exports and the base registries; `
  + (canRequireEsm
    ? `require() of ${TIERS.length} specifiers returns the import instance`
    : `this Node ${process.version} cannot require ESM, so require() was checked to fail with ERR_REQUIRE_ESM`));
