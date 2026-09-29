/**
 * The OpenUI component library the agent may compose, and the prompt that
 * teaches it.
 *
 * One module owns both halves on purpose. The renderer accepts exactly the
 * components in `AGENT_UI_COMPONENTS` and the prompt is **generated from that
 * same library object**, so the two cannot drift: adding a component to the
 * list teaches the model about it and lets the renderer draw it in the same
 * edit, and removing one does both too.
 *
 * Three things about the generation call, all of them measured rather than
 * assumed, because the wrong call **fails silently**:
 *
 * - `library.prompt(options)` and
 *   `generateSystemPrompt({library: library.toSpec(), promptOptions})` produce
 *   the identical string. Anything else, including
 *   `generateSystemPrompt(library, options)` and
 *   `generateSystemPrompt({library, promptOptions})`, produces a plausible
 *   prompt in which every component name is the literal `undefined`, because
 *   the per-component signature the generator reads exists only on `toSpec()`.
 *   `openuiLibrary.test.ts` pins both the correct count of zero and the wrong
 *   calls' count of one per component, so a future refactor to the "simpler"
 *   call fails CI instead of shipping a useless prompt.
 * - `openuiChatLibrary` is **already a built Library**, so `createLibrary` on
 *   it throws `input.components is not iterable`. Its `components` map is what
 *   a subset is built from.
 * - The shipped `openuiChatAdditionalRules` and `openuiChatExamples` describe
 *   the **full 58 component library**. Carried unfiltered onto a subset they
 *   teach the model to emit `FollowUpBlock`, `Carousel` and `Form`, none of
 *   which the renderer has, so the output fails to parse. `usableWithSubset`
 *   drops those mechanically, from the component list itself, so the filter
 *   cannot go stale when the list changes.
 *
 * Two of that filter's three clauses are product rules rather than
 * housekeeping, and they are the reason it is not just a name check:
 *
 * - **No URL, ever.** `Message.tsx` blocks markdown images outright because a
 *   fetched URL is an exfiltration channel, and a rule telling the model to
 *   emit `https://picsum.photos/...` would walk straight around that.
 * - **Nothing that invites invented data.** OpenUI ships with "When asked
 *   about data, generate realistic/plausible data", which is the exact
 *   opposite of this product's provenance rule. This is the one renderer tier
 *   whose numbers the model types itself, so the rule has to live here.
 */

import { createLibrary, type Library, type PromptOptions } from '@openuidev/react-lang'
import {
  openuiChatAdditionalRules,
  openuiChatExamples,
  openuiChatLibrary,
} from '@openuidev/react-ui/genui-lib'

/**
 * The components the agent may compose, and the only ones it is taught.
 *
 * Chosen for what a trading answer actually needs: text and callouts, a table,
 * the four 2D chart shapes, a pie, tags, lists and collapsible sections.
 *
 * Three deliberate omissions:
 *
 * - **Every image component** (`Image`, `ImageBlock`, `ImageGallery`,
 *   `Carousel`). A rendered image is a fetch to a URL the model chose, which
 *   is the exfiltration channel `Message.tsx` already closes for markdown.
 * - **Every form component** (`Form`, `Input`, `Select`, `Button`, ...). A
 *   form implies an action, and every action in this product goes through a
 *   tool with a confirmation and a risk guard behind it.
 * - **Scatter** (`ScatterChart`, `ScatterSeries`, `Point`). Purely a budget
 *   cut, and the least costly one: scatter is the only 2D shape whose two axes
 *   are both numbers the model composes, and it costs 291 prompt characters
 *   this prompt does not have. See `AGENT_UI_PROMPT_MAX_CHARS`.
 */
export const AGENT_UI_COMPONENTS: readonly string[] = [
  'Card',
  'CardHeader',
  'TextContent',
  'MarkDownRenderer',
  'Callout',
  'TextCallout',
  'Separator',
  'Table',
  'Col',
  'BarChart',
  'LineChart',
  'AreaChart',
  'HorizontalBarChart',
  'Series',
  'PieChart',
  'Slice',
  'TagBlock',
  'Tag',
  'ListBlock',
  'ListItem',
  'SectionBlock',
  'SectionItem',
]

/**
 * The rules this product adds on top of the ones OpenUI ships.
 *
 * The first is the provenance rule. The `viz` frame carries a chart a tool
 * built from a service call, so the model never types those numbers; this tier
 * is the one where it does, which is why the rule lives in the prompt here
 * rather than in the plumbing.
 */
const AGENT_UI_RULES: readonly string[] = [
  'Every number here comes from a tool result you actually received in this conversation. Never type a price, a quantity, a P&L or a Greek you remember, were told, or worked out.',
  'Never emit a URL, a link or an image. Nothing here fetches one, and a fetched URL is how data leaves the machine.',
  'Plain text only: no emoji and no decorative icons.',
]

/**
 * The budget for the generated prompt **file**, in characters.
 *
 * `build_agent` caps the whole system prompt at `DEFAULT_MAX_PROMPT_CHARS`
 * (30000) and `render_sections` enforces it by dropping **whole** unpinned
 * sections from the end, with nothing but a log line to say so. Overshooting
 * therefore does not truncate this section; it silently deletes another one.
 *
 * The arithmetic, measured on 2026-09-03 against the running instance:
 *
 * | part | chars |
 * | --- | --- |
 * | cap, `DEFAULT_MAX_PROMPT_CHARS` | 30000 |
 * | `build_system_prompt(surface='chat', trading_enabled=True)` | 15060 |
 * | section title and the two separators around it | about 45 |
 * | left for this prompt | about 8895 |
 *
 * Note the base prompt is 15060 and not the 12768 an earlier measurement
 * found: it has grown by the web search and visualization sections since. The
 * headroom is what moves, so the test asserts against this constant and this
 * constant is what a future measurement updates.
 */
export const AGENT_UI_PROMPT_MAX_CHARS = 8800

/** Every component name the shipped chat library defines, subset or not. */
const ALL_CHAT_COMPONENTS: readonly string[] = Object.keys(openuiChatLibrary.components)

/** Shipped guidance that names a component the subset does not have. */
const OUTSIDE_SUBSET: readonly string[] = ALL_CHAT_COMPONENTS.filter(
  (name) => !AGENT_UI_COMPONENTS.includes(name)
)

/** Anything that would have the model fetch something. */
const URL_LIKE = /https?:\/\//i

/** Anything that invites the model to make the numbers up. */
const INVENTS_DATA = /\b(realistic|plausible)\b/i

/**
 * Whether a shipped rule or example is safe to carry onto the subset.
 *
 * @param text - One entry of `openuiChatAdditionalRules` or
 *   `openuiChatExamples`.
 * @returns True when it names no component outside the subset, contains no
 *   URL, and does not ask for invented data.
 */
export function usableWithSubset(text: string): boolean {
  if (URL_LIKE.test(text)) return false
  if (INVENTS_DATA.test(text)) return false
  return !OUTSIDE_SUBSET.some((name) => new RegExp(`\\b${name}\\b`).test(text))
}

/** The prompt options the subset is generated with. */
const AGENT_UI_PROMPT_OPTIONS: PromptOptions = {
  additionalRules: [...openuiChatAdditionalRules.filter(usableWithSubset), ...AGENT_UI_RULES],
  examples: openuiChatExamples.filter(usableWithSubset),
}

/**
 * Names in `AGENT_UI_COMPONENTS` the installed package does not define.
 *
 * Empty in a healthy install. A `@openuidev` upgrade that renames or removes a
 * component makes it non-empty, and `openuiLibrary.test.ts` fails on that
 * rather than the chat page throwing at import time: a renamed component is
 * one component missing from a chat, not a dead page.
 *
 * @returns The missing names, in list order.
 */
export function missingAgentUiComponents(): string[] {
  const defined = openuiChatLibrary.components
  return AGENT_UI_COMPONENTS.filter((name) => !defined[name])
}

/**
 * The library the `Renderer` draws with, and the one the prompt is built from.
 *
 * Built once at module load. `root` is carried over from the shipped chat
 * library, which is what makes `root = Card(...)` the entry point the prompt
 * describes.
 */
export const agentUiLibrary: Library = createLibrary({
  components: AGENT_UI_COMPONENTS.map((name) => openuiChatLibrary.components[name]).filter(Boolean),
  root: openuiChatLibrary.root,
})

/**
 * Replace the few non-ASCII characters the shipped prompt contains.
 *
 * The repository is ASCII only, and this string is written to a tracked file.
 * Folding also costs the model nothing: an em dash spelled ` - ` reads the
 * same and tokenises no worse.
 *
 * @param text - The generated prompt.
 * @returns The same text with typographic punctuation replaced.
 */
export function foldToAscii(text: string): string {
  // Written as escapes rather than as the characters themselves, because
  // this repository is ASCII only and a file that folds smart quotes must
  // not contain any.
  return text
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u201c\u201d]/g, '"')
    .replace(/\s*\u2014\s*/g, ' - ')
    .replace(/\s*\u2013\s*/g, '-')
    .replace(/\u2026/g, '...')
    .replace(/\u00a0/g, ' ')
}

/** A parenthesised union of type names, as a signature spells its children. */
const UNION = /\(([A-Za-z][A-Za-z0-9]*(?: \| [A-Za-z][A-Za-z0-9]*)+)\)/g

/**
 * Narrow the child unions in a signature to the components that exist.
 *
 * Subsetting a library narrows which components are **defined**, but it does
 * not narrow the zod schema of the ones that survive, so `Card`'s generated
 * signature still advertises `Image`, `ImageGallery`, `Form` and `Carousel` as
 * legal children when none of them is in the library. That is not cosmetic:
 * the model is being told it may emit a component that cannot parse, and the
 * image ones are precisely the exfiltration channel `Message.tsx` closes for
 * markdown.
 *
 * A union is only rewritten when **every** member is a known component name,
 * so a union of string literals such as `("pie" | "donut")` is left alone, and
 * so is one naming a type this filter does not recognise.
 *
 * @param prompt - The generated prompt.
 * @returns The prompt with every child union reduced to the subset.
 */
export function pruneUnknownComponents(prompt: string): string {
  return prompt.replace(UNION, (whole, body: string) => {
    const members = body.split(' | ')
    if (!members.every((name) => ALL_CHAT_COMPONENTS.includes(name))) return whole
    const kept = members.filter((name) => AGENT_UI_COMPONENTS.includes(name))
    // A union that empties out would leave a signature reading `()[]`, which
    // says less than the wrong list does. Nothing in the subset does this, and
    // the test would catch it if a future cut did.
    return kept.length > 0 ? `(${kept.join(' | ')})` : whole
  })
}

/**
 * The system prompt that teaches the model this library.
 *
 * @returns The prompt, pruned and ASCII folded, ready to be handed to the
 *   backend as one prompt section. Deterministic: the same installed package
 *   always produces the same string, which is what lets the generated file be
 *   compared.
 */
export function buildAgentUiPrompt(): string {
  return pruneUnknownComponents(foldToAscii(agentUiLibrary.prompt(AGENT_UI_PROMPT_OPTIONS)))
}

/**
 * Where the generated prompt is written, relative to the repository root.
 *
 * `docs/prompt/` is where this repository already keeps text that is fed to a
 * model verbatim; `flow-import-format.md` is the precedent. The backend reads
 * the file rather than the frontend posting it, so the prompt costs nothing at
 * request time and is reviewable in a diff.
 */
export const AGENT_UI_PROMPT_PATH = 'docs/prompt/openui-lang.md'

/**
 * The generated file, banner and all.
 *
 * Both the generator script and the test that guards it call this, so the
 * comparison is against one definition of the file rather than against a
 * second copy of the formatting that can drift from the first.
 *
 * The banner is a markdown comment, so a backend that feeds the whole file to
 * the model as one prompt section pays about 150 characters for provenance and
 * renders nothing. That is why `AGENT_UI_PROMPT_MAX_CHARS` is measured against
 * this whole file and not against the prompt inside it: the file is what the
 * budget actually has to hold. The banner deliberately carries no package
 * version, because the file tracks the prompt's **content**: an upgrade that
 * changes nothing needs no commit, and one that changes something fails the
 * test whatever its version number says.
 *
 * @returns The file's exact contents, ending in a newline.
 */
export function renderAgentUiPromptFile(): string {
  return [
    '<!--',
    'GENERATED by frontend/scripts/generate-openui-prompt.mjs from the component',
    'subset in frontend/src/lib/agent/openuiLibrary.ts. Do not edit by hand.',
    '-->',
    '',
    buildAgentUiPrompt().trimEnd(),
    '',
  ].join('\n')
}
