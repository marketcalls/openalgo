// frontend/src/components/ai-analysis/tabs/FundamentalTab.tsx
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { BarChart3 } from 'lucide-react'

export function FundamentalTab() {
  const upcomingFeatures = [
    'P/E Ratio',
    'P/B Ratio',
    'ROCE',
    'Debt-to-Equity',
    'Revenue Growth',
    'EPS Trend',
    'Sector Comparison',
    'Quarterly Results',
  ]

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex flex-col items-center justify-center py-16 text-center gap-4">
          <div className="rounded-full bg-muted p-4">
            <BarChart3 className="h-10 w-10 text-muted-foreground" />
          </div>
          <h3 className="text-lg font-semibold">Fundamental Analysis</h3>
          <p className="text-sm text-muted-foreground max-w-md">
            Comprehensive fundamental analysis with key financial metrics and ratios.
          </p>
          <ul className="text-sm text-muted-foreground space-y-1.5 text-left">
            {upcomingFeatures.map((feature) => (
              <li key={feature} className="flex items-center gap-2">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-muted-foreground/40" />
                {feature}
              </li>
            ))}
          </ul>
          <Badge variant="outline" className="mt-2 text-xs">
            Coming in Phase 4
          </Badge>
        </div>
      </CardContent>
    </Card>
  )
}
