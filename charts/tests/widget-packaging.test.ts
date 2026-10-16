/**
 * The widget tier's packaging, checked at the seams.
 *
 * A tier is declared in five places that nothing ties together: the rollup
 * entries, package.json `exports`, `.size-limit.json`, `typedoc.json` and the
 * tsconfig path map. CLAUDE.md records what happens when one of them lags (the
 * API reference documented four tiers of seven for several releases), so this
 * suite cross-checks the five against each other rather than pinning the
 * widget's rows alone: a ninth tier added to one list and not the rest fails
 * here too.
 *
 * The ESLint half runs the real linter over probe snippets, because the tier
 * ACL is the only thing that keeps the engine DOM-free once a DOM tier exists,
 * and a rule that is merely written down is not a rule.
 */
/// <reference types="vite/client" />
import { describe, it, expect } from 'vitest';
import { ESLint } from 'eslint';
import pkg from '../package.json';
import sizeLimit from '../.size-limit.json';
import typedoc from '../typedoc.json';
import tsconfig from '../tsconfig.json';
// @ts-expect-error rollup.config.js is plain JS with no declaration file; its shape is asserted below.
import rollupConfig from '../rollup.config.js';
import checkDtsSource from '../scripts/check-dts.mjs?raw';
import checkShakeSource from '../scripts/check-shake.mjs?raw';
import skillsCoverageSource from '../scripts/check-skills-coverage.mjs?raw';

// The repo root as a filesystem path, taken from this module's URL. Nothing
// else in tests/ touches Node, so the suite carries no Node typings, and ESLint
// wants absolute paths for its cwd and for the probe files. Same drive-letter
// fix-up as rollup.config.js.
const ROOT = decodeURIComponent(new URL('..', import.meta.url).pathname).replace(/^\/([A-Za-z]:)/, '$1');
const at = (rel: string) => ROOT + rel;
const PKG = 'openalgo-charts';
const WIDGET_BUNDLE = 'dist/openalgo-charts.widget.mjs';
const WIDGET_TYPES = './dist/widget/index.d.ts';

interface RollupEntry {
  input: string;
  external?: (id: string) => boolean;
  preserveEntrySignatures?: string;
  output: { file: string; format: string; paths?: Record<string, string>; dir?: string; entryFileNames?: string; chunkFileNames?: string };
}

// The widget writes its parts that load on first use beside it, so its output
// is a directory with a named entry file; that file is the tier bundle.
const configs = (rollupConfig as unknown as RollupEntry[]).map((c) => (c.output.dir === undefined ? c
  : { ...c, output: { ...c.output, file: `${c.output.dir}/${c.output.entryFileNames}` } }));
// The tier bundles: ESM, under dist/, and not the docs-only combined bundle.
const esTiers = configs.filter(
  (c) => c.output.format === 'es' && c.output.file.endsWith('.mjs') && !c.output.file.includes('.all.'),
);
const dtsTiers = configs.filter((c) => c.output.file.endsWith('.d.ts'));

/** `dist/openalgo-charts.draw.mjs` is `openalgo-charts/draw`; the base file is the bare name. */
function specifierOfBundle(file: string): string {
  const m = /^dist\/openalgo-charts(?:\.([a-z]+))?\.mjs$/.exec(file);
  if (!m) throw new Error(`not a tier bundle: ${file}`);
  return m[1] ? `${PKG}/${m[1]}` : PKG;
}

/** `./draw` in `exports` is `openalgo-charts/draw`; `.` is the bare name. */
const specifierOfExport = (key: string) => (key === '.' ? PKG : `${PKG}/${key.slice(2)}`);

const exportsMap = pkg.exports as Record<string, { types: string; import: string; default: string }>;
const sizeRows = sizeLimit as { name: string; path: string | string[]; limit: string }[];
const pathsOf = (row: { path: string | string[] }) => (Array.isArray(row.path) ? row.path : [row.path]);

describe('the widget is a tier bundle like the other seven', () => {
  it('rollup builds src/widget/index.ts into its own ESM bundle and its own .d.ts', () => {
    const js = esTiers.find((c) => c.output.file === WIDGET_BUNDLE);
    expect(js?.input).toBe('src/widget/index.ts');
    const types = dtsTiers.find((c) => c.output.file === 'dist/widget/index.d.ts');
    expect(types?.input).toBe('src/widget/index.ts');
  });

  it('every tier bundle is a package export with matching types, and every export is a bundle', () => {
    const fromRollup = new Map(esTiers.map((c) => [specifierOfBundle(c.output.file), c.output.file]));
    const fromExports = new Map(Object.keys(exportsMap).map((k) => [specifierOfExport(k), exportsMap[k]]));
    expect([...fromExports.keys()].sort()).toEqual([...fromRollup.keys()].sort());
    for (const [spec, entry] of fromExports) {
      expect(entry.import).toBe(`./${fromRollup.get(spec)}`);
      // The .d.ts path is the tier's `typesFile` in rollup.config.js.
      const dts = dtsTiers.find((c) => `./${c.output.file}` === entry.types);
      expect(dts, `${spec} types ${entry.types} are not built`).toBeDefined();
    }
    expect(exportsMap['./widget']).toEqual({ types: WIDGET_TYPES, import: `./${WIDGET_BUNDLE}`, default: `./${WIDGET_BUNDLE}` });
  });

  it('typedoc documents every tier entry point', () => {
    const inputs = esTiers.map((c) => c.input).sort();
    expect([...typedoc.entryPoints].sort()).toEqual(inputs);
  });

  it('tsconfig maps every tier specifier to its source entry', () => {
    const paths = tsconfig.compilerOptions.paths as Record<string, string[]>;
    for (const c of esTiers) {
      expect(paths[specifierOfBundle(c.output.file)]).toEqual([`./${c.input}`]);
    }
  });
});

describe('the widget shares one engine with the page rather than inlining a second', () => {
  const widget = esTiers.find((c) => c.output.file === WIDGET_BUNDLE)!;
  const widgetDts = dtsTiers.find((c) => c.output.file === 'dist/widget/index.d.ts')!;

  it('leaves the base and every other tier external in the JS build', () => {
    expect(widget.external?.(PKG)).toBe(true);
    for (const c of esTiers) {
      const spec = specifierOfBundle(c.output.file);
      expect(widget.external?.(spec), spec).toBe(true);
    }
    // Its own modules and node built-ins are not external.
    expect(widget.external?.('./styles')).toBe(false);
    expect(widget.external?.('openalgo-charts-something-else')).toBe(false);
  });

  it('emits each external tier as a sibling path so dist/ serves with no import map', () => {
    for (const c of esTiers) {
      const spec = specifierOfBundle(c.output.file);
      expect(widget.output.paths?.[spec]).toBe(`./${c.output.file.slice('dist/'.length)}`);
    }
  });

  it('leaves the same specifiers external in the .d.ts build', () => {
    expect(widgetDts.external?.(PKG)).toBe(true);
    expect(widgetDts.external?.(`${PKG}/draw`)).toBe(true);
  });

  it('writes its first-use parts beside it, and keeps the shell in the tier file', () => {
    // The hash: a part imports the tier's helpers by minified names, so a
    // tier file must never be handed a part a cache kept from another build.
    expect(widget.output.chunkFileNames).toBe('openalgo-charts.widget.[name]-[hash].mjs');
    // Without it rollup moves the shell into a chunk behind a re-exporting
    // entry, and the tier's size row would measure only that entry.
    expect(widget.preserveEntrySignatures).toBe('allow-extension');
  });

  it('the base entry stays a self-contained bundle', () => {
    const base = esTiers.find((c) => c.output.file === 'dist/openalgo-charts.mjs')!;
    expect(base.external).toBeUndefined();
  });
});

describe('the widget is budgeted', () => {
  it('has its own size-limit row', () => {
    const own = sizeRows.filter((r) => pathsOf(r).length === 1 && pathsOf(r)[0] === WIDGET_BUNDLE);
    expect(own).toHaveLength(1);
    expect(own[0].limit).toMatch(/^\d+(?:\.\d+)? kB$/);
  });

  it('its first-use parts have a row, by glob, since each name changes with its content', () => {
    expect(sizeRows.filter((r) => r.path === 'dist/openalgo-charts.widget.*.mjs')).toHaveLength(1);
  });

  it('the Everything row measures every tier bundle, the widget included', () => {
    const everything = sizeRows.find((r) => r.name.startsWith('Everything'))!;
    const measured = pathsOf(everything).sort();
    expect(measured).toEqual(esTiers.map((c) => c.output.file).sort());
  });

  it('the terminal row is the set one createWidget call loads', () => {
    const terminal = sizeRows.find((r) => r.name.startsWith('Widget terminal'))!;
    expect(pathsOf(terminal).sort()).toEqual(
      ['dist/openalgo-charts.mjs', 'dist/openalgo-charts.draw.mjs', 'dist/openalgo-charts.indicators.mjs', WIDGET_BUNDLE].sort(),
    );
  });

  it('is marked as having side effects, like the other registering tiers', () => {
    expect(pkg.sideEffects).toContain(`./${WIDGET_BUNDLE}`);
    expect(pkg.sideEffects).toContain('**/widget/**');
  });
});

describe('the tier ACL keeps the engine DOM-free', () => {
  const eslint = new ESLint({ cwd: ROOT, overrideConfigFile: at('eslint.config.js') });

  /** Lint a one-import probe as if it lived at `file`; return the ACL messages. */
  async function acl(file: string, spec: string): Promise<string[]> {
    const code = `import { x } from '${spec}';\nexport const y = x;\n`;
    const [result] = await eslint.lintText(code, { filePath: at(file) });
    return result.messages.filter((m) => m.ruleId === 'no-restricted-imports').map((m) => m.message);
  }

  it('the base tier cannot import the widget', async () => {
    expect(await acl('src/core/probe.ts', '../widget/index')).toHaveLength(1);
    expect(await acl('src/render/probe.ts', '../widget/dialogs/settings')).toHaveLength(1);
  });

  it('no other lazy tier can import the widget', async () => {
    for (const tier of ['draw', 'indicators', 'trade', 'transform', 'profile', 'webgl']) {
      expect(await acl(`src/${tier}/probe.ts`, '../widget/index'), tier).toHaveLength(1);
    }
  });

  it('the widget reaches the draw tier through its package specifier only', async () => {
    const [relative] = await acl('src/widget/probe.ts', '../draw/index');
    expect(relative).toContain("'openalgo-charts/draw'");
    expect(await acl('src/widget/dialogs/probe.ts', '../../draw/controller')).toHaveLength(1);
    expect(await acl('src/widget/probe.ts', 'openalgo-charts/draw')).toHaveLength(0);
  });

  it('the widget takes Chart from the package, never from core', async () => {
    const [relative] = await acl('src/widget/probe.ts', '../core/chart');
    expect(relative).toContain("'openalgo-charts'");
    expect(await acl('src/widget/probe.ts', '../index')).toHaveLength(1);
    expect(await acl('src/widget/probe.ts', 'openalgo-charts')).toHaveLength(0);
  });

  it('the widget may still import pure helpers by path, as every tier does', async () => {
    expect(await acl('src/widget/probe.ts', '../helpers/math')).toHaveLength(0);
    expect(await acl('src/widget/probe.ts', './styles')).toHaveLength(0);
  });
});

describe('the build guards know the tier exists', () => {
  // These scripts run against dist/, which the unit suite never builds, so the
  // assertion is on their source: each names the widget where it enumerates
  // tiers. Weak, but it catches the tier being dropped from a list.
  it('check-dts guards the widget declarations against inlining the draw tier', () => {
    expect(checkDtsSource).toContain("'dist/widget/index.d.ts'");
    expect(checkDtsSource).toContain("'declare class DrawingController'");
  });

  it('check-shake asserts a chart-only import carries no widget', () => {
    expect(checkShakeSource).toContain("'oac-widget'");
  });

  it('skills coverage enumerates the widget tier', () => {
    expect(skillsCoverageSource).toContain("widget: 'openalgo-charts.widget.mjs'");
  });
});
