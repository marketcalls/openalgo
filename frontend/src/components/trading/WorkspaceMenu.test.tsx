import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type {
  IndexedDbWorkspaceStorage,
  WorkspaceCatalog,
  WorkspaceDocument,
} from 'openalgo-charts/workspace'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useChartWorkspaceCatalog } from '@/hooks/useChartWorkspaceCatalog'
import { WorkspaceMenu } from './WorkspaceMenu'

const payload = {
  layout: {
    rows: 1,
    columns: 1,
    slots: [{ paneId: 'one', row: 0, column: 0, rowSpan: 1, columnSpan: 1 }],
  },
  activePaneId: 'one',
  sync: { crosshair: true, viewport: false, symbol: false, interval: false },
  panes: [
    {
      id: 'one',
      symbol: 'BHEL',
      exchange: 'NSE',
      interval: '5m',
      chartType: 'candlestick',
      chart: { version: 1 as const },
      settings: {},
      volume: true,
      magnet: 'off' as const,
      stay: false,
      comparisons: [],
      comparisonMode: 'price' as const,
    },
  ],
}
function harness(failWrite = false, transitionPending = false) {
  let value: WorkspaceCatalog | null = null
  const storage: IndexedDbWorkspaceStorage = {
    async read() {
      return structuredClone(value)
    },
    async write(_key, next) {
      if (failWrite) throw new Error('Storage full')
      value = structuredClone(next)
    },
    async close() {},
  }
  const factory = () => storage
  const opened = vi.fn(async (_document: WorkspaceDocument) => {})
  const cancel = vi.fn()
  function Host() {
    const catalog = useChartWorkspaceCatalog('alice', factory)
    const [activeId, setActiveId] = useState<string | null>(null)
    const create = async (name: string) => {
      const document = await catalog.run((repo) => repo.createWorkspace(name, payload))
      setActiveId(document.id)
      return document
    }
    return (
      <WorkspaceMenu
        {...catalog}
        transitionPending={transitionPending}
        cancelOpening={cancel}
        activeId={activeId}
        saveAs={create}
        create={create}
        save={async () => {
          if (activeId) await catalog.run((repo) => repo.saveWorkspace(activeId, payload))
        }}
        openWorkspace={opened}
        importWorkspace={async (document) => {
          const saved = (await catalog.run((repo) =>
            repo.importDocument(document)
          )) as WorkspaceDocument
          await opened(saved)
          return saved
        }}
        onRemoved={(id) => {
          if (activeId === id) setActiveId(null)
        }}
      />
    )
  }
  render(<Host />)
  return { saved: () => value, opened, cancel }
}
async function open() {
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Workspaces', exact: true }))
  await waitFor(() => expect(screen.queryByText('Loading workspaces...')).not.toBeInTheDocument())
  return user
}
afterEach(() => vi.restoreAllMocks())

describe('named workspace menu', () => {
  it('keeps cancellation accessible inside the modal while chart loading blocks other actions', async () => {
    const host = harness(false, true),
      user = await open()
    expect(screen.getByRole('button', { name: 'Refresh', exact: true })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Cancel workspace loading' }))
    expect(host.cancel).toHaveBeenCalledOnce()
  })
  it('persists the account autosave preference through the repository', async () => {
    const host = harness(),
      user = await open()
    await user.click(screen.getByRole('checkbox', { name: 'Autosave chart changes' }))
    await waitFor(() => expect(host.saved()?.autosave).toBe(true))
  })
  it('saves the grid with a name, opens the selected document, and supports rename, duplicate and delete', async () => {
    const host = harness(),
      user = await open()
    expect(screen.getByText('No saved workspaces')).toBeVisible()
    await user.type(screen.getByLabelText('Workspace name'), 'Morning')
    await user.click(screen.getByRole('button', { name: 'Save as' }))
    await screen.findByRole('option', { name: 'Morning' })
    expect(host.saved()?.workspaces[0].panes).toEqual(payload.panes)
    await user.click(screen.getByRole('button', { name: 'Open', exact: true }))
    expect(host.opened).toHaveBeenCalledWith(expect.objectContaining({ name: 'Morning' }))
    await user.clear(screen.getByLabelText('Saved workspace name'))
    await user.type(screen.getByLabelText('Saved workspace name'), 'Afternoon')
    await user.click(screen.getByRole('button', { name: 'Rename' }))
    await screen.findByRole('option', { name: 'Afternoon' })
    await user.click(screen.getByRole('button', { name: 'Duplicate' }))
    await screen.findByRole('option', { name: 'Afternoon copy' })
    await user.click(screen.getByRole('button', { name: 'Delete', exact: true }))
    await waitFor(() => expect(host.saved()?.workspaces).toHaveLength(1))
  })

  it('keeps the entered name and error after a rejected save', async () => {
    const host = harness(true),
      user = await open()
    await user.type(screen.getByLabelText('Workspace name'), 'Keep this')
    await user.click(screen.getByRole('button', { name: 'Save as' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Storage full')
    expect(screen.getByLabelText('Workspace name')).toHaveValue('Keep this')
    expect(host.saved()).toBeNull()
  })

  it('validates imported documents before any host action and releases exported URLs', async () => {
    const host = harness(),
      user = await open()
    const upload = async (value: unknown) => {
      const text = JSON.stringify(value),
        file = new File([text], 'workspace.json', { type: 'application/json' })
      Object.defineProperty(file, 'text', { value: async () => text })
      await user.upload(screen.getByLabelText('Import workspace JSON'), file)
    }
    await upload({ kind: 'indicator-template' })
    expect(await screen.findByRole('alert')).toBeVisible()
    expect(host.opened).not.toHaveBeenCalled()
    await upload({
      ...payload,
      kind: 'workspace',
      version: 1,
      id: 'external',
      name: 'Imported',
      createdAt: 1,
      updatedAt: 1,
    })
    await screen.findByRole('option', { name: 'Imported' })
    expect(host.saved()?.workspaces[0].id).not.toBe('external')
    expect(host.opened).toHaveBeenCalledOnce()
    const create = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:workspace')
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    await user.click(screen.getByRole('button', { name: 'Export JSON' }))
    expect(create).toHaveBeenCalledWith(expect.any(Blob))
    await waitFor(() => expect(revoke).toHaveBeenCalledWith('blob:workspace'))
  })
})
