/**
 * Guard the tier type declarations against re-inlining shared types.
 *
 * Each tier is bundled into its own `.d.ts`. If a tier imports a shared type
 * through a *relative* path, the bundler inlines the declaration, and because
 * the core classes carry private members, TypeScript treats that copy as a
 * different type. The symptom is brutal and silent: a consumer doing
 *
 *   const chart = createChart(el);
 *   new DrawingController(chart);
 *
 * gets "Types have separate declarations of a private property '_container'",
 * with no way to fix it from outside the package. The tiers must import shared
 * types from the package entry, which tier builds leave external.
 *
 * The widget adds a second seam of the same shape one level up: it builds on
 * the draw tier, so a `DrawingController` inlined into its declarations is a
 * different class from the one `openalgo-charts/draw` exports, and
 * `widget.draw` stops being assignable to a host's own controller variable.
 *
 * Last, a host compiles against the built declarations, so the draw tier's
 * events on the chart bus are known to arrive typed, and every declaration
 * holds for a host that compiles as strictly as the library does (see the
 * notes at the end).
 *
 * Runs after `build` in `npm run verify`.
 */
import { readFileSync, existsSync } from 'node:fs';
import process from 'node:process';
import ts from 'typescript';

/** Declarations that must never appear in any tier's bundle. */
const FORBIDDEN = [
  'declare class Chart',
  'declare class TimeScale',
  'declare class PriceScale',
  'declare class DataLayer',
  'declare class TradingCapabilityError',
];

/**
 * Tier declaration files, each with the further declarations it must not carry
 * because another tier owns them. The draw tier legitimately declares its
 * controller and layer; the widget has to import them.
 */
const TIERS = {
  'dist/draw/index.d.ts': [],
  'dist/indicators/index.d.ts': [],
  'dist/trade/index.d.ts': [],
  'dist/transform/index.d.ts': [],
  'dist/profile/index.d.ts': [],
  'dist/webgl/index.d.ts': [],
  'dist/workspace/index.d.ts': [],
  'dist/widget/index.d.ts': ['declare class DrawingController', 'declare class DrawingLayer'],
};

let failed = false;

for (const [file, ownForbidden] of Object.entries(TIERS)) {
  if (!existsSync(file)) {
    console.error(`check-dts: ${file} is missing. Did the build run?`);
    failed = true;
    continue;
  }
  const src = readFileSync(file, 'utf8');
  for (const decl of [...FORBIDDEN, ...ownForbidden]) {
    // Word-boundary the name so `declare class ChartSomething` is not a hit.
    const re = new RegExp(`${decl}\\b`);
    if (re.test(src)) {
      console.error(
        `check-dts: ${file} inlines "${decl}".\n` +
        '  A tier must import shared types from the entry that owns them:\n' +
        "    import type { IPrimitive } from 'openalgo-charts';\n" +
        "    import type { DrawingController } from 'openalgo-charts/draw';\n" +
        '  A relative import gets bundled in as a second declaration, and the\n' +
        '  private members make it a different type to every consumer.',
      );
      failed = true;
    }
  }
}

// A structurally compatible declaration can still hide a second error constructor.
// Check the built entries too, because hosts catch refusals across these imports.
try {
  const [base, trade] = await Promise.all([
    import('../dist/openalgo-charts.mjs'),
    import('../dist/openalgo-charts.trade.mjs'),
  ]);
  if (base.TradingCapabilityError !== trade.TradingCapabilityError) {
    console.error('check-dts: base and trade export different TradingCapabilityError constructors');
    failed = true;
  }
  for (const [name, entry] of [['base', base], ['trade', trade]]) {
    let refusal;
    try { entry.assertTradingCapability({ place: false }, { operation: 'place' }); }
    catch (error) { refusal = error; }
    if (!(refusal instanceof base.TradingCapabilityError)
      || !(refusal instanceof trade.TradingCapabilityError) || refusal.preflight !== true) {
      console.error(`check-dts: ${name} capability refusal does not match both public error constructors`);
      failed = true;
    }
  }
} catch (error) {
  console.error(`check-dts: cannot verify shared capability runtime: ${error.message}`);
  failed = true;
}

// The draw tier types its events on the chart bus by merging them into the
// base's `ChartEventMap`, inside `declare module 'openalgo-charts'`. A
// declaration bundler may drop a block like that, and nothing else would
// notice: the draw names would fall back to the deprecated string overload and
// compile anyway. So compile a host against the built declarations, where
// `chart.on('draw:add', ...)` must be typed and a wrong field must not compile.
//
// The host compiles with the two flags src is held to (tsconfig.json), and
// with every tier's declarations among its inputs and skipLibCheck off, so an
// error inside the declarations themselves fails here too. A host that turns
// those flags on reads our declarations that way; before 2.6.0 one of them,
// OpenAlgoTradeFeed against OrderFeed, did not compile for it.
const HOST = 'tests/types/chart-events-host.ts';
const DIST_PATHS = {
  'openalgo-charts': ['dist/index.d.ts'],
  ...Object.fromEntries(Object.keys(TIERS).map((file) => [`openalgo-charts/${file.split('/')[1]}`, [file]])),
};
const hostOptions = {
  strict: true, noUncheckedIndexedAccess: true, exactOptionalPropertyTypes: true,
  noEmit: true, skipLibCheck: false, types: [],
  target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler,
  lib: ['lib.es2020.d.ts', 'lib.dom.d.ts', 'lib.dom.iterable.d.ts'],
  baseUrl: process.cwd(), paths: DIST_PATHS,
};
const program = ts.createProgram([HOST, ...Object.values(DIST_PATHS).flat()], hostOptions);
const draw = ts.resolveModuleName('openalgo-charts/draw', HOST, hostOptions, ts.sys).resolvedModule;
if (!draw?.resolvedFileName.replace(/\\/g, '/').endsWith('/dist/draw/index.d.ts')) {
  console.error(`check-dts: ${HOST} did not resolve openalgo-charts/draw to dist/draw/index.d.ts`);
  failed = true;
}
const typeErrors = ts.getPreEmitDiagnostics(program).filter((d) => d.category === ts.DiagnosticCategory.Error);
if (typeErrors.length > 0) {
  console.error(`check-dts: ${HOST} does not compile against the built declarations:\n` + ts.formatDiagnostics(typeErrors, {
    getCanonicalFileName: (name) => name, getCurrentDirectory: () => process.cwd(), getNewLine: () => '\n',
  }));
  failed = true;
}

if (failed) process.exit(1);
console.log(`check-dts: ${Object.keys(TIERS).length} tier declarations, shared capability identity and the typed event map clean under both strict flags`);
