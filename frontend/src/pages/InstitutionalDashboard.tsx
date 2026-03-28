import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Search, Crosshair, FlaskConical } from 'lucide-react'
import { DashboardLayout } from '@/components/dashboard/DashboardLayout'
import { MarketRibbon } from '@/components/dashboard/MarketRibbon'
import { useDashboardStore } from '@/stores/dashboardStore'
import { cn } from '@/lib/utils'
import type { Timeframe } from '@/types/dashboard'

const TIMEFRAMES: Timeframe[] = ['1m', '5m', '15m', '1h', '4h']

export default function InstitutionalDashboard() {
  const symbol = useDashboardStore((s) => s.selectedSymbol)
  const setSymbol = useDashboardStore((s) => s.setSymbol)
  const selectedTf = useDashboardStore((s) => s.selectedTimeframe)
  const setTimeframe = useDashboardStore((s) => s.setTimeframe)
  const mode = useDashboardStore((s) => s.mode)
  const setMode = useDashboardStore((s) => s.setMode)
  const [searchInput, setSearchInput] = useState(symbol)

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    if (searchInput.trim()) setSymbol(searchInput.trim().toUpperCase())
  }

  return (
    <div className="flex h-screen flex-col bg-slate-950 text-white">
      {/* Top Bar */}
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2">
        <div className="flex items-center gap-3">
          <Link
            to="/dashboard"
            className="text-slate-500 hover:text-slate-300 transition-colors"
          >
            <ArrowLeft size={18} />
          </Link>
          <h1 className="text-sm font-bold tracking-wide text-slate-200">
            AAUM
          </h1>
          <span className="rounded bg-sky-600/20 border border-sky-600/30 px-2 py-0.5 text-[10px] font-bold text-sky-400">
            LIVE
          </span>

          {/* ── MODE TOGGLE ── */}
          <div className="flex items-center rounded-lg bg-slate-800/60 border border-slate-700/50 p-0.5">
            <button
              onClick={() => setMode('execution')}
              className={cn(
                'flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-semibold transition-all',
                mode === 'execution'
                  ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-600/20'
                  : 'text-slate-400 hover:text-slate-200',
              )}
            >
              <Crosshair size={12} />
              Execution
            </button>
            <button
              onClick={() => setMode('research')}
              className={cn(
                'flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-semibold transition-all',
                mode === 'research'
                  ? 'bg-sky-600 text-white shadow-lg shadow-sky-600/20'
                  : 'text-slate-400 hover:text-slate-200',
              )}
            >
              <FlaskConical size={12} />
              Research
            </button>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Symbol Search */}
          <form onSubmit={handleSearch} className="flex items-center gap-1">
            <div className="relative">
              <Search
                size={12}
                className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500"
              />
              <input
                type="text"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="h-7 w-28 rounded border border-slate-700 bg-slate-900 pl-6 pr-2 text-xs text-slate-200 placeholder-slate-600 focus:border-sky-600 focus:outline-none"
                placeholder="Symbol..."
              />
            </div>
          </form>

          {/* Timeframe Selector */}
          <div className="flex items-center gap-0.5">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={cn(
                  'px-3 py-1 rounded text-xs font-medium transition-colors',
                  selectedTf === tf
                    ? 'bg-emerald-600 text-white'
                    : 'bg-slate-800 text-slate-400 hover:bg-slate-700',
                )}
              >
                {tf}
              </button>
            ))}
          </div>

          {/* Symbol Display */}
          <span className="text-sm font-black text-slate-100 tracking-wide">
            {symbol}
          </span>
        </div>
      </div>

      {/* Market Summary Ribbon */}
      <MarketRibbon />

      {/* Dashboard Grid */}
      <div className="flex-1 min-h-0">
        <DashboardLayout />
      </div>
    </div>
  )
}
