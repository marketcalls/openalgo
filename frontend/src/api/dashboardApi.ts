import { useQuery } from '@tanstack/react-query'
import { apiClient } from './client'
import type {
  AgentConsensusResponse,
  CommandCenterResponse,
  DashboardApiResponse,
  InstitutionalScoreResponse,
  ModelPredictionsResponse,
  OIIntelligenceResponse,
  RiskSnapshotResponse,
  SelfLearningResponse,
  StockScannerResponse,
  TimeframeMatrixResponse,
} from '@/types/dashboard'

// ─────────────────────────────────────────────────────────────────────────────
// AAUM Institutional Dashboard — API Layer (TanStack Query Hooks)
// ─────────────────────────────────────────────────────────────────────────────

const DASHBOARD_BASE = '/aaum/dashboard'

// ── Generic fetcher ──────────────────────────────────────────────────────────

async function fetchDashboard<T>(path: string, params?: Record<string, string>): Promise<T> {
  const response = await apiClient.get<DashboardApiResponse<T>>(
    `${DASHBOARD_BASE}${path}`,
    { params },
  )
  if (response.data.status === 'error') {
    throw new Error(response.data.error ?? 'Dashboard API error')
  }
  return response.data.data
}

// ── Query Key Factory ────────────────────────────────────────────────────────

export const dashboardKeys = {
  all: ['dashboard'] as const,
  commandCenter: (symbol: string) => [...dashboardKeys.all, 'command-center', symbol] as const,
  institutionalScore: (symbol: string) =>
    [...dashboardKeys.all, 'institutional-score', symbol] as const,
  agentConsensus: (symbol: string) => [...dashboardKeys.all, 'agent-consensus', symbol] as const,
  modelPredictions: (symbol: string) =>
    [...dashboardKeys.all, 'model-predictions', symbol] as const,
  oiIntelligence: (symbol: string) => [...dashboardKeys.all, 'oi-intelligence', symbol] as const,
  selfLearning: (symbol?: string) => [...dashboardKeys.all, 'self-learning', symbol ?? ''] as const,
  riskSnapshot: () => [...dashboardKeys.all, 'risk-snapshot'] as const,
  stockScanner: () => [...dashboardKeys.all, 'stock-scanner'] as const,
  timeframeMatrix: (symbol: string) =>
    [...dashboardKeys.all, 'timeframe-matrix', symbol] as const,
}

// ── Hooks ────────────────────────────────────────────────────────────────────

export function useCommandCenter(symbol: string) {
  return useQuery({
    queryKey: dashboardKeys.commandCenter(symbol),
    queryFn: () => fetchDashboard<CommandCenterResponse>('/command-center', { symbol }),
    enabled: !!symbol,
    staleTime: 10_000,
    refetchInterval: 15_000,
  })
}

export function useInstitutionalScore(symbol: string) {
  return useQuery({
    queryKey: dashboardKeys.institutionalScore(symbol),
    queryFn: () => fetchDashboard<InstitutionalScoreResponse>('/institutional-score', { symbol }),
    enabled: !!symbol,
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
}

export function useAgentConsensus(symbol: string) {
  return useQuery({
    queryKey: dashboardKeys.agentConsensus(symbol),
    queryFn: () => fetchDashboard<AgentConsensusResponse>('/agent-consensus', { symbol }),
    enabled: !!symbol,
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
}

export function useModelPredictions(symbol: string) {
  return useQuery({
    queryKey: dashboardKeys.modelPredictions(symbol),
    queryFn: () => fetchDashboard<ModelPredictionsResponse>('/model-predictions', { symbol }),
    enabled: !!symbol,
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
}

export function useOIIntelligence(symbol: string) {
  return useQuery({
    queryKey: dashboardKeys.oiIntelligence(symbol),
    queryFn: () => fetchDashboard<OIIntelligenceResponse>('/oi-intelligence', { symbol }),
    enabled: !!symbol,
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
}

export function useSelfLearning(symbol?: string) {
  return useQuery({
    queryKey: dashboardKeys.selfLearning(symbol),
    queryFn: () =>
      fetchDashboard<SelfLearningResponse>(
        '/self-learning',
        symbol ? { symbol } : undefined,
      ),
    staleTime: 60_000,
    refetchInterval: 120_000,
  })
}

export function useRiskSnapshot() {
  return useQuery({
    queryKey: dashboardKeys.riskSnapshot(),
    queryFn: () => fetchDashboard<RiskSnapshotResponse>('/risk-snapshot'),
    staleTime: 10_000,
    refetchInterval: 15_000,
  })
}

export function useStockScanner() {
  return useQuery({
    queryKey: dashboardKeys.stockScanner(),
    queryFn: () => fetchDashboard<StockScannerResponse>('/stock-scanner'),
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
}

export function useTimeframeMatrix(symbol: string) {
  return useQuery({
    queryKey: dashboardKeys.timeframeMatrix(symbol),
    queryFn: () => fetchDashboard<TimeframeMatrixResponse>('/timeframe-matrix', { symbol }),
    enabled: !!symbol,
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
}
