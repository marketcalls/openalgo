import type { WorkspacePayload } from 'openalgo-charts/workspace'
import { useCallback, useEffect, useRef, useState } from 'react'
import { PreparedChartGrid } from '@/lib/trading/preparedGrid'
import { WorkspaceTransition } from '@/lib/trading/workspaceTransition'

interface View {
  account: string | null
  grids: PreparedChartGrid[]
  current: PreparedChartGrid | null
  pending: boolean
  error: string | null
}
interface Owner {
  account: string | null
  live: boolean
  grids: Set<PreparedChartGrid>
  current: PreparedChartGrid | null
  transition: WorkspaceTransition<PreparedChartGrid>
  operation: number
}
const empty = (account: string | null): View => ({
  account,
  grids: [],
  current: null,
  pending: false,
  error: null,
})

/** The account owns both React staging and the cancellable catalog transaction. */
export function useWorkspaceGridTransition(
  account: string | null,
  publish: (grid: PreparedChartGrid) => void,
  lock: (pending: boolean) => void
) {
  const callbacks = useRef({ publish, lock })
  callbacks.current = { publish, lock }
  const ownerRef = useRef<Owner | null>(null)
  const [view, setView] = useState<View>(() => empty(account))

  useEffect(() => {
    const owner: Owner = {
      account,
      live: true,
      grids: new Set(),
      current: null,
      operation: 0,
      transition: new WorkspaceTransition<PreparedChartGrid>(
        null,
        (pending) => {
          if (!owner.live) return
          for (const grid of owner.grids) grid.setLocked(pending || grid !== owner.current)
          callbacks.current.lock(pending)
          setView((previous) => ({ ...previous, pending }))
        },
        (error) => {
          if (owner.live)
            setView((previous) => ({
              ...previous,
              error: error instanceof Error ? error.message : String(error),
            }))
          else console.error('Workspace cleanup failed', error)
        }
      ),
    }
    ownerRef.current = owner
    callbacks.current.lock(false)
    setView(empty(account))
    return () => {
      owner.live = false
      callbacks.current.lock(true)
      owner.transition.destroy()
      owner.grids.clear()
      if (ownerRef.current === owner) ownerRef.current = null
    }
  }, [account])

  const open = useCallback(
    async (
      payload: WorkspacePayload,
      persist: (signal: AbortSignal) => Promise<unknown>,
      beforePublish?: (grid: PreparedChartGrid) => void
    ) => {
      const owner = ownerRef.current
      if (!owner?.live || owner.account !== account) throw new Error('Workspace account changed')
      const operation = ++owner.operation
      setView((previous) => ({ ...previous, error: null }))
      try {
        return await owner.transition.open(
          () => {
            const grid = new PreparedChartGrid(payload)
            owner.grids.add(grid)
            setView((previous) => ({
              ...previous,
              grids: [...owner.grids].filter((item) => !item.disposed),
            }))
            return grid
          },
          persist,
          (grid) => {
            beforePublish?.(grid)
            grid.activate(grid.payload.sync)
            callbacks.current.publish(grid)
            owner.current = grid
            owner.grids = new Set([grid])
            setView((previous) => ({ ...previous, grids: [grid], current: grid }))
          }
        )
      } catch (error) {
        if (owner.live && owner.operation === operation)
          setView((previous) => ({
            ...previous,
            error: error instanceof Error ? error.message : String(error),
          }))
        throw error
      } finally {
        if (owner.live) {
          owner.grids = new Set([...owner.grids].filter((grid) => !grid.disposed))
          setView((previous) => ({ ...previous, grids: [...owner.grids] }))
        }
      }
    },
    [account]
  )

  const cancel = useCallback(() => ownerRef.current?.transition.cancel(), [])
  return { ...(view.account === account ? view : empty(account)), open, cancel }
}
