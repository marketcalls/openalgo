/**
 * The microphone in the composer.
 *
 * One toggle over the state machine in `lib/agent/voice.ts`: press to open a
 * session, press again to close it. Everything else it shows is read from that
 * controller rather than tracked here, because the connection outlives any
 * render and a second copy of its state is a second thing to get wrong.
 *
 * Three decisions worth stating:
 *
 * - **It renders nothing at all when voice is off.** Not disabled, not a
 *   tooltip explaining how to turn it on: absent. The master switch means the
 *   microphone never appears, and a greyed control beside the send button is a
 *   standing invitation to click a feature that is switched off. The same
 *   applies with no key stored, which is a session that cannot be minted.
 * - **The accessible name says what pressing it does**, not what state the
 *   session is in. A screen reader user pressing "Stop the voice session"
 *   knows what will happen; "Listening" does not tell them.
 * - **The last thing heard is shown**, truncated, on a screen wide enough for
 *   it. Speech recognition mishears, and a trader who cannot see what was heard
 *   has no way to tell a wrong answer from a wrong question.
 */

import { useQuery } from '@tanstack/react-query'
import { AudioLines, Loader2, Mic, MicOff } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { agentQueryKeys, getVoiceConfig } from '@/api/agent'
import { Button } from '@/components/ui/button'
import {
  createVoiceController,
  type VoiceController,
  type VoiceState,
  type VoiceStatus,
  type VoiceTranscriptLine,
} from '@/lib/agent/voice'
import { cn } from '@/lib/utils'

/** What each state says under the button. Plain text, no icons in the words. */
const STATE_LABEL: Record<VoiceState, string> = {
  idle: '',
  connecting: 'Connecting',
  listening: 'Listening',
  thinking: 'Thinking',
  speaking: 'Speaking',
  error: 'Voice error',
}

export interface VoiceButtonProps {
  /** The model a spoken turn runs on, matching the composer's own picker. */
  modelId?: number | null
  /** Whether this surface asks for order tools. The backend still decides. */
  tradingEnabled?: boolean
  /** Blocks starting a session, for a surface that is not ready to run a turn. */
  disabled?: boolean
  /**
   * Runs one spoken turn on the page's own stream and returns what to say.
   *
   * Supplying it is what makes a spoken turn appear on screen: the page runs it
   * through the same send a typed question uses, so the question, the answer
   * and the tool timeline all render as an ordinary message.
   */
  ask?: (question: string) => Promise<string>
  /** Receives the controller so the page can report tool activity into it. */
  onController?: (controller: VoiceController | null) => void
  /** Every finalised spoken line, for the page to record. */
  onSpokenLine?: (role: 'trader' | 'agent', text: string) => void
  /** The live transcript, for the page to render in the thread. */
  onTranscript?: (lines: VoiceTranscriptLine[]) => void
  className?: string
}

export function VoiceButton({
  modelId = null,
  tradingEnabled = false,
  disabled = false,
  ask,
  onController,
  onSpokenLine,
  onTranscript,
  className,
}: VoiceButtonProps) {
  // The same cache entry the config panel reads and writes, so turning voice on
  // over there reaches this button without a reload. A second key holding a
  // second shape of the same configuration is how those two drift apart.
  const config = useQuery({
    queryKey: agentQueryKeys.voice(),
    queryFn: getVoiceConfig,
    staleTime: 30_000,
  })

  const idleTimeout = config.data?.data.voice_idle_timeout_seconds ?? 0

  const [status, setStatus] = useState<VoiceStatus>({ state: 'idle', error: null })
  const [lines, setLines] = useState<VoiceTranscriptLine[]>([])

  // Held in a ref, not a dependency: the page rebuilds this callback on most
  // renders, and rebuilding the controller mid-session would drop the call.
  const askRef = useRef(ask)
  askRef.current = ask
  const spokenLineRef = useRef(onSpokenLine)
  spokenLineRef.current = onSpokenLine
  const onTranscriptRef = useRef(onTranscript)
  onTranscriptRef.current = onTranscript

  // One controller for the life of the mount. It is rebuilt when the turn's
  // model or the trading ask changes, because those travel with every spoken
  // turn and a live session holding the previous pair would keep using it.
  const controller = useMemo(
    () =>
      createVoiceController({
        modelId,
        tradingEnabled,
        // Read from the operator's configuration rather than hardcoded: an
        // open microphone is billed for as long as it is open, and how long a
        // desk tolerates a quiet one is not ours to decide.
        idleTimeoutSeconds: idleTimeout,
        ask: (question) => {
          const run = askRef.current
          if (!run) return Promise.resolve('')
          return run(question)
        },
        onSpokenLine: (role, text) => spokenLineRef.current?.(role, text),
      }),
    [modelId, tradingEnabled, idleTimeout]
  )

  // The page needs the controller to report tool activity into it while it runs
  // a spoken turn. Handed over on mount and withdrawn on unmount, so a stale
  // controller cannot be spoken into after its session has gone.
  useEffect(() => {
    onController?.(controller)
    return () => onController?.(null)
  }, [controller, onController])

  useEffect(() => {
    setStatus(controller.status())
    setLines(controller.transcript())
    const offStatus = controller.onStatus(setStatus)
    const offTranscript = controller.onTranscript((next) => {
      setLines(next)
      onTranscriptRef.current?.(next)
    })
    return () => {
      offStatus()
      offTranscript()
      // Unmounting with the microphone open would leave the browser's
      // recording indicator on with nothing behind it.
      controller.stop()
    }
  }, [controller])

  const live = status.state !== 'idle' && status.state !== 'error'
  const heard = lines.length > 0 ? lines[lines.length - 1] : null

  // Absent, not disabled: see the module docstring. A stored key is part of the
  // same question, because a session cannot be minted without one.
  const voice = config.data?.data
  if (!voice?.voice_enabled || !voice.key?.has_value) return null

  const name = voice.voice_agent_name || 'the voice agent'
  const action = live ? 'Stop the voice session' : `Talk to ${name}`

  return (
    <div className={cn('flex min-w-0 items-center gap-1.5', className)}>
      <Button
        type="button"
        variant={live ? 'secondary' : 'ghost'}
        size="icon-sm"
        onClick={() => (live ? controller.stop() : void controller.start())}
        disabled={disabled && !live}
        aria-label={action}
        title={status.error ?? action}
      >
        {status.state === 'connecting' || status.state === 'thinking' ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        ) : status.state === 'speaking' ? (
          <AudioLines className="h-4 w-4" aria-hidden />
        ) : status.state === 'error' ? (
          <MicOff className="h-4 w-4 text-destructive" aria-hidden />
        ) : (
          <Mic
            className={cn('h-4 w-4', status.state === 'listening' && 'text-destructive')}
            aria-hidden
          />
        )}
      </Button>

      {/* A live region so the state change is announced rather than only seen.
          Empty while idle, which is the whole composer row it gives back. */}
      <span
        aria-live="polite"
        className={cn(
          'truncate text-[11px] leading-none',
          status.state === 'error' ? 'text-destructive' : 'text-muted-foreground'
        )}
      >
        {status.state === 'error' ? (status.error ?? STATE_LABEL.error) : STATE_LABEL[status.state]}
      </span>

      {/* What was heard, so a mishearing is visible before the answer is. */}
      {live && heard && (
        <span
          className="hidden max-w-[14rem] truncate text-[11px] leading-none text-muted-foreground sm:inline"
          title={heard.text}
        >
          {heard.role === 'trader' ? 'You: ' : `${name}: `}
          {heard.text}
        </span>
      )}
    </div>
  )
}
