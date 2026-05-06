/**
 * Strategy v2 API client.
 *
 * All endpoints under /strategy/api/v2 use the existing webClient (cookie
 * session + CSRF) since they are authenticated UI endpoints. The webhook
 * URL itself (/strategy/webhook/<uuid>) is unauthenticated by URL secret +
 * the signing layer in services/strategy/ingestion_service.py — those
 * webhooks are NOT called from this client.
 *
 * See docs/plans/2026-05-06-strategy-v2-implementation-plan.md §5.3 + §8.4.
 */
import { webClient } from './client'
import type {
  StrategyV2,
  StrategyV2WithLegs,
  StrategyV2CreatePayload,
  StrategyV2UpdatePayload,
  StrategyLeg,
  LegPayload,
  WebhookRotateResponse,
  WebhookTestResponse,
  AuditVerifyResponse,
  StrategyRun,
  RunOrderbookResponse,
  RunListResponse,
  RunTradeRow,
  RunPositionRow,
  RunEventRow,
  StrategyRiskConfig,
  RiskConfigPayload,
  AccountRiskConfig,
  AccountRiskConfigPayload,
  AccountRiskConfigResponse,
  StrategyState,
} from '@/types/strategy_v2'

const ROOT = '/strategy/api/v2'

export const strategyV2Api = {
  // ---- Strategy CRUD ----
  list: async (): Promise<StrategyV2[]> => {
    const r = await webClient.get<{ strategies: StrategyV2[] }>(`${ROOT}/strategy`)
    return r.data.strategies || []
  },

  get: async (id: number): Promise<StrategyV2WithLegs> => {
    const r = await webClient.get<StrategyV2WithLegs>(`${ROOT}/strategy/${id}`)
    return r.data
  },

  create: async (data: StrategyV2CreatePayload) => {
    /** Returns the strategy with one-time webhook_secret + webhook_hmac_key
     *  fields — show them in a copy-once modal and then drop. */
    const r = await webClient.post<{
      status: string
      strategy: StrategyV2 & { webhook_secret?: string; webhook_hmac_key?: string }
      message: string
    }>(`${ROOT}/strategy`, data)
    return r.data
  },

  update: async (id: number, data: StrategyV2UpdatePayload) => {
    const r = await webClient.put<{ status: string; strategy: StrategyV2 }>(
      `${ROOT}/strategy/${id}`,
      data
    )
    return r.data
  },

  remove: async (id: number) => {
    const r = await webClient.delete<{ status: string }>(`${ROOT}/strategy/${id}`)
    return r.data
  },

  toggle: async (id: number) => {
    const r = await webClient.post<{
      status: string
      is_active: boolean
      state: StrategyState
    }>(`${ROOT}/strategy/${id}/toggle`)
    return r.data
  },

  // ---- Leg CRUD ----
  addLeg: async (strategyId: number, leg: LegPayload) => {
    const r = await webClient.post<{ status: string; leg: StrategyLeg }>(
      `${ROOT}/strategy/${strategyId}/legs`,
      leg
    )
    return r.data.leg
  },

  updateLeg: async (strategyId: number, legId: number, leg: Partial<LegPayload>) => {
    const r = await webClient.put<{ status: string; leg: StrategyLeg }>(
      `${ROOT}/strategy/${strategyId}/legs/${legId}`,
      leg
    )
    return r.data.leg
  },

  removeLeg: async (strategyId: number, legId: number) => {
    const r = await webClient.delete<{ status: string }>(
      `${ROOT}/strategy/${strategyId}/legs/${legId}`
    )
    return r.data
  },

  // ---- Webhook actions ----
  rotateWebhook: async (id: number, confirm: string): Promise<WebhookRotateResponse> => {
    const r = await webClient.post<WebhookRotateResponse>(
      `${ROOT}/strategy/${id}/webhook/rotate`,
      { confirm }
    )
    return r.data
  },

  testWebhook: async (id: number, payload: object): Promise<WebhookTestResponse> => {
    const r = await webClient.post<WebhookTestResponse>(
      `${ROOT}/strategy/${id}/webhook/test`,
      payload
    )
    return r.data
  },

  /** Build the URL the user pastes into TradingView/Python/etc. */
  webhookUrl: (webhookId: string): string => {
    if (typeof window === 'undefined') return ''
    return `${window.location.origin}/strategy/webhook/${webhookId}`
  },

  // ---- Audit chain verifier (Phase 0) ----
  verifyAudit: async (runId: number): Promise<AuditVerifyResponse> => {
    const r = await webClient.get<AuditVerifyResponse>(`${ROOT}/audit/verify/${runId}`)
    return r.data
  },

  // ---- Reporting (Phase 2) ----
  listRuns: async (strategyId: number) => {
    const r = await webClient.get<{ status: string; data: StrategyRun[] }>(
      `${ROOT}/strategy/${strategyId}/runs`
    )
    return r.data.data || []
  },

  getRun: async (runId: number): Promise<StrategyRun> => {
    const r = await webClient.get<{ status: string; data: StrategyRun }>(
      `${ROOT}/run/${runId}`
    )
    return r.data.data
  },

  runOrderbook: async (runId: number): Promise<RunOrderbookResponse> => {
    const r = await webClient.get<RunOrderbookResponse>(`${ROOT}/run/${runId}/orderbook`)
    return r.data
  },

  runTradebook: async (runId: number): Promise<RunListResponse<RunTradeRow>> => {
    const r = await webClient.get<RunListResponse<RunTradeRow>>(`${ROOT}/run/${runId}/tradebook`)
    return r.data
  },

  runPositionbook: async (runId: number): Promise<RunListResponse<RunPositionRow>> => {
    const r = await webClient.get<RunListResponse<RunPositionRow>>(
      `${ROOT}/run/${runId}/positionbook`
    )
    return r.data
  },

  runEvents: async (runId: number): Promise<RunListResponse<RunEventRow>> => {
    const r = await webClient.get<RunListResponse<RunEventRow>>(`${ROOT}/run/${runId}/events`)
    return r.data
  },

  // ---- Phase 4: strategy-level risk config ----
  getRiskConfig: async (strategyId: number): Promise<StrategyRiskConfig> => {
    const r = await webClient.get<{ status: string; data: StrategyRiskConfig }>(
      `${ROOT}/strategy/${strategyId}/risk_config`
    )
    return r.data.data
  },

  updateRiskConfig: async (
    strategyId: number,
    payload: RiskConfigPayload
  ): Promise<StrategyRiskConfig> => {
    const r = await webClient.put<{ status: string; data: StrategyRiskConfig }>(
      `${ROOT}/strategy/${strategyId}/risk_config`,
      payload
    )
    return r.data.data
  },

  // ---- Phase 4.5: account-level risk config + state + unlock ----
  getAccountRiskConfig: async (): Promise<AccountRiskConfigResponse> => {
    const r = await webClient.get<AccountRiskConfigResponse>(`${ROOT}/account/risk_config`)
    return r.data
  },

  updateAccountRiskConfig: async (
    payload: AccountRiskConfigPayload
  ): Promise<AccountRiskConfig> => {
    const r = await webClient.put<{ status: string; config: AccountRiskConfig }>(
      `${ROOT}/account/risk_config`,
      payload
    )
    return r.data.config
  },

  unlockAccount: async (): Promise<AccountRiskConfig> => {
    const r = await webClient.post<{ status: string; config: AccountRiskConfig }>(
      `${ROOT}/account/unlock`
    )
    return r.data.config
  },
}
