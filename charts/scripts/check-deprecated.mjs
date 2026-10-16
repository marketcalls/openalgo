// @ts-check
/**
 * The deprecation policy as a lint rule, loaded by eslint.config.js for src/.
 *
 * COMPATIBILITY.md keeps a deprecated API until the next major and asks the
 * declaration to say so. A bare `@deprecated` tells a host that an API is
 * going but not when, so the host cannot plan a migration, and nothing ever
 * falls due: a tag like that outlives the release that should have removed
 * the API. Every tag therefore names the release that removes it, as
 * "removed in X.Y.Z", and that release must be a later major than the one
 * being built. Once the package reaches it the tag fails, so the removal is a
 * gate rather than a good intention.
 *
 * The tag must sit in a doc block. A line comment or a plain block comment
 * reaches neither the editor's strike-through nor the API reference, which
 * are the two places a host would see it.
 *
 * What counts as a tag, and where its text ends, is the compiler's call: it is
 * the compiler that strikes a name through in a host's editor. It reads a tag
 * in the middle of a line as well as at the start of one, ends a tag's text at
 * the next tag even on the same line, and reads none inside a code span. The
 * rule asks it rather than imitating it, so the two cannot disagree.
 */
import { readFileSync } from 'node:fs';
import ts from 'typescript';

/** The removal clause every tag carries; its words may wrap onto the next line. */
const REMOVAL = /\bremoved\s+in\s+(\d+)\.(\d+)\.(\d+)\b/i;

/** @param {string} version */
function parseVersion(version) {
  const m = /^(\d+)\.(\d+)\.(\d+)/.exec(version);
  if (m === null) throw new Error(`deprecation-version: "${version}" is not a release version`);
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

/** @param {number[]} a @param {number[]} b */
function compare(a, b) {
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] - b[i];
  return 0;
}

/** The version in package.json, which is the release the tree is building toward. */
function packageVersion() {
  return JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8')).version;
}

/**
 * What is wrong with one tag's text, or null when it meets the policy.
 * `tagText` is the text the compiler gives the tag, which ends at the next tag.
 *
 * @param {string} tagText
 * @param {string} current the version being built
 * @returns {{ messageId: string, data: Record<string, string> } | null}
 */
export function deprecationProblem(tagText, current) {
  const m = REMOVAL.exec(tagText);
  if (m === null) return { messageId: 'missing', data: {} };
  const removal = [Number(m[1]), Number(m[2]), Number(m[3])];
  const now = parseVersion(current);
  const data = { removal: removal.join('.'), current, next: `${now[0] + 1}.0.0` };
  if (compare(removal, now) <= 0) return { messageId: 'reached', data };
  if (removal[0] <= now[0]) return { messageId: 'sameMajor', data };
  return null;
}

/**
 * The `@deprecated` tags the compiler reads in one doc comment: where each
 * starts, as an offset into `doc`, and the text that belongs to it.
 *
 * @param {string} doc a whole doc comment, from its opening slash to its closing one
 * @returns {{ at: number, text: string }[]}
 */
export function deprecatedTags(doc) {
  const source = ts.createSourceFile('probe.ts', `${doc}\nfunction probe() {}\n`, ts.ScriptTarget.Latest, true);
  const [statement] = source.statements;
  if (statement === undefined) return [];
  return ts.getJSDocTags(statement)
    .filter((tag) => tag.tagName.text === 'deprecated')
    .map((tag) => ({ at: tag.getStart(source), text: ts.getTextOfJSDocComment(tag.comment) ?? '' }));
}

/** @type {import('eslint').Rule.RuleModule} */
export const deprecationVersionRule = {
  meta: {
    type: 'problem',
    docs: { description: 'Every @deprecated tag names the later major release that removes the API.' },
    schema: [{
      type: 'object',
      properties: { version: { type: 'string' } },
      additionalProperties: false,
    }],
    messages: {
      missing: '@deprecated must name the release that removes the API, as "removed in X.Y.Z" (see COMPATIBILITY.md).',
      sameMajor: '@deprecated names removal in {{removal}}, but a deprecated API stays until the next major after {{current}}: name {{next}} or later.',
      reached: '@deprecated names removal in {{removal}}, and that release has been reached ({{current}}): remove the API rather than the tag.',
      notDoc: '@deprecated belongs in a /** doc block */, the only comment the editor and the API reference read.',
    },
  },
  create(context) {
    const options = /** @type {{ version?: string } | undefined} */ (context.options[0]);
    const current = options?.version ?? packageVersion();
    const source = context.sourceCode;
    return {
      Program() {
        for (const comment of source.getAllComments()) {
          if (!comment.value.includes('@deprecated')) continue;
          const isDoc = comment.type === 'Block' && comment.value.startsWith('*');
          // A tag outside a doc block is read the way the compiler would read
          // it inside one: a tag its author meant, in a place no tool looks.
          // The `/**` put in front is one character longer than `//` or `/*`.
          const doc = isDoc ? `/*${comment.value}*/` : `/**${comment.value}*/`;
          const origin = /** @type {[number, number]} */ (comment.range)[0] - (isDoc ? 0 : 1);
          for (const tag of deprecatedTags(doc)) {
            const loc = { start: source.getLocFromIndex(origin + tag.at), end: source.getLocFromIndex(origin + tag.at + 11) };
            if (!isDoc) {
              context.report({ loc, messageId: 'notDoc' });
              continue;
            }
            const problem = deprecationProblem(tag.text, current);
            if (problem !== null) context.report({ loc, messageId: problem.messageId, data: problem.data });
          }
        }
      },
    };
  },
};
