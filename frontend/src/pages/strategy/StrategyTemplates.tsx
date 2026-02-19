import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { PresetDefinition } from '@/types/strategy-builder'
import { STRATEGY_TEMPLATES } from '@/api/strategy-templates'
import { TemplateGrid } from '@/components/strategy-templates/TemplateGrid'
import { DeployDialog } from '@/components/strategy-templates/DeployDialog'

type FilterTab = 'all' | 'neutral' | 'bullish' | 'bearish'

export default function StrategyTemplates() {
  const navigate = useNavigate()
  const [filter, setFilter] = useState<FilterTab>('all')
  const [deployTemplate, setDeployTemplate] = useState<PresetDefinition | null>(null)

  const filtered =
    filter === 'all'
      ? STRATEGY_TEMPLATES
      : STRATEGY_TEMPLATES.filter((p) => p.category === filter)

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-bold mb-1">Strategy Templates</h1>
        <p className="text-sm text-muted-foreground">
          Pre-built F&O strategy templates. Deploy with one click and customize.
        </p>
      </div>

      <Tabs value={filter} onValueChange={(v) => setFilter(v as FilterTab)}>
        <TabsList>
          <TabsTrigger value="all" className="text-xs">All</TabsTrigger>
          <TabsTrigger value="neutral" className="text-xs">Neutral</TabsTrigger>
          <TabsTrigger value="bullish" className="text-xs">Bullish</TabsTrigger>
          <TabsTrigger value="bearish" className="text-xs">Bearish</TabsTrigger>
        </TabsList>

        <TabsContent value={filter} className="mt-4">
          <TemplateGrid templates={filtered} onDeploy={setDeployTemplate} />
        </TabsContent>
      </Tabs>

      <DeployDialog
        open={!!deployTemplate}
        onClose={() => setDeployTemplate(null)}
        template={deployTemplate}
        onDeployed={() => navigate('/strategy/hub')}
      />
    </div>
  )
}
