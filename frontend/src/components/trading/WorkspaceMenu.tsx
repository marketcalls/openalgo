import { parseWorkspaceDocument, type WorkspaceDocument } from 'openalgo-charts/workspace'
import { useEffect, useId, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import type { ChartWorkspaceCatalogState } from '@/hooks/useChartWorkspaceCatalog'
import { TickBox } from './TickBox'

interface Props extends ChartWorkspaceCatalogState {
  activeId: string | null
  transitionPending?: boolean
  cancelOpening?(): void
  status?: string
  save(): Promise<void>
  saveAs(name: string): Promise<WorkspaceDocument>
  create(name: string): Promise<WorkspaceDocument>
  openWorkspace(document: WorkspaceDocument): Promise<unknown>
  importWorkspace(document: WorkspaceDocument): Promise<WorkspaceDocument>
  onRemoved(id: string): void
}
interface Result {
  message: string
  select?: string
  clearName?: boolean
}

export function WorkspaceMenu({
  catalog,
  loading,
  pending,
  error,
  run,
  reload,
  activeId,
  transitionPending = false,
  cancelOpening,
  status,
  save,
  saveAs,
  create,
  openWorkspace,
  importWorkspace,
  onRemoved,
}: Props) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [savedName, setSavedName] = useState('')
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const action = useRef(0)
  const inFlight = useRef(false)
  const selected = catalog?.workspaces.find((item) => item.id === selectedId)
  const active = catalog?.workspaces.find((item) => item.id === activeId)
  const disabled = loading || pending || busy || transitionPending
  useEffect(
    () => () => {
      action.current++
    },
    []
  )
  useEffect(() => {
    setSavedName(selected?.name ?? '')
  }, [selected?.name])

  async function perform(operation: () => Promise<Result>) {
    if (disabled || inFlight.current) return
    const token = ++action.current
    inFlight.current = true
    setBusy(true)
    setFailure(null)
    setMessage('')
    try {
      const result = await operation()
      if (token !== action.current) return
      setMessage(result.message)
      if (result.select !== undefined) setSelectedId(result.select)
      if (result.clearName) setName('')
    } catch (cause) {
      if (token === action.current)
        setFailure(cause instanceof Error ? cause.message : String(cause))
    } finally {
      if (token === action.current) {
        inFlight.current = false
        setBusy(false)
      }
    }
  }
  const openSaved = (document: WorkspaceDocument) =>
    perform(async () => {
      await openWorkspace(document)
      return { message: 'Workspace opened', select: document.id }
    })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          data-workspace-control
          variant="outline"
          size="sm"
          className="h-8 shrink-0 px-2.5 text-xs"
          title={active ? `Workspace: ${active.name}` : 'Save or open a complete chart grid'}
        >
          Workspaces
        </Button>
      </DialogTrigger>
      <DialogContent
        data-workspace-control
        className="max-h-[90dvh] overflow-y-auto sm:max-w-xl"
        style={{ maxWidth: 'min(36rem, calc(100vw - 2rem))' }}
      >
        <DialogHeader>
          <DialogTitle>Chart workspaces</DialogTitle>
          <DialogDescription>
            Save the complete chart grid for your account in this browser. Export a workspace to
            share its chart configuration.
          </DialogDescription>
        </DialogHeader>
        <p className="text-sm">
          {active ? `Current: ${active.name}` : 'Current: unnamed workspace'}
          {status ? ` (${status})` : ''}
        </p>
        {(failure || error) && (
          <p role="alert" className="text-sm text-destructive">
            {failure || error}
          </p>
        )}
        {message && <output className="text-sm text-muted-foreground">{message}</output>}
        {loading && <p className="text-sm">Loading workspaces...</p>}
        {transitionPending && cancelOpening && (
          <Button variant="outline" onClick={cancelOpening}>
            Cancel workspace loading
          </Button>
        )}
        <label className="flex items-center gap-2 text-sm">
          <TickBox
            label="Autosave chart changes"
            checked={catalog?.autosave === true}
            disabled={disabled}
            onChange={(enabled) =>
              void perform(async () => {
                await run((repository) => repository.setAutosave(enabled))
                return { message: enabled ? 'Autosave enabled' : 'Autosave disabled' }
              })
            }
          />
          Autosave chart changes
        </label>
        <div className="flex flex-wrap gap-2">
          <Button
            disabled={disabled || !active}
            onClick={() =>
              void perform(async () => {
                await save()
                return { message: 'Workspace saved' }
              })
            }
          >
            Save
          </Button>
          <Button
            variant="outline"
            disabled={disabled}
            onClick={() =>
              void perform(async () => {
                await reload()
                return { message: 'Workspace list refreshed' }
              })
            }
          >
            Refresh
          </Button>
        </div>
        <div className="grid gap-2 border-t pt-3">
          <label htmlFor={`${id}-name`} className="text-sm font-medium">
            Workspace name
          </label>
          <Input
            id={`${id}-name`}
            maxLength={120}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={disabled || !name.trim()}
              onClick={() =>
                void perform(async () => {
                  const saved = await saveAs(name.trim())
                  return { message: 'Workspace saved', select: saved.id, clearName: true }
                })
              }
            >
              Save as
            </Button>
            <Button
              variant="outline"
              disabled={disabled || !name.trim()}
              onClick={() =>
                void perform(async () => {
                  const saved = await create(name.trim())
                  return { message: 'New workspace opened', select: saved.id, clearName: true }
                })
              }
            >
              New workspace
            </Button>
          </div>
        </div>
        <div className="grid gap-2 border-t pt-3">
          <label htmlFor={`${id}-saved`} className="text-sm font-medium">
            Saved workspace
          </label>
          <select
            id={`${id}-saved`}
            value={selected?.id ?? ''}
            disabled={disabled}
            onChange={(event) => setSelectedId(event.target.value)}
            className="h-9 min-w-0 rounded-md border bg-background px-3 text-sm"
          >
            <option value="">Choose a workspace</option>
            {catalog?.workspaces.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
          {catalog?.workspaces.length === 0 && (
            <p className="text-sm text-muted-foreground">No saved workspaces</p>
          )}
          {selected && (
            <>
              <div className="flex flex-wrap gap-2">
                <Button disabled={disabled} onClick={() => void openSaved(selected)}>
                  Open
                </Button>
                <Button
                  variant="outline"
                  disabled={disabled}
                  onClick={() =>
                    void perform(async () => {
                      const copy = await run((repository) =>
                        repository.duplicate('workspace', selected.id, `${selected.name} copy`)
                      )
                      return { message: 'Workspace duplicated', select: copy.id }
                    })
                  }
                >
                  Duplicate
                </Button>
                <Button
                  variant="outline"
                  disabled={disabled}
                  onClick={() =>
                    void perform(async () => {
                      const text = await run((repository) =>
                        repository.exportDocument('workspace', selected.id)
                      )
                      const url = URL.createObjectURL(
                        new Blob([text], { type: 'application/json' })
                      )
                      try {
                        const anchor = document.createElement('a')
                        anchor.href = url
                        anchor.download = 'chart-workspace.json'
                        anchor.click()
                      } finally {
                        URL.revokeObjectURL(url)
                      }
                      return { message: 'Workspace exported' }
                    })
                  }
                >
                  Export JSON
                </Button>
                <Button
                  variant="outline"
                  disabled={disabled}
                  onClick={() =>
                    void perform(async () => {
                      await run((repository) => repository.remove('workspace', selected.id))
                      onRemoved(selected.id)
                      return {
                        message:
                          'Saved workspace deleted; the displayed charts are still available',
                        select: '',
                      }
                    })
                  }
                >
                  Delete
                </Button>
              </div>
              <label htmlFor={`${id}-rename`} className="text-sm font-medium">
                Saved workspace name
              </label>
              <div className="flex gap-2">
                <Input
                  id={`${id}-rename`}
                  maxLength={120}
                  value={savedName}
                  onChange={(event) => setSavedName(event.target.value)}
                />
                <Button
                  variant="outline"
                  disabled={disabled || !savedName.trim()}
                  onClick={() =>
                    void perform(async () => {
                      await run((repository) =>
                        repository.rename('workspace', selected.id, savedName.trim())
                      )
                      return { message: 'Workspace renamed' }
                    })
                  }
                >
                  Rename
                </Button>
              </div>
            </>
          )}
        </div>
        {!!catalog?.recentWorkspaceIds.length && (
          <div className="grid gap-1 border-t pt-3">
            <p className="text-sm font-medium">Recent workspaces</p>
            {catalog.recentWorkspaceIds.map((key) => {
              const document = catalog.workspaces.find((item) => item.id === key)
              return document ? (
                <Button
                  key={key}
                  variant="ghost"
                  className="justify-start"
                  disabled={disabled}
                  onClick={() => void openSaved(document)}
                >
                  {document.name}
                </Button>
              ) : null
            })}
          </div>
        )}
        <label htmlFor={`${id}-import`} className="text-sm font-medium">
          Import workspace JSON
        </label>
        <Input
          id={`${id}-import`}
          type="file"
          accept=".json,application/json"
          disabled={disabled}
          onChange={(event) => {
            const file = event.target.files?.[0]
            event.target.value = ''
            if (!file) return
            void perform(async () => {
              if (file.size > 5 * 1024 * 1024)
                throw new Error('Workspace file size must be at most 5 MB')
              const document = parseWorkspaceDocument(await file.text())
              const saved = await importWorkspace(document)
              return { message: 'Workspace imported and opened', select: saved.id }
            })
          }}
        />
      </DialogContent>
    </Dialog>
  )
}
