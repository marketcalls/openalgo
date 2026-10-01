import { act, renderHook, waitFor } from '@testing-library/react'
import type { IndexedDbWorkspaceStorage, WorkspaceCatalog } from 'openalgo-charts/workspace'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useChartWorkspaceCatalog } from './useChartWorkspaceCatalog'

function deferred() {
  let resolve!: () => void
  const promise = new Promise<void>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function storage() {
  const records = new Map<string, WorkspaceCatalog>()
  const adapters: IndexedDbWorkspaceStorage[] = []
  let beforeWrite: (() => Promise<void>) | undefined
  const factory = () => {
    let closed = false
    const adapter: IndexedDbWorkspaceStorage = {
      async read(key) {
        if (closed) throw new Error('closed')
        return structuredClone(records.get(key) ?? null)
      },
      async write(key, value, expected) {
        if (closed) throw new Error('closed')
        await beforeWrite?.()
        if ((records.get(key)?.revision ?? 0) !== expected) throw new Error('conflict')
        records.set(key, structuredClone(value))
      },
      close: vi.fn(async () => {
        closed = true
      }),
    }
    adapters.push(adapter)
    return adapter
  }
  return {
    records,
    adapters,
    factory,
    deferWrites: (fn?: () => Promise<void>) => {
      beforeWrite = fn
    },
  }
}

afterEach(() => vi.unstubAllGlobals())

describe('account-bound chart catalog', () => {
  it('loads and updates the real repository in the current account namespace', async () => {
    const store = storage()
    const { result } = renderHook(() => useChartWorkspaceCatalog('alice', store.factory))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.catalog?.templates).toEqual([])
    await act(async () => {
      await result.current.run((repo) => repo.createTemplate('Momentum', []))
    })
    expect(result.current.catalog?.templates[0].name).toBe('Momentum')
    expect(store.records.has('oa-trading:alice')).toBe(true)
    expect(result.current.pending).toBe(false)
  })

  it('keeps the previous list after a rejected write and allows a retry', async () => {
    const store = storage()
    const { result } = renderHook(() => useChartWorkspaceCatalog('alice', store.factory))
    await waitFor(() => expect(result.current.loading).toBe(false))
    await act(async () => {
      await result.current.run((repo) => repo.createTemplate('First', []))
    })
    store.deferWrites(async () => {
      throw new Error('Storage quota reached')
    })
    await act(async () => {
      await expect(result.current.run((repo) => repo.createTemplate('Second', []))).rejects.toThrow(
        'quota'
      )
    })
    expect(result.current.catalog?.templates.map((item) => item.name)).toEqual(['First'])
    expect(result.current.error).toContain('quota')
    store.deferWrites()
    await act(async () => {
      await result.current.run((repo) => repo.createTemplate('Second', []))
    })
    expect(result.current.catalog?.templates.map((item) => item.name)).toEqual(['First', 'Second'])
    expect(result.current.error).toBeNull()
  })

  it('keeps pending true until every concurrent operation finishes', async () => {
    const store = storage()
    const { result } = renderHook(() => useChartWorkspaceCatalog('alice', store.factory))
    await waitFor(() => expect(result.current.loading).toBe(false))
    const slow = deferred()
    let first!: Promise<unknown>
    let second!: Promise<unknown>
    act(() => {
      first = result.current.run((repo) => repo.createTemplate('First', []))
      second = result.current.run(async (repo) => {
        await slow.promise
        return repo.createTemplate('Second', [])
      })
    })
    await act(async () => {
      await first
    })
    expect(result.current.pending).toBe(true)
    await act(async () => {
      slow.resolve()
      await second
    })
    expect(result.current.pending).toBe(false)
    expect(result.current.catalog?.templates).toHaveLength(2)
  })

  it('finishes an old write in its owner namespace without publishing stale success', async () => {
    const store = storage()
    const gate = deferred()
    const started = deferred()
    const { result, rerender } = renderHook(
      ({ account }) => useChartWorkspaceCatalog(account, store.factory),
      { initialProps: { account: 'alice' } }
    )
    await waitFor(() => expect(result.current.loading).toBe(false))
    const oldRun = result.current.run
    store.deferWrites(async () => {
      started.resolve()
      await gate.promise
    })
    let outcome!: Promise<unknown>
    act(() => {
      outcome = oldRun((repo) => repo.createTemplate('Private', [])).catch((error) => error)
    })
    await act(async () => {
      await started.promise
    })
    rerender({ account: 'bob' })
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.catalog?.templates).toEqual([])
    await act(async () => {
      gate.resolve()
    })
    expect(await outcome).toMatchObject({ message: expect.stringMatching(/account|session/i) })
    expect(store.records.get('oa-trading:alice')?.templates[0].name).toBe('Private')
    expect(store.records.has('oa-trading:bob')).toBe(false)
    expect(result.current.catalog?.templates).toEqual([])
    expect(result.current.error).toBeNull()
    await expect(oldRun((repo) => repo.createTemplate('Wrong owner', []))).rejects.toThrow(
      /account|session/i
    )
  })

  it('rejects delayed completions after unmount and closes its adapter', async () => {
    const store = storage()
    const { result, unmount } = renderHook(() => useChartWorkspaceCatalog('alice', store.factory))
    await waitFor(() => expect(result.current.loading).toBe(false))
    const gate = deferred()
    let outcome!: Promise<unknown>
    act(() => {
      outcome = result.current
        .run(async () => {
          await gate.promise
          return 'done'
        })
        .catch((error) => error)
    })
    unmount()
    gate.resolve()
    expect(await outcome).toBeInstanceOf(Error)
    expect(store.adapters[0].close).toHaveBeenCalledOnce()
  })

  it('creates no repository for an absent account', async () => {
    const factory = vi.fn(storage().factory)
    const { result } = renderHook(() => useChartWorkspaceCatalog(null, factory))
    expect(factory).not.toHaveBeenCalled()
    expect(result.current.catalog).toBeNull()
    expect(result.current.loading).toBe(false)
    await expect(result.current.run((repo) => repo.createTemplate('No owner', []))).rejects.toThrow(
      /account|session/i
    )
  })

  it('reports unavailable browser storage without falling back to shared preferences', async () => {
    vi.stubGlobal('indexedDB', undefined)
    const { result } = renderHook(() => useChartWorkspaceCatalog('alice'))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.error).toMatch(/storage|IndexedDB/i)
    expect(result.current.catalog).toBeNull()
  })

  it('creates a fresh adapter after StrictMode cleanup', async () => {
    const store = storage()
    const { result, unmount } = renderHook(() => useChartWorkspaceCatalog('alice', store.factory), {
      reactStrictMode: true,
    })
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(store.adapters).toHaveLength(2)
    expect(store.adapters[0].close).toHaveBeenCalledOnce()
    await act(async () => {
      await result.current.run((repo) => repo.createTemplate('Fresh', []))
    })
    expect(result.current.catalog?.templates[0].name).toBe('Fresh')
    unmount()
    expect(store.adapters[1].close).toHaveBeenCalledOnce()
  })

  it('reloads changes saved by another repository', async () => {
    const store = storage()
    const first = renderHook(() => useChartWorkspaceCatalog('alice', store.factory))
    const second = renderHook(() => useChartWorkspaceCatalog('alice', store.factory))
    await waitFor(() =>
      expect(first.result.current.loading || second.result.current.loading).toBe(false)
    )
    await act(async () => {
      await second.result.current.run((repo) => repo.createTemplate('Elsewhere', []))
    })
    expect(first.result.current.catalog?.templates).toEqual([])
    await act(async () => {
      await first.result.current.reload()
    })
    expect(first.result.current.catalog?.templates[0].name).toBe('Elsewhere')
  })
})
