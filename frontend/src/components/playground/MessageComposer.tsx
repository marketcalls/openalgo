import { useState, useCallback, useEffect, useRef } from 'react'
import { Button } from '@/components/ui/button'
import { JsonEditor } from '@/components/ui/json-editor'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Send, FileText } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { MessageTemplate } from '@/types/websocket'

// Extended template type with category
interface CategorizedTemplate extends MessageTemplate {
  category: 'auth' | 'subscribe' | 'depth' | 'unsubscribe' | 'broker'
}

// Message templates organized by category
const MESSAGE_TEMPLATES: CategorizedTemplate[] = [
  // Authentication
  {
    key: 'authenticate',
    label: 'Authenticate',
    description: 'Authenticate with API key',
    template: { action: 'authenticate', api_key: '{{API_KEY}}' },
    category: 'auth',
  },
  // Subscriptions
  {
    key: 'subscribe_ltp',
    label: 'Subscribe LTP',
    description: 'Last Traded Price (Mode 1)',
    template: {
      action: 'subscribe',
      symbol: 'RELIANCE',
      exchange: 'NSE',
      mode: 1,
    },
    category: 'subscribe',
  },
  {
    key: 'subscribe_quote',
    label: 'Subscribe Quote',
    description: 'Full Quote data (Mode 2)',
    template: {
      action: 'subscribe',
      symbol: 'RELIANCE',
      exchange: 'NSE',
      mode: 2,
    },
    category: 'subscribe',
  },
  {
    key: 'subscribe_multiple',
    label: 'Subscribe Multiple',
    description: 'Multiple symbols at once',
    template: {
      action: 'subscribe',
      symbols: [
        { symbol: 'RELIANCE', exchange: 'NSE' },
        { symbol: 'TCS', exchange: 'NSE' },
        { symbol: 'INFY', exchange: 'NSE' },
      ],
      mode: 1,
    },
    category: 'subscribe',
  },
  // Depth Subscriptions (Mode 3)
  {
    key: 'subscribe_depth_5',
    label: 'Depth 5 Levels',
    description: 'Market Depth - 5 bid/ask levels',
    template: {
      action: 'subscribe',
      symbol: 'RELIANCE',
      exchange: 'NSE',
      mode: 3,
      depth: 5,
    },
    category: 'depth',
  },
  {
    key: 'subscribe_depth_20',
    label: 'Depth 20 Levels',
    description: 'Market Depth - 20 bid/ask levels',
    template: {
      action: 'subscribe',
      symbol: 'RELIANCE',
      exchange: 'NSE',
      mode: 3,
      depth: 20,
    },
    category: 'depth',
  },
  {
    key: 'subscribe_depth_30',
    label: 'Depth 30 Levels',
    description: 'Market Depth - 30 levels (broker dependent)',
    template: {
      action: 'subscribe',
      symbol: 'RELIANCE',
      exchange: 'NSE',
      mode: 3,
      depth: 30,
    },
    category: 'depth',
  },
  {
    key: 'subscribe_depth_50',
    label: 'Depth 50 Levels',
    description: 'Full Depth - 50 levels (broker dependent)',
    template: {
      action: 'subscribe',
      symbol: 'RELIANCE:50',
      exchange: 'NSE',
      mode: 3,
      depth: 50,
    },
    category: 'depth',
  },
  // Unsubscribe
  {
    key: 'unsubscribe_ltp',
    label: 'Unsubscribe LTP',
    description: 'Unsubscribe from LTP (Mode 1)',
    template: {
      action: 'unsubscribe',
      symbol: 'RELIANCE',
      exchange: 'NSE',
      mode: 1,
    },
    category: 'unsubscribe',
  },
  {
    key: 'unsubscribe_quote',
    label: 'Unsubscribe Quote',
    description: 'Unsubscribe from Quote (Mode 2)',
    template: {
      action: 'unsubscribe',
      symbol: 'RELIANCE',
      exchange: 'NSE',
      mode: 2,
    },
    category: 'unsubscribe',
  },
  {
    key: 'unsubscribe_depth',
    label: 'Unsubscribe Depth',
    description: 'Unsubscribe from Depth (Mode 3)',
    template: {
      action: 'unsubscribe',
      symbol: 'RELIANCE',
      exchange: 'NSE',
      mode: 3,
    },
    category: 'unsubscribe',
  },
  {
    key: 'unsubscribe_depth_50',
    label: 'Unsubscribe Depth 50',
    description: 'Unsubscribe from 50-level Depth (broker dependent)',
    template: {
      action: 'unsubscribe',
      symbol: 'RELIANCE:50',
      exchange: 'NSE',
      mode: 3,
      depth: 50,
    },
    category: 'unsubscribe',
  },
  {
    key: 'unsubscribe_all',
    label: 'Unsubscribe All',
    description: 'Unsubscribe from all symbols',
    template: { action: 'unsubscribe_all' },
    category: 'unsubscribe',
  },
  // Broker Info
  {
    key: 'get_broker_info',
    label: 'Get Broker Info',
    description: 'Current broker information',
    template: { action: 'get_broker_info' },
    category: 'broker',
  },
  {
    key: 'get_supported_brokers',
    label: 'Get Supported Brokers',
    description: 'List all supported brokers',
    template: { action: 'get_supported_brokers' },
    category: 'broker',
  },
  {
    key: 'ping',
    label: 'Ping',
    description: 'Test connection latency',
    template: { action: 'ping', timestamp: '{{TIMESTAMP}}' },
    category: 'broker',
  },
]

// Category labels for display
const CATEGORY_LABELS: Record<CategorizedTemplate['category'], string> = {
  auth: 'Authentication',
  subscribe: 'Subscriptions',
  depth: 'Market Depth',
  unsubscribe: 'Unsubscribe',
  broker: 'Broker Info',
}

// Get templates grouped by category
const getTemplatesByCategory = () => {
  const grouped: Record<string, CategorizedTemplate[]> = {}
  for (const template of MESSAGE_TEMPLATES) {
    if (!grouped[template.category]) {
      grouped[template.category] = []
    }
    grouped[template.category].push(template)
  }
  return grouped
}

interface MessageComposerProps {
  value: string
  onChange: (value: string) => void
  onSend: (message: string) => void
  disabled?: boolean
  apiKey?: string
}

export function MessageComposer({
  value,
  onChange,
  onSend,
  disabled = false,
  apiKey = '',
}: MessageComposerProps) {
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null)
  const editorRef = useRef<{ focus: () => void } | null>(null)

  // Apply template
  const applyTemplate = useCallback(
    (templateKey: string) => {
      const template = MESSAGE_TEMPLATES.find((t) => t.key === templateKey)
      if (!template) return

      let templateStr = JSON.stringify(template.template, null, 2)

      // Replace {{API_KEY}} placeholder with actual API key
      if (apiKey && templateStr.includes('{{API_KEY}}')) {
        templateStr = templateStr.replace('{{API_KEY}}', apiKey)
      }

      // Replace {{TIMESTAMP}} placeholder with current timestamp
      if (templateStr.includes('{{TIMESTAMP}}')) {
        templateStr = templateStr.replace('"{{TIMESTAMP}}"', String(Date.now()))
      }

      onChange(templateStr)
      setSelectedTemplate(templateKey)

      // Focus editor after applying template
      setTimeout(() => {
        editorRef.current?.focus()
      }, 100)
    },
    [onChange, apiKey]
  )

  const handleSend = useCallback(() => {
    if (!value.trim()) return
    onSend(value)
  }, [value, onSend])

  // Handle keyboard shortcuts
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      // Ctrl+Enter or Cmd+Enter to send
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        if (disabled) return
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend, disabled]
  )

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])

  return (
    <div className="flex flex-col h-full bg-card/50 rounded-lg border border-border overflow-hidden">
      {/* Template selector */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border bg-card/30">
        <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
        <Select
          value={selectedTemplate || ''}
          onValueChange={(value) => {
            if (value) {
              applyTemplate(value)
            }
          }}
          disabled={disabled}
        >
          <SelectTrigger className="flex-1 h-8 text-xs">
            <SelectValue placeholder="Select a template..." />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(getTemplatesByCategory()).map(([category, templates]) => (
              <SelectGroup key={category}>
                <SelectLabel className="text-xs font-semibold text-muted-foreground">
                  {CATEGORY_LABELS[category as CategorizedTemplate['category']]}
                </SelectLabel>
                {templates.map((template) => (
                  <SelectItem key={template.key} value={template.key}>
                    {template.label} - {template.description}
                  </SelectItem>
                ))}
              </SelectGroup>
            ))}
          </SelectContent>
        </Select>
        {selectedTemplate && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
            onClick={() => {
              setSelectedTemplate(null)
              onChange('')
            }}
          >
            Clear
          </Button>
        )}
      </div>

      {/* JSON Editor */}
      <div className="flex-1 min-h-0">
        <JsonEditor
          value={value}
          onChange={onChange}
          placeholder='{"action": "authenticate", "api_key": "..."}'
          className="h-full"
          readOnly={disabled}
        />
      </div>

      {/* Send button */}
      <div className="flex items-center justify-between px-3 py-2 border-t border-border bg-card/30">
        <span className="text-[10px] text-muted-foreground">
          Ctrl+Enter to send
        </span>
        <Button
          size="sm"
          className={cn(
            'h-8 px-4',
            disabled
              ? 'bg-muted text-muted-foreground cursor-not-allowed'
              : 'bg-sky-600 hover:bg-sky-700 text-white'
          )}
          onClick={handleSend}
          disabled={disabled || !value.trim()}
        >
          <Send className="h-3.5 w-3.5 mr-1.5" />
          Send Message
        </Button>
      </div>
    </div>
  )
}
