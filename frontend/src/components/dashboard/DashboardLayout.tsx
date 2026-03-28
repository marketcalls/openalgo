import { useDashboardStore } from '@/stores/dashboardStore'
import { CommandCenter } from './CommandCenter'
import { SmartChart } from './SmartChart'
import { RiskMeter } from './RiskMeter'
import { TimeframeMatrix } from './TimeframeMatrix'
import { InstitutionalScore } from './InstitutionalScore'
import { AgentConsensus } from './AgentConsensus'
import { ModelPredictions } from './ModelPredictions'
import { OIIntelligence } from './OIIntelligence'
import { DepthHeatmap } from './DepthHeatmap'
import { DangerAlerts } from './DangerAlerts'
import { SelfLearningPanel } from './SelfLearningPanel'
import { StockScanner } from './StockScanner'

// ---------------------------------------------------------------------------
// DashboardLayout -- Two distinct modes for different workflows.
//
// EXECUTION MODE (default): 2 dominant panels + 5 compact strips.
//   Top 60%:  CommandCenter (40%) | SmartChart (60%)
//   Bottom:   TF Matrix | Inst. Score | Risk | Alerts | Agents (mini)
//
// RESEARCH MODE: 12 panels in a 4-column layout with reduced detail.
// ---------------------------------------------------------------------------

function ExecutionLayout() {
  return (
    <div className="flex h-full flex-col gap-1.5 p-1.5">
      {/* TOP: Command Center + Smart Chart (60% of screen height) */}
      <div className="flex gap-1.5" style={{ flex: '0 0 62%' }}>
        {/* Command Center: 40% width */}
        <div style={{ flex: '0 0 38%' }}>
          <CommandCenter />
        </div>
        {/* Smart Chart: 60% width */}
        <div className="flex-1 min-w-0">
          <SmartChart />
        </div>
      </div>

      {/* BOTTOM: 5 compact strips (remaining height) */}
      <div className="flex-1 min-h-0 grid grid-cols-5 gap-1.5">
        <TimeframeMatrix />
        <InstitutionalScore />
        <RiskMeter />
        <DangerAlerts />
        <AgentConsensus />
      </div>
    </div>
  )
}

function ResearchLayout() {
  return (
    <div
      className="grid h-full w-full gap-1.5 p-1.5"
      style={{
        gridTemplateColumns: 'repeat(4, 1fr)',
        gridTemplateRows: 'repeat(12, 1fr)',
      }}
    >
      {/* Row 1-5: Main panels */}
      <div style={{ gridColumn: '1 / 2', gridRow: '1 / 6' }}>
        <CommandCenter />
      </div>

      <div style={{ gridColumn: '2 / 4', gridRow: '1 / 6' }}>
        <SmartChart />
      </div>

      <div style={{ gridColumn: '4 / 5', gridRow: '1 / 3' }}>
        <RiskMeter />
      </div>

      <div style={{ gridColumn: '4 / 5', gridRow: '3 / 6' }}>
        <InstitutionalScore />
      </div>

      {/* Row 6-8: Analysis panels */}
      <div style={{ gridColumn: '1 / 2', gridRow: '6 / 9' }}>
        <TimeframeMatrix />
      </div>

      <div style={{ gridColumn: '2 / 3', gridRow: '6 / 9' }}>
        <AgentConsensus />
      </div>

      <div style={{ gridColumn: '3 / 4', gridRow: '6 / 9' }}>
        <ModelPredictions />
      </div>

      <div style={{ gridColumn: '4 / 5', gridRow: '6 / 9' }}>
        <OIIntelligence />
      </div>

      {/* Row 9-10: Secondary panels */}
      <div style={{ gridColumn: '1 / 2', gridRow: '9 / 11' }}>
        <DepthHeatmap />
      </div>

      <div style={{ gridColumn: '2 / 3', gridRow: '9 / 11' }}>
        <DangerAlerts />
      </div>

      <div style={{ gridColumn: '3 / 5', gridRow: '9 / 11' }}>
        <SelfLearningPanel />
      </div>

      {/* Row 11-12: Stock Scanner (full width) */}
      <div style={{ gridColumn: '1 / 5', gridRow: '11 / 13' }}>
        <StockScanner />
      </div>
    </div>
  )
}

export function DashboardLayout() {
  const mode = useDashboardStore((s) => s.mode)

  return mode === 'execution' ? <ExecutionLayout /> : <ResearchLayout />
}
