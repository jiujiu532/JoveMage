import apiClient from './client'
import type { ChannelDescriptor } from '@/config/channels'

/**
 * GET /api/channels 响应。
 * 字段与后端 services/channels/descriptors.py 对齐；
 * 熔断/临期预警等 P1-B/C 字段前端可选消费，缺席不炸。
 */
export type ChannelsListResponse = {
  channels: ChannelDescriptor[]
}

/**
 * 账号行为档案（P2）。
 * GET /api/accounts/{account_id}/usage
 * 后端 services/channel_usage_service.account_profile 返回：
 * today 嵌套对象 + failure_reasons 数组 + recent 明细。
 */
export type AccountUsageToday = {
  calls: number
  success: number
  failed: number
  /** 0-1 */
  success_rate: number
  credits: number
  quota: number
}

export type AccountUsageRecentItem = {
  ts?: number
  trace_id?: string
  channel?: string
  account_id?: string
  action?: string
  model?: string
  cost?: { credits?: number; quota?: number; kind?: string }
  result?: string
  upstream_id?: string
  elapsed_ms?: number
  attempt_seq?: number
  note?: string
}

export type AccountUsageFailureReason = {
  reason: string
  count: number
}

export type AccountUsageProfile = {
  account_id: string
  today: AccountUsageToday
  failure_reasons: AccountUsageFailureReason[]
  recent: AccountUsageRecentItem[]
}

/** trace 载荷快照（脱敏，白名单字段）。 */
export type ChannelTracePayload = {
  model?: string
  channel?: string
  endpoint?: string
  prompt?: string
  size?: string
  quality?: string
  n?: number
  input_image_count?: number
  request_shape?: Record<string, unknown>
  [key: string]: unknown
}

export type ChannelTraceStage = {
  stage: string
  elapsed_ms: number
}

export type ChannelTraceAttempt = {
  seq?: number
  account_id?: string
  channel?: string
  result?: string
  reason?: string
  elapsed_ms?: number
  [key: string]: unknown
}

/**
 * GET /api/channels/traces/{trace_id} 响应（admin）。
 * 脱敏载荷快照 + attempt 序列 + 阶段耗时。
 */
export type ChannelTraceResponse = {
  trace_id: string
  call_id?: string
  payload?: ChannelTracePayload
  replay_params?: Record<string, unknown>
  stages?: ChannelTraceStage[]
  attempts?: ChannelTraceAttempt[]
  call?: Record<string, unknown>
  ts?: number
  updated_at?: number
}

/** Firefly credits 对账单账号行（POST /api/channels/firefly/reconcile）。 */
export type FireflyReconcileAccountRow = {
  account_id: string
  ledger_used?: number | null
  local_credits?: number | null
  remote_credits?: number | null
  remote_total?: number | null
  remote_used?: number | null
  drift?: number | null
  status: 'ok' | 'drift' | 'error' | string
  error?: string | null
}

/** Firefly credits 对账汇总。 */
export type FireflyReconcileResponse = {
  channel?: string
  tolerance?: number
  total?: number
  ok: number
  drift: number
  error: number
  accounts: FireflyReconcileAccountRow[]
  ts?: number
}

export const channelsApi = {
  /** 渠道描述符权威列表（鉴权：Bearer） */
  list: () => apiClient.get<never, ChannelsListResponse>('/api/channels'),

  /**
   * 账号行为档案：今日调用 / 成功率 / credits / 最近流水 / 失败原因。
   * 后端在 api/accounts.py；未上线时调用方 catch 后走空态。
   */
  getAccountProfile: (accountId: string, channel?: string) =>
    apiClient.get<never, AccountUsageProfile>(
      `/api/accounts/${encodeURIComponent(accountId)}/usage`,
      channel ? { params: { channel } } : undefined,
    ),

  /** trace 载荷快照 + attempt + 阶段耗时（admin）。 */
  getTrace: (traceId: string) =>
    apiClient.get<never, ChannelTraceResponse>(
      `/api/channels/traces/${encodeURIComponent(traceId)}`,
    ),

  /**
   * Firefly credits 对账：本地账本 vs 远端余额。
   * POST /api/channels/firefly/reconcile?tolerance=
   */
  reconcileFirefly: (tolerance?: number) =>
    apiClient.post<never, FireflyReconcileResponse>(
      '/api/channels/firefly/reconcile',
      null,
      typeof tolerance === 'number' && Number.isFinite(tolerance)
        ? { params: { tolerance } }
        : undefined,
    ),
}
