// @ts-check
/**
 * Lint config. Two jobs, and the second is the one that earns its keep.
 *
 * 1. Ordinary correctness rules over TypeScript.
 * 2. The TIER ACL. This package's whole shape is eight lazily-loaded ESM bundles
 *    with enforced Brotli budgets, which only works while the base tier never
 *    reaches into a lazy one. ARCHITECTURE.md says so in prose; prose does not
 *    fail CI, and a single stray import is enough to pull a 27 KB tier into the
 *    61 KB base without anything going red. `npm run size` catches it only if
 *    the result happens to cross a budget line.
 *
 * The ACL is written against what the tree actually does today, with each
 * existing crossing named and justified rather than waved through, so a NEW
 * crossing fails and an old one stays visible.
 */
import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import { deprecationVersionRule } from './scripts/check-deprecated.mjs';
import { readFileSync } from 'node:fs';

/**
 * Lazy tiers: each is its own bundle and its own size budget. The widget is the
 * one tier allowed to build DOM (a toolbar, a rail, dialogs); everything else
 * under src/ touches the document only to own its canvases.
 */
const LAZY_TIERS = ['indicators', 'draw', 'transform', 'profile', 'trade', 'webgl', 'widget', 'workspace'];

/**
 * Base-tier directories. Everything here lands in `openalgo-charts.mjs`, so an
 * import from one of these into a lazy tier is a size regression by definition.
 */
const BASE_DIRS = [
  'core', 'render', 'scale', 'model', 'primitives',
  'input', 'feed', 'replay', 'compare', 'link', 'helpers', 'alerts',
];

/**
 * File length. A source file past `maxLines` is usually doing more than one
 * job: chart.ts reached 6,729 lines before 2.5.7 split it by responsibility.
 * The files in `caps` were already over the limit when it arrived, so each is
 * held to its size on the day it was listed. A cap may be lowered, never
 * raised, and tests/line-caps.test.ts makes a file that drops under the limit
 * leave the list.
 */
const LINES = JSON.parse(readFileSync(new URL('./scripts/line-caps.json', import.meta.url), 'utf8'));

const crossTier = (tiers, why) => ({
  patterns: tiers.map((t) => ({
    group: [`**/${t}/**`, `../${t}/*`, `../../${t}/*`, `./${t}/*`],
    message: why,
  })),
});

export default tseslint.config(
  { ignores: ['dist/**', 'dist-baseline/**', 'node_modules/**', 'website/**', 'examples/**', 'coverage/**', '.worktrees/**', 'artifacts/**'] },

  js.configs.recommended,
  ...tseslint.configs.recommended,

  {
    files: ['**/*.ts'],
    rules: {
      // TypeScript resolves identifiers itself, including every DOM and ES
      // global, and reports an unknown one as a compile error. Leaving
      // `no-undef` on just means re-declaring lib.dom in an eslint globals
      // block and getting 81 false positives until it is complete.
      'no-undef': 'off',
      // The codebase leans on `unknown` at its public edges and narrows
      // deliberately; an explicit `any` is the thing worth flagging.
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/consistent-type-imports': ['error', { prefer: 'type-imports', fixStyle: 'inline-type-imports' }],
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      eqeqeq: ['error', 'always', { null: 'ignore' }],
      'no-console': 'error',
    },
  },

  // ── the tier ACL ────────────────────────────────────────────────────────────
  {
    files: BASE_DIRS.map((d) => `src/${d}/**/*.ts`),
    rules: {
      'no-restricted-imports': [
        'error',
        crossTier(
          LAZY_TIERS,
          'Base tier must not import a lazy tier: it pulls that whole bundle into openalgo-charts.mjs. ' +
            'Invert the dependency (register into a base registry from the tier) instead.',
        ),
      ],
    },
  },

  // The widget sits above every other tier, and nothing below it may know it
  // exists: a draw or indicator module that imported a dialog would carry the
  // DOM tier into a bundle whose whole promise is that it ships none.
  {
    files: LAZY_TIERS.filter((t) => t !== 'widget').map((t) => `src/${t}/**/*.ts`),
    rules: {
      'no-restricted-imports': [
        'error',
        crossTier(
          ['widget'],
          'Only a host imports the widget tier. A tier that needs UI describes it (a settings schema, an event) and lets the widget render it.',
        ),
      ],
    },
  },

  // The widget builds on the base and on the draw tier, and must reach both
  // through their package specifiers. A relative import of `../core/chart` or
  // `../draw/index` is inlined into the widget bundle as a second, private copy:
  // a second `Chart` class the base never constructs, a second tool registry
  // `createChart` never reads, and `.d.ts` output that check-dts.mjs rejects.
  // `openalgo-charts` and `openalgo-charts/<tier>` are external in
  // rollup.config.js and resolve to src/ through tsconfig `paths`, so the
  // package form costs nothing in development. Pure helpers (`../helpers/*`,
  // `../render/pill`) stay importable by path, as they are from every tier.
  {
    files: ['src/widget/**/*.ts'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            ...LAZY_TIERS.filter((t) => t !== 'widget').map((t) => ({
              group: [`**/${t}/**`, `../${t}/*`, `../../${t}/*`],
              message: `Import the ${t} tier as 'openalgo-charts/${t}': a relative path inlines a second copy of it into the widget bundle.`,
            })),
            {
              group: ['**/core/**', '../core/*', '../../core/*', '../index', '../index.ts', '../all', '../all.ts'],
              message: "Import Chart, createChart and the option types from 'openalgo-charts': a relative path inlines a second Chart class into the widget bundle.",
            },
          ],
        },
      ],
    },
  },

  // ── the deprecation policy ─────────────────────────────────────────────────
  // COMPATIBILITY.md keeps a deprecated API until the next major. Every
  // `@deprecated` tag in shipped source names the release that removes it, and
  // fails once the package reaches that release. The rule lives in
  // scripts/check-deprecated.mjs, where tests/deprecation-policy.test.ts
  // drives it through this config.
  {
    files: ['src/**/*.ts'],
    plugins: { oac: { rules: { 'deprecation-version': deprecationVersionRule } } },
    rules: { 'oac/deprecation-version': 'error' },
  },

  // `openalgo-trade.ts` is the OpenAlgo broker adapter. It is types-plus-one-
  // validator against the trade tier, and it lives in `feed/` because that is
  // where the OpenAlgo transports live. Named rather than silently allowed: if
  // this grows past `validateQuantity`, the adapter belongs in `trade/`.
  {
    files: ['src/feed/openalgo-trade.ts'],
    rules: { 'no-restricted-imports': 'off' },
  },

  // Note on `src/index.ts`: the base entry re-exports four standalone
  // calculators (ema, rsi, atr, supertrend). They are plain functions over
  // `Bar[]` with no registry, no descriptor and no tier imports, which is what
  // makes them safe to ship in base; the indicator TIER is
  // `indicators/index.ts` and stays out. The ACL above targets `src/<dir>/**`,
  // so the entry point is outside it by construction and needs no exemption.

  // File length (see LINES above). Blank lines and comments count, because a
  // long file is long to read whatever its lines hold.
  {
    files: ['src/**/*.ts'],
    rules: { 'max-lines': ['error', { max: LINES.maxLines, skipBlankLines: false, skipComments: false }] },
  },
  ...Object.entries(LINES.caps).map(([file, max]) => ({
    files: [file],
    rules: { 'max-lines': ['error', { max, skipBlankLines: false, skipComments: false }] },
  })),

  // Node scripts (.cjs / .mjs). `no-undef` is off for the same reason as in TS:
  // enumerating the Node globals here just to satisfy it buys nothing, and
  // these files are never shipped.
  {
    files: ['**/*.cjs', '**/*.mjs', '*.config.js'],
    rules: {
      'no-undef': 'off',
      '@typescript-eslint/no-require-imports': 'off',
      'no-console': 'off',
    },
  },

  // Tests and scripts are not shipped; they may reach anywhere and may log.
  {
    files: ['tests/**/*.ts', 'tests/**/*.cjs', 'scripts/**/*.mjs', '*.config.ts', '*.config.js'],
    rules: {
      'no-console': 'off',
      'no-restricted-imports': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
      // The fake DOM/canvas helpers stand in for browser APIs whose real
      // signatures are `Function`-shaped listener bags. Naming each one buys
      // nothing in a test double.
      '@typescript-eslint/no-unsafe-function-type': 'off',
    },
  },
);
