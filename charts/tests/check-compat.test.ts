/**
 * scripts/check-compat.mjs holds every tier's declarations to earlier releases,
 * and a gate like that is worth only what it catches. The fixture in
 * scripts/fixtures/compat is two releases of a small package whose second
 * release makes one change per rule: each must come out as exactly the finding
 * named here, with the right direction, and nothing it should let through may
 * come out at all. The run against the published releases is `npm run
 * check:compat`; this proves the walk underneath it.
 */
import { describe, expect, it } from 'vitest';
import { comparePackages, deprecations, KINDS } from '../scripts/check-compat.mjs';

// Same root derivation as line-caps.test.ts: the suite carries no Node typings.
const ROOT = decodeURIComponent(new URL('..', import.meta.url).pathname).replace(/^\/([A-Za-z]:)/, '$1');
const FIXTURE = `${ROOT}scripts/fixtures/compat/`;
const RETIRED = [{ names: ['retiredHelper'], removedIn: '3.0.0' }];

let compared: ReturnType<typeof comparePackages> | undefined;
/** The fixture compared once for the whole file: it builds a program over both releases. */
const fixture = (): ReturnType<typeof comparePackages> =>
  (compared ??= comparePackages(`${FIXTURE}old`, `${FIXTURE}new`, RETIRED));

/** Each finding as one line: status, kind, where, direction and detail. */
const lines = (): string[] => fixture().findings
  .map((f) => `${f.status} ${f.kind} ${f.where} (${f.direction})${f.detail ? ` ${f.detail}` : ''}`)
  .sort();

describe('check-compat on a fixture of two releases', () => {
  it('finds each removal and narrowing, in the direction the value travels, and nothing else', () => {
    expect(lines()).toEqual([
      'additive variant-added Chart.seriesType() (library hands back) "area"',
      'deprecated export-removed retiredHelper (library hands back)',
      // A method parameter: the compiler would pass this, since it checks
      // method parameters both ways round.
      'narrowing no-longer-accepted Chart.setPrecision(digits) (host passes in) "auto"',
      'narrowing no-longer-accepted ChartOptions.scale (host passes in) "log"',
      // A field of the payload the library hands a host callback set in an option.
      'narrowing removed ClickEvent.time (library hands back)',
      // An optional option removed: the compiler accepts an object literal
      // written for the old release, and the option silently stops working.
      'narrowing removed ChartOptions.legacyTheme (host passes in)',
      'narrowing export-removed legacyHelper (library hands back)',
      'narrowing may-now-return SavedState.zoom (library hands back) undefined',
      'narrowing new-required DataFeed.close (host passes in)',
      'narrowing no-longer-value Marker (library hands back)',
      'narrowing now-required ChartOptions.locale (host passes in)',
      'narrowing tier-removed openalgo-charts/extra (library hands back)',
    ].sort());
  });

  it('lets through what only adds: new exports, new members, a constant value, private and handle members', () => {
    const where = fixture().findings.map((f) => f.where);
    expect(fixture().tiers[0]?.added).toEqual(['newHelper']);
    for (const quiet of ['ChartOptions.height', 'Chart.resize', 'SAVE_DELAY_MS', 'Chart._secret', 'IndicatorApi.barSource', 'ChartOptions.width']) {
      expect(where.some((w) => w.startsWith(quiet))).toBe(false);
    }
  });

  it('names every kind it reports in words', () => {
    for (const f of fixture().findings) expect(KINDS[f.kind]).toBeTypeOf('string');
  });
});

describe('deprecations from COMPATIBILITY.md', () => {
  it('reads each row that names a later major, with its backticked names', () => {
    const rows = deprecations();
    const find = (name: string) => rows.find((r) => r.names.includes(name));
    expect(find('mapOrder')?.removedIn).toBe('3.0.0');
    expect(find('Chart.movePriceAxis')?.removedIn).toBe('3.0.0');
    expect(find('ChartClickEvent')?.names).toEqual(expect.arrayContaining(['shiftKey', 'ctrlKey', 'metaKey']));
  });

  it('skips a row whose removal falls in the current major, which would be no deprecation at all', () => {
    const text = [
      '## Deprecated APIs', '',
      '| Deprecated | Declared in | Replacement since | Removed in | Use instead |',
      '| --- | --- | --- | --- | --- |',
      '| `soonGone` | `src/a.ts` | 2.0.0 | 2.9.0 | `other` |',
      '| `laterGone` | `src/b.ts` | 2.0.0 | 3.0.0 | `other` |',
      '', '## Next section',
    ].join('\n');
    expect(deprecations(text)).toEqual([{ names: ['laterGone'], removedIn: '3.0.0' }]);
  });
});
