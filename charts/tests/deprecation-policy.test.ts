/**
 * The deprecation policy in COMPATIBILITY.md, checked where it can drift.
 *
 * The policy keeps a deprecated API until the next major and asks its
 * declaration to say so. Written only in prose it held for years with no tag
 * anywhere in src, so a host had no warning in its editor and no date to plan
 * a migration against. Three things are checked here:
 *
 * - the lint rule itself, over probe snippets through the real linter, because
 *   a rule that is only configured is not known to fire, and against the
 *   compiler, because the compiler decides what a host's editor strikes through;
 * - COMPATIBILITY.md lists every tagged declaration with the same removal
 *   release, and every declaration it lists carries the tag, so the table a
 *   host reads and the strike-through its editor shows cannot disagree;
 * - every comment in src that announces an old form kept beside a new one is
 *   classified, so a shim nobody listed fails here instead of passing quietly.
 */
/// <reference types="vite/client" />
import ts from 'typescript';
import { describe, expect, it } from 'vitest';
import { ESLint } from 'eslint';
import pkg from '../package.json';
import compatibility from '../COMPATIBILITY.md?raw';
import timeSource from '../src/feed/time.ts?raw';
import skillEvents from '../.github/skills/openalgo-charts/references/events-and-state.md?raw';
import siteEvents from '../website/pages/docs/events.mdx?raw';

// Same root derivation as widget-packaging.test.ts: the suite carries no Node
// typings, and ESLint wants absolute paths.
const ROOT = decodeURIComponent(new URL('..', import.meta.url).pathname).replace(/^\/([A-Za-z]:)/, '$1');
const at = (rel: string): string => ROOT + rel;
const RULE = 'oac/deprecation-version';

type Sources = Record<string, string>;
const SOURCES = (import.meta as unknown as {
  glob(pattern: string, options: { query: string; import: string; eager: true }): Sources;
}).glob('../src/**/*.ts', { query: '?raw', import: 'default', eager: true });

const [MAJOR] = pkg.version.split('.').map(Number);
const NEXT = `${MAJOR + 1}.0.0`;

/**
 * The `@deprecated` tags the compiler reads in one doc comment, with their
 * text. This is the oracle the rule is held to, written here independently of
 * the rule so the two cannot share a mistake.
 */
function compilerTags(doc: string): string[] {
  const source = ts.createSourceFile('probe.ts', `${doc}\nfunction probe() {}\n`, ts.ScriptTarget.Latest, true);
  return ts.getJSDocTags(source.statements[0])
    .filter(tag => tag.tagName.text === 'deprecated')
    .map(tag => ts.getTextOfJSDocComment(tag.comment) ?? '');
}

describe('the deprecation lint rule', () => {
  const eslint = new ESLint({ cwd: ROOT, overrideConfigFile: at('eslint.config.js') });

  /** Lint `code` as if it lived at `file`; return what the deprecation rule says. */
  async function problems(code: string, file = 'src/core/probe.ts'): Promise<string[]> {
    const [result] = await eslint.lintText(code, { filePath: at(file) });
    return result.messages.filter(m => m.ruleId === RULE).map(m => m.message);
  }

  it('rejects a tag that names no removal release', async () => {
    const [message] = await problems('/** @deprecated Use `y`. */\nexport const x = 1;\n');
    expect(message).toContain('removed in');
  });

  it('accepts a tag that names a later major and a replacement', async () => {
    const code = `/** @deprecated Since 1.0.0; removed in ${NEXT}. Use \`y\`. */\nexport const x = 1;\n`;
    expect(await problems(code)).toEqual([]);
  });

  it('reads a tag that wraps onto the next line of the block', async () => {
    const code = [
      '/**',
      ' * An old name.',
      ' *',
      ' * @deprecated Since 1.0.0;',
      ` *   removed in ${NEXT}. Use \`y\`.`,
      ' * @param z unused',
      ' */',
      'export function x(z: number): number { return z; }',
      '',
    ].join('\n');
    expect(await problems(code)).toEqual([]);
  });

  it('reads a removal clause that wraps between its words', async () => {
    const code = [
      '/**',
      ' * @deprecated Since 1.0.0, and removed',
      ` *   in ${NEXT}. Use \`y\`.`,
      ' */',
      'export const x = 1;',
      '',
    ].join('\n');
    expect(await problems(code)).toEqual([]);
  });

  it('does not let the version of the next tag stand in for this one', async () => {
    const code = [
      '/**',
      ' * @deprecated Use `y`.',
      ` * @see removed in ${NEXT}`,
      ' */',
      'export const x = 1;',
      '',
    ].join('\n');
    expect(await problems(code)).toHaveLength(1);
  });

  it('does not let the version of a later tag on the same line stand in for this one', async () => {
    // The compiler ends the tag's text at the `@see`, so the release belongs to that tag.
    expect(await problems(`/** @deprecated Use \`y\`. @see removed in ${NEXT} */\nexport const x = 1;\n`)).toHaveLength(1);
  });

  it('rejects a versionless tag in the middle of a line, where the compiler reads one too', async () => {
    expect(await problems('/** Old name. @deprecated use y */\nexport const x = 1;\n')).toHaveLength(1);
    const code = `/** Old name. @deprecated Removed in ${NEXT}. Use \`y\`. */\nexport const x = 1;\n`;
    expect(await problems(code)).toEqual([]);
  });

  it('rejects a versionless tag that follows another tag on its line', async () => {
    expect(await problems('/**\n * @remarks going away @deprecated use y\n */\nexport const x = 1;\n')).toHaveLength(1);
    expect(await problems('/**\n * @param z unused @deprecated use y\n */\nexport function x(z: number): number { return z; }\n'))
      .toHaveLength(1);
  });

  it('rejects a removal inside the current major', async () => {
    const code = `/** @deprecated Since 1.0.0; removed in ${MAJOR}.99.0. Use \`y\`. */\nexport const x = 1;\n`;
    const [message] = await problems(code);
    expect(message).toContain(NEXT);
  });

  it('rejects a removal release that has already shipped', async () => {
    const code = `/** @deprecated Since 0.1.0; removed in ${MAJOR}.0.0. Use \`y\`. */\nexport const x = 1;\n`;
    const [message] = await problems(code);
    expect(message).toContain('has been reached');
  });

  it('rejects a tag outside a doc block, where neither the editor nor the reference reads it', async () => {
    expect(await problems(`// @deprecated removed in ${NEXT}\nexport const x = 1;\n`)).toHaveLength(1);
    expect(await problems(`/* @deprecated removed in ${NEXT} */\nexport const x = 1;\n`)).toHaveLength(1);
  });

  it('leaves the word alone where the compiler reads no tag', async () => {
    for (const doc of [
      '/** Explains why an `@deprecated` tag names its release. */',
      '/** A note (@deprecated) in brackets. */',
      '/** Glued to a word, as in foo@deprecated. */',
      '/** A different tag, @deprecatedAlias, which is not this one. */',
    ]) {
      expect(compilerTags(doc), doc).toEqual([]);
      expect(await problems(`${doc}\nexport const x = 1;\n`), doc).toEqual([]);
    }
  });

  it('reports exactly the versionless tags the compiler reads, wherever they sit', async () => {
    const corpus = [
      '/** @deprecated first */',
      '/** Old name. @deprecated use y */',
      '/**\n * @remarks going away @deprecated use y\n */',
      `/** @deprecated first @deprecated Removed in ${NEXT}. */`,
      '/** `unclosed @deprecated use y */',
      '/** text\t@deprecated after a tab */',
      '/** An `@deprecated` in a code span. */',
      `/** {@link y} @deprecated Removed in ${NEXT}. */`,
    ];
    for (const doc of corpus) {
      const expected = compilerTags(doc).filter(text => !/\bremoved\s+in\s+\d+\.\d+\.\d+/i.test(text)).length;
      expect(await problems(`${doc}\nexport const x = 1;\n`), doc).toHaveLength(expected);
    }
  });

  it('applies to every tier, the widget included', async () => {
    for (const dir of ['core', 'draw', 'indicators', 'trade', 'widget', 'workspace']) {
      expect(await problems('/** @deprecated gone soon */\nexport const x = 1;\n', `src/${dir}/probe.ts`), dir).toHaveLength(1);
    }
  });
});

/** One `@deprecated` tag in src: where it is, what it names, and the release it gives. */
interface Tagged { file: string; name: string; removal: string | null }

/** The declarations a tag can deprecate, each with a name a host would type. */
const DECLARATIONS = new Set<ts.SyntaxKind>([
  ts.SyntaxKind.FunctionDeclaration, ts.SyntaxKind.ClassDeclaration, ts.SyntaxKind.InterfaceDeclaration,
  ts.SyntaxKind.TypeAliasDeclaration, ts.SyntaxKind.EnumDeclaration, ts.SyntaxKind.EnumMember,
  ts.SyntaxKind.ModuleDeclaration, ts.SyntaxKind.VariableDeclaration, ts.SyntaxKind.PropertySignature,
  ts.SyntaxKind.PropertyDeclaration, ts.SyntaxKind.MethodSignature, ts.SyntaxKind.MethodDeclaration,
  ts.SyntaxKind.GetAccessor, ts.SyntaxKind.SetAccessor,
]);

/**
 * Every declaration the compiler reads a `@deprecated` tag on, with its name.
 * The compiler finds the tag, so a one-line `/** @deprecated ... *\/ foo: T;`
 * counts, and the word inside a code span does not.
 */
function taggedDeclarations(sources: Sources = SOURCES): Tagged[] {
  const out: Tagged[] = [];
  for (const [key, text] of Object.entries(sources)) {
    if (!text.includes('@deprecated')) continue;
    const file = key.replace(/^\.\.\//, '');
    const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
    const seen = new Set<ts.JSDocTag>();
    const visit = (node: ts.Node): void => {
      const name = DECLARATIONS.has(node.kind) ? (node as ts.NamedDeclaration).name : undefined;
      if (name !== undefined) {
        for (const tag of ts.getJSDocTags(node)) {
          if (tag.tagName.text !== 'deprecated' || seen.has(tag)) continue;
          seen.add(tag);
          const removal = /removed\s+in\s+(\d+\.\d+\.\d+)/i.exec(ts.getTextOfJSDocComment(tag.comment) ?? '');
          out.push({ file, name: name.getText(source), removal: removal?.[1] ?? null });
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
  }
  return out;
}

/** The body of one `##` or `###` section of COMPATIBILITY.md. */
function section(heading: string): string {
  const start = compatibility.indexOf(`${heading}\n`);
  if (start === -1) return '';
  const body = compatibility.slice(start + heading.length + 1);
  const end = body.search(/\n#{2,3} /);
  return end === -1 ? body : body.slice(0, end);
}

/** The rows of the deprecation table in COMPATIBILITY.md, as cell arrays. */
function deprecationRows(): string[][] {
  return section('## Deprecated APIs').split('\n')
    .filter(line => line.startsWith('|') && !/^\|\s*-/.test(line))
    .slice(1)
    .map(line => line.split('|').slice(1, -1).map(cell => cell.trim()));
}

/** The identifiers a table cell names in backticks, last segment of each. */
const namesIn = (cell: string): string[] =>
  [...cell.matchAll(/`([A-Za-z_$][\w$.]*)`/g)].map(m => m[1].split('.').pop() ?? '');

/**
 * Rows whose tag waits on a change to a file another stream of work owns.
 * The change that adds the tag removes the entry here, and this suite fails
 * until it does, so the list cannot outlive the wait.
 */
const PENDING_TAGS: readonly { file: string; name: string }[] = [];

describe('the compatibility shims', () => {
  const tagged = taggedDeclarations();

  it('are found by the compiler, one-line doc blocks included', () => {
    const probe = {
      '../src/probe.ts': [
        'export interface Probe {',
        `  /** @deprecated Removed in ${NEXT}. Read \`b\`. */ a: number;`,
        '  /** Mentions an `@deprecated` tag without being one. */',
        '  b: number;',
        '}',
        '',
      ].join('\n'),
    };
    expect(taggedDeclarations(probe)).toEqual([{ file: 'src/probe.ts', name: 'a', removal: NEXT }]);
  });

  it('carry a deprecation tag where the code keeps an old form for compatibility', () => {
    // Each of these exists only so code written against an earlier release
    // keeps compiling: a newer declaration does the same job and more.
    const shims = [
      ['src/feed/openalgo-trade.ts', 'mapOrder'],
      ['src/model/indicator-instance.ts', 'dashed'],
      ['src/core/chart.ts', 'shiftKey'],
      ['src/core/chart.ts', 'ctrlKey'],
      ['src/core/chart.ts', 'metaKey'],
      ['src/core/chart.ts', 'renderer'],
      ['src/core/chart.ts', 'movePriceAxis'],
      ['src/core/chart.ts', 'movable'],
      // The string form of the bus beside the typed `ChartEventMap` overloads.
      ['src/core/chart.ts', 'on'],
      ['src/core/chart.ts', 'once'],
      ['src/core/chart.ts', 'off'],
      ['src/core/chart.ts', 'emit'],
      ['src/core/chart-events.ts', 'priceAxisMoved'],
    ];
    const found = tagged.map(t => `${t.file}#${t.name}`);
    expect(found).toEqual(expect.arrayContaining(shims.map(([file, name]) => `${file}#${name}`)));
  });

  it('are each listed in COMPATIBILITY.md with the release the tag gives', () => {
    const rows = deprecationRows();
    expect(rows.length).toBeGreaterThan(0);
    const unlisted = tagged.filter(t => !rows.some(row =>
      row[1]?.includes(t.file) && new RegExp(`\\b${t.name}\\b`).test(row[0] ?? '') && row[3]?.includes(t.removal ?? '?')));
    expect(unlisted).toEqual([]);
  });

  it('are each tagged in the code when COMPATIBILITY.md lists them, unless the tag waits on another change', () => {
    const untagged: string[] = [];
    for (const row of deprecationRows()) {
      const file = /`(src\/[^`]+\.ts)`/.exec(row[1] ?? '')?.[1];
      // A wire key, a union member or an event name has no declaration to carry a tag; the row says which.
      if (file === undefined || /a wire key|a union member|an event name/.test(row[1] ?? '')) continue;
      const names = namesIn(row[0] ?? '');
      const isTagged = tagged.some(t => t.file === file && names.includes(t.name));
      const isPending = PENDING_TAGS.some(p => p.file === file && names.includes(p.name));
      if (!isTagged && !isPending) untagged.push(row[0] ?? '');
    }
    expect(untagged).toEqual([]);
  });

  it('list each event only a deprecated method emits, and mark it where events are documented', () => {
    // An event that only a deprecated method emits goes with that method. Its
    // `ChartEventMap` key carries the tag, but an editor strikes through a
    // declaration, not the string a host passes to `on`, so the table and the
    // event pages have to say so themselves. The engine emits through `_emit`.
    const emitted = (node: ts.Node, out: string[]): string[] => {
      if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && /^_?emit$/.test(node.expression.name.text)
        && node.arguments[0] !== undefined && ts.isStringLiteral(node.arguments[0])) out.push(node.arguments[0].text);
      ts.forEachChild(node, child => { emitted(child, out); });
      return out;
    };
    const fromDeprecated = new Set<string>();
    const fromOthers = new Set<string>();
    for (const [key, text] of Object.entries(SOURCES)) {
      if (!text.includes('emit(')) continue;
      const source = ts.createSourceFile(key, text, ts.ScriptTarget.Latest, true);
      const visit = (node: ts.Node): void => {
        if (ts.isMethodDeclaration(node) || ts.isFunctionDeclaration(node)) {
          const deprecated = ts.getJSDocTags(node).some(tag => tag.tagName.text === 'deprecated');
          for (const name of emitted(node, [])) (deprecated ? fromDeprecated : fromOthers).add(name);
          return;
        }
        ts.forEachChild(node, visit);
      };
      visit(source);
    }
    const onlyDeprecated = [...fromDeprecated].filter(name => !fromOthers.has(name));
    expect(onlyDeprecated).toContain('priceAxisMoved');
    const rows = deprecationRows();
    /** The table row an events page gives `name`, by its first cell. */
    const rowOf = (text: string, name: string): string | undefined =>
      text.split('\n').find(line => line.startsWith(`| \`${name}\` |`));
    for (const name of onlyDeprecated) {
      expect(rows.some(row => namesIn(row[0] ?? '').includes(name) && /an event name/.test(row[1] ?? '') && row[3] === NEXT), name).toBe(true);
      for (const [page, text] of [['events-and-state.md', skillEvents], ['events.mdx', siteEvents]] as const) {
        expect(rowOf(text, name), `${name} in ${page}`).toContain(`Deprecated, removed in ${NEXT}`);
      }
    }
  });

  it('wait on another change only while the tag is still missing', () => {
    for (const p of PENDING_TAGS) {
      const now = tagged.some(t => t.file === p.file && t.name === p.name);
      expect(now, `${p.file}#${p.name} is tagged now: drop it from PENDING_TAGS`).toBe(false);
      expect(deprecationRows().some(row => row[1]?.includes(p.file) && namesIn(row[0] ?? '').includes(p.name)), p.name).toBe(true);
    }
  });
});

/**
 * Phrases this codebase writes beside an old public form that it keeps for
 * callers of an earlier release. A comment carrying one marks a shim someone
 * noticed; each must be classified in {@link CLASSIFIED}, so a new one fails
 * here until it is recorded as deprecated, kept, undecided or internal.
 */
const COMPAT_MARKER = /\bpredat(?:e|es|ing) `|\bshipped under\b|\bold name\b|\blegacy (?:names?|topic)\b|\bpublic API since\b|\bkept for (?:hosts|the published surface)\b|\bretained so\b|\bback-?compat|\btyped against either\b/i;

interface Classified {
  file: string;
  /** Matches the marked comment line. */
  line: RegExp;
  /** `deprecated`, `kept` and `undecided` must be named in that part of COMPATIBILITY.md. */
  status: 'deprecated' | 'kept' | 'undecided' | 'internal';
  /** What COMPATIBILITY.md names it by, or why it is internal. */
  name: string;
}

const CLASSIFIED: readonly Classified[] = [
  { file: 'src/core/chart.ts', line: /`rendererKind` shipped under/, status: 'deprecated', name: '`Chart.renderer`' },
  { file: 'src/core/chart-input.ts', line: /flat flags predate `modifiers`/, status: 'deprecated', name: '`shiftKey`' },
  { file: 'src/core/chart-input.ts', line: /typed against either/, status: 'deprecated', name: '`shiftKey`' },
  { file: 'src/core/chart-input.ts', line: /`subscribeClick` stays hit-only/, status: 'internal',
    name: 'the behaviour of a current helper beside the richer click event, not an older form of anything' },
  { file: 'src/draw/controller.ts', line: /predating `setPlacementMode`/, status: 'internal',
    name: 'a guard for a draw tier loaded beside an older base bundle; nothing public is kept' },
  { file: 'src/feed/openalgo-trade.ts', line: /kept for the published surface/, status: 'deprecated', name: '`mapOrder`' },
  { file: 'src/feed/openalgo-ws.ts', line: /learned the old name/, status: 'deprecated', name: '`depth_level`' },
  { file: 'src/feed/openalgo-ws.ts', line: /legacy topic identity/, status: 'kept', name: '`topic`' },
  { file: 'src/feed/time.ts', line: /public API since/, status: 'kept', name: '`utcSecondsToIstParts`' },
  { file: 'src/model/indicator-instance.ts', line: /hosts predating `lineStyle`/, status: 'deprecated', name: '`level.dashed`' },
  { file: 'src/model/indicator-instance.ts', line: /`dashed` predates `lineStyle`/, status: 'kept', name: '`dashed`' },
  { file: 'src/widget/localization.ts', line: /Retained so existing host translation catalogs/, status: 'deprecated',
    name: 'Enter a valid expiry date and time in UTC' },
  // One comment keeps several keys; each deprecation it covers is named, so a missing row fails.
  { file: 'src/widget/localization.ts', line: /Retained so existing host translation catalogs/, status: 'deprecated',
    name: 'Widget message keys "Dark" and "Light"' },
  { file: 'src/widget/localization.ts', line: /catalogs written for the armed wording/, status: 'deprecated',
    name: 'Keep tool armed' },
];

/** Where COMPATIBILITY.md records each status. */
const SECTION_FOR: Record<Exclude<Classified['status'], 'internal'>, string> = {
  deprecated: '## Deprecated APIs',
  kept: '### Kept on purpose',
  undecided: '### Not decided yet',
};

describe('the compatibility inventory', () => {
  const marked = Object.entries(SOURCES).flatMap(([key, text]) => {
    const file = key.replace(/^\.\.\//, '');
    return text.split('\n').filter(line => COMPAT_MARKER.test(line)).map(line => ({ file, line: line.trim() }));
  });

  it('classifies every comment that marks an old form kept beside a new one', () => {
    const unclassified = marked.filter(m => !CLASSIFIED.some(c => c.file === m.file && c.line.test(m.line)));
    expect(unclassified).toEqual([]);
  });

  it('holds no classification the code no longer marks', () => {
    const stale = CLASSIFIED.filter(c => !marked.some(m => m.file === c.file && c.line.test(m.line)));
    expect(stale).toEqual([]);
  });

  it('names each deprecated, kept or undecided form in its part of COMPATIBILITY.md', () => {
    const missing = CLASSIFIED
      .filter(c => c.status !== 'internal')
      .filter(c => !section(SECTION_FOR[c.status as Exclude<Classified['status'], 'internal'>]).includes(c.name))
      .map(c => `${c.status}: ${c.name}`);
    expect(missing).toEqual([]);
  });

  it('lists every IST helper among the forms kept on purpose', () => {
    // The helpers above the zone-aware divider are the IST special case.
    const istPart = timeSource.split('// Zone-aware time')[0];
    const helpers = [...istPart.matchAll(/^export (?:function|const|interface) (\w*(?:Ist|IST)\w*)/gm)].map(m => m[1]);
    expect(helpers.length).toBeGreaterThan(5);
    const kept = section('### Kept on purpose');
    expect(helpers.filter(name => !kept.includes(`\`${name}\``))).toEqual([]);
  });
});
