/**
 * Telling a plan model apart from an API model, everywhere it is shown.
 *
 * This is the whole point of the ChatGPT subscription feature, and it is a
 * naming problem rather than a plumbing one. LiteLLM offers the same ten models
 * under two providers with two different bills:
 *
 * ```
 * openai/gpt-5.4     your API key       -> OpenAI API credits
 * chatgpt/gpt-5.4    an OAuth sign-in   -> your Plus or Pro plan
 * ```
 *
 * Eight of the ten share a bare name with an `openai` model, `gpt-5.4` and
 * `gpt-5.4-pro` among them; only `gpt-5.3-instant` and `gpt-5.3-codex-spark`
 * are subscription only. So an operator who has registered both ends up with
 * two rows reading GPT-5.4 that bill to different places, and nothing in the
 * data distinguishes them except the prefix on the stored model name. The UI is
 * the only thing that can tell them apart, which is why the test is here rather
 * than left to each component.
 *
 * The prefix is the test because it is what the operator actually stored: a
 * `chatgpt` model is registered under `provider_kind: 'litellm'` and its name is
 * passed to LiteLLM verbatim, prefix included. `MODEL_PREFIX` in
 * `services/agent/chatgpt_oauth.py` is the same string on the server.
 */

/** The prefix a plan model's stored name carries. Mirrors MODEL_PREFIX. */
export const CHATGPT_MODEL_PREFIX = 'chatgpt/'

/** The provider id LiteLLM lists the plan models under. Mirrors PROVIDER_ID. */
export const CHATGPT_PROVIDER_ID = 'chatgpt'

/**
 * The short label a plan row wears, wherever a model is named.
 *
 * Says the billing path rather than the provider, because the provider is the
 * part an operator can already read off the model name. What they cannot read
 * off it is which of two identically named rows costs them money per token.
 */
export const SUBSCRIPTION_BADGE = 'ChatGPT plan'

/** Its counterpart, used only where the contrast has to be drawn explicitly. */
export const METERED_BADGE = 'API credits'

/**
 * Whether a stored model name bills to a ChatGPT plan.
 *
 * @param modelName - `ag_provider_model.model_name`, as stored.
 * @returns True for a `chatgpt/` model, false for everything else including a
 *   missing name. Unknown is never read as a subscription: a row wrongly
 *   labelled as covered by a plan is the reading that costs somebody money.
 */
export function isSubscriptionModel(modelName: string | null | undefined): boolean {
  if (typeof modelName !== 'string') return false
  return modelName.trim().toLowerCase().startsWith(CHATGPT_MODEL_PREFIX)
}

/**
 * The model name with its provider prefix removed.
 *
 * @param modelName - A stored model name, with or without a prefix.
 * @returns The bare name, which is the half that collides with an `openai` row.
 */
export function bareModelName(modelName: string): string {
  const last = modelName.split('/').pop()
  return last ?? modelName
}

/** Segments that are acronyms rather than words, and are shouted, not capitalised. */
const ACRONYMS = new Set(['gpt', 'ai', 'api'])

/**
 * A display name that says where the turn is billed before it says the model.
 *
 * "ChatGPT Plan: GPT-5.4" rather than "GPT-5.4", so the picker and the registry
 * are unambiguous even for an operator who never renamed their rows. The prefix
 * leads because that is what a reader is scanning for when two rows share a
 * name; putting it after the model puts the distinguishing half where the
 * column is most likely to truncate.
 *
 * The model half keeps the id's own hyphens rather than flattening them to
 * spaces, so "GPT-5.4-Pro" still reads back as the id it was made from.
 *
 * @param modelName - The stored model name, with or without its prefix.
 * @returns A suggested display name. Only a suggestion: it stays editable, and
 *   an empty model name yields an empty string rather than a bare label.
 */
export function suggestSubscriptionDisplayName(modelName: string): string {
  const bare = bareModelName(modelName).trim()
  if (!bare) return ''
  const pretty = bare
    .split('-')
    .map((segment) => {
      if (!segment) return segment
      if (ACRONYMS.has(segment.toLowerCase())) return segment.toUpperCase()
      return segment[0].toUpperCase() + segment.slice(1)
    })
    .join('-')
  return `ChatGPT Plan: ${pretty}`
}
