import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { IndicatorState } from 'openalgo-charts'
import type { IndexedDbWorkspaceStorage, WorkspaceCatalog } from 'openalgo-charts/workspace'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useChartWorkspaceCatalog } from '@/hooks/useChartWorkspaceCatalog'
import { IndicatorTemplates, type IndicatorTemplateTarget } from './IndicatorTemplates'

const studies: IndicatorState[] = [{ indicatorId: 'ema', settings: { period: 9 }, paneIndex: 0 }]
function harness(options: { failWrite?: boolean; noTarget?: boolean } = {}) {
  let value: WorkspaceCatalog | null = null
  const storage: IndexedDbWorkspaceStorage = {
    async read() {
      return structuredClone(value)
    },
    async write(_key, next) {
      if (options.failWrite) throw new Error('Storage quota reached')
      value = structuredClone(next)
    },
    async close() {},
  }
  const factory = () => storage
  let target: IndicatorTemplateTarget | null = options.noTarget
    ? null
    : {
        captureIndicatorTemplate: vi.fn(() => structuredClone(studies)),
        applyIndicatorTemplate: vi.fn(async () => {}),
      }
  function Host() {
    const catalog = useChartWorkspaceCatalog('alice', factory)
    return <IndicatorTemplates {...catalog} target={() => target} />
  }
  render(<Host />)
  return {
    target,
    select: (next: IndicatorTemplateTarget | null) => {
      target = next
    },
    saved: () => value,
  }
}

async function open() {
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Templates', exact: true }))
  await waitFor(() => expect(screen.queryByText('Loading templates…')).not.toBeInTheDocument())
  return user
}
async function save(user: ReturnType<typeof userEvent.setup>, name = 'Momentum') {
  await user.type(screen.getByLabelText('New template name'), name)
  await user.click(screen.getByRole('button', { name: 'Save current studies' }))
  await screen.findByRole('option', { name })
}
function fileOf(input: unknown) {
  const text = JSON.stringify(input)
  const file = new File([text], 'studies.json', { type: 'application/json' })
  Object.defineProperty(file, 'text', { value: async () => text })
  return file
}
const emptyTemplate = {
  kind: 'indicator-template',
  version: 1,
  id: 'external',
  name: 'Clean',
  createdAt: 1,
  updatedAt: 1,
  indicators: [],
}

afterEach(() => vi.restoreAllMocks())

describe('named indicator templates', () => {
  it('saves real captured studies with a name and applies to the current focused target', async () => {
    const host = harness()
    const user = await open()
    await save(user)
    expect(host.saved()?.templates[0].indicators).toEqual(studies)
    const other = {
      captureIndicatorTemplate: vi.fn(() => []),
      applyIndicatorTemplate: vi.fn(async () => {}),
    }
    host.select(other)
    await user.click(screen.getByRole('button', { name: 'Replace studies' }))
    expect(other.applyIndicatorTemplate).toHaveBeenCalledWith(studies, 'replace')
    await user.click(screen.getByRole('button', { name: 'Add studies' }))
    expect(other.applyIndicatorTemplate).toHaveBeenLastCalledWith(studies, 'append')
    expect(host.target?.applyIndicatorTemplate).not.toHaveBeenCalled()
  })

  it('renames, duplicates and deletes a selected template through the repository', async () => {
    const host = harness()
    const user = await open()
    await save(user)
    await user.clear(screen.getByLabelText('Saved template name'))
    await user.type(screen.getByLabelText('Saved template name'), 'Trend')
    await user.click(screen.getByRole('button', { name: 'Rename' }))
    await screen.findByRole('option', { name: 'Trend' })
    await user.click(screen.getByRole('button', { name: 'Duplicate' }))
    await screen.findByRole('option', { name: 'Trend copy' })
    expect(host.saved()?.templates).toHaveLength(2)
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(host.saved()?.templates).toHaveLength(1))
    expect(host.saved()?.templates[0].name).toBe('Trend')
  })

  it('imports an empty template with a fresh identity and clears studies on replace', async () => {
    const host = harness()
    const user = await open()
    await user.upload(screen.getByLabelText('Import template JSON'), fileOf(emptyTemplate))
    await screen.findByText('No studies')
    expect(host.saved()?.templates[0].id).not.toBe('external')
    await user.click(screen.getByRole('button', { name: 'Replace studies' }))
    expect(host.target?.applyIndicatorTemplate).toHaveBeenCalledWith([], 'replace')
  })

  it('exports a portable document and releases the temporary URL', async () => {
    harness()
    const user = await open()
    await save(user)
    const create = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:template')
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    await user.click(screen.getByRole('button', { name: 'Export JSON' }))
    expect(create).toHaveBeenCalledWith(expect.any(Blob))
    expect(click).toHaveBeenCalledOnce()
    await waitFor(() => expect(revoke).toHaveBeenCalledWith('blob:template'))
  })

  it('keeps the entered name and dialog open after a rejected save', async () => {
    const host = harness({ failWrite: true })
    const user = await open()
    await user.type(screen.getByLabelText('New template name'), 'Keep this name')
    await user.click(screen.getByRole('button', { name: 'Save current studies' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('quota')
    expect(screen.getByLabelText('New template name')).toHaveValue('Keep this name')
    expect(screen.getByRole('dialog')).toBeVisible()
    expect(host.saved()).toBeNull()
  })

  it('rejects malformed, wrong-kind and oversized imports without writing', async () => {
    const host = harness()
    const user = await open()
    await user.upload(
      screen.getByLabelText('Import template JSON'),
      fileOf({ ...emptyTemplate, kind: 'workspace' })
    )
    expect(await screen.findByRole('alert')).toHaveTextContent(/kind|template/i)
    const oversized = fileOf(emptyTemplate)
    Object.defineProperty(oversized, 'size', { value: 6 * 1024 * 1024 })
    await user.upload(screen.getByLabelText('Import template JSON'), oversized)
    expect(await screen.findByRole('alert')).toHaveTextContent(/size|5 MB/i)
    await user.upload(screen.getByLabelText('Import template JSON'), fileOf({}))
    expect(await screen.findByRole('alert')).toHaveTextContent(/kind|template/i)
    expect(host.saved()).toBeNull()
  })

  it('reports missing chart or custom studies without claiming success', async () => {
    const host = harness({ noTarget: true })
    const user = await open()
    await user.type(screen.getByLabelText('New template name'), 'Unavailable')
    await user.click(screen.getByRole('button', { name: 'Save current studies' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/chart/i)
    await user.upload(screen.getByLabelText('Import template JSON'), fileOf(emptyTemplate))
    host.select({
      captureIndicatorTemplate: () => [],
      applyIndicatorTemplate: async () => {
        throw new Error('Missing custom study: local-oscillator')
      },
    })
    await user.click(screen.getByRole('button', { name: 'Replace studies' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('local-oscillator')
  })

  it('disables mutations while catalog loading or a write is pending', async () => {
    const props = {
      catalog: null,
      loading: true,
      pending: false,
      error: null,
      reload: vi.fn(),
      run: vi.fn(),
      target: () => null,
    }
    const { rerender } = render(<IndicatorTemplates {...props} />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Templates', exact: true }))
    expect(screen.getByRole('button', { name: 'Save current studies' })).toBeDisabled()
    rerender(<IndicatorTemplates {...props} loading={false} pending />)
    fireEvent.change(screen.getByLabelText('New template name'), { target: { value: 'Busy' } })
    expect(screen.getByRole('button', { name: 'Save current studies' })).toBeDisabled()
  })
})
