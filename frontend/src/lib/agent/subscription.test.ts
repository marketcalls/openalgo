/**
 * Telling a plan model apart from an API model with the same name.
 *
 * Eight of the ten `chatgpt/` models share a bare name with an `openai` model,
 * so this test is written against the pairs that actually collide rather than
 * against invented ids: `gpt-5.4` and `gpt-5.4-pro` exist under both providers
 * and bill to different places, and `gpt-5.3-instant` and `gpt-5.3-codex-spark`
 * exist only under the plan.
 */

import { describe, expect, it } from 'vitest'
import {
  bareModelName,
  CHATGPT_MODEL_PREFIX,
  isSubscriptionModel,
  suggestSubscriptionDisplayName,
} from './subscription'

/** The two names that mean different bills. */
const COLLIDING = ['gpt-5.4', 'gpt-5.4-pro', 'gpt-5.2', 'gpt-5.3-codex']

describe('isSubscriptionModel', () => {
  it('separates the plan half of a colliding pair from the API half', () => {
    for (const bare of COLLIDING) {
      expect(isSubscriptionModel(`${CHATGPT_MODEL_PREFIX}${bare}`)).toBe(true)
      expect(isSubscriptionModel(`openai/${bare}`)).toBe(false)
      // The bare name on its own is how an `openai` row stores it, so it must
      // not be read as a plan model.
      expect(isSubscriptionModel(bare)).toBe(false)
    }
  })

  it('recognises the two models that exist only under the plan', () => {
    expect(isSubscriptionModel('chatgpt/gpt-5.3-instant')).toBe(true)
    expect(isSubscriptionModel('chatgpt/gpt-5.3-codex-spark')).toBe(true)
  })

  // Unknown is never read as a subscription. A row wrongly labelled as covered
  // by a plan is the reading that costs somebody money.
  it('reads a missing or unrelated name as metered', () => {
    expect(isSubscriptionModel(null)).toBe(false)
    expect(isSubscriptionModel(undefined)).toBe(false)
    expect(isSubscriptionModel('')).toBe(false)
    expect(isSubscriptionModel('anthropic/claude-sonnet-4-20250514')).toBe(false)
    // A provider whose id merely starts with the same letters is not this one.
    expect(isSubscriptionModel('chatgptclone/gpt-5.4')).toBe(false)
  })

  it('is not fooled by case or surrounding whitespace', () => {
    expect(isSubscriptionModel('  ChatGPT/GPT-5.4  ')).toBe(true)
  })
})

describe('bareModelName', () => {
  it('strips whichever provider prefix a name carries', () => {
    expect(bareModelName('chatgpt/gpt-5.4')).toBe('gpt-5.4')
    expect(bareModelName('openai/gpt-5.4')).toBe('gpt-5.4')
    expect(bareModelName('gpt-5.4')).toBe('gpt-5.4')
  })
})

describe('suggestSubscriptionDisplayName', () => {
  // The point of the suggestion: accepting both defaults must not produce two
  // rows called the same thing.
  it('names the billing path, so the two halves of a pair differ', () => {
    expect(suggestSubscriptionDisplayName('chatgpt/gpt-5.4')).toBe('ChatGPT Plan: GPT-5.4')
    expect(suggestSubscriptionDisplayName('chatgpt/gpt-5.4-pro')).toBe('ChatGPT Plan: GPT-5.4-Pro')
  })

  it('keeps the id readable for the longer names', () => {
    expect(suggestSubscriptionDisplayName('chatgpt/gpt-5.3-codex-spark')).toBe(
      'ChatGPT Plan: GPT-5.3-Codex-Spark'
    )
    expect(suggestSubscriptionDisplayName('chatgpt/gpt-5.3-chat-latest')).toBe(
      'ChatGPT Plan: GPT-5.3-Chat-Latest'
    )
  })

  it('suggests nothing rather than a bare label for an empty name', () => {
    expect(suggestSubscriptionDisplayName('')).toBe('')
    expect(suggestSubscriptionDisplayName('chatgpt/')).toBe('')
  })
})
