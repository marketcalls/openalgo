/**
 * scripts/check-cycles.mjs holds the "no import cycles" gate (CLAUDE.md,
 * Quality gates: Structure). The fixture in scripts/fixtures/cycles has one
 * loop of each kind the check tells apart: a runtime loop closed through the
 * package name, one closed by an import whose names are all types but which
 * still loads its module, two that only types close, and a dynamic import that
 * closes none. The run against src is `npm run check:cycles`; this proves the
 * walk and the ratchet underneath it.
 */
import { describe, expect, it } from 'vitest';
import { measureCycles, ratchetProblems } from '../scripts/check-cycles.mjs';

// Same root derivation as line-caps.test.ts: the suite carries no Node typings.
const ROOT = decodeURIComponent(new URL('..', import.meta.url).pathname).replace(/^\/([A-Za-z]:)/, '$1');
const FIXTURE = `${ROOT}scripts/fixtures/cycles`;

describe('check-cycles on a fixture', () => {
  const measured = measureCycles(FIXTURE);

  it('finds the runtime loops, through the package name and through an import of types only', () => {
    expect(measured.runtime).toEqual([
      ['src/index.ts', 'src/value-a.ts', 'src/value-b.ts'],
      ['src/inline-a.ts', 'src/inline-b.ts'],
    ]);
  });

  it('adds the loops only types close to the type-inclusive set, and never a dynamic import', () => {
    expect(measured.typeInclusive).toEqual([
      ['src/index.ts', 'src/value-a.ts', 'src/value-b.ts'],
      ['src/inline-a.ts', 'src/inline-b.ts'],
      ['src/reexport-a.ts', 'src/reexport-b.ts'],
      ['src/type-a.ts', 'src/type-b.ts'],
    ]);
    expect(measured.typeInclusive.flat()).not.toContain('src/lazy-a.ts');
  });

  it('reports an import it cannot resolve rather than dropping the edge', () => {
    expect(measured.unresolved).toEqual(['src/broken.ts:2 ./missing']);
  });
});

describe('the type-inclusive ratchet', () => {
  it('passes the sizes it was measured at', () => {
    expect(ratchetProblems([3, 2, 2, 2], [3, 2, 2, 2])).toEqual([]);
  });

  it('fails a new component and a component that grew, whatever order they come in', () => {
    expect(ratchetProblems([3, 2, 2, 2, 2], [3, 2, 2, 2])).toHaveLength(1);
    expect(ratchetProblems([2, 4, 2, 2], [3, 2, 2, 2])).toHaveLength(1);
    // Two components merged: one fewer, but the largest grew.
    expect(ratchetProblems([5, 2, 2], [3, 2, 2, 2])).toHaveLength(1);
  });

  it('fails a ratchet left above what it measures, so it is lowered as the loops shrink', () => {
    const [problem] = ratchetProblems([3, 2], [3, 2, 2, 2]);
    expect(problem).toContain('[3, 2]');
  });
});
