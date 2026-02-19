import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import type { PresetDefinition } from '@/types/strategy-builder'

interface TemplateCardProps {
  template: PresetDefinition
  onDeploy: (template: PresetDefinition) => void
}

const CATEGORY_STYLES: Record<string, string> = {
  neutral: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
  bullish: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
  bearish: 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
}

export function TemplateCard({ template, onDeploy }: TemplateCardProps) {
  return (
    <Card className="flex flex-col">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <CardTitle className="text-sm">{template.name}</CardTitle>
          <Badge variant="outline" className={`text-[10px] ${CATEGORY_STYLES[template.category] || ''}`}>
            {template.category}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="flex-1 pb-2">
        <p className="text-xs text-muted-foreground mb-3">{template.description}</p>
        <div className="space-y-1">
          {template.legs.map((leg, idx) => (
            <div key={idx} className="flex items-center gap-1.5 text-xs">
              <span className={leg.action === 'BUY' ? 'text-green-600' : 'text-red-600'}>
                {leg.action}
              </span>
              <span>{leg.option_type || 'FUT'}</span>
              <span className="text-muted-foreground">{leg.offset}</span>
            </div>
          ))}
        </div>
      </CardContent>
      <CardFooter className="pt-2">
        <Button size="sm" className="w-full" onClick={() => onDeploy(template)}>
          Deploy
        </Button>
      </CardFooter>
    </Card>
  )
}
