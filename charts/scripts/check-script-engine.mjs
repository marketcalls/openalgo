/** Test a built script engine checkout without adding a product dependency. */
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';
import process from 'node:process';
import { typecheckIntegration } from './typecheck-integration.mjs';

const root = process.argv[2] ?? process.env.SCRIPT_ENGINE_ROOT;
if (!root) throw new Error('Usage: node scripts/check-script-engine.mjs <built-script-engine-checkout>');
const scriptRoot = resolve(root);
for (const name of ['core', 'adapters/charts']) {
  for (const extension of ['js', 'd.ts']) {
    const path = resolve(scriptRoot, `dist/${name}/index.${extension}`);
    if (!existsSync(path)) throw new Error(`Build the requested script engine checkout first; missing ${path}`);
  }
}
typecheckIntegration(['integration/script-engine.test.ts'], {
  'script-engine-under-test': [resolve(scriptRoot, 'dist/core/index.d.ts')],
  'script-engine-under-test/adapters/charts': [resolve(scriptRoot, 'dist/adapters/charts/index.d.ts')],
});
// The cases gate on the version the build reports, not the manifest's: a
// checkout whose package.json moved on without a rebuild runs its old build.
const { VERSION: built } = await import(pathToFileURL(resolve(scriptRoot, 'dist/core/index.js')).href);
const stated = JSON.parse(readFileSync(resolve(scriptRoot, 'package.json'), 'utf8')).version;
process.stdout.write(built === stated
  ? `script engine ${built}: public adapter types compatible; testing runtime boundary.\n`
  : `script engine build ${built} under package.json ${stated}: the build is stale, so cases that need a newer engine skip; `
    + 'rebuild the checkout to run them. Public adapter types compatible; testing runtime boundary.\n');
const run = spawnSync(process.execPath, [
  'node_modules/vitest/vitest.mjs', 'run', '--config', 'vitest.script-engine.config.ts',
], { stdio: 'inherit', env: { ...process.env, SCRIPT_ENGINE_ROOT: scriptRoot } });
if (run.error) throw run.error;
process.exit(run.status ?? 1);
