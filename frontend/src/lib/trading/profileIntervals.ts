import { intervalSeconds } from './intervals'
import type { ProfileKind } from './profileSettings'

export function profileIntervalSupported(
  kind: ProfileKind,
  interval: string,
  blockMinutes: number
): boolean {
  const seconds = intervalSeconds(interval)
  if (!seconds || seconds < 0 || seconds >= 86400) return false
  return kind !== 'tpo' || (seconds <= blockMinutes * 60 && (blockMinutes * 60) % seconds === 0)
}

/** Choose a broker-supported source that can resolve each profile's periods. */
export function selectProfileInterval(
  kind: ProfileKind,
  current: string,
  blockMinutes: number,
  available: readonly string[]
): string | null {
  const supported = (iv: string) =>
    available.includes(iv) && profileIntervalSupported(kind, iv, blockMinutes)
  if (supported(current)) return current
  return ['5m', ...available].find(supported) ?? null
}
