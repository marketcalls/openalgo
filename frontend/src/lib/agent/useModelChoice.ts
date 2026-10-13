/**
 * The model the assistant runs on, remembered in this browser and shared by
 * every place the assistant appears (`/agent` and the `/trading` panel).
 *
 * Without it each page started on the configured default. The chat page let
 * the trader pick another model for the session, but the chart panel had no
 * picker at all, so a default whose key had stopped working failed there while
 * the chat page kept answering on the model picked by hand.
 *
 * Null means "the configured default", sent as no `model_id` at all. A stored
 * choice is only used while that model is still offered (registered and
 * enabled); once it is gone the choice falls back to the default and the
 * stale value is forgotten, so a deleted model never produces a failed turn.
 * Every storage access is guarded: a private window or blocked storage still
 * gets a working picker, it just does not remember.
 */

import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import { agentQueryKeys, listModels } from '@/api/agent'

export const MODEL_CHOICE_KEY = 'oa-agent-model'

function readStored(): number | null {
  try {
    const raw = window.localStorage.getItem(MODEL_CHOICE_KEY)
    if (!raw) return null
    const id = Number(raw)
    return Number.isInteger(id) && id > 0 ? id : null
  } catch {
    return null
  }
}

function writeStored(id: number | null): void {
  try {
    if (id == null) window.localStorage.removeItem(MODEL_CHOICE_KEY)
    else window.localStorage.setItem(MODEL_CHOICE_KEY, String(id))
  } catch {
    // Not remembered; the choice still applies to this page.
  }
}

/** The chosen model id (null for the configured default) and its setter. */
export function useModelChoice(): [number | null, (id: number | null) => void] {
  const [chosen, setChosen] = useState<number | null>(readStored)

  const { data } = useQuery({
    queryKey: agentQueryKeys.models(),
    queryFn: listModels,
    staleTime: 60_000,
  })

  // A remembered model that is no longer offered falls back to the default.
  useEffect(() => {
    if (chosen == null || !data) return
    if (!data.some((model) => model.id === chosen && model.enabled)) {
      writeStored(null)
      setChosen(null)
    }
  }, [chosen, data])

  // Another tab, or the other page open beside this one, picking a model.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === MODEL_CHOICE_KEY) setChosen(readStored())
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const choose = useCallback((id: number | null) => {
    writeStored(id)
    setChosen(id)
  }, [])

  return [chosen, choose]
}
