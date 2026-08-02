/**
 * 账号页全局操作确认降频（localStorage）。
 * key = 动作:范围档；极高危（delete+channel/all）永不可跳过。
 */
import type { AccountGlobalAction, AccountGlobalScope } from './accountPageShared'

export type ConfirmMuteMode = 'always' | '3days' | 'forever'
export type ConfirmLevel = 'low' | 'medium' | 'high' | 'critical'

export type ConfirmMuteEntry = {
  until?: number
  mode?: 'forever'
}

export type ConfirmMuteStore = Record<string, ConfirmMuteEntry>

export const CONFIRM_MUTE_STORAGE_KEY = 'jovemage.confirmMute'
const THREE_DAYS_MS = 3 * 24 * 60 * 60 * 1000

export function muteKey(action: AccountGlobalAction, scope: AccountGlobalScope): string {
  return `${action}:${scope}`
}

export function getConfirmLevel(action: AccountGlobalAction, scope: AccountGlobalScope): ConfirmLevel {
  if (action === 'delete' && (scope === 'channel' || scope === 'all')) return 'critical'
  if (action === 'delete') return 'high'
  if (action === 'relogin') return 'high'
  if (action === 'inspect') return 'medium'
  if (action === 'refresh' && (scope === 'channel' || scope === 'all')) return 'medium'
  return 'low'
}

/** 是否允许「3 天内不再提醒」 */
export function canMuteThreeDays(action: AccountGlobalAction, scope: AccountGlobalScope): boolean {
  return getConfirmLevel(action, scope) !== 'critical'
}

/** 是否允许「不再提醒此项」 */
export function canMuteForever(action: AccountGlobalAction, scope: AccountGlobalScope): boolean {
  const level = getConfirmLevel(action, scope)
  return level === 'low'
}

/** 极高危：需输入 DELETE */
export function requiresDeleteTypedConfirm(action: AccountGlobalAction, scope: AccountGlobalScope): boolean {
  return action === 'delete' && (scope === 'channel' || scope === 'all')
}

function readStore(): ConfirmMuteStore {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(CONFIRM_MUTE_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as ConfirmMuteStore
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
  } catch {
    return {}
  }
}

function writeStore(store: ConfirmMuteStore) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(CONFIRM_MUTE_STORAGE_KEY, JSON.stringify(store))
  } catch {
    // ignore quota / private mode
  }
}

export function isConfirmMuted(action: AccountGlobalAction, scope: AccountGlobalScope): boolean {
  if (getConfirmLevel(action, scope) === 'critical') return false
  const entry = readStore()[muteKey(action, scope)]
  if (!entry) return false
  if (entry.mode === 'forever') return canMuteForever(action, scope)
  const until = Number(entry.until || 0)
  return Number.isFinite(until) && until > Date.now() / 1000
}

export function setConfirmMute(
  action: AccountGlobalAction,
  scope: AccountGlobalScope,
  mode: ConfirmMuteMode,
) {
  if (mode === 'always') {
    clearConfirmMute(action, scope)
    return
  }
  if (mode === 'forever' && !canMuteForever(action, scope)) return
  if (mode === '3days' && !canMuteThreeDays(action, scope)) return

  const store = readStore()
  const key = muteKey(action, scope)
  if (mode === 'forever') {
    store[key] = { mode: 'forever' }
  } else {
    store[key] = { until: Math.floor((Date.now() + THREE_DAYS_MS) / 1000) }
  }
  writeStore(store)
}

export function clearConfirmMute(action?: AccountGlobalAction, scope?: AccountGlobalScope) {
  if (!action || !scope) {
    writeStore({})
    return
  }
  const store = readStore()
  delete store[muteKey(action, scope)]
  writeStore(store)
}

export function scopeLabel(scope: AccountGlobalScope): string {
  switch (scope) {
    case 'selected':
      return '已勾选'
    case 'filter':
      return '当前筛选'
    case 'channel':
      return '当前渠道'
    case 'all':
      return '全部渠道'
    default:
      return String(scope)
  }
}

export function actionTitle(action: AccountGlobalAction): string {
  switch (action) {
    case 'refresh':
      return '刷新额度'
    case 'inspect':
      return '一键巡检'
    case 'delete':
      return '清理删除'
    case 'relogin':
      return '批量重新登录'
    default:
      return '确认操作'
  }
}

export function consequenceText(action: AccountGlobalAction, options?: {
  autoRemoveInvalid?: boolean | null
  autoRemoveRateLimited?: boolean | null
  reloginCan?: number
  reloginSkip?: number
  skipReasons?: Record<string, number>
}): string {
  if (action === 'refresh') {
    return '将向 ChatGPT 上游发起批量请求；若设置开启自动移除，异常/额度耗尽账号可能被自动删除。'
  }
  if (action === 'inspect') {
    const invalid = options?.autoRemoveInvalid
    const limited = options?.autoRemoveRateLimited
    const suffix = '巡检过程中可随时停止（当前批次完成后收尾）。'
    if (invalid === false && limited === false) {
      return `仅探活标记，不会删除任何账号（设置中「自动移除异常 / 额度耗尽」均已关闭）。${suffix}`
    }
    const invalidText = invalid == null ? '以设置页为准' : (invalid ? '已开启' : '已关闭')
    const limitedText = limited == null ? '以设置页为准' : (limited ? '已开启' : '已关闭')
    return `将远程探活，并遵守设置策略：自动移除异常账号（${invalidText}）、自动移除额度耗尽账号（${limitedText}）。可在设置页修改。${suffix}`
  }
  if (action === 'delete') {
    return '删除后不可恢复，请确认渠道与数量无误。'
  }
  if (action === 'relogin') {
    const can = Math.max(0, Number(options?.reloginCan || 0))
    const skip = Math.max(0, Number(options?.reloginSkip || 0))
    const reasonParts = Object.entries(options?.skipReasons || {})
      .filter(([, count]) => Number(count) > 0)
      .map(([reason, count]) => `${reason} ${count}`)
    const reasonText = reasonParts.length ? `（${reasonParts.join('；')}）` : ''
    return `仅 AHEM 邮箱账号可重登。可重登 ${can}，跳过 ${skip}${reasonText}。`
  }
  return ''
}
