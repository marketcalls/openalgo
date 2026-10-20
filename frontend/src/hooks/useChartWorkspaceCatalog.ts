import {
  createIndexedDbWorkspaceStorage,
  type IndexedDbWorkspaceStorage,
  type WorkspaceCatalog,
  WorkspaceRepository,
} from 'openalgo-charts/workspace'
import { useCallback, useEffect, useRef, useState } from 'react'

export interface ChartWorkspaceCatalogState {
  catalog: WorkspaceCatalog | null
  loading: boolean
  pending: boolean
  error: string | null
  reload(): Promise<void>
  run<T>(operation: (repository: WorkspaceRepository) => Promise<T>): Promise<T>
}

interface Owner {
  account: string
  repository: WorkspaceRepository
  storage: IndexedDbWorkspaceStorage
  active: boolean
  pending: number
}
interface View {
  account: string | null
  catalog: WorkspaceCatalog | null
  loading: boolean
  pending: boolean
  error: string | null
}

function browserStorage(): IndexedDbWorkspaceStorage {
  if (!window.indexedDB) throw new Error('Browser workspace storage is unavailable')
  return createIndexedDbWorkspaceStorage(window.indexedDB)
}

const sessionError = () =>
  new Error('Chart workspace account or session changed. Retry in the current session.')
const errorMessage = (error: unknown) => (error instanceof Error ? error.message : String(error))
const empty = (account: string | null): View => ({
  account,
  catalog: null,
  loading: account !== null,
  pending: false,
  error: null,
})

/** Each mounted account owns its repository and every pending completion. */
export function useChartWorkspaceCatalog(
  account: string | null,
  storageFactory: () => IndexedDbWorkspaceStorage = browserStorage
): ChartWorkspaceCatalogState {
  const ownerRef = useRef<Owner | null>(null)
  const [view, setView] = useState<View>(() => empty(account))

  const owns = useCallback((owner: Owner) => owner.active && ownerRef.current === owner, [])
  const refresh = useCallback(
    async (owner: Owner) => {
      const catalog = await owner.repository.load()
      if (!owns(owner)) throw sessionError()
      setView((previous) => ({
        ...previous,
        catalog:
          previous.catalog && previous.catalog.revision > catalog.revision
            ? previous.catalog
            : catalog,
        loading: false,
        error: null,
      }))
    },
    [owns]
  )

  useEffect(() => {
    setView(empty(account))
    if (account === null) return
    let storage: IndexedDbWorkspaceStorage | undefined
    let owner: Owner
    try {
      storage = storageFactory()
      owner = {
        account,
        storage,
        repository: new WorkspaceRepository(storage, `oa-trading:${account}`),
        active: true,
        pending: 0,
      }
      ownerRef.current = owner
    } catch (error) {
      void storage?.close().catch(() => {})
      setView({ ...empty(account), loading: false, error: errorMessage(error) })
      return
    }
    void refresh(owner).catch((error) => {
      if (owns(owner))
        setView((previous) => ({ ...previous, loading: false, error: errorMessage(error) }))
    })
    return () => {
      owner.active = false
      if (ownerRef.current === owner) ownerRef.current = null
      void owner.storage.close().catch(() => {})
    }
  }, [account, storageFactory, refresh, owns])

  const currentOwner = useCallback(() => {
    const owner = ownerRef.current
    if (!owner || owner.account !== account || !owns(owner)) throw sessionError()
    return owner
  }, [account, owns])

  const reload = useCallback(async () => {
    const owner = currentOwner()
    setView((previous) => ({ ...previous, loading: true, error: null }))
    try {
      await refresh(owner)
    } catch (error) {
      if (!owns(owner)) throw sessionError()
      setView((previous) => ({ ...previous, loading: false, error: errorMessage(error) }))
      throw error
    }
  }, [currentOwner, owns, refresh])

  const run = useCallback(
    async <T>(operation: (repository: WorkspaceRepository) => Promise<T>): Promise<T> => {
      const owner = currentOwner()
      owner.pending++
      setView((previous) => ({ ...previous, pending: true, error: null }))
      try {
        const result = await operation(owner.repository)
        if (!owns(owner)) throw sessionError()
        await refresh(owner)
        return result
      } catch (error) {
        if (!owns(owner)) throw sessionError()
        setView((previous) => ({ ...previous, error: errorMessage(error) }))
        throw error
      } finally {
        owner.pending--
        if (owns(owner)) setView((previous) => ({ ...previous, pending: owner.pending > 0 }))
      }
    },
    [currentOwner, owns, refresh]
  )

  // Avoid showing the outgoing account's catalog before its effect cleanup runs.
  const visible = view.account === account ? view : empty(account)
  return {
    catalog: visible.catalog,
    loading: visible.loading,
    pending: visible.pending,
    error: visible.error,
    reload,
    run,
  }
}
