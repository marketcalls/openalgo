/**
 * The compatibility gate, second half: the documents earlier releases saved.
 *
 *   node scripts/generate-saved-documents.mjs             # rewrite tests/fixtures/saved-documents/<version>/
 *   node scripts/generate-saved-documents.mjs --check     # this build loads each fixture in a real browser
 *   node scripts/generate-saved-documents.mjs --self      # each release loads the fixtures it wrote
 *   node scripts/generate-saved-documents.mjs --reverse   # this build writes, the previous release loads
 *   node scripts/generate-saved-documents.mjs --reverse 2.5.1   # or the release named
 *
 * A host keeps what the chart hands it: a chart state with its studies, a
 * drawings document, the widget's persisted layout, a workspace and an alert
 * list. Each earlier release in BASELINES (scripts/compat-packages.mjs) writes
 * those five, through its own public API, in Chromium, from the packed
 * release as published. scripts/fixtures/saved-documents.html builds a chart
 * the way a host does on a seeded random walk in NSE sessions and saves it,
 * as seven files: the widget layout both as persisted and as `getState`
 * returns it, and the workspace both exported and as its catalog stored it.
 * The page replaces Math.random, crypto.randomUUID and Date.now with
 * deterministic ones before any library code runs, so a rerun writes the same
 * bytes and the fixtures only change when a release is added.
 *
 * The documents are committed, and tests/saved-documents.test.ts loads each on
 * the current code and saves it again. The other modes print what each
 * document became, loaded and saved again, and write nothing: `--check` is
 * the unit test's load in a real browser against the build, `--self` tells a
 * change the old release makes to its own documents from one this release
 * makes, and `--reverse` reports what a downgrade meets. None runs in CI.
 */
import { createServer } from 'node:http';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { extname, join, resolve, sep } from 'node:path';
import process from 'node:process';
import { chromium } from '@playwright/test';
import { BASELINES, packedRelease } from './compat-packages.mjs';

const ROOT = resolve(import.meta.dirname, '..');
const OUT = join(ROOT, 'tests', 'fixtures', 'saved-documents');
const PAGE = join(ROOT, 'scripts', 'fixtures', 'saved-documents.html');
const MIME = { '.html': 'text/html', '.mjs': 'text/javascript', '.js': 'text/javascript', '.map': 'application/json' };

/** Run before any page script: every source of chance and time the library reads, fixed. */
function deterministic() {
  let seed = 20260910;
  Math.random = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 2 ** 32; };
  let uuid = 0;
  crypto.randomUUID = () => `00000000-0000-4000-8000-${String(++uuid).padStart(12, '0')}`;
  const now = Date.UTC(2026, 8, 10, 6, 32); // 12:02 IST on the Thursday of the fixture week
  Date.now = () => now;
}

/** Serve the harness, and each build's dist under /lib/<label>/: a release version, or `current` for the working tree. */
function serve() {
  const server = createServer((req, res) => {
    const path = decodeURIComponent((req.url ?? '/').split('?')[0]);
    let file = null;
    if (path === '/') file = PAGE;
    const lib = /^\/lib\/([^/]+)\/([^/]+)$/.exec(path);
    if (lib !== null) {
      const dist = lib[1] === 'current' ? join(ROOT, 'dist') : join(packedRelease(lib[1]), 'dist');
      const target = resolve(dist, lib[2]);
      if (target.startsWith(dist + sep)) file = target;
    }
    try {
      if (file === null) throw new Error('not found');
      const body = readFileSync(file);
      res.writeHead(200, { 'Content-Type': MIME[extname(file)] ?? 'application/octet-stream' });
      res.end(body);
    } catch {
      res.writeHead(404);
      res.end('not found');
    }
  });
  // An ephemeral port: this never shares a fixed port with a test server.
  return new Promise((done) => server.listen(0, '127.0.0.1', () => done(server)));
}

async function openHarness(browser, url, label) {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.addInitScript(deterministic);
  await page.goto(`${url}/?lib=${label}`);
  await page.waitForFunction(() => window.harnessReady === true, null, { timeout: 30_000 })
    .catch(() => { throw new Error(`the harness did not start on ${label}: ${errors.join('; ') || 'no error reported'}`); });
  return { page, errors };
}

/** Pretty JSON with a newline, the way the repository keeps its data files. */
const json = (value) => `${JSON.stringify(value, null, 2)}\n`;

const NAMES = ['chart-state', 'drawings', 'alerts', 'widget-storage', 'widget-state', 'workspace', 'workspace-catalog'];
const readFixtures = (version) => Object.fromEntries(NAMES.map((name) => [name, JSON.parse(readFileSync(join(OUT, version, `${name}.json`), 'utf8'))]));

/** Each path where two JSON values differ, at the shallowest point, as tests/saved-documents.test.ts lists them. */
function changes(before, after, path = []) {
  if (Object.is(before, after)) return [];
  const here = path.join('.');
  if (before === undefined) return [`added ${here}`];
  if (after === undefined) return [`removed ${here}`];
  if (typeof before === 'object' && before !== null && typeof after === 'object' && after !== null
    && Array.isArray(before) === Array.isArray(after)) {
    return [...new Set([...Object.keys(before), ...Object.keys(after)])].flatMap((k) => changes(before[k], after[k], [...path, k]));
  }
  return [`changed ${here}`];
}

/** One build loads documents and saves them again: what it made of each, and what changed. */
async function loadWith(browser, url, label, documents) {
  const reader = await openHarness(browser, url, label);
  const loaded = await reader.page.evaluate((d) => window.harness.load(d), documents);
  if (reader.errors.length) throw new Error(`${label} raised page errors: ${reader.errors.join('; ')}`);
  await reader.page.close();
  return Object.fromEntries(Object.entries(loaded).map(([name, r]) => [name,
    r.refused !== undefined ? r : { ...r.summary, changes: changes(documents[name], r.saved) }]));
}

async function main() {
  const args = process.argv.slice(2);
  // Fetch every release first, so a registry failure stops the run before any file is written.
  for (const b of BASELINES) packedRelease(b.version);
  const server = await serve();
  const url = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch();
  try {
    if (args.includes('--reverse')) {
      const named = args[args.indexOf('--reverse') + 1];
      const previous = named !== undefined && /^\d+\.\d+\.\d+$/.test(named) ? named : BASELINES[BASELINES.length - 1].version;
      const writer = await openHarness(browser, url, 'current');
      const written = await writer.page.evaluate(() => window.harness.write());
      console.log(`generate-saved-documents: the working tree (version ${written.version}) wrote, ${previous} loaded and saved again:`);
      console.log(json(await loadWith(browser, url, previous, written.documents)));
      return;
    }
    if (args.includes('--check') || args.includes('--self')) {
      for (const b of BASELINES) {
        const reader = args.includes('--self') ? b.version : 'current';
        console.log(`generate-saved-documents: ${reader === 'current' ? 'the working tree' : reader} loaded what ${b.version} wrote and saved it again:`);
        console.log(json(await loadWith(browser, url, reader, readFixtures(b.version))));
      }
      return;
    }
    let bars = null;
    for (const b of BASELINES) {
      const writer = await openHarness(browser, url, b.version);
      const written = await writer.page.evaluate(() => window.harness.write());
      if (written.version !== b.version) throw new Error(`the page ran ${written.version}, not ${b.version}`);
      if (writer.errors.length) throw new Error(`${b.version} raised page errors: ${writer.errors.join('; ')}`);
      const dir = join(OUT, b.version);
      mkdirSync(dir, { recursive: true });
      for (const [name, doc] of Object.entries(written.documents)) writeFileSync(join(dir, `${name}.json`), json(doc));
      if (bars !== null && JSON.stringify(bars) !== JSON.stringify(written.bars)) throw new Error('the releases were given different bars');
      bars = written.bars;
      console.log(`generate-saved-documents: ${b.version} wrote ${Object.keys(written.documents).length} documents to ${dir}`);
      await writer.page.close();
    }
    // One bar a line: the bars are data the documents sit on, not a document to read field by field.
    writeFileSync(join(OUT, 'bars.json'), json(bars).replace(/\{\n\s+"time"[^}]*\}/g, (bar) => bar.replace(/\n\s*/g, ' ')));
  } finally {
    await browser.close();
    server.close();
  }
}

main().catch((error) => {
  console.error(`generate-saved-documents: ${error.message}`);
  process.exit(1);
});
