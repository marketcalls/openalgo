import type { ComponentProps } from 'react'
import { useCallback, useRef } from 'react'
import type { PreparedChartGrid } from '@/lib/trading/preparedGrid'
import { ChartPane } from './ChartPane'

type PaneProps = ComponentProps<typeof ChartPane>
interface Props
  extends Omit<
    PaneProps,
    | 'paneId'
    | 'style'
    | 'initialWorkspacePane'
    | 'linkGroup'
    | 'onInitialized'
    | 'onInitializationError'
  > {
  owner: PreparedChartGrid
  active: boolean
  focusedPaneId?: string
}

/** Hidden panes retain their measured dimensions and identity during publication. */
export function WorkspaceGrid({
  owner,
  active,
  focusedPaneId = owner.payload.activePaneId,
  ...props
}: Props) {
  const latest = useRef({ active, props })
  latest.current = { active, props }
  const visible = () => latest.current.active && !owner.disposed
  const register = useCallback<NonNullable<PaneProps['onTerminalChange']>>(
    (id, terminal) => {
      owner.register(id, terminal)
      if (latest.current.active && !owner.disposed)
        latest.current.props.onTerminalChange?.(id, terminal)
    },
    [owner]
  )
  const initialized = useCallback<NonNullable<PaneProps['onInitialized']>>(
    (id, terminal) => owner.initialized(id, terminal),
    [owner]
  )
  const failed = useCallback<NonNullable<PaneProps['onInitializationError']>>(
    (_id, error) => owner.fail(error),
    [owner]
  )
  const locked = !active || props.transitionLocked === true
  return (
    <div
      data-workspace-grid={owner.key}
      data-workspace-active={active}
      aria-hidden={active ? undefined : true}
      inert={locked ? true : undefined}
      className="grid h-full min-h-0 gap-2 p-2"
      style={{
        gridTemplateColumns: owner.geometry.columns,
        gridTemplateRows: owner.geometry.rows,
        gridTemplateAreas: owner.geometry.areas,
        ...(active
          ? {}
          : { position: 'absolute', inset: 0, visibility: 'hidden', pointerEvents: 'none' }),
      }}
    >
      {owner.geometry.panes.map(({ id, area, pane }, index) => (
        <ChartPane
          {...props}
          key={id}
          paneId={id}
          style={{ gridArea: area }}
          initialWorkspacePane={pane}
          transitionLocked={locked}
          armed={props.armed && !locked}
          linkGroup={owner.linkGroup}
          paneLabel={`Chart ${index + 1}`}
          focused={active && id === focusedPaneId}
          layoutPicker={
            props.toolbarHost !== undefined || index === 0 ? props.layoutPicker : undefined
          }
          onWorkspaceChange={() => {
            if (visible() && !locked) latest.current.props.onWorkspaceChange?.()
          }}
          onReplayStart={
            props.onReplayStart
              ? (paneId) => {
                  if (visible() && !latest.current.props.transitionLocked)
                    latest.current.props.onReplayStart?.(paneId)
                }
              : undefined
          }
          onBeforeSourceChange={
            props.onBeforeSourceChange
              ? () => {
                  if (visible() && !latest.current.props.transitionLocked)
                    latest.current.props.onBeforeSourceChange?.()
                }
              : undefined
          }
          onInitialized={initialized}
          onInitializationError={failed}
          onTerminalChange={register}
          onSymbolChange={(paneId, key) => {
            if (owner.disposed) return
            owner.symbols.set(paneId, key)
            if (visible()) latest.current.props.onSymbolChange?.(paneId, key)
          }}
          onObjectsChange={(paneId, objects) => {
            if (owner.disposed) return
            if (objects) owner.objects.set(paneId, objects)
            else owner.objects.delete(paneId)
            if (visible()) latest.current.props.onObjectsChange?.(paneId, objects)
          }}
          onAlertsReady={(paneId, alerts) => {
            if (owner.disposed) return
            if (visible()) latest.current.props.onAlertsReady?.(paneId, alerts)
          }}
          onAlertFired={(fire) => {
            if (visible()) latest.current.props.onAlertFired?.(fire)
          }}
          onAlertsChanged={() => {
            if (visible()) latest.current.props.onAlertsChanged?.()
          }}
          onFocusPane={(terminal, paneId) => {
            if (visible()) latest.current.props.onFocusPane?.(terminal, paneId)
          }}
          onDrawStats={(stats) => {
            if (visible()) latest.current.props.onDrawStats?.(stats)
          }}
        />
      ))}
    </div>
  )
}
