import { parseIndicatorTemplate } from 'openalgo-charts/workspace'
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
import type { TradingTerminal } from '@/lib/trading/terminal'

export type IndicatorTemplateTarget = Pick<
  TradingTerminal,
  'captureIndicatorTemplate' | 'applyIndicatorTemplate'
>
interface Props extends ChartWorkspaceCatalogState {
  target(): IndicatorTemplateTarget | null
}
interface ActionResult {
  message: string
  select?: string
  clearName?: boolean
}

/** One template picker for the workspace; resolve focus when the action begins. */
export function IndicatorTemplates({
  catalog,
  loading,
  pending,
  error,
  run,
  reload,
  target,
}: Props) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [savedName, setSavedName] = useState('')
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const alive = useRef(true)
  const inFlight = useRef(false)
  const selected = catalog?.templates.find((item) => item.id === selectedId)
  const disabled = loading || pending || busy

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  useEffect(() => {
    setSavedName(selected?.name ?? '')
  }, [selected?.name])

  async function perform(action: () => Promise<ActionResult>) {
    if (inFlight.current || disabled) return
    inFlight.current = true
    setBusy(true)
    setFailure(null)
    setMessage('')
    try {
      const result = await action()
      if (!alive.current) return
      setMessage(result.message)
      if (result.select !== undefined) setSelectedId(result.select)
      if (result.clearName) setName('')
    } catch (cause) {
      if (alive.current) setFailure(cause instanceof Error ? cause.message : String(cause))
    } finally {
      inFlight.current = false
      if (alive.current) setBusy(false)
    }
  }

  function chart() {
    const current = target()
    if (!current) throw new Error('Select a loaded chart first')
    return current
  }

  async function importFile(file: File) {
    if (file.size > 5 * 1024 * 1024) throw new Error('Template file size must be at most 5 MB')
    const document = parseIndicatorTemplate(await file.text())
    const saved = await run((repository) => repository.importDocument(document))
    return { message: 'Template imported', select: saved.id }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          data-workspace-control
          variant="outline"
          size="sm"
          className="h-8 shrink-0 px-2.5 text-xs"
          title="Templates for the selected chart"
        >
          Templates
        </Button>
      </DialogTrigger>
      <DialogContent
        data-workspace-control
        className="max-h-[90dvh] overflow-y-auto sm:max-w-xl"
        style={{ maxWidth: 'min(36rem, calc(100vw - 2rem))' }}
      >
        <DialogHeader>
          <DialogTitle>Indicator templates</DialogTitle>
          <DialogDescription>
            Save studies and their styles, then apply them to the selected chart. Templates are
            saved for your account in this browser.
          </DialogDescription>
        </DialogHeader>
        {(failure || error) && (
          <p role="alert" className="text-sm text-destructive">
            {failure || error}
          </p>
        )}
        {message && <output className="text-sm text-muted-foreground">{message}</output>}
        {loading && <p className="text-sm">Loading templates…</p>}
        <form
          className="grid gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            void perform(async () => {
              const indicators = chart().captureIndicatorTemplate()
              const saved = await run((repository) =>
                repository.createTemplate(name.trim(), indicators)
              )
              return { message: 'Template saved', select: saved.id, clearName: true }
            })
          }}
        >
          <label htmlFor={`${id}-new`} className="text-sm font-medium">
            New template name
          </label>
          <Input
            id={`${id}-new`}
            maxLength={120}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <Button type="submit" disabled={disabled || !name.trim()}>
            Save current studies
          </Button>
        </form>
        <div className="grid gap-2 border-t pt-4">
          <label htmlFor={`${id}-saved`} className="text-sm font-medium">
            Saved template
          </label>
          <select
            id={`${id}-saved`}
            value={selected?.id ?? ''}
            disabled={disabled}
            className="h-9 min-w-0 rounded-md border bg-background px-3 text-sm"
            onChange={(event) => setSelectedId(event.target.value)}
          >
            <option value="">Choose a template</option>
            {catalog?.templates.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
          {catalog?.templates.length === 0 && (
            <p className="text-sm text-muted-foreground">No saved templates</p>
          )}
          {selected && (
            <>
              <p className="text-sm text-muted-foreground">
                {selected.indicators.length
                  ? `${selected.indicators.length} studies`
                  : 'No studies'}
              </p>
              <div className="flex flex-wrap gap-2">
                {(['replace', 'append'] as const).map((mode) => (
                  <Button
                    key={mode}
                    disabled={disabled}
                    variant={mode === 'replace' ? 'default' : 'outline'}
                    onClick={() =>
                      void perform(async () => {
                        await chart().applyIndicatorTemplate(selected.indicators, mode)
                        return {
                          message:
                            mode === 'replace'
                              ? 'Studies replaced on the selected chart'
                              : 'Studies added to the selected chart',
                        }
                      })
                    }
                  >
                    {mode === 'replace' ? 'Replace studies' : 'Add studies'}
                  </Button>
                ))}
              </div>
              <label htmlFor={`${id}-rename`} className="mt-2 text-sm font-medium">
                Saved template name
              </label>
              <Input
                id={`${id}-rename`}
                maxLength={120}
                value={savedName}
                onChange={(event) => setSavedName(event.target.value)}
              />
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  disabled={disabled || !savedName.trim()}
                  onClick={() =>
                    void perform(async () => {
                      await run((repository) =>
                        repository.rename('indicator-template', selected.id, savedName.trim())
                      )
                      return { message: 'Template renamed' }
                    })
                  }
                >
                  Rename
                </Button>
                <Button
                  variant="outline"
                  disabled={disabled}
                  onClick={() =>
                    void perform(async () => {
                      const saved = await run((repository) =>
                        repository.duplicate(
                          'indicator-template',
                          selected.id,
                          `${selected.name.slice(0, 115)} copy`
                        )
                      )
                      return { message: 'Template duplicated', select: saved.id }
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
                      await run((repository) =>
                        repository.remove('indicator-template', selected.id)
                      )
                      return { message: 'Template deleted', select: '' }
                    })
                  }
                >
                  Delete
                </Button>
                <Button
                  variant="outline"
                  disabled={disabled}
                  onClick={() =>
                    void perform(async () => {
                      const json = await run((repository) =>
                        repository.exportDocument('indicator-template', selected.id)
                      )
                      if (!alive.current) return { message: '' }
                      const url = URL.createObjectURL(
                        new Blob([json], { type: 'application/json' })
                      )
                      try {
                        const anchor = document.createElement('a')
                        anchor.href = url
                        anchor.download = `${selected.name.replace(/[^\p{L}\p{N}_-]+/gu, '-').slice(0, 80) || 'indicator-template'}.json`
                        anchor.click()
                      } finally {
                        setTimeout(() => URL.revokeObjectURL(url), 0)
                      }
                      return { message: 'Template exported' }
                    })
                  }
                >
                  Export JSON
                </Button>
              </div>
            </>
          )}
        </div>
        <div className="grid gap-2 border-t pt-4">
          <label htmlFor={`${id}-import`} className="text-sm font-medium">
            Import template JSON
          </label>
          <Input
            id={`${id}-import`}
            type="file"
            accept="application/json,.json"
            disabled={disabled}
            onChange={(event) => {
              const file = event.target.files?.[0]
              event.target.value = ''
              if (file) void perform(() => importFile(file))
            }}
          />
          <Button
            variant="ghost"
            disabled={disabled}
            onClick={() =>
              void perform(async () => {
                await reload()
                return { message: 'Templates refreshed' }
              })
            }
          >
            Refresh templates
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
