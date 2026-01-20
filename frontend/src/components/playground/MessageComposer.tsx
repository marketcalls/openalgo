import { useState, useCallback, useEffect, useRef } from 'react'
import { Button } from '@/components/ui/button'
import { JsonEditor } from '@/components/ui/json-editor'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Send, FileText } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { MessageTemplate } from '@/types/websocket'

// Message templates for common WebSocket actions
const MESSAGE_TEMPLATES: MessageTemplate[] = [
  {
    key: 'authenticate',
    label: 'Authenticate',
    description: 'Authenticate with API key',
    template: { action: 'authenticate', api_key: '{{API_KEY}}' },
  },
  {
    key: 'subscribe_ltp',
    label: 'Subscribe LTP',
    description: 'Subscribe to Last Traded Price (Mode 1)',
    template: {
      action: 'subscribe',
      symbols: [{ symbol: 'RELIANCE', exchange: 'NSE' }],
      mode: 1,
    },
  },
  {
    key: 'subscribe_quote',
    label: 'Subscribe Quote',
    description: 'Subscribe to Quote data (Mode 2)',
    template: {
      action: 'subscribe',
      symbols: [{ symbol: 'RELIANCE', exchange: 'NSE' }],
      mode: 2,
    },
  },
  {
    key: 'subscribe_depth',
    label: 'Subscribe Depth',
    description: 'Subscribe to Market Depth (Mode 3)',
    template: {
      action: 'subscribe',
      symbols: [{ symbol: 'RELIANCE', exchange: 'NSE' }],
      mode: 3,
    },
  },
  {
    key: 'subscribe_multiple',
    label: 'Subscribe Multiple',
    description: 'Subscribe to multiple symbols',
    template: {
      action: 'subscribe',
      symbols: [
        { symbol: 'RELIANCE', exchange: 'NSE' },
        { symbol: 'TCS', exchange: 'NSE' },
        { symbol: 'INFY', exchange: 'NSE' },
      ],
      mode: 1,
    },
  },
  {
    key: 'unsubscribe',
    label: 'Unsubscribe',
    description: 'Unsubscribe from symbol',
    template: {
      action: 'unsubscribe',
      symbols: [{ symbol: 'RELIANCE', exchange: 'NSE' }],
      mode: 1,
    },
  },
  {
    key: 'unsubscribe_all',
    label: 'Unsubscribe All',
    description: 'Unsubscribe from all symbols',
    template: { action: 'unsubscribe_all' },
  },
  {
    key: 'get_broker_info',
    label: 'Get Broker Info',
    description: 'Get current broker information',
    template: { action: 'get_broker_info' },
  },
  {
    key: 'get_supported_brokers',
    label: 'Get Supported Brokers',
    description: 'List all supported brokers',
    template: { action: 'get_supported_brokers' },
  },
]

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
            {MESSAGE_TEMPLATES.map((template) => (
              <SelectItem key={template.key} value={template.key}>
                {template.label} - {template.description}
              </SelectItem>
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
