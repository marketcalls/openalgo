import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { alertSoundManager } from '@/lib/trading/alertSoundManager'
import { act, render, screen, userEvent } from '@/test/test-utils'
import { ActiveAlertBanner } from './ActiveAlertBanner'

describe('ActiveAlertBanner', () => {
  beforeEach(() => {
    alertSoundManager.dismissAll()
  })

  afterEach(() => {
    alertSoundManager.dismissAll()
  })

  it('renders nothing when no alert is ringing', () => {
    const { container } = render(<ActiveAlertBanner />)
    expect(container.firstChild).toBeNull()
  })

  it('renders ringing banner when persistent alert rings', async () => {
    render(<ActiveAlertBanner />)

    await act(async () => {
      alertSoundManager.trigger({
        id: 'a-bell',
        title: 'RELIANCE 1250 Crossed',
        soundName: 'siren',
        duration: 'untilDismissed',
      })
    })

    expect(screen.getByText('RELIANCE 1250 Crossed')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /stop \/ dismiss/i })).toBeInTheDocument()
  })

  it('dismisses all alerts when STOP / DISMISS button is clicked', async () => {
    const user = userEvent.setup()
    render(<ActiveAlertBanner />)

    await act(async () => {
      alertSoundManager.trigger({
        id: 'a-bell',
        title: 'RELIANCE 1250 Crossed',
        soundName: 'siren',
        duration: 'untilDismissed',
      })
    })

    const stopBtn = screen.getByRole('button', { name: /stop \/ dismiss/i })
    await user.click(stopBtn)

    expect(alertSoundManager.isRinging()).toBe(false)
  })
})
