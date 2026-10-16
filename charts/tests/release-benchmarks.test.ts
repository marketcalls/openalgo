/**
 * Every release from 2.5.8 on publishes its benchmark: the render bench on the
 * new build against the release before it, in benchmarks/releases.json and on
 * the website's Benchmarks page (CLAUDE.md, before every npm publish). The
 * version bump is the commit that must carry the entry, so this fails a
 * package version that has none, the way a release without its changelog
 * entry would be caught in review.
 */
import { describe, expect, it } from 'vitest';
import pkg from '../package.json';
import data from '../benchmarks/releases.json';

const RENDERERS = ['canvas2d', 'webgl2'];
const BARS = [10000, 50000, 200000];
const METRICS = ['pan', 'zoomOut', 'tick'];

type Cell = { renderer: string; bars: number; metric: string; releaseP95: number[]; previousP95: number[] };
type Release = {
  version: string; date: string; comparedWith: string;
  runs: { release: number; previous: number };
  machine: { cpu: string; logicalCpus: number; os: string; browser: string; gl: string; dpr: number };
  cells: Cell[];
};

const releases = data.releases as Release[];
const semver = (v: string): number[] => v.split('.').map(Number);
const newer = (a: string, b: string): boolean => {
  const [x, y] = [semver(a), semver(b)];
  for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] > y[i];
  return false;
};

describe('release benchmarks', () => {
  it('has an entry for the package version', () => {
    expect(releases.map((r) => r.version), `run npm run bench:release for ${pkg.version}`).toContain(pkg.version);
  });

  it('lists each version once, newest first, each against an older release', () => {
    const versions = releases.map((r) => r.version);
    expect(new Set(versions).size).toBe(versions.length);
    for (let i = 1; i < releases.length; i++) expect(newer(releases[i - 1].version, releases[i].version)).toBe(true);
    for (const r of releases) {
      expect(newer(r.version, r.comparedWith), `${r.version} is compared with ${r.comparedWith}`).toBe(true);
      expect(r.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(r.machine.cpu.length).toBeGreaterThan(0);
      expect(r.machine.logicalCpus).toBeGreaterThan(0);
    }
  });

  it('holds every renderer, bar count and scenario, with the runs it claims', () => {
    for (const r of releases) {
      expect(r.cells).toHaveLength(RENDERERS.length * BARS.length * METRICS.length);
      for (const renderer of RENDERERS) {
        for (const bars of BARS) {
          for (const metric of METRICS) {
            const c = r.cells.find((x) => x.renderer === renderer && x.bars === bars && x.metric === metric);
            expect(c, `${r.version} ${renderer} ${bars} ${metric}`).toBeDefined();
            expect(c!.releaseP95).toHaveLength(r.runs.release);
            expect(c!.previousP95).toHaveLength(r.runs.previous);
            for (const p of [...c!.releaseP95, ...c!.previousP95]) expect(p).toBeGreaterThan(0);
          }
        }
      }
    }
  });
});
