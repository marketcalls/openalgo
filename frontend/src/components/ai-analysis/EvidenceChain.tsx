// frontend/src/components/ai-analysis/EvidenceChain.tsx

interface EvidenceChainProps {
  reasoning: string[]
}

export function EvidenceChain({ reasoning }: EvidenceChainProps) {
  if (!reasoning || reasoning.length === 0) {
    return (
      <div className="flex items-center justify-center py-4 text-sm text-muted-foreground">
        No reasoning data available
      </div>
    )
  }

  return (
    <ul className="space-y-1.5">
      {reasoning.map((item, idx) => (
        <li key={idx} className="flex items-start gap-2 text-sm leading-relaxed">
          <span className="mt-1.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-green-500" />
          <span className="text-muted-foreground">{item}</span>
        </li>
      ))}
    </ul>
  )
}
