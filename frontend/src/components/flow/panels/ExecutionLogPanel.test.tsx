/**
 * What the execution log says about a run the server started in the background.
 *
 * Under the gthread web server a workflow that waits on a Delay or Wait Until
 * step is answered 202 with status "accepted" and keeps running on the server.
 * The editor read anything other than "success" as a failure and showed a red
 * "Failed" for a run that would still place its orders when the wait ended,
 * which invites the trader to place them again by hand.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ExecutionLogPanel } from './ExecutionLogPanel'

describe('ExecutionLogPanel', () => {
  it('shows a run started in the background as running, not as failed', () => {
    render(
      <ExecutionLogPanel
        logs={[
          {
            time: '2026-09-23T09:20:00.000Z',
            message: 'Workflow started. It waits on a Delay or Wait Until step.',
            level: 'info',
          },
        ]}
        status="started"
        onClose={() => {}}
      />
    )

    expect(screen.getByText('Running in background')).toBeTruthy()
    expect(screen.queryByText('Failed')).toBeNull()
    expect(screen.queryByText('Completed')).toBeNull()
  })

  it('still shows a failed run as failed', () => {
    render(<ExecutionLogPanel logs={[]} status="error" onClose={() => {}} />)

    expect(screen.getByText('Failed')).toBeTruthy()
  })
})
