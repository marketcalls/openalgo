import type {
  ChartObjectDrawing,
  ChartObjectDrawingSource,
  ChartObjectProvider,
} from 'openalgo-charts'
import type { ProfileKind } from './profileSettings'

/**
 * Stable structural drawing source for a terminal whose drawing controller is
 * loaded lazily and replaced with every chart generation.
 *
 * ChartObjects keeps this proxy for its own lifetime. Attaching a newer
 * controller immediately redirects every operation; a late cleanup may only
 * detach the controller it originally installed.
 */
export class CurrentDrawingSource implements ChartObjectDrawingSource {
  private current: ChartObjectDrawingSource | null = null

  attach(source: ChartObjectDrawingSource): void {
    this.current = source
  }

  detach(source: ChartObjectDrawingSource): void {
    if (this.current === source) this.current = null
  }

  drawings(): readonly ChartObjectDrawing[] {
    return this.current?.drawings() ?? []
  }

  get(id: string): ChartObjectDrawing | undefined {
    return this.current?.get(id)
  }

  selection(): readonly string[] {
    return this.current?.selection() ?? []
  }

  select(id: string | readonly string[] | null, additive = false): void {
    this.current?.select(id, additive)
  }

  update(id: string, patch: { visible?: boolean; locked?: boolean }): void {
    this.current?.update(id, patch)
  }

  remove(id: string): boolean {
    return this.current?.remove(id) ?? false
  }
}

const PROFILE_NAMES: Record<ProfileKind, string> = {
  tpo: 'Time Price Opportunity',
  'session-volume-profile': 'Session Volume Profile',
}

/** Profiles are host primitives, so only explicitly supported actions exist. */
export function profileObjectProvider(
  kind: ProfileKind,
  openSettings: () => void
): ChartObjectProvider {
  return {
    id: `profile:${kind}`,
    get: () => ({
      kind: 'profile',
      name: PROFILE_NAMES[kind],
      paneIndex: 0,
      visible: true,
    }),
    openSettings,
  }
}
