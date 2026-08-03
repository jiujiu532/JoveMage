import type { AccountTaskTier, AccountTaskType } from '@/api/accounts'
import { REFRESH_BATCH_SIZE } from './accountPageShared'

/** 底栏勾选 ≤50 为 light，>50 为 heavy；顶栏范围任务调用方直接传 heavy */
export const LIGHT_TIER_MAX = 50

export function resolveSelectedTier(count: number): AccountTaskTier {
  return count > LIGHT_TIER_MAX ? 'heavy' : 'light'
}

export function taskTypeLabel(type: AccountTaskType | string | undefined): string {
  switch (String(type || '')) {
    case 'account_refresh':
      return '刷新'
    case 'account_inspect':
      return '巡检'
    case 'account_delete':
      return '删除'
    case 'account_relogin':
    case 'relogin_batch':
      return '重登'
    case 'account_enable':
      return '启用'
    case 'account_disable':
      return '禁用'
    case 'account_reset':
      return '重置'
    default:
      return type ? String(type) : '任务'
  }
}

export function tierBadgeLabel(tier: AccountTaskTier | string | undefined): string {
  return tier === 'light' ? '轻' : '重'
}

/**
 * UI 状态：running / stopping / completed / stopped / failed
 * stopping = running + cancel_requested
 * cancelled 后端字段映射为 stopped
 */
export type AccountTaskUiStatus = 'running' | 'stopping' | 'completed' | 'stopped' | 'failed'

export function resolveTaskUiStatus(task: {
  status?: string
  cancel_requested?: boolean
  error?: string | null
}): AccountTaskUiStatus {
  const status = String(task.status || '').toLowerCase()
  if (status === 'failed' || task.error) return 'failed'
  if (status === 'completed') return 'completed'
  if (status === 'stopped' || status === 'cancelled') return 'stopped'
  if (status === 'running' && task.cancel_requested) return 'stopping'
  if (status === 'running') return 'running'
  if (task.cancel_requested) return 'stopping'
  return 'running'
}

export function taskStatusLabel(
  uiStatus: AccountTaskUiStatus,
  options?: { batchRemaining?: number; kindHint?: string },
): string {
  const batchRemaining = Math.max(0, Number(options?.batchRemaining || 0))
  switch (uiStatus) {
    case 'stopping':
      return batchRemaining > 0 ? `停止中 本批剩 ${batchRemaining}` : '停止中…'
    case 'completed':
      return '已完成'
    case 'stopped':
      return '已停止'
    case 'failed':
      return '失败'
    default:
      return options?.kindHint || '运行中'
  }
}

export const STOP_HINT_TEXT =
  `停止不会立刻生效。当前批次（最多 ${REFRESH_BATCH_SIZE} 个账号）会跑完并等待线程收束后停止；已处理结果保留。完全停止前不能开始同档新任务。`

export function isTerminalUiStatus(status: AccountTaskUiStatus): boolean {
  return status === 'completed' || status === 'stopped' || status === 'failed'
}

export function isDeleteTaskType(type: string | undefined): boolean {
  return String(type || '') === 'account_delete'
}

export function isInspectTaskType(type: string | undefined): boolean {
  return String(type || '') === 'account_inspect'
}
