// Copies the built OpenAlgo Charts bundles from ../dist into the docs site so the
// live, in-page chart demos run against the real library. Runs automatically
// before `next dev` / `next build` (see package.json predev/prebuild). If the
// library has not been built yet, it prints a hint instead of failing the build.
import { mkdirSync, copyFileSync, existsSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { lightDiagram } from './diagram-light.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const distDir = resolve(here, '..', '..', 'dist');
const outDir = resolve(here, '..', 'lib', 'oac');

// The architecture diagram is edited in docs/ (README and ARCHITECTURE.md show
// it) and the site serves its own copy from public/. Copy it here so the two
// cannot drift: the site once carried a whole release's pre-release sizes
// because only dist/ was synced.
const diagram = resolve(here, '..', '..', 'docs', 'architecture-diagram.svg');
if (existsSync(diagram)) {
  copyFileSync(diagram, resolve(here, '..', 'public', 'architecture-diagram.svg'));
  // The light site shows a variant derived from the same file, never a second copy.
  writeFileSync(resolve(here, '..', 'public', 'architecture-diagram-light.svg'), lightDiagram(readFileSync(diagram, 'utf8')));
  console.log('[sync-lib] copied docs/architecture-diagram.svg and its light variant into website/public');
}

if (!existsSync(distDir)) {
  console.warn('[sync-lib] ../dist not found. Run `npm run build` in the repo root first.');
  process.exit(0);
}

// Emptied first: a widget part's file name changes with its content, so a copy
// over the last sync would keep every part the library no longer builds.
rmSync(outDir, { recursive: true, force: true });
mkdirSync(outDir, { recursive: true });

const wanted = readdirSync(distDir).filter((f) => f.endsWith('.mjs') || f.endsWith('.mjs.map'));
let copied = 0;
for (const file of wanted) {
  copyFileSync(join(distDir, file), join(outDir, file));
  copied += 1;
}
console.log(`[sync-lib] copied ${copied} bundle file(s) into website/lib/oac`);

// Publish the same standalone profile demo used during development. Relative
// module paths work under both a local preview and the website's base path.
const demoSource = resolve(here, '..', '..', 'examples', 'market-profile');
const demoOutput = resolve(here, '..', 'public', 'demos', 'market-profile');
const demoBundles = resolve(demoOutput, '..', 'dist');
mkdirSync(demoOutput, { recursive: true });
rmSync(demoBundles, { recursive: true, force: true });
mkdirSync(demoBundles, { recursive: true });
const demoHtml = readFileSync(join(demoSource, 'index.html'), 'utf8').replaceAll("from '/dist/", "from '../dist/");
writeFileSync(join(demoOutput, 'index.html'), demoHtml);
copyFileSync(join(demoSource, 'themes.js'), join(demoOutput, 'themes.js'));
for (const name of ['openalgo-charts.mjs', 'openalgo-charts.profile.mjs']) {
  copyFileSync(join(distDir, name), join(demoBundles, name));
  if (existsSync(join(distDir, name + '.map'))) copyFileSync(join(distDir, name + '.map'), join(demoBundles, name + '.map'));
}
console.log('[sync-lib] copied standalone profile demo and its bundles into website/public/demos');

// Keep the order-flow docs embed identical to the standalone replay demo.
const orderflowOutput = resolve(here, '..', 'public', 'demos', 'orderflow');
mkdirSync(orderflowOutput, { recursive: true });
const orderflowHtml = readFileSync(resolve(here, '..', '..', 'examples', 'orderflow', 'index.html'), 'utf8')
  .replaceAll("from '/dist/", "from '../dist/");
writeFileSync(join(orderflowOutput, 'index.html'), orderflowHtml);
console.log('[sync-lib] copied standalone order-flow demo into website/public/demos');

// The profiles selector uses the same maintained pages at both entry points.
const profilesHtml = readFileSync(resolve(here, '..', '..', 'examples', 'phase11-profiles.html'), 'utf8')
  .replaceAll("from '../dist/", "from './dist/");
writeFileSync(resolve(demoOutput, '..', 'phase11-profiles.html'), profilesHtml);

// The drawing catalog is shared by the standalone demo and website embeds.
const drawingOutput = resolve(demoOutput, '..', 'drawings');
mkdirSync(drawingOutput, { recursive: true });
for (const name of ['index.html', 'gallery.js']) {
  const source = readFileSync(resolve(here, '..', '..', 'examples', 'drawings', name), 'utf8')
    .replaceAll("from '/dist/", "from '../dist/");
  writeFileSync(join(drawingOutput, name), source);
}
for (const name of wanted) copyFileSync(join(distDir, name), join(demoBundles, name));

// Keep the metadata example on the same bundles as the generated API reference.
const instrumentsOutput = resolve(demoOutput, '..', 'instruments');
mkdirSync(instrumentsOutput, { recursive: true });
copyFileSync(resolve(here, '..', '..', 'examples', 'instruments.html'), join(instrumentsOutput, 'index.html'));
