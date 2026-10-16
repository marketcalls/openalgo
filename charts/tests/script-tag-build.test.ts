/**
 * The script-tag build and the require() path, checked at the seams.
 *
 * A page with no bundler loads one classic script per tier. Each tier file
 * must read the base (and, for the widget, the draw tier) from the page's
 * `OpenAlgoCharts` global, never inline its own copy, or it registers into a
 * registry `createChart` never reads. That is a property of the rollup
 * config, so it is asserted here where it is fast; scripts/check-exports.mjs
 * runs the built files and compares their keys with the declarations, and
 * tests/e2e/script-tag.spec.ts draws with them in three browsers.
 */
import { afterEach, describe, expect, it } from 'vitest';
import pkg from '../package.json';
import sizeLimit from '../.size-limit.json';
// @ts-expect-error rollup.config.js is plain JS with no declaration file; its shape is asserted below.
import rollupConfig from '../rollup.config.js';

interface Output {
  file?: string;
  dir?: string;
  format: string;
  name?: string;
  globals?: (id: string) => string | undefined;
  banner?: (chunk: { imports: string[] }) => string;
  inlineDynamicImports?: boolean;
}
interface Config { input: string; external?: (id: string) => boolean; output: Output }

const PKG = 'openalgo-charts';
const configs = rollupConfig as unknown as Config[];
// The ESM tiers: one .mjs file each, or a directory for the widget and its parts; not the docs bundle.
const esTiers = configs.filter((c) => c.output.format === 'es' && !c.input.endsWith('all.ts')
  && (c.output.dir !== undefined || c.output.file!.endsWith('.mjs')));
const scripts = configs.filter((c) => c.output.format === 'iife');
const scriptOf = (input: string) => scripts.find((c) => c.input === input);
/** `src/draw/index.ts` is the `draw` tier; `src/index.ts` is the base. */
const keyOf = (input: string) => /^src\/(?:([a-z]+)\/)?index\.ts$/.exec(input)?.[1] ?? 'index';

describe('every tier has a classic-script file', () => {
  it('one IIFE per ESM tier, from the same entry', () => {
    expect(scripts.map((c) => c.input).sort()).toEqual(esTiers.map((c) => c.input).sort());
  });

  it('the base file and global are the ones every release has shipped', () => {
    const base = scriptOf('src/index.ts')!;
    expect(base.output.file).toBe('dist/openalgo-charts.standalone.js');
    expect(base.output.name).toBe('OpenAlgoCharts');
    expect(base.external).toBeUndefined();
    expect(base.output.banner).toBeUndefined();
    expect(pkg.unpkg).toBe('dist/openalgo-charts.standalone.js');
    expect(pkg.jsdelivr).toBe('dist/openalgo-charts.standalone.js');
  });

  it('a tier file sits beside its ESM file and adds itself to the global under its subpath name', () => {
    for (const c of scripts.filter((s) => s.input !== 'src/index.ts')) {
      const key = keyOf(c.input);
      expect(c.output.file, key).toBe(`dist/openalgo-charts.${key}.standalone.js`);
      expect(c.output.name, key).toBe(`OpenAlgoCharts.${key}`);
    }
  });
});

describe('a tier file uses the page\'s base, never a private copy', () => {
  it('leaves the same specifiers external as its ESM build', () => {
    for (const c of scripts.filter((s) => s.input !== 'src/index.ts')) {
      const es = esTiers.find((e) => e.input === c.input)!;
      for (const id of [PKG, `${PKG}/draw`, `${PKG}/workspace`, `${PKG}/trade`, './styles', 'openalgo-charts-other']) {
        expect(c.external?.(id), `${c.input} ${id}`).toBe(es.external?.(id));
      }
    }
  });

  it('reads each external from the global: the base itself, a tier by its key', () => {
    const widget = scriptOf('src/widget/index.ts')!;
    expect(widget.output.globals?.(PKG)).toBe('OpenAlgoCharts');
    expect(widget.output.globals?.(`${PKG}/draw`)).toBe('OpenAlgoCharts.draw');
    // Anything else keeps rollup's own naming, the namespace root included.
    expect(widget.output.globals?.('OpenAlgoCharts')).toBeUndefined();
  });

  it('the widget carries its first-use parts, since a classic script cannot share a split chunk', () => {
    expect(scriptOf('src/widget/index.ts')!.output.inlineDynamicImports).toBe(true);
  });
});

describe('a tier file loaded out of order says what to load first', () => {
  const g = globalThis as { OpenAlgoCharts?: unknown };
  afterEach(() => { delete g.OpenAlgoCharts; });
  const run = (input: string, imports: string[]) => {
    const banner = scriptOf(input)!.output.banner!({ imports });
    return () => new Function(banner)();
  };

  it('with no base on the page, names the base file', () => {
    expect(run('src/profile/index.ts', [])).toThrow(
      'openalgo-charts.profile.standalone.js needs openalgo-charts.standalone.js loaded before it');
    expect(run('src/draw/index.ts', [PKG])).toThrow(
      'openalgo-charts.draw.standalone.js needs openalgo-charts.standalone.js loaded before it');
  });

  it('the widget with the base but no draw tier names both files', () => {
    g.OpenAlgoCharts = {};
    const widget = run('src/widget/index.ts', [PKG, `${PKG}/draw`]);
    expect(widget).toThrow(
      'openalgo-charts.widget.standalone.js needs openalgo-charts.standalone.js and openalgo-charts.draw.standalone.js loaded before it');
    g.OpenAlgoCharts = { draw: {} };
    expect(widget).not.toThrow();
  });
});

describe('the script-tag build is budgeted', () => {
  it('one row measures all nine files together', () => {
    const rows = (sizeLimit as { path: string | string[] }[]).filter(
      (r) => Array.isArray(r.path) && r.path.every((p) => p.endsWith('.standalone.js')));
    expect(rows).toHaveLength(1);
    expect([...(rows[0].path as string[])].sort()).toEqual(scripts.map((c) => c.output.file).sort());
  });
});

describe('require() reaches the same ESM files, never a CommonJS copy', () => {
  it('each export resolves require through a default condition to its import file', () => {
    for (const [spec, entry] of Object.entries(pkg.exports as Record<string, Record<string, string>>)) {
      expect(Object.keys(entry), spec).toEqual(['types', 'import', 'default']);
      expect(entry.default, spec).toBe(entry.import);
    }
    expect((pkg as { main?: string }).main).toBeUndefined();
    expect(pkg.type).toBe('module');
  });
});
