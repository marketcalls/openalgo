import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import type { StrategyTemplate } from '@/api/strategy-templates'

interface TemplateCardProps {
  template: StrategyTemplate
  onDeploy: (template: StrategyTemplate) => void
}

const CATEGORY_STYLES: Record<string, string> = {
  neutral: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
  bullish: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
  bearish: 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
}

export function TemplateCard({ template, onDeploy }: TemplateCardProps) {
  const legs = template.legs_config || []

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
          {legs.map((leg: Record<string, unknown>, idx: number) => (
            <div key={idx} className="flex items-center gap-1.5 text-xs">
              <span className={String(leg.action) === 'BUY' ? 'text-green-600' : 'text-red-600'}>
                {String(leg.action)}
              </span>
              <span>{String(leg.option_type || 'FUT')}</span>
              <span className="text-muted-foreground">{String(leg.offset || '')}</span>
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
