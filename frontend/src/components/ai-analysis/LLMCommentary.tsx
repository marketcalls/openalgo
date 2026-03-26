import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { useAuthStore } from '@/stores/authStore'
import { llmApi } from '@/api/llm'
import { Bot, Loader2, RefreshCw } from 'lucide-react'
import type { AIAnalysisResult } from '@/types/ai-analysis'

interface LLMCommentaryProps {
  analysis: AIAnalysisResult | null
}

export function LLMCommentary({ analysis }: LLMCommentaryProps) {
  const apiKey = useAuthStore((s) => s.apiKey)
  const [enabled, setEnabled] = useState(false)

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['llm-commentary', analysis?.symbol, analysis?.signal],
    queryFn: async () => {
      if (!apiKey || !analysis) return null
      const response = await llmApi.getCommentary(apiKey, analysis as unknown as Record<string, unknown>)
      return response.data ?? null
    },
    enabled: enabled && !!apiKey && !!analysis,
    staleTime: 120_000,
  })

  if (!analysis) return null

  if (!enabled) {
    return (
      <Button variant="outline" size="sm" onClick={() => setEnabled(true)}>
        <Bot className="h-4 w-4 mr-1" /> Get AI Commentary
      </Button>
    )
  }

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Generating commentary...
      </div>
    )
  }

  if (!data) {
    return <p className="text-xs text-muted-foreground">LLM unavailable -- check Ollama or set GEMINI_API_KEY</p>
  }

  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2">
        <Bot className="h-4 w-4 mt-0.5 text-blue-500 shrink-0" />
        <p className="text-sm">{data.commentary}</p>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground">via {data.provider}/{data.model}</span>
        <Button variant="ghost" size="sm" onClick={() => refetch()}>
          <RefreshCw className="h-3 w-3" />
        </Button>
      </div>
    </div>
  )
}
