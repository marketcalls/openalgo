import type { PresetDefinition } from '@/types/strategy-builder'
import { TemplateCard } from './TemplateCard'

interface TemplateGridProps {
  templates: PresetDefinition[]
  onDeploy: (template: PresetDefinition) => void
}

export function TemplateGrid({ templates, onDeploy }: TemplateGridProps) {
  if (templates.length === 0) {
    return (
      <div className="flex items-center justify-center h-40 text-sm text-muted-foreground">
        No templates match the selected filter.
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {templates.map((template) => (
        <TemplateCard key={template.id} template={template} onDeploy={onDeploy} />
      ))}
    </div>
  )
}
