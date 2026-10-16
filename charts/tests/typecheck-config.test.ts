/**
 * The shipped code compiles under the two flags that tsconfig.json adds to
 * `strict`: `noUncheckedIndexedAccess` (an index read may be undefined) and
 * `exactOptionalPropertyTypes` (an absent property is not one set to
 * undefined). tests/tsconfig.json turns them off for the tests alone, for the
 * reason written there and in CONTRIBUTING.md. It must stay the tests' own:
 * those two flags and nothing more, and no source file among its inputs, or
 * src would gain a second, looser home.
 */
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

// Same root derivation as line-caps.test.ts: the suite carries no Node typings.
const ROOT = decodeURIComponent(new URL('..', import.meta.url).pathname).replace(/^\/([A-Za-z]:)/, '$1');

const parse = (config: string): ts.ParsedCommandLine => {
  const parsed = ts.getParsedCommandLineOfConfigFile(`${ROOT}${config}`, {}, {
    ...ts.sys, onUnRecoverableConfigFileDiagnostic: (d) => { throw new Error(ts.flattenDiagnosticMessageText(d.messageText, '\n')); },
  });
  if (parsed === undefined || parsed.errors.length > 0) throw new Error(`${config} did not parse`);
  return parsed;
};

describe('the TypeScript configurations', () => {
  const main = parse('tsconfig.json');
  const tests = parse('tests/tsconfig.json');

  it('compile src, and only src, with both flags', () => {
    expect(main.options.noUncheckedIndexedAccess).toBe(true);
    expect(main.options.exactOptionalPropertyTypes).toBe(true);
    expect(main.fileNames.length).toBeGreaterThan(0);
    expect(main.fileNames.filter((f) => !f.startsWith(`${ROOT}src/`))).toEqual([]);
  });

  it('turn off exactly those two flags for the tests, over no source file', () => {
    const keys = new Set([...Object.keys(main.options), ...Object.keys(tests.options)]);
    const differ = [...keys].filter((k) => k !== 'configFilePath'
      && JSON.stringify(main.options[k]) !== JSON.stringify(tests.options[k]));
    expect(differ.sort()).toEqual(['exactOptionalPropertyTypes', 'noUncheckedIndexedAccess']);
    expect(tests.fileNames.length).toBeGreaterThan(0);
    expect(tests.fileNames.filter((f) => !f.startsWith(`${ROOT}tests/`))).toEqual([]);
  });
});
