/**
 * The house writing rules, held mechanically over the words a person reads:
 * every string the engine and the widget spell out in src, the markup,
 * strings and text of the examples, and the prose of the examples' guides
 * and the website's pages. No em or en dash, no arrow, tick or cross
 * character standing in for a word, no emoji, no "arm" wording in what src
 * or the examples show (Live, On, Off and Active say it), and sandbox or
 * analyzer mode, never paper or virtual trading. 2.5.10 found dashes in page
 * titles, thrown messages and canvas placeholders, arrows in hints, a camera
 * emoji on a button and "Arm trading" on an order gate, none of which any
 * check had looked at.
 *
 * The characters are held everywhere else too: every comment, doc comment and
 * test title in src, tests and scripts, and the skills, docs, examples and
 * website sources, read whole. Code cannot hold one outside a comment or a
 * string, so a whole file is read rather than parsed. 2.6.0 found 230 dashes
 * in the comments of src alone, which nothing had checked.
 *
 * A deliberate exception goes in writing-rules-allow.json with its reason.
 * The deprecated message keys that still say armed are listed there one by
 * one, so a new one is caught.
 */
/// <reference types="vite/client" />
import ts from 'typescript';
import { describe, expect, it } from 'vitest';
import allow from './writing-rules-allow.json';
// A glob leaves out the file that runs it, so this one is read by name.
import SELF from './writing-rules.test.ts?raw';

type Sources = Record<string, string>;
type Glob = { glob(pattern: string | string[], options: { query: string; import: string; eager: true }): Sources };
const SRC = (import.meta as unknown as Glob).glob('../src/**/*.ts', { query: '?raw', import: 'default', eager: true });
const EXAMPLES = (import.meta as unknown as Glob).glob(['../examples/**/*.html', '../examples/**/*.js', '!../examples/**/tests/**'], { query: '?raw', import: 'default', eager: true });
const DOCS = (import.meta as unknown as Glob).glob(['../examples/**/*.md', '../website/pages/**/*.mdx', '!../examples/**/tests/**'], { query: '?raw', import: 'default', eager: true });
/** Every other file a person reads or edits, read whole. */
const EVERYWHERE: Sources = { './writing-rules.test.ts': SELF, ...(import.meta as unknown as Glob).glob([
  '../src/**/*.ts', '../tests/**/*.{ts,mjs,cjs,js,json,html}', '../scripts/**/*.{mjs,js,mts,ts,json,html}',
  '../integration/**/*.ts', '../examples/**/*.{js,mjs,html,css,py}', '../website/pages/**/*.{ts,tsx}',
  '../website/components/**/*.{ts,tsx,css}', '../website/*.{md,ts,tsx,js,mjs}', '../.github/**/*.{md,yml}',
  '../docs/**/*.{md,svg}', '../*.md', '../typedoc.json', '../package.json',
  '!../**/node_modules/**', '!../scripts/fixtures/writing-rules/**',
], { query: '?raw', import: 'default', eager: true }) };
/** A file of each kind the rules forbid, which the scan must find. */
const FIXTURE = (import.meta as unknown as Glob).glob('../scripts/fixtures/writing-rules/*', { query: '?raw', import: 'default', eager: true });

/** Characters that stand in for words: dashes, arrows, ticks and crosses, pictographs. */
// Written by code point and name, so this file holds none of the characters or
// entities it forbids: the en and em dash, the arrows block, and the tick and
// cross marks.
const FORBIDDEN = [[0x2013, 0x2014], [0x2190, 0x21ff], [0x2713, 0x2713], [0x2715, 0x2715]]
  .map(([from, to]) => `${String.fromCharCode(from)}-${String.fromCharCode(to)}`).join('');
const ENTITIES = ['mdash', 'ndash', 'rarr', 'larr'].map(name => `&${name};`).join('|');
const SYMBOL = new RegExp(`[${FORBIDDEN}]|${ENTITIES}|${/\p{Extended_Pictographic}/u.source}`, 'u');
/** "Arm" in a reader's words; the examples say Live, On, Off or Active. */
const ARM = /\barm(?:ed|ing|s)?\b/i;
/** The house words are sandbox and analyzer mode. */
const PAPER = /\b(?:paper|virtual) trading\b/i;

interface Finding { file: string; line: number; text: string }

/** String and template literal text in JS or TS source, with the line it starts on. */
function literals(file: string, text: string): { line: number; text: string }[] {
  const kind = file.endsWith('.ts') ? ts.ScriptKind.TS : ts.ScriptKind.JS;
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
  const out: { line: number; text: string }[] = [];
  const visit = (node: ts.Node): void => {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)
      || ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node)) {
      out.push({ line: source.getLineAndCharacterOfPosition(node.getStart()).line + 1, text: node.text });
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return out;
}

/** An HTML page's reader-facing text: its markup outside comments, and its scripts' literals. */
function pageText(file: string, html: string): { line: number; text: string }[] {
  const out: { line: number; text: string }[] = [];
  const lineAt = (index: number): number => html.slice(0, index).split('\n').length;
  const blank = (s: string): string => s.replace(/[^\n]/g, ' ');
  // Scripts go through the parser; comments are blanked so line numbers hold.
  // An end tag may carry space or attributes before its `>` (`</script >`), which
  // the browser still honours, so the patterns accept them.
  const markup = html.replace(/<script\b[^>]*>([\s\S]*?)<\/script[^>]*>/gi, (whole, body: string, at: number) => {
    const offset = lineAt(at + whole.indexOf(body)) - 1;
    for (const found of literals(`${file}.js`, body)) out.push({ line: found.line + offset, text: found.text });
    return blank(whole);
  }).replace(/<!--[\s\S]*?-->/g, blank).replace(/<style\b[^>]*>[\s\S]*?<\/style[^>]*>/gi, blank);
  markup.split('\n').forEach((text, index) => { if (text.trim() !== '') out.push({ line: index + 1, text }); });
  return out;
}

/** An entry marked whole names one literal exactly; otherwise any literal holding its text. */
const allowed = (file: string, text: string): boolean =>
  (allow as { file: string; text: string; whole?: boolean; reason: string }[])
    .some(entry => file.endsWith(entry.file) && (entry.whole === true ? text === entry.text : text.includes(entry.text)));

/** Numeric character references as the characters a reader sees. */
const decoded = (text: string): string => text
  .replace(/&#(\d+);/g, (_, n: string) => String.fromCodePoint(Number(n)))
  .replace(/&#x([0-9a-f]+);/gi, (_, n: string) => String.fromCodePoint(parseInt(n, 16)));

/** A glob key as a path from the package root: this folder's own files come back as `./name`. */
const repoPath = (key: string): string => (key.startsWith('./') ? `tests/${key.slice(2)}` : key.replace(/^\.\.\//, ''));

function scan(sources: Sources, read: (file: string, text: string) => { line: number; text: string }[], rule: RegExp): Finding[] {
  const found: Finding[] = [];
  for (const [file, text] of Object.entries(sources)) {
    for (const item of read(file, text)) {
      if (rule.test(decoded(item.text)) && !allowed(file, item.text)) found.push({ file: repoPath(file), line: item.line, text: item.text.trim().slice(0, 120) });
    }
  }
  return found;
}

const read = (file: string, text: string): { line: number; text: string }[] => (file.endsWith('.html') ? pageText(file, text) : literals(file, text));
/** A guide's every line: its prose, and the code it shows, are both read. */
const lines = (_file: string, text: string): { line: number; text: string }[] => text.split('\n').map((line, index) => ({ line: index + 1, text: line }));
/**
 * The strings src spells out, less a whole literal that is one lower-case word:
 * that is a value compared in code (the alert state 'armed'), not a word shown.
 */
const shownLiterals = (file: string, text: string): { line: number; text: string }[] => literals(file, text).filter(item => !/^[a-z]+$/.test(item.text));
/**
 * Every line, less the text an allowlist entry lets that file show (the key
 * glyphs formatCombo prints), so the rest of such a line is still read.
 */
const everyLine = (file: string, text: string): { line: number; text: string }[] => lines(file, text).map(item => ({
  ...item,
  text: (allow as { file: string; text: string; whole?: boolean }[])
    .filter(entry => entry.whole !== true && file.endsWith(entry.file))
    .reduce((rest, entry) => rest.split(entry.text).join(''), item.text),
}));

describe('the house writing rules', () => {
  it('finds the files it is meant to read', () => {
    expect(Object.keys(SRC).length).toBeGreaterThan(300);
    expect(Object.keys(EXAMPLES).some(file => file.endsWith('examples/yfinance/index.html'))).toBe(true);
    expect(Object.keys(EXAMPLES).some(file => file.includes('/tests/'))).toBe(false);
    expect(Object.keys(DOCS).some(file => file.endsWith('examples/live/README.md'))).toBe(true);
    expect(Object.keys(DOCS).some(file => file.endsWith('website/pages/docs/profiles-and-orderflow.mdx'))).toBe(true);
    for (const expected of ['src/index.ts', 'tests/writing-rules.test.ts', 'tests/e2e/smoke.spec.ts', 'scripts/check-shake.mjs',
      'examples/yfinance/tests/account.test.js', 'examples/yfinance/server.py', 'website/components/DepthLadderDemo.tsx',
      '.github/skills/openalgo-charts/references/indicators.md', 'docs/api-introduction.md', 'README.md', 'typedoc.json']) {
      expect(Object.keys(EVERYWHERE).some(file => repoPath(file) === expected), expected).toBe(true);
    }
    expect(Object.keys(EVERYWHERE).some(file => file.includes('node_modules') || file.includes('fixtures/writing-rules'))).toBe(false);
  });

  it('finds each kind of character in a fixture, and lets a section rule and a hyphen through', () => {
    const found = scan(FIXTURE, everyLine, SYMBOL).map(item => `${item.file.replace(/^.*\//, '')}:${item.line}`);
    expect(found.sort()).toEqual(['sample.md:1', 'sample.md:2', 'sample.ts:3', 'sample.ts:4', 'sample.ts:5', 'sample.ts:6']);
  });

  it('keeps them out of every comment, doc comment and test title, and every other page and guide', () => {
    expect(scan(EVERYWHERE, everyLine, SYMBOL)).toEqual([]);
  });

  it('keeps dashes, arrows, ticks, crosses and emoji out of the strings src spells out', () => {
    expect(scan(SRC, literals, SYMBOL)).toEqual([]);
  });

  it('keeps them out of the examples too', () => {
    expect(scan(EXAMPLES, read, SYMBOL)).toEqual([]);
  });

  it('keeps them out of the guides of the examples and the pages of the website', () => {
    expect(scan(DOCS, lines, SYMBOL)).toEqual([]);
  });

  it('says Live, On, Off or Active in src and the examples, never arm', () => {
    expect(scan(SRC, shownLiterals, ARM)).toEqual([]);
    expect(scan(EXAMPLES, read, ARM)).toEqual([]);
  });

  it('says sandbox or analyzer mode, never paper or virtual trading', () => {
    expect(scan(SRC, literals, PAPER)).toEqual([]);
    expect(scan(EXAMPLES, read, PAPER)).toEqual([]);
    expect(scan(DOCS, lines, PAPER)).toEqual([]);
  });
});
