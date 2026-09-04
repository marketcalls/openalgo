/**
 * What must stay true about the OpenUI library and the prompt built from it.
 *
 * The first test is the defect itself. The prompt generator **fails silently**
 * when it is called the wrong way: it returns a plausible, well-formed prompt
 * in which every component name is the literal `undefined`, because the
 * per-component signature it reads exists only on `toSpec()`. Nothing throws,
 * nothing logs, and the only symptom is a model that cannot name a single
 * component. So the wrong calls are exercised here on purpose and pinned to
 * their exact damage, and the right ones are pinned to zero.
 *
 * The second thing this file guards is drift. The prompt is generated from the
 * same library object the browser renders with, and committed to
 * `docs/prompt/openui-lang.md` because a production server has no Node.js and
 * a `git pull` has to be enough to upgrade. A `@openuidev` upgrade that changes
 * a component's signature therefore changes what the renderer accepts while the
 * committed prompt still describes the old shape. Regenerating and comparing is
 * what turns that into a failed build instead of a model being told about a
 * library it is no longer being given.
 */

import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createLibrary, generateSystemPrompt } from '@openuidev/react-lang'
import { openuiChatLibrary } from '@openuidev/react-ui/genui-lib'
import { describe, expect, it } from 'vitest'
import {
  AGENT_UI_COMPONENTS,
  AGENT_UI_PROMPT_MAX_CHARS,
  AGENT_UI_PROMPT_PATH,
  agentUiLibrary,
  buildAgentUiPrompt,
  foldToAscii,
  missingAgentUiComponents,
  pruneUnknownComponents,
  renderAgentUiPromptFile,
  usableWithSubset,
} from './openuiLibrary'

/**
 * The generated file, found from wherever the runner was started.
 *
 * `import.meta.url` is not a file URL under the jsdom environment, so the
 * lookup walks up from the working directory instead: `frontend/` when the
 * documented command is used, the repository root when CI runs vitest from
 * there.
 */
function promptFilePath(): string {
  for (const prefix of ['.', '..', '../..']) {
    const candidate = resolve(process.cwd(), prefix, AGENT_UI_PROMPT_PATH)
    if (existsSync(candidate)) return candidate
  }
  throw new Error(
    `${AGENT_UI_PROMPT_PATH} was not found above ${process.cwd()}. Generate it: cd frontend && node scripts/generate-openui-prompt.mjs`
  )
}

function countUndefined(prompt: string): number {
  return (prompt.match(/undefined/g) || []).length
}

describe('the generation call', () => {
  it('names every component, and the wrong calls name none', () => {
    const prompt = buildAgentUiPrompt()
    expect(countUndefined(prompt)).toBe(0)
    for (const name of AGENT_UI_COMPONENTS) {
      expect(prompt).toContain(name)
    }

    // The two shapes that look right and are not. Each emits the literal
    // `undefined` once per component, which is the whole of the damage: the
    // prompt is otherwise well formed, so nothing downstream notices.
    const wrongPositional = generateSystemPrompt(
      agentUiLibrary as unknown as Parameters<typeof generateSystemPrompt>[0]
    )
    const wrongLibraryObject = generateSystemPrompt({
      library: agentUiLibrary,
    } as unknown as Parameters<typeof generateSystemPrompt>[0])

    expect(countUndefined(wrongPositional)).toBe(AGENT_UI_COMPONENTS.length)
    expect(countUndefined(wrongLibraryObject)).toBe(AGENT_UI_COMPONENTS.length)
  })

  it('agrees with generateSystemPrompt on the library spec', () => {
    // The two documented correct forms. Asserted equal so a future refactor
    // between them cannot change what the model is told.
    expect(foldToAscii(generateSystemPrompt({ library: agentUiLibrary.toSpec() }))).toBe(
      foldToAscii(agentUiLibrary.prompt())
    )
  })

  it('refuses to rebuild the shipped library, which is already built', () => {
    // Documented so nobody reaches for the obvious call: `openuiChatLibrary` is
    // a Library, not a definition, and `createLibrary` needs the components
    // array that only its `components` map can supply.
    expect(() =>
      createLibrary(openuiChatLibrary as unknown as Parameters<typeof createLibrary>[0])
    ).toThrow()
  })
})

describe('the component subset', () => {
  it('resolves every name against the installed package', () => {
    expect(missingAgentUiComponents()).toEqual([])
    expect(Object.keys(agentUiLibrary.components)).toHaveLength(AGENT_UI_COMPONENTS.length)
  })

  it('drops shipped guidance that names a component the subset does not have', () => {
    // Carried unfiltered, these teach the model to emit components the
    // renderer has never heard of, and the block fails to parse.
    expect(usableWithSubset('Use FollowUpBlock at the END of a Card.')).toBe(false)
    expect(usableWithSubset('Carousel takes an array of slides.')).toBe(false)
    expect(usableWithSubset('Use ListBlock when presenting a set of options.')).toBe(true)
  })

  it('drops any rule that would have the model fetch or invent something', () => {
    expect(usableWithSubset('always use real URLs like https://picsum.photos/seed/x/800/500')).toBe(
      false
    )
    expect(usableWithSubset('When asked about data, generate realistic/plausible data')).toBe(false)
  })

  it('teaches nothing it cannot render, and nothing this product refuses', () => {
    const prompt = buildAgentUiPrompt()
    // Subsetting the library narrows which components are defined but not the
    // schema of the ones that stay, so without pruning Card's own signature
    // still offers all four of these as legal children.
    for (const name of ['FollowUpBlock', 'Carousel', 'ImageGallery', 'ScatterChart']) {
      expect(prompt).not.toContain(name)
    }
    expect(prompt).not.toMatch(/\b(realistic|plausible)\b/i)
    expect(prompt).not.toContain('picsum.photos')
    // The provenance rule. This is the one tier whose numbers the model types.
    expect(prompt).toContain('Every number here comes from a tool result')
    expect(prompt).toContain('Never emit a URL, a link or an image')
  })

  it('leaves a union of literals alone while narrowing a union of components', () => {
    expect(pruneUnknownComponents('x(children: (TextContent | ImageGallery | Table)[])')).toBe(
      'x(children: (TextContent | Table)[])'
    )
    // A size or a variant is not a component list and must survive untouched.
    expect(pruneUnknownComponents('size?: ("small" | "default" | "large")')).toBe(
      'size?: ("small" | "default" | "large")'
    )
    // Nothing recognisable, so nothing is assumed.
    expect(pruneUnknownComponents('(Alpha | Beta)')).toBe('(Alpha | Beta)')
  })
})

describe('the committed prompt file', () => {
  it('matches a fresh regeneration', () => {
    const onDisk = readFileSync(promptFilePath(), 'utf8')
    expect(
      onDisk,
      `${AGENT_UI_PROMPT_PATH} is stale. Regenerate it: cd frontend && node scripts/generate-openui-prompt.mjs`
    ).toBe(renderAgentUiPromptFile())
  })

  it('is ASCII, so it can live in this repository', () => {
    const offenders = [
      ...new Set([...renderAgentUiPromptFile()].filter((c) => c.charCodeAt(0) > 127)),
    ]
    expect(offenders).toEqual([])
  })

  it('fits the system prompt budget', () => {
    // Overshooting does not truncate this section. `render_sections` drops
    // whole unpinned sections from the end to fit the cap, so an oversized
    // prompt here silently deletes a different one.
    expect(renderAgentUiPromptFile().length).toBeLessThanOrEqual(AGENT_UI_PROMPT_MAX_CHARS)
  })
})
