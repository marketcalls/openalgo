import { useState, useMemo } from 'react'
import { Search, ArrowUpDown, Loader2 } from 'lucide-react'
import { Panel } from './shared/Panel'
import { SignalBadge } from './shared/SignalBadge'
import { cn } from '@/lib/utils'
import { useStockScanner } from '@/api/dashboardApi'
import { useDashboardStore } from '@/stores/dashboardStore'
import type { ScannerRow } from '@/types/dashboard'

type SortKey = keyof ScannerRow

export function StockScanner() {
  const setSymbol = useDashboardStore((s) => s.setSymbol)
  const { data: scannerData, isLoading } = useStockScanner()
  const scannerRows = scannerData?.rows ?? []
  const [sortKey, setSortKey] = useState<SortKey>('institutionalScore')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const sorted = useMemo(() => {
    return [...scannerRows].sort((a, b) => {
      const av = a[sortKey]
      const bv = b[sortKey]
      if (typeof av === 'number' && typeof bv === 'number') return sortDir === 'desc' ? bv - av : av - bv
      return sortDir === 'desc' ? String(bv).localeCompare(String(av)) : String(av).localeCompare(String(bv))
    })
  }, [scannerRows, sortKey, sortDir])

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))
    else { setSortKey(key); setSortDir('desc') }
  }

  const headers: Array<{ key: SortKey; label: string }> = [
    { key: 'symbol', label: 'Symbol' }, { key: 'ltp', label: 'Price' },
    { key: 'changePct', label: 'Chg%' }, { key: 'institutionalScore', label: 'Score' },
    { key: 'signal', label: 'Signal' }, { key: 'relativeVolume', label: 'RVol' },
    { key: 'sector', label: 'Sector' },
  ]

  if (isLoading) {
    return (
      <Panel title="Stock Scanner" icon={<Search size={14} />} compact className="h-full">
        <div className="flex h-full items-center justify-center">
          <Loader2 size={20} className="animate-spin text-slate-500" />
        </div>
      </Panel>
    )
  }

  return (
    <Panel title="Stock Scanner" icon={<Search size={14} />} compact className="h-full">
      <div className="overflow-auto h-full">
        <table className="w-full text-[10px]">
          <thead className="sticky top-0 bg-slate-950 z-10">
            <tr className="text-slate-500 border-b border-slate-800">
              {headers.map((h) => (
                <th key={h.key} className="px-2 py-1.5 text-left font-medium cursor-pointer hover:text-slate-300 whitespace-nowrap"
                  onClick={() => handleSort(h.key)}>
                  <div className="flex items-center gap-0.5">
                    {h.label}
                    {sortKey === h.key && <ArrowUpDown size={8} className="text-sky-400" />}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr key={row.symbol} className="border-b border-slate-800/30 hover:bg-slate-800/30 cursor-pointer"
                onClick={() => setSymbol(row.symbol)}>
                <td className="px-2 py-1 font-bold text-slate-200">{row.symbol}</td>
                <td className="px-2 py-1 font-mono text-slate-300">{row.ltp.toFixed(2)}</td>
                <td className={cn('px-2 py-1 font-mono font-bold', row.changePct >= 0 ? 'text-emerald-400' : 'text-rose-400')}>
                  {row.changePct > 0 ? '+' : ''}{row.changePct.toFixed(2)}%
                </td>
                <td className="px-2 py-1 font-mono text-slate-300">{row.institutionalScore}</td>
                <td className="px-2 py-1"><SignalBadge signal={row.signal} size="sm" /></td>
                <td className="px-2 py-1 font-mono text-slate-400">{row.relativeVolume.toFixed(1)}x</td>
                <td className="px-2 py-1 text-slate-500">{row.sector}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}
