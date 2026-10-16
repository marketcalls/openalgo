/**
 * scripts/check-unused-exports.mjs holds the "no unused exports" gate
 * (CLAUDE.md, Quality gates: Surface). The fixture in
 * scripts/fixtures/unused-exports declares one export per way a module can
 * be used or not: through the entry, by name, through a namespace, a dynamic
 * import, destructuring, a barrel and an object shorthand; only by a test;
 * only in its own file; and not at all, including one that is only
 * re-exported and one that is only imported. The run against src is
 * `npm run check:unused-exports`; this proves the walk underneath it.
 */
import { describe, expect, it } from 'vitest';
import { allowlistProblems, findUnusedExports } from '../scripts/check-unused-exports.mjs';

// Same root derivation as line-caps.test.ts: the suite carries no Node typings.
const ROOT = decodeURIComponent(new URL('..', import.meta.url).pathname).replace(/^\/([A-Za-z]:)/, '$1');
const FIXTURE = `${ROOT}scripts/fixtures/unused-exports`;

describe('check-unused-exports on a fixture', () => {
  const found = findUnusedExports(FIXTURE, { references: ['tests'] });

  it('fails an export nothing references, a re-export and an unread import included', () => {
    expect(found.unused).toEqual(['src/lib.ts onlyImported', 'src/lib.ts onlyReexported', 'src/lib.ts unusedAnywhere']);
  });

  it('counts a test as a use', () => {
    expect(found.testOnly).toEqual(['src/lib.ts usedByTestOnly']);
  });

  it('reports an export used only in its own file apart from the rest', () => {
    expect(found.localOnly).toEqual(['src/lib.ts usedLocally']);
  });

  it('takes what the entry exports as public, and every other way of using a name as a use', () => {
    expect(found.public).toBe(3);
    // The other eight exports of lib.ts are read from src (seven ways, and
    // doubled by name), so they are in none of the lists.
    expect(found.total - found.public - found.unused.length - found.testOnly.length - found.localOnly.length).toBe(8);
  });
});

describe('the allowlist of exports nothing uses yet', () => {
  it('fails an unused export that is not listed', () => {
    expect(allowlistProblems(['src/a.ts x', 'src/b.ts y'], ['src/a.ts x'])).toHaveLength(1);
  });

  it('fails a listed export that is used now or gone, so the list only shrinks', () => {
    const problems = allowlistProblems(['src/a.ts x'], ['src/a.ts x', 'src/b.ts y']);
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain('src/b.ts y');
  });

  it('passes when the list and the tree agree', () => {
    expect(allowlistProblems(['src/a.ts x'], ['src/a.ts x'])).toEqual([]);
  });
});
