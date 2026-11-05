import { Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { pythonStrategyApi } from '@/api/python-strategy'
import { render, screen, userEvent, waitFor } from '@/test/test-utils'
import type { PythonStrategy } from '@/types/python-strategy'
import { showToast } from '@/utils/toast'
import EditPythonStrategy from './EditPythonStrategy'

vi.mock('@/api/python-strategy', () => ({
  pythonStrategyApi: {
    getStrategy: vi.fn(),
    getStrategyContent: vi.fn(),
    saveStrategy: vi.fn(),
    startStrategy: vi.fn(),
    stopStrategy: vi.fn(),
    exportStrategy: vi.fn(),
  },
}))
vi.mock('@/utils/toast', () => ({
  showToast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))
// The real editor is a code editor; a textarea is enough to type into.
vi.mock('@/components/ui/python-editor', () => ({
  PythonEditor: (props: { value: string; onChange?(v: string): void; readOnly?: boolean }) => (
    <textarea
      aria-label="Code"
      value={props.value}
      readOnly={props.readOnly}
      onChange={(e) => props.onChange?.(e.target.value)}
    />
  ),
}))

const api = vi.mocked(pythonStrategyApi)

const strategy = (status: string): PythonStrategy =>
  ({ id: 's1', name: 'Bot', status, file_name: 'bot.py' }) as PythonStrategy

function renderEditor() {
  window.history.pushState(null, '', '/python/s1/edit')
  return render(
    <Routes>
      <Route path="/python/:strategyId/edit" element={<EditPythonStrategy />} />
      <Route path="/python/:strategyId/logs" element={<p>logs page</p>} />
    </Routes>
  )
}

beforeEach(() => {
  // Reset, not clear: a queued mockResolvedValueOnce must not leak into the next test.
  vi.resetAllMocks()
  api.getStrategyContent.mockResolvedValue({
    content: 'print(1)',
    file_name: 'bot.py',
  } as never)
})

describe('run controls in the code editor', () => {
  it('starts a stopped strategy and reads its new status back', async () => {
    const user = userEvent.setup()
    api.getStrategy
      .mockResolvedValueOnce(strategy('stopped'))
      .mockResolvedValueOnce(strategy('running'))
    api.startStrategy.mockResolvedValue({ status: 'success', message: 'Started' })
    renderEditor()

    await user.click(await screen.findByRole('button', { name: 'Start' }))

    expect(api.startStrategy).toHaveBeenCalledWith('s1')
    expect(await screen.findByRole('button', { name: 'Stop' })).toBeInTheDocument()
  })

  it('reads the status back after a refused start too', async () => {
    const user = userEvent.setup()
    // The schedule started it after the page loaded, so the start is refused.
    api.getStrategy
      .mockResolvedValueOnce(strategy('stopped'))
      .mockResolvedValueOnce(strategy('running'))
    api.startStrategy.mockResolvedValue({ status: 'error', message: 'Strategy already running' })
    renderEditor()

    await user.click(await screen.findByRole('button', { name: 'Start' }))

    expect(showToast.error).toHaveBeenCalledWith('Strategy already running', 'pythonStrategy')
    expect(await screen.findByRole('button', { name: 'Stop' })).toBeInTheDocument()
  })

  it('cancels a scheduled start', async () => {
    const user = userEvent.setup()
    api.getStrategy.mockResolvedValue(strategy('scheduled'))
    api.stopStrategy.mockResolvedValue({ status: 'success', message: 'Cancelled' })
    renderEditor()

    await user.click(await screen.findByRole('button', { name: 'Cancel' }))
    expect(api.stopStrategy).toHaveBeenCalledWith('s1')
  })

  it('will not start, or leave for the logs, with unsaved changes', async () => {
    const user = userEvent.setup()
    api.getStrategy.mockResolvedValue(strategy('stopped'))
    renderEditor()

    await user.type(await screen.findByLabelText('Code'), '\nprint(2)')

    await user.click(screen.getByRole('button', { name: 'Start' }))
    expect(api.startStrategy).not.toHaveBeenCalled()
    expect(showToast.error).toHaveBeenCalledWith(
      'Save or discard changes before starting',
      'pythonStrategy'
    )

    await user.click(screen.getByRole('link', { name: 'View Logs' }))
    expect(screen.queryByText('logs page')).toBeNull()
    expect(screen.getByLabelText('Code')).toHaveValue('print(1)\nprint(2)')
  })

  it('opens the logs when nothing is unsaved', async () => {
    const user = userEvent.setup()
    api.getStrategy.mockResolvedValue(strategy('stopped'))
    renderEditor()

    await user.click(await screen.findByRole('link', { name: 'View Logs' }))
    await waitFor(() => expect(screen.getByText('logs page')).toBeInTheDocument())
  })
})
