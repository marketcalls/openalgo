import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { createServer } from 'node:http';
import { cp, mkdir, readFile, readdir, writeFile, appendFile } from 'node:fs/promises';
import { cpus, freemem, platform, release, tmpdir, totalmem } from 'node:os';
import { basename, dirname, extname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { setTimeout as delay } from 'node:timers/promises';
import { chromium } from '@playwright/test';
import { assessRun, THRESHOLDS } from './browser-endurance-metrics.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const { values } = parseArgs({ options: {
  'duration-seconds': { type: 'string', default: '1800' },
  'sample-seconds': { type: 'string', default: '30' },
  'warmup-seconds': { type: 'string', default: '5' },
  cycles: { type: 'string', default: '30' },
  bars: { type: 'string', default: '2000' },
  charts: { type: 'string', default: '2' },
  'tick-hz': { type: 'string', default: '10' },
  output: { type: 'string' },
  'dist-directory': { type: 'string' },
  'heap-snapshot': { type: 'boolean', default: false },
  'memory-mode': { type: 'string', default: 'quiescent' },
  headed: { type: 'boolean', default: false },
  help: { type: 'boolean', default: false },
} });

if (values.help) {
  console.log('Usage: node scripts/browser-endurance.mjs [--duration-seconds 1800] [--sample-seconds 30] [--warmup-seconds 5] [--cycles 30] [--bars 2000] [--charts 2] [--tick-hz 10] [--headed] [--heap-snapshot] [--memory-mode uninterrupted|quiescent] [--dist-directory <existing dist>] [--output <new p3- directory>]');
  process.exit(0);
}

function number(name, min, max, integer = false) {
  const value = Number(values[name]);
  if (!Number.isFinite(value) || value < min || value > max || (integer && !Number.isInteger(value))) throw new Error(`--${name} must be ${integer ? 'an integer' : 'a number'} from ${min} to ${max}`);
  return value;
}

const workload = {
  durationSeconds: number('duration-seconds', 10, 86400),
  sampleSeconds: number('sample-seconds', 1, 300),
  warmupSeconds: number('warmup-seconds', 1, 120),
  cycles: number('cycles', 1, 1000, true),
  bars: number('bars', 200, 100000, true),
  charts: number('charts', 1, 4, true),
  tickHz: number('tick-hz', 1, 60),
  indicators: ['ema', 'bollinger', 'rsi', 'macd', 'volume'],
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 1,
  renderer: 'canvas2d',
  update: 'same timestamp forming-bar replacement, no append',
};
if (workload.sampleSeconds > workload.durationSeconds / 2) throw new Error('sample interval must permit at least three memory observations, including the baseline');
if (!['uninterrupted', 'quiescent'].includes(values['memory-mode'])) throw new Error('--memory-mode must be uninterrupted or quiescent');

const stamp = new Date().toISOString().replace(/[:.]/g, '-');
const output = resolve(values.output ?? join(tmpdir(), `p3-browser-endurance-${stamp}`));
const dist = resolve(values['dist-directory'] ?? join(root, 'dist'));
if (!basename(output).startsWith('p3-')) throw new Error('output directory name must begin with p3-');
await mkdir(dirname(output), { recursive: true });
await mkdir(output);
const snapshot = join(output, 'snapshot');
await mkdir(snapshot);
const report = {
  schemaVersion: 1,
  evidence: 'current-candidate synthetic workload',
  status: 'running',
  startedAt: new Date().toISOString(),
  pid: process.pid,
  command: process.argv,
  workload,
  memoryProtocol: { mode: values['memory-mode'], samplingPausesMs: 0, missedTicksReplayed: false, frameTimingContinuesDuringSampling: true },
  thresholds: THRESHOLDS,
  host: { platform: platform(), release: release(), architecture: process.arch, node: process.version, cpuModel: cpus()[0]?.model, logicalCpus: cpus().length, totalMemoryBytes: totalmem(), freeMemoryBytesAtStart: freemem() },
  browser: { name: 'chromium', headless: !values.headed },
  samples: [],
  errors: [],
  limitations: [
    'Synthetic deterministic bars, not live-feed or connected-broker evidence.',
    'The requested wall-clock duration is not a full trading day unless actually configured and completed.',
    'Chromium Canvas2D at the declared viewport and DPR only; no Firefox, WebKit, mobile or WebGL performance claim.',
    'CDP collected JavaScript heap and DOM counters do not measure total browser, GPU, canvas backing-store or process memory.',
    'Forced garbage collection and pixel/screenshot probes add overhead; frame gates include collection during the live phase.',
    'Frame callbacks and two-frame pointer latency are responsiveness proxies, not physical display presentation or input-to-photon measurements.',
    'Thresholds are regression budgets for this declared workload, not a contractual latency or memory guarantee.',
    'Concurrent host activity is not controlled; compare runs only with their recorded device and workload context.',
  ],
};
let browser;
let server;

async function writeReport() {
  await writeFile(join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n');
}

async function hashes(directory) {
  const result = {};
  for (const name of (await readdir(directory)).filter(name => name.endsWith('.mjs')).sort()) {
    result[name] = createHash('sha256').update(await readFile(join(directory, name))).digest('hex');
  }
  return result;
}

try {
  report.source = {
    commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim(),
    workingTree: execFileSync('git', ['status', '--short'], { cwd: root, encoding: 'utf8' }).trim(),
    distInputDirectory: dist,
  };
  const before = await hashes(dist);
  if (!before['openalgo-charts.mjs'] || !before['openalgo-charts.indicators.mjs']) throw new Error('Build dist before running browser endurance');
  await cp(dist, join(snapshot, 'dist'), { recursive: true });
  await cp(join(root, 'scripts/fixtures/browser-endurance.html'), join(snapshot, 'index.html'));
  const copied = await hashes(join(snapshot, 'dist'));
  const after = await hashes(dist);
  if (JSON.stringify(before) !== JSON.stringify(copied) || JSON.stringify(before) !== JSON.stringify(after)) throw new Error('dist changed while snapshotting; rerun after the build completes');
  report.source.distSha256 = copied;
  report.source.harnessSha256 = {};
  for (const file of ['scripts/browser-endurance.mjs', 'scripts/browser-endurance-metrics.mjs', 'scripts/fixtures/browser-endurance.html']) {
    report.source.harnessSha256[file] = createHash('sha256').update(await readFile(join(root, file))).digest('hex');
  }
  await writeFile(join(output, 'manifest.json'), JSON.stringify(report.source, null, 2) + '\n');

  server = createServer(async (request, response) => {
    try {
      const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
      const file = resolve(snapshot, '.' + (pathname === '/' ? '/index.html' : pathname));
      if (!file.startsWith(snapshot + sep)) { response.writeHead(403); response.end(); return; }
      const body = await readFile(file);
      response.writeHead(200, { 'Content-Type': extname(file) === '.html' ? 'text/html' : 'text/javascript', 'Cache-Control': 'no-store' });
      response.end(body);
    } catch {
      response.writeHead(404); response.end('Not found');
    }
  });
  await new Promise((accept, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', accept); });
  const origin = `http://127.0.0.1:${server.address().port}`;
  report.serverOrigin = origin;
  browser = await chromium.launch({ headless: !values.headed, args: ['--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows'] });
  report.browser.version = browser.version();
  report.browser.backgroundThrottlingDisabled = true;
  const context = await browser.newContext({ viewport: workload.viewport, deviceScaleFactor: workload.deviceScaleFactor });
  await context.route('**/*', route => {
    if (new URL(route.request().url()).origin === origin) return route.continue();
    report.errors.push(`Unexpected external request: ${route.request().url()}`);
    return route.abort();
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on('pageerror', error => report.errors.push(String(error)));
  page.on('crash', () => report.errors.push('Browser page crashed'));
  page.on('console', message => { if (message.type() === 'error') report.errors.push(message.text()); });
  await page.goto(origin);
  await page.waitForFunction(() => Boolean(window.endurance));
  report.browser.device = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl');
    const debug = gl?.getExtension('WEBGL_debug_renderer_info');
    const device = { userAgent: navigator.userAgent, hardwareConcurrency: navigator.hardwareConcurrency, deviceMemoryGiB: navigator.deviceMemory ?? null, pixelRatio: devicePixelRatio, screen: { width: screen.width, height: screen.height }, visibility: document.visibilityState, graphicsRenderer: debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : null };
    gl?.getExtension('WEBGL_lose_context')?.loseContext();
    return device;
  });
  report.runtimeVersion = await page.evaluate(() => window.endurance.version);
  const cdp = await context.newCDPSession(page);
  await cdp.send('HeapProfiler.enable');
  async function collectedMemory() {
    const uncollected = await cdp.send('Runtime.getHeapUsage');
    const paused = values['memory-mode'] === 'quiescent' ? await page.evaluate(() => window.endurance.pauseUpdates()) : null;
    let result;
    try {
      await page.evaluate(() => window.endurance.settle());
      await cdp.send('HeapProfiler.collectGarbage');
      await delay(50);
      await cdp.send('HeapProfiler.collectGarbage');
      const heap = await cdp.send('Runtime.getHeapUsage');
      const dom = await cdp.send('Memory.getDOMCounters');
      result = { heap: heap.usedSize, uncollectedHeapBeforeCollection: uncollected.usedSize, totalHeap: heap.totalSize, embedderHeap: heap.embedderHeapUsedSize ?? null, backingStorage: heap.backingStorageSize ?? null, ...dom, samplingPauseMs: 0, ticksDuringCollection: null };
    } finally {
      if (paused) {
        const resumed = await page.evaluate(paused => window.endurance.resumeUpdates(paused), paused);
        if (result) result.ticksDuringCollection = resumed.ticksDuringCollection;
        if (paused.running) {
          report.memoryProtocol.samplingPausesMs += resumed.elapsedMs;
          if (result) result.samplingPauseMs = resumed.elapsedMs;
        }
      }
    }
    return result;
  }

  console.log(`Browser endurance PID ${process.pid}; artifacts ${output}; snapshot ready; ${origin}`);
  for (let i = 0; i < 5; i++) await page.evaluate(bars => window.endurance.cycle(bars), workload.bars);
  const teardownBefore = await collectedMemory();
  let minimumCyclePixels = Infinity;
  for (let i = 0; i < workload.cycles; i++) {
    minimumCyclePixels = Math.min(minimumCyclePixels, await page.evaluate(bars => window.endurance.cycle(bars), workload.bars));
  }
  const teardownAfter = await collectedMemory();
  report.teardown = { cycles: workload.cycles, heapBefore: teardownBefore.heap, heapAfter: teardownAfter.heap, nodesBefore: teardownBefore.nodes, nodesAfter: teardownAfter.nodes, listenersBefore: teardownBefore.jsEventListeners, listenersAfter: teardownAfter.jsEventListeners, canvasesAfter: await page.locator('canvas').count(), minimumCyclePixels };
  if (minimumCyclePixels < THRESHOLDS.candlePixels) report.errors.push('Create/destroy cycles did not paint enough candle pixels');
  await page.evaluate(({ charts, bars, tickHz }) => { window.endurance.create(charts, bars); window.endurance.start(tickHz); }, workload);
  await delay(workload.warmupSeconds * 1000);
  await page.evaluate(() => window.endurance.settle());
  report.rendering = { before: await page.evaluate(() => window.endurance.paintProbe()), after: [], changed: [] };
  await page.screenshot({ path: join(output, 'start.png') });
  await page.evaluate(() => window.endurance.reset());
  const started = performance.now();
  report.liveStartedAt = new Date().toISOString();

  async function pointerProbe(index) {
    const previous = await page.evaluate(() => window.endurance.pointerArm());
    await page.mouse.move(100 + (index % 8) * 43, 150 + (index % 4) * 20);
    await page.waitForFunction(previous => window.endurance.pointerDone() > previous, previous);
  }

  async function sample() {
    const inspected = await page.evaluate(() => window.endurance.inspect());
    const memory = await collectedMemory();
    const value = { seconds: (performance.now() - started) / 1000, ...memory, ticks: inspected.ticks, bars: inspected.bars, timing: inspected.timing, interaction: inspected.interaction };
    report.samples.push(value);
    await appendFile(join(output, 'samples.ndjson'), JSON.stringify(value) + '\n');
    await writeReport();
    console.log(`LIVE ${value.seconds.toFixed(1)}s / ${workload.durationSeconds}s; ticks ${value.ticks}; heap ${(value.heap / 1048576).toFixed(2)} MiB; frame p99 ${value.timing.p99 ?? 'pending'}ms`);
  }

  await pointerProbe(0);
  await sample();
  while ((performance.now() - started) / 1000 < workload.durationSeconds) {
    const remaining = workload.durationSeconds * 1000 - (performance.now() - started);
    await delay(Math.max(1, Math.min(workload.sampleSeconds * 1000, remaining)));
    await pointerProbe(report.samples.length);
    await sample();
  }
  await page.evaluate(() => window.endurance.stop());
  report.elapsedSeconds = (performance.now() - started) / 1000;
  const last = await page.evaluate(() => window.endurance.inspect());
  report.timing = last.timing;
  report.interaction = last.interaction;
  report.rendering.after = await page.evaluate(() => window.endurance.paintProbe());
  report.rendering.changed = report.rendering.after.map((probe, i) => probe.hash !== report.rendering.before[i].hash);
  await page.screenshot({ path: join(output, 'end.png') });
  if (values['heap-snapshot']) {
    report.heapSnapshot = { file: 'live-end.heapsnapshot', startedAt: new Date().toISOString(), phase: 'after live measurement, before chart destruction', includedInFrameTiming: false };
    const chunks = [];
    const receive = ({ chunk }) => chunks.push(chunk);
    cdp.on('HeapProfiler.addHeapSnapshotChunk', receive);
    try {
      await cdp.send('HeapProfiler.takeHeapSnapshot', { reportProgress: false });
      await writeFile(join(output, report.heapSnapshot.file), chunks.join(''));
    } finally {
      cdp.off('HeapProfiler.addHeapSnapshotChunk', receive);
      report.heapSnapshot.finishedAt = new Date().toISOString();
    }
  }
  await page.evaluate(() => window.endurance.destroy());
  report.finalMemory = await collectedMemory();
  report.finalCanvases = await page.locator('canvas').count();
  report.gates = assessRun(report);
  report.status = report.gates.every(gate => gate.pass) ? 'passed' : 'failed';
} catch (error) {
  report.status = 'failed';
  report.errors.push(error.stack ?? String(error));
} finally {
  await browser?.close().catch(error => report.errors.push(String(error)));
  if (server) await new Promise(accept => server.close(accept));
  if (report.errors.length) report.status = 'failed';
  report.finishedAt = new Date().toISOString();
  await writeReport();
  const lines = [
    '# Browser endurance report', '',
    `Status: ${report.status}. Evidence: ${report.evidence}.`, '',
    `Runtime: ${report.runtimeVersion ?? 'unavailable'}. Chromium: ${report.browser.version ?? 'unavailable'}.`,
    `Device: ${report.host.cpuModel}, ${report.host.logicalCpus} logical CPUs, ${(report.host.totalMemoryBytes / 1073741824).toFixed(1)} GiB RAM, ${report.host.platform} ${report.host.release}.`,
    `Requested live phase: ${workload.durationSeconds}s. Measured: ${report.elapsedSeconds?.toFixed(2) ?? 'incomplete'}s.`, '',
    '| Gate | Result | Observed | Limit |', '| --- | --- | --- | --- |',
    ...(report.gates ?? []).map(gate => `| ${gate.name} | ${gate.pass ? 'PASS' : 'FAIL'} | ${JSON.stringify(gate.value)} | ${gate.limit} |`), '',
    '## Limitations', '', ...report.limitations.map(value => `- ${value}`), '',
    '## Errors', '', ...(report.errors.length ? report.errors.map(value => `- ${value}`) : ['None.']), '',
  ];
  await writeFile(join(output, 'summary.md'), lines.join('\n'));
  console.log(`Browser endurance ${report.status.toUpperCase()}: ${join(output, 'report.json')}`);
  for (const gate of report.gates ?? []) if (!gate.pass) console.error(`FAIL ${gate.name}: ${JSON.stringify(gate.value)} (limit ${gate.limit})`);
  for (const error of report.errors) console.error(error);
  if (report.status !== 'passed') process.exitCode = 1;
}
