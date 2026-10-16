/**
 * Write the release's benchmark entry: the render bench on this build and on
 * the release before it, measured in one session on one machine, into
 * benchmarks/releases.json and the website's Benchmarks page.
 *
 *   npm run build && npm run bench:release
 *   npm run bench:release -- --previous v2.5.7 --runs 5 --previous-runs 5
 *   npm run bench:release -- --reuse     # aggregate runs already on disk
 *
 * Run it after the version bump and the final build, like the size
 * measurement, on the reference machine with nothing else running: load only
 * ever adds time, and a comparison is fair only when both builds were timed
 * under the same conditions. That is why the previous release is rebuilt from
 * its tag and measured again here rather than quoted from its own entry, which
 * may come from another machine or another day.
 *
 * Each cell keeps every run's p95; the page quotes the lowest, the figure
 * closest to what the machine itself costs. A run of this build that fails its
 * render bench budgets stops the script: that is a regression to fix, not a
 * number to publish. The previous release may fail today's budgets, which is
 * the point of the comparison, so only its timings are required.
 */
import { execFileSync, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { cpus, release as osRelease, type as osType } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { BENCH_BAR_COUNTS, BENCH_METRICS, BENCH_RENDERERS } from './render-bench-budgets.mjs';
import { DATA_FILE, compareVersions, readReleases, writePage } from './release-benchmarks.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const args = process.argv.slice(2);
const arg = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] !== undefined ? args[i + 1] : fallback;
};
const fail = (message) => {
  console.error(`bench:release: ${message}`);
  process.exit(1);
};

const version = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')).version;
const runs = Number(arg('--runs', '5'));
const previousRuns = Number(arg('--previous-runs', '5'));
if (!(runs >= 1 && previousRuns >= 1)) fail('--runs and --previous-runs must be at least 1');

/** The highest release tag below this version. */
function previousTag() {
  const tags = execFileSync('git', ['tag', '--list', 'v*'], { cwd: root, encoding: 'utf8' })
    .split('\n').map((t) => t.trim()).filter((t) => /^v\d+\.\d+\.\d+$/.test(t))
    .map((t) => t.slice(1)).filter((v) => compareVersions(v, version) < 0)
    .sort(compareVersions);
  if (tags.length === 0) fail(`no release tag below ${version}`);
  return `v${tags[tags.length - 1]}`;
}

const tag = arg('--previous', previousTag());
const previous = tag.replace(/^v/, '');
const out = join(root, 'artifacts', 'bench-release', version);
const rowFiles = BENCH_RENDERERS.flatMap((r) => BENCH_BAR_COUNTS.map((b) => `${r}-${b}.json`));

/** The VERSION a build folder carries, asked of the bundle itself rather than trusted. */
async function builtVersion(dir) {
  const file = join(root, dir, 'openalgo-charts.mjs');
  if (!existsSync(file)) return null;
  return (await import(pathToFileURL(file).href)).VERSION ?? null;
}

function bench(dist, dir) {
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  const result = spawnSync(process.execPath, [join(root, 'scripts', 'render-bench.mjs'), '--reporter=line'], {
    cwd: root,
    stdio: 'inherit',
    env: { ...process.env, OAC_RENDER_BENCH_OUT: dir, OAC_RENDER_BENCH_DIST: dist },
  });
  const missing = rowFiles.filter((f) => !existsSync(join(dir, f)));
  if (missing.length > 0) fail(`${dist} left no timings for ${missing.join(', ')} in ${dir}`);
  return result.status ?? 1;
}

if (!args.includes('--reuse')) {
  if ((await builtVersion('dist')) !== version) fail(`dist/ is not a ${version} build; run npm run build first`);
  execFileSync(process.execPath, [join(root, 'scripts', 'build-baseline.mjs'), tag], { cwd: root, stdio: 'inherit' });
  if ((await builtVersion('dist-baseline')) !== previous) fail(`dist-baseline/ is not a ${previous} build`);
  console.log(`bench:release: ${runs} runs of ${version}, then ${previousRuns} of ${previous}. Keep the machine idle.`);
  for (let i = 1; i <= runs; i++) {
    if (bench('dist', join(out, `release-run${i}`)) !== 0) {
      fail(`${version} failed its render bench budgets on run ${i}; fix the regression before publishing a benchmark`);
    }
  }
  for (let i = 1; i <= previousRuns; i++) bench('dist-baseline', join(out, `previous-run${i}`));
}

/** Every run's rows, by kind, checked to be timings of the expected version. */
function collect(kind, expected) {
  const dirs = existsSync(out) ? readdirSync(out).filter((d) => d.startsWith(`${kind}-run`)).sort() : [];
  if (dirs.length === 0) fail(`no ${kind} runs in ${out}`);
  return dirs.map((d) => rowFiles.map((f) => {
    const rec = JSON.parse(readFileSync(join(out, d, f), 'utf8'));
    if (rec.env.version !== expected) fail(`${join(d, f)} timed ${rec.env.version}, expected ${expected}`);
    return rec;
  }));
}

const releaseRuns = collect('release', version);
const previousRunsData = collect('previous', previous);

const cells = [];
for (const renderer of BENCH_RENDERERS) {
  for (const bars of BENCH_BAR_COUNTS) {
    for (const metric of BENCH_METRICS) {
      const p95s = (all) => all.map((run) => {
        const rec = run.find((r) => r.renderer === renderer && r.bars === bars);
        return rec.rows.find((row) => row.metric === metric).p95;
      });
      cells.push({ renderer, bars, metric, releaseP95: p95s(releaseRuns), previousP95: p95s(previousRunsData) });
    }
  }
}

const env = releaseRuns[0][0].env;
const cpu = cpus();
const entry = {
  version,
  date: new Date().toISOString().slice(0, 10),
  comparedWith: previous,
  runs: { release: releaseRuns.length, previous: previousRunsData.length },
  machine: {
    cpu: cpu[0]?.model.trim() ?? 'unknown CPU',
    logicalCpus: cpu.length,
    os: `${{ Windows_NT: 'Windows', Darwin: 'macOS' }[osType()] ?? osType()} ${osRelease()}`,
    browser: `headless Chromium ${env.userAgent.match(/Chrome\/([\d.]+)/)?.[1] ?? ''}`.trim(),
    gl: /SwiftShader/i.test(env.gl) ? 'software GL (SwiftShader)' : env.gl,
    dpr: env.dpr,
  },
  cells,
};

const data = readReleases();
data.releases = [entry, ...data.releases.filter((r) => r.version !== version)]
  .sort((a, b) => compareVersions(b.version, a.version));
writeFileSync(DATA_FILE, `${JSON.stringify(data, null, 2)}\n`);
writePage(data);
console.log(`bench:release: wrote the ${version} entry (against ${previous}) to benchmarks/releases.json and website/pages/benchmarks.mdx`);
