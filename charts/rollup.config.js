import typescript from '@rollup/plugin-typescript';
import terser from '@rollup/plugin-terser';
import dts from 'rollup-plugin-dts';

// One entry point per loadable tier (see ARCHITECTURE.md section 2). The widget
// is the only tier that ships DOM. Workspace documents/storage are separate
// so persistence does not increase the base engine or widget download.
const entries = {
  index: 'src/index.ts',
  trade: 'src/trade/index.ts',
  transform: 'src/transform/index.ts',
  profile: 'src/profile/index.ts',
  indicators: 'src/indicators/index.ts',
  draw: 'src/draw/index.ts',
  webgl: 'src/webgl/index.ts',
  widget: 'src/widget/index.ts',
  workspace: 'src/workspace/index.ts',
};

const outFile = {
  index: 'openalgo-charts',
  trade: 'openalgo-charts.trade',
  transform: 'openalgo-charts.transform',
  profile: 'openalgo-charts.profile',
  indicators: 'openalgo-charts.indicators',
  draw: 'openalgo-charts.draw',
  webgl: 'openalgo-charts.webgl',
  widget: 'openalgo-charts.widget',
  workspace: 'openalgo-charts.workspace',
};

const typesFile = {
  index: 'index',
  trade: 'trade/index',
  transform: 'transform/index',
  profile: 'profile/index',
  indicators: 'indicators/index',
  draw: 'draw/index',
  webgl: 'webgl/index',
  widget: 'widget/index',
  workspace: 'workspace/index',
};

/**
 * Every tier is its own bundle, so anything it deep-imports from the base is
 * inlined: a second, private copy. That is only a size cost for pure
 * functions, but for the registries (chart types, indicators) it is a
 * correctness bug: a tier would register into a Map that `createChart` never
 * reads. Tiers therefore import shared runtime state from `openalgo-charts`,
 * which is external for tier builds and emitted as a plain import.
 *
 * The same rule holds one level up. The widget builds on the draw tier (the
 * controller, the icon sprite, the tool registry), so `openalgo-charts/draw`
 * and every other tier specifier are external too. A widget that inlined the
 * draw tier would carry a second `DrawingController` class and a second tool
 * table, and `instanceof` would stop agreeing across them; `check-dts.mjs`
 * fails the build if a tier's declarations inline one of those classes.
 */
const PKG = 'openalgo-charts';
const specifierOf = (key) => (key === 'index' ? PKG : `${PKG}/${key}`);
const tierExternal = (id) => id === PKG || id.startsWith(`${PKG}/`);

/**
 * Emit each shared import as a path relative to the tier bundle rather than
 * the bare specifier, so `<script type="module">` loading /dist/*.mjs straight
 * from a server works with no import map. Bundlers and Node resolve the
 * relative path just as happily. (The .d.ts builds keep the bare specifier,
 * which TypeScript resolves through package.json exports.)
 */
const tierPaths = Object.fromEntries(
  Object.keys(entries).map((key) => [specifierOf(key), `./${outFile[key]}.mjs`]),
);

const abs = (rel) => new URL(rel, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1');

/**
 * Resolve the package's own specifiers to their source entries. Used only by
 * the bundles that must inline everything (the combined docs bundle and the
 * base declarations); tier bundles, ESM and script-tag alike, leave them
 * external so the import survives into the output.
 */
const aliasSelf = {
  name: 'alias-self-reference',
  resolveId(id) {
    const key = Object.keys(entries).find((k) => specifierOf(k) === id);
    return key ? { id: abs(entries[key]) } : null;
  },
};

/**
 * The widget loads the UI a user has to open (the shortcuts editor, the
 * Layouts menu, the templates list, the grid bar's menus) with `import()`
 * on first use (src/widget/lazy.ts). Those chunks are written beside the tier
 * as `openalgo-charts.widget.<part>-<hash>.mjs`: a chunk resolves against the
 * tier's own URL, so a CDN or `type="module"` page needs nothing more, and a bundler
 * follows the import and splits it the same way. Every other tier is one file.
 * The tier file itself keeps everything a widget loads before anyone opens a
 * part: `allow-extension` lets the chunks import the shell's helpers from it,
 * where rollup would otherwise move the whole shell into a second chunk behind
 * a re-exporting facade, and the tier's size row would measure the facade.
 * Those helpers go by minified names that change from build to build, so a
 * part only works with the tier file it was built with. The content hash in
 * its name makes a new tier file ask for its own parts, never an old copy a
 * browser or proxy kept from the release before. `npm run build` empties dist/
 * first, or a rebuild would leave the previous parts there for `npm pack` and
 * the parts' size row to pick up.
 */
const outputOf = (key) => key === 'widget'
  ? { dir: 'dist', entryFileNames: `${outFile[key]}.mjs`, chunkFileNames: `${outFile[key]}.[name]-[hash].mjs` }
  : { file: `dist/${outFile[key]}.mjs` };

const js = Object.entries(entries).map(([key, input]) => ({
  input,
  external: key === 'index' ? undefined : tierExternal,
  preserveEntrySignatures: key === 'widget' ? 'allow-extension' : 'exports-only',
  output: {
    ...outputOf(key),
    format: 'es',
    sourcemap: true,
    paths: tierPaths,
  },
  plugins: [
    typescript({ tsconfig: './tsconfig.build.json' }),
    terser({ format: { comments: false } }),
  ],
}));

/**
 * The script-tag build: one classic script per tier, for a page that loads no
 * modules. The base file defines the `OpenAlgoCharts` global, as it always
 * has, and each tier file adds itself to it under its subpath name, so
 * `import { X } from 'openalgo-charts/draw'` reads `OpenAlgoCharts.draw.X`.
 * A key per tier rather than one flat object keeps two tiers' names from
 * colliding (base and widget both export `withAlpha`, with different code).
 *
 * A tier file leaves the same specifiers external as its ESM build and reads
 * them from that global, for the reason given where `PKG` is defined: it must
 * register into the base the page loaded, never a private copy. Its banner stops it before it
 * runs when what it reads is missing, and names the files to load first,
 * where it would otherwise fail somewhere inside with a bare TypeError.
 *
 * The widget's first-use parts are bundled into its file. A classic script
 * cannot share a split chunk, and a part fetched as a module would import the
 * ESM base and widget files, whose registries are not the ones on the page.
 */
const GLOBAL = 'OpenAlgoCharts';
const keyOfSpecifier = (id) => (id === PKG ? 'index' : id.slice(PKG.length + 1));
const globalOf = (id) => (!tierExternal(id) ? undefined : id === PKG ? GLOBAL : `${GLOBAL}.${keyOfSpecifier(id)}`);
const scriptFile = (key) => `${outFile[key]}.standalone.js`;

const loadFirst = (key) => (chunk) => {
  const tiers = chunk.imports.filter((id) => id !== PKG);
  const missing = [`typeof ${GLOBAL}=="undefined"`, ...tiers.map((id) => `!${globalOf(id)}`)].join('||');
  const first = ['index', ...tiers.map(keyOfSpecifier)].map(scriptFile).join(' and ');
  return `if(${missing})throw new Error(${JSON.stringify(`${scriptFile(key)} needs ${first} loaded before it`)});`;
};

const scriptTags = Object.entries(entries).map(([key, input]) => ({
  input,
  external: key === 'index' ? undefined : tierExternal,
  output: {
    file: `dist/${scriptFile(key)}`,
    format: 'iife',
    name: key === 'index' ? GLOBAL : `${GLOBAL}.${key}`,
    globals: globalOf,
    banner: key === 'index' ? undefined : loadFirst(key),
    inlineDynamicImports: key === 'widget',
    // A map here carries positions and names, not source text, and a page that
    // wants them can load the module build, whose maps a bundler also composes
    // into its own. So the tier scripts ship none: maps for them were half a
    // megabyte of every install, packed. The base script keeps the map it has
    // always shipped.
    sourcemap: key === 'index',
  },
  plugins: [
    typescript({ tsconfig: './tsconfig.build.json' }),
    terser({ format: { comments: false } }),
  ],
}));

// Combined bundle (base + every tier in one module instance), docs live demos
// only. Nothing is external here, so the tiers resolve the package specifiers
// to the real source modules and share one registry. No .d.ts (not a published
// entry point).
const allBundle = {
  input: 'src/all.ts',
  output: {
    file: 'dist/openalgo-charts.all.mjs',
    format: 'es',
    sourcemap: true,
  },
  plugins: [
    aliasSelf,
    typescript({ tsconfig: './tsconfig.build.json' }),
    terser({ format: { comments: false } }),
  ],
};

const types = Object.entries(entries).map(([key, input]) => ({
  input,
  external: key === 'index' ? undefined : tierExternal,
  output: { file: `dist/${typesFile[key]}.d.ts`, format: 'es' },
  plugins: [...(key === 'index' ? [aliasSelf] : []), dts()],
}));

export default [...js, ...scriptTags, allBundle, ...types];
