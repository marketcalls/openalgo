/**
 * Build a reference `dist-baseline/` from another git ref, so
 * `tests/e2e/render-parity.spec.ts` can compare the working tree's pixels
 * against a known-good release in a real browser.
 *
 * Unit tests here run against a recording canvas: they prove what the renderer
 * ASKED the browser to draw, never what the browser actually painted. Two
 * shipped defects passed a fully green suite for exactly that reason
 * (see CLAUDE.md). This is the harness that closes the gap, and it matters more
 * with every renderer change: the LOD tiers, the backend port, and the WebGL2
 * backend all claim to paint what the current path paints, and that claim needs
 * a pixel-level check rather than a code review.
 *
 *   node scripts/build-baseline.mjs [ref]     # default: master
 *
 * The build runs in a detached git worktree, so the working tree is never
 * stashed or checked out from under an editor. `node_modules` is shared with
 * the main checkout by symlink where the platform allows it (a junction on
 * Windows), and copied when it does not.
 */
import { execFileSync } from 'node:child_process';
import { cpSync, existsSync, mkdtempSync, rmSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const ref = process.argv[2] ?? 'master';
const root = resolve(import.meta.dirname, '..');
const out = join(root, 'dist-baseline');

// No shell: a shell would need the args escaped, and every command here is
// either a real binary (git) or a JS entry point run through this same node.
const run = (cmd, args, cwd) => execFileSync(cmd, args, { cwd, stdio: 'inherit' });
const node = (script, args, cwd) => execFileSync(process.execPath, [script, ...args], { cwd, stdio: 'inherit' });

// Fail early with a useful message rather than deep inside a worktree add.
try {
  execFileSync('git', ['rev-parse', '--verify', `${ref}^{commit}`], { cwd: root, stdio: 'pipe' });
} catch {
  console.error(`build-baseline: '${ref}' is not a commit in this repository`);
  process.exit(1);
}

const work = mkdtempSync(join(tmpdir(), 'oac-baseline-'));
const tree = join(work, 'src');

try {
  console.log(`build-baseline: checking out ${ref}`);
  run('git', ['worktree', 'add', '--detach', tree, ref], root);

  // Reuse the installed toolchain: a fresh `npm ci` here would take minutes and
  // could resolve different patch versions, which is its own source of pixel drift.
  const deps = join(tree, 'node_modules');
  try {
    symlinkSync(join(root, 'node_modules'), deps, 'junction');
  } catch {
    console.log('build-baseline: symlink unavailable, copying node_modules');
    cpSync(join(root, 'node_modules'), deps, { recursive: true });
  }

  console.log('build-baseline: building');
  node(join(root, 'node_modules', 'rollup', 'dist', 'bin', 'rollup'), ['-c'], tree);

  rmSync(out, { recursive: true, force: true });
  cpSync(join(tree, 'dist'), out, { recursive: true });
  console.log(`build-baseline: ${ref} -> dist-baseline/`);
} finally {
  rmSync(work, { recursive: true, force: true });
  // Drop the registration the removed directory left behind.
  try {
    run('git', ['worktree', 'prune'], root);
  } catch {
    /* best effort: a stale entry is harmless and `git worktree prune` fixes it */
  }
}

if (!existsSync(join(out, 'openalgo-charts.mjs'))) {
  console.error('build-baseline: build produced no base bundle');
  process.exit(1);
}
