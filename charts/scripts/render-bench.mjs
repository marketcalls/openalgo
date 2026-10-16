/**
 * Run the render bench (tests/e2e/render-bench.perf.ts) on its own.
 *
 *   npm run build
 *   npm run bench:render                     # every row, Chromium
 *   npm run bench:render -- --grep webgl2    # extra arguments go to Playwright
 *
 * The bench is a Playwright project only while OAC_RENDER_BENCH is set, so a
 * plain `playwright test` never times frames beside a hundred other specs.
 * This sets it the same way on every shell, which an npm script cannot do
 * without a dependency. Results land in artifacts/render-bench/ (one JSON per
 * row, with every sample) unless OAC_RENDER_BENCH_OUT names another directory,
 * and a summary follows the run: in the terminal, and in the job summary when
 * GitHub Actions provides one, so a runner's numbers can be read without
 * downloading anything.
 */
import { spawnSync } from 'node:child_process';
import { appendFileSync, existsSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { BENCH_BAR_COUNTS, BENCH_METRICS, BENCH_METRIC_LABELS, BENCH_RENDERERS } from './render-bench-budgets.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const out = resolve(process.env.OAC_RENDER_BENCH_OUT ?? join(root, 'artifacts', 'render-bench'));

if (!existsSync(join(root, 'dist', 'openalgo-charts.mjs'))) {
  console.error('render bench: no dist/ build. Run `npm run build` first.');
  process.exit(1);
}

// A row this run does not reach must not be summarised from an earlier run.
// Only the bench's own file names are removed: the directory may be shared.
const rowFiles = BENCH_RENDERERS.flatMap((r) => BENCH_BAR_COUNTS.map((b) => `${r}-${b}.json`));
if (existsSync(out)) for (const name of readdirSync(out)) if (rowFiles.includes(name)) rmSync(join(out, name));

const cli = join(root, 'node_modules', '@playwright', 'test', 'cli.js');
const result = spawnSync(
  process.execPath,
  [cli, 'test', '--project=render-bench', ...process.argv.slice(2)],
  { cwd: root, stdio: 'inherit', env: { ...process.env, OAC_RENDER_BENCH: '1', OAC_RENDER_BENCH_OUT: out } },
);
if (result.error) {
  console.error(`render bench: could not start Playwright: ${result.error.message}`);
  process.exit(1);
}

const records = rowFiles.filter((name) => existsSync(join(out, name)))
  .map((name) => JSON.parse(readFileSync(join(out, name), 'utf8')));
if (records.length > 0) {
  const head = ['Renderer', 'Bars', ...BENCH_METRICS.map((m) => `${BENCH_METRIC_LABELS[m]} (budget)`)];
  const rows = records.map((rec) => [
    rec.renderer,
    rec.bars.toLocaleString('en-US'),
    ...BENCH_METRICS.map((m) => {
      const row = rec.rows.find((r) => r.metric === m);
      return `${row.p95} ms (${row.budget} ms)${row.p95 > row.budget ? ' over' : ''}`;
    }),
  ]);
  const env = records[0].env;
  const table = [
    `Render bench, openalgo-charts ${env.version}: ${env.userAgent.match(/Chrome\/[\d.]+/)?.[0] ?? 'Chromium'}, ${env.gl}, ${env.cores} logical CPUs`,
    '',
    `| ${head.join(' | ')} |`,
    `| ${head.map(() => '---').join(' | ')} |`,
    ...rows.map((r) => `| ${r.join(' | ')} |`),
  ].join('\n');
  console.log(`\n${table}\n`);
  if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, `${table}\n`);
}
process.exit(result.status ?? 1);
