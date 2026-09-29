/**
 * Unsaved edits kept per script.
 *
 * Two copies matter and each is tested for what it alone covers: the page's
 * copy is what survives a switch of script or a closed panel, including where
 * storage is refused, and storage is what survives a reload.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  dropDraft,
  fingerprintOf,
  flushDrafts,
  forgetDraftsInPage,
  hasDraft,
  keepDraft,
  readDraft,
  WRITE_DELAY_MS,
} from './openscriptDrafts'

const KEY = 'oa-trading-script-draft:trend.oscript'

beforeEach(() => {
  forgetDraftsInPage()
  localStorage.clear()
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('keeping a draft', () => {
  it('holds what was typed, and what it was typed over', () => {
    keepDraft('trend.oscript', 'edited', 'saved')
    expect(readDraft('trend.oscript')).toEqual({ text: 'edited', base: fingerprintOf('saved') })
    expect(hasDraft('trend.oscript')).toBe(true)
  })

  it('forgets the draft once the text matches the saved copy again', () => {
    keepDraft('trend.oscript', 'edited', 'saved')
    keepDraft('trend.oscript', 'saved', 'saved')
    flushDrafts()
    expect(readDraft('trend.oscript')).toBeNull()
    expect(localStorage.getItem(KEY)).toBeNull()
  })

  it('keeps one draft per script', () => {
    keepDraft('a.oscript', 'one', '')
    keepDraft('b.oscript', 'two', '')
    expect(readDraft('a.oscript')?.text).toBe('one')
    expect(readDraft('b.oscript')?.text).toBe('two')
  })

  it('refuses a name the panel would not accept, since it is read back into a URL', () => {
    keepDraft('../x.oscript', 'text', '')
    keepDraft('noextension', 'text', '')
    expect(readDraft('../x.oscript')).toBeNull()
    expect(readDraft('noextension')).toBeNull()
  })
})

describe('storage', () => {
  it('is written a moment after typing stops, not on every key', () => {
    vi.useFakeTimers()
    keepDraft('trend.oscript', 'e', 'saved')
    keepDraft('trend.oscript', 'ed', 'saved')
    expect(localStorage.getItem(KEY)).toBeNull()
    vi.advanceTimersByTime(WRITE_DELAY_MS)
    expect(JSON.parse(localStorage.getItem(KEY) ?? '{}').text).toBe('ed')
  })

  it('is written at once when flushed, which is what a closing panel does', () => {
    keepDraft('trend.oscript', 'edited', 'saved')
    flushDrafts()
    expect(JSON.parse(localStorage.getItem(KEY) ?? '{}').text).toBe('edited')
  })

  it('carries a draft over a reload, which is the page forgetting its own copy', () => {
    keepDraft('trend.oscript', 'edited', 'saved')
    flushDrafts()
    forgetDraftsInPage()
    expect(readDraft('trend.oscript')).toEqual({ text: 'edited', base: fingerprintOf('saved') })
  })

  it('reads a stored value that is not a draft as no draft', () => {
    localStorage.setItem(KEY, 'not json')
    expect(readDraft('trend.oscript')).toBeNull()
    localStorage.setItem(KEY, JSON.stringify({ text: 5 }))
    expect(readDraft('trend.oscript')).toBeNull()
  })

  it('still keeps the draft in the page when storage refuses it', () => {
    // Private mode, blocked site data or a full quota. A switch of script and
    // a closed panel must still be lossless; only a reload is lost.
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError')
    })
    keepDraft('trend.oscript', 'edited', 'saved')
    expect(() => flushDrafts()).not.toThrow()
    expect(readDraft('trend.oscript')?.text).toBe('edited')
  })

  it('dropping a draft removes it from storage as well', () => {
    keepDraft('trend.oscript', 'edited', 'saved')
    flushDrafts()
    dropDraft('trend.oscript')
    expect(localStorage.getItem(KEY)).toBeNull()
    forgetDraftsInPage()
    expect(readDraft('trend.oscript')).toBeNull()
  })
})

describe('the fingerprint of the saved copy', () => {
  it('tells two texts apart and agrees with itself', () => {
    expect(fingerprintOf('plot(close)')).toBe(fingerprintOf('plot(close)'))
    expect(fingerprintOf('plot(close)')).not.toBe(fingerprintOf('plot(open)'))
    expect(fingerprintOf('')).not.toBe(fingerprintOf(' '))
  })
})
