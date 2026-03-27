import { useState } from 'react'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Button } from '@/components/ui/button'
import { ChevronDown, ChevronUp } from 'lucide-react'

interface IndicatorItem {
  id: string
  name: string
  category: string
}

interface IndicatorSelectorProps {
  indicators: IndicatorItem[]
  selected: string[]
  onSelectionChange: (selected: string[]) => void
}

export function IndicatorSelector({ indicators, selected, onSelectionChange }: IndicatorSelectorProps) {
  const [expanded, setExpanded] = useState(false)

  if (!indicators || indicators.length === 0) {
    return <p className="text-xs text-muted-foreground">No custom indicators available</p>
  }

  const toggle = (id: string) => {
    if (selected.includes(id)) {
      onSelectionChange(selected.filter((s) => s !== id))
    } else {
      onSelectionChange([...selected, id])
    }
  }

  const displayList = expanded ? indicators : indicators.slice(0, 10)

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {selected.length} of {indicators.length} selected
        </span>
        <div className="flex gap-1">
          <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={() => onSelectionChange(indicators.map(i => i.id))}>
            All
          </Button>
          <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={() => onSelectionChange([])}>
            None
          </Button>
        </div>
      </div>

      <ScrollArea className={expanded ? 'h-64' : 'h-auto'}>
        <div className="space-y-1">
          {displayList.map((ind) => (
            <div key={ind.id} className="flex items-center gap-2 py-0.5">
              <Checkbox
                id={`ind-${ind.id}`}
                checked={selected.includes(ind.id)}
                onCheckedChange={() => toggle(ind.id)}
              />
              <Label htmlFor={`ind-${ind.id}`} className="text-xs cursor-pointer">
                {ind.name}
              </Label>
            </div>
          ))}
        </div>
      </ScrollArea>

      {indicators.length > 10 && (
        <Button variant="ghost" size="sm" className="w-full h-6 text-xs"
          onClick={() => setExpanded(!expanded)}>
          {expanded ? <><ChevronUp className="h-3 w-3 mr-1" /> Show Less</> : <><ChevronDown className="h-3 w-3 mr-1" /> Show All ({indicators.length})</>}
        </Button>
      )}
    </div>
  )
}
