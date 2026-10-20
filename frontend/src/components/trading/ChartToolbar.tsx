import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'

/** Controls keep their pane's React owner when displayed in the workspace row. */
export function ChartToolbar({
  host,
  active,
  fullscreen,
  children,
}: {
  host?: HTMLElement | null
  active: boolean
  fullscreen: boolean
  children: ReactNode
}) {
  if (host === undefined) return children
  if (!active) return null
  if (fullscreen) return children
  return host ? createPortal(children, host) : null
}
