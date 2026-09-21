import { describe, expect, it, vi } from 'vitest'
import { WorkspaceTransition } from './workspaceTransition'

function deferred<T = void>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}
function grid(ready = Promise.resolve()) {
  return { ready, destroy: vi.fn() }
}
async function flush() {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

describe('transactional workspace ownership', () => {
  it('retains the published grid and unlocks when the previous grid cleanup throws', async () => {
    const old = grid(),
      next = grid(),
      pending = vi.fn(),
      cleanup = vi.fn()
    const failure = new Error('Old feed cleanup failed')
    old.destroy.mockImplementation(() => {
      throw failure
    })
    const owner = new WorkspaceTransition(old, pending, cleanup)
    await expect(
      owner.open(
        () => next,
        async () => {},
        () => {}
      )
    ).resolves.toBe(next)
    expect(next.destroy).not.toHaveBeenCalled()
    expect(pending).toHaveBeenLastCalledWith(false)
    expect(cleanup).toHaveBeenCalledWith(failure)
    owner.destroy()
    expect(next.destroy).toHaveBeenCalledOnce()
  })

  it('unlocks after a cancelled staging cleanup throws and can open another grid', async () => {
    const old = grid(),
      staging = grid(new Promise(() => {})),
      next = grid()
    const pending = vi.fn(),
      cleanup = vi.fn()
    staging.destroy.mockImplementation(() => {
      throw new Error('Staging cleanup failed')
    })
    const owner = new WorkspaceTransition(old, pending, cleanup)
    const opening = owner.open(
      () => staging,
      async () => {},
      () => {}
    )
    const rejected = expect(opening).rejects.toThrow(/cancel/i)
    expect(() => owner.cancel()).not.toThrow()
    await rejected
    expect(pending).toHaveBeenLastCalledWith(false)
    expect(old.destroy).not.toHaveBeenCalled()
    expect(cleanup).toHaveBeenCalledOnce()
    await expect(
      owner.open(
        () => next,
        async () => {},
        () => {}
      )
    ).resolves.toBe(next)
    owner.destroy()
  })

  it('releases the active grid on teardown even when pending cleanup throws', async () => {
    const old = grid(),
      staging = grid(new Promise(() => {}))
    staging.destroy.mockImplementation(() => {
      throw new Error('Staging cleanup failed')
    })
    const owner = new WorkspaceTransition(
      old,
      () => {},
      () => {}
    )
    const opening = owner.open(
      () => staging,
      async () => {},
      () => {}
    )
    const rejected = expect(opening).rejects.toThrow(/cancel/i)
    expect(() => owner.destroy()).not.toThrow()
    await rejected
    owner.destroy()
    expect(old.destroy).toHaveBeenCalledOnce()
    expect(staging.destroy).toHaveBeenCalledOnce()
  })

  it('releases a grid even when its factory cancels ownership before returning', async () => {
    const old = grid(),
      next = grid(),
      publish = vi.fn()
    const owner = new WorkspaceTransition(old)
    await expect(
      owner.open(
        () => {
          owner.cancel()
          return next
        },
        async () => {},
        publish
      )
    ).rejects.toThrow(/cancel/i)
    expect(next.destroy).toHaveBeenCalledTimes(1)
    expect(old.destroy).not.toHaveBeenCalled()
    expect(publish).not.toHaveBeenCalled()
    owner.destroy()
  })

  it('keeps the old grid until all panes and the catalog commit are ready', async () => {
    const old = grid(),
      first = deferred(),
      second = deferred(),
      write = deferred()
    const next = grid(Promise.all([first.promise, second.promise]).then(() => {}))
    const pending = vi.fn(),
      persist = vi.fn(() => write.promise),
      publish = vi.fn()
    const owner = new WorkspaceTransition(old, pending)
    const opening = owner.open(() => next, persist, publish)
    second.resolve()
    await flush()
    expect(persist).not.toHaveBeenCalled()
    expect(old.destroy).not.toHaveBeenCalled()
    first.resolve()
    await flush()
    expect(persist).toHaveBeenCalledTimes(1)
    expect(publish).not.toHaveBeenCalled()
    write.resolve()
    await expect(opening).resolves.toBe(next)
    expect(publish).toHaveBeenCalledWith(next)
    expect(old.destroy).toHaveBeenCalledTimes(1)
    expect(next.destroy).not.toHaveBeenCalled()
    expect(pending.mock.calls).toEqual([[true], [false]])
    owner.destroy()
    expect(next.destroy).toHaveBeenCalledTimes(1)
  })

  it('destroys every staged owner on pane failure and retains the previous grid', async () => {
    const old = grid(),
      first = deferred(),
      second = deferred()
    const next = grid(Promise.all([first.promise, second.promise]).then(() => {}))
    const persist = vi.fn(),
      publish = vi.fn()
    const owner = new WorkspaceTransition(old)
    const opening = owner.open(() => next, persist, publish)
    const rejected = expect(opening).rejects.toThrow('History unavailable')
    first.reject(new Error('History unavailable'))
    await rejected
    second.resolve()
    await flush()
    expect(next.destroy).toHaveBeenCalledTimes(1)
    expect(old.destroy).not.toHaveBeenCalled()
    expect(persist).not.toHaveBeenCalled()
    expect(publish).not.toHaveBeenCalled()
    owner.destroy()
  })

  it('retains the previous grid when the active-document write is refused', async () => {
    const old = grid(),
      next = grid(),
      publish = vi.fn()
    const owner = new WorkspaceTransition(old)
    await expect(
      owner.open(
        () => next,
        async () => {
          throw new Error('Storage full')
        },
        publish
      )
    ).rejects.toThrow('Storage full')
    expect(publish).not.toHaveBeenCalled()
    expect(old.destroy).not.toHaveBeenCalled()
    expect(next.destroy).toHaveBeenCalledTimes(1)
    owner.destroy()
  })

  it('rejects a superseded open promptly even if its readiness never settles', async () => {
    const old = grid(),
      stale = grid(new Promise(() => {})),
      next = grid()
    const owner = new WorkspaceTransition(old),
      firstPublish = vi.fn(),
      secondPublish = vi.fn()
    const first = owner.open(
      () => stale,
      async () => {},
      firstPublish
    )
    const cancelled = expect(first).rejects.toThrow(/cancel/i)
    await owner.open(
      () => next,
      async () => {},
      secondPublish
    )
    await cancelled
    expect(stale.destroy).toHaveBeenCalledTimes(1)
    expect(firstPublish).not.toHaveBeenCalled()
    expect(secondPublish).toHaveBeenCalledWith(next)
    expect(old.destroy).toHaveBeenCalledTimes(1)
    owner.destroy()
  })

  it('aborts the pending catalog operation and ignores a late storage response', async () => {
    const old = grid(),
      next = grid(),
      write = deferred(),
      publish = vi.fn()
    const owner = new WorkspaceTransition(old)
    let signal: AbortSignal | undefined
    const persist = vi.fn((value: AbortSignal) => {
      signal = value
      return write.promise
    })
    const opening = owner.open(() => next, persist, publish)
    const cancelled = expect(opening).rejects.toThrow(/cancel/i)
    await flush()
    expect(persist).toHaveBeenCalledTimes(1)
    owner.cancel()
    await cancelled
    expect(signal?.aborted).toBe(true)
    write.resolve()
    await flush()
    expect(publish).not.toHaveBeenCalled()
    expect(next.destroy).toHaveBeenCalledTimes(1)
    expect(old.destroy).not.toHaveBeenCalled()
    owner.destroy()
  })

  it('releases old and pending grids on account change or page teardown', async () => {
    const old = grid(),
      ready = deferred(),
      next = grid(ready.promise),
      publish = vi.fn()
    const owner = new WorkspaceTransition(old)
    const opening = owner.open(
      () => next,
      async () => {},
      publish
    )
    const cancelled = expect(opening).rejects.toThrow(/cancel/i)
    owner.destroy()
    owner.destroy()
    await cancelled
    ready.resolve()
    await flush()
    expect(old.destroy).toHaveBeenCalledTimes(1)
    expect(next.destroy).toHaveBeenCalledTimes(1)
    expect(publish).not.toHaveBeenCalled()
    await expect(
      owner.open(
        () => grid(),
        async () => {},
        publish
      )
    ).rejects.toThrow(/closed/i)
  })

  it('recovers from synchronous preparation failure without losing the old grid', async () => {
    const old = grid(),
      next = grid(),
      pending = vi.fn(),
      publish = vi.fn()
    const owner = new WorkspaceTransition(old, pending)
    await expect(
      owner.open(
        () => {
          throw new Error('Bad document')
        },
        async () => {},
        publish
      )
    ).rejects.toThrow('Bad document')
    expect(old.destroy).not.toHaveBeenCalled()
    await owner.open(
      () => next,
      async () => {},
      publish
    )
    expect(old.destroy).toHaveBeenCalledTimes(1)
    expect(pending.mock.calls).toEqual([[true], [false], [true], [false]])
    owner.destroy()
  })
})
