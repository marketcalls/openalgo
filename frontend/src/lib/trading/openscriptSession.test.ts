/**
 * What the panel remembers between one opening and the next.
 *
 * The panel is unmounted whenever another one is up, so everything here is the
 * difference between coming back to the script you were writing and coming
 * back to an empty editor. Two things have to hold, and neither is obvious
 * from reading the happy path.
 *
 * A remembered name is read back into a request for a file, so it is held to
 * the same shape the panel holds a typed name to. What comes back is whatever
 * is in this browser's storage, which is not a place to trust.
 *
 * And a deleted script has to leave both lists. Without that the menu keeps
 * offering a file that is gone and the panel reopens it on the next load,
 * showing a failure the trader had no part in causing.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  forgetScript,
  noteOpened,
  RECENT_LIMIT,
  readLastOpened,
  readRecents,
  writeLastOpened,
} from './openscriptSession'

beforeEach(() => {
  localStorage.clear()
})

describe('the script the panel comes back to', () => {
  it('is the last one opened', () => {
    noteOpened('supertrend.oscript')
    expect(readLastOpened()).toBe('supertrend.oscript')
  })

  it('is nothing before anything has been opened', () => {
    expect(readLastOpened()).toBeNull()
    expect(readRecents()).toEqual([])
  })

  it('refuses a stored name the panel would not accept', () => {
    // Storage is this browser's, not ours. A name that escapes the directory
    // or carries a slash becomes a URL the panel asks the server for, so it is
    // checked on the way out rather than trusted because we wrote it.
    for (const bad of ['../../etc/passwd', 'a/b.oscript', 'plain.txt', '', '-leading.oscript']) {
      localStorage.setItem('oa-trading-script-open', bad)
      expect(readLastOpened()).toBeNull()
    }
  })

  it('is cleared when there is nothing to come back to', () => {
    noteOpened('a.oscript')
    writeLastOpened(null)
    expect(readLastOpened()).toBeNull()
  })
})

describe('the recent scripts', () => {
  it('are newest first, with no repeats', () => {
    noteOpened('a.oscript')
    noteOpened('b.oscript')
    // Asserted on what the call RETURNS, which is what the menu renders from.
    // Reading it back instead hides a write that repeats, because the reader
    // dedupes too: the list would be wrong in storage and right on screen
    // until some other reader came along.
    expect(noteOpened('a.oscript')).toEqual(['a.oscript', 'b.oscript'])
    expect(readRecents()).toEqual(['a.oscript', 'b.oscript'])
  })

  it('stop at the limit, dropping the oldest', () => {
    for (const name of ['a', 'b', 'c', 'd', 'e']) noteOpened(`${name}.oscript`)
    const recents = readRecents()
    expect(recents).toHaveLength(RECENT_LIMIT)
    expect(recents).toEqual(['e.oscript', 'd.oscript', 'c.oscript'])
  })

  it('come back as the call returned them', () => {
    // The caller renders from what it was handed rather than reading storage
    // again. If the two ever disagree the menu shows one thing and the next
    // load shows another, which is the kind of bug nobody reports properly.
    const returned = noteOpened('a.oscript')
    expect(returned).toEqual(readRecents())
  })

  it('survive a stored value that is not a list of names', () => {
    for (const junk of ['{}', 'null', 'not json at all', '[1,2,3]', '["../x"]']) {
      localStorage.setItem('oa-trading-script-recent', junk)
      expect(readRecents()).toEqual([])
    }
  })

  it('drop a deleted script from the menu and from the next load', () => {
    noteOpened('keep.oscript')
    noteOpened('gone.oscript')
    expect(readLastOpened()).toBe('gone.oscript')
    expect(forgetScript('gone.oscript')).toEqual(['keep.oscript'])
    expect(readRecents()).toEqual(['keep.oscript'])
    // The one that was deleted was also the one open, so there is nothing to
    // come back to. Leaving it set is how the panel greets you with the
    // failure of a file you deleted yourself.
    expect(readLastOpened()).toBeNull()
  })

  it('leaves the last opened alone when a different script is deleted', () => {
    noteOpened('gone.oscript')
    noteOpened('keep.oscript')
    forgetScript('gone.oscript')
    expect(readLastOpened()).toBe('keep.oscript')
  })
})

describe('storage that will not cooperate', () => {
  it('reads as empty rather than throwing', () => {
    // Private mode, blocked site data, or simply out of quota. A panel that
    // will not open because it could not remember a file name is a far worse
    // failure than one that opens on nothing.
    const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    expect(readLastOpened()).toBeNull()
    expect(readRecents()).toEqual([])
    get.mockRestore()
  })

  it('writes without throwing, and still answers the caller', () => {
    const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota')
    })
    expect(() => writeLastOpened('a.oscript')).not.toThrow()
    // The returned list is still right for this session even though nothing
    // was persisted, so the menu works until the tab is closed.
    expect(noteOpened('a.oscript', [])).toEqual(['a.oscript'])
    set.mockRestore()
  })
})
