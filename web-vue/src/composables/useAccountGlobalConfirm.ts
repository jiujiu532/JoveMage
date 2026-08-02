/**
 * 账号页全局操作确认：分级 + 提醒降频 + 高危输入。
 * 单例 Promise 队列，避免并发 ask 互相覆盖。
 */
import { ref } from 'vue'
import type { AccountGlobalAction, AccountGlobalScope } from '@/views/accounts/accountPageShared'
import {
  actionTitle,
  canMuteForever,
  canMuteThreeDays,
  consequenceText,
  isConfirmMuted,
  requiresDeleteTypedConfirm,
  scopeLabel,
  setConfirmMute,
  type ConfirmMuteMode,
} from '@/views/accounts/accountConfirmMute'

export type GlobalConfirmAskOptions = {
  action: AccountGlobalAction
  scope: AccountGlobalScope
  count: number
  channelLabel: string
  /** 覆盖范围文案；默认 scopeLabel(scope) */
  scopeText?: string
  title?: string
  consequence?: string
  policyLines?: string[]
  confirmText?: string
  cancelText?: string
  danger?: boolean
  autoRemoveInvalid?: boolean | null
  autoRemoveRateLimited?: boolean | null
  reloginCan?: number
  reloginSkip?: number
  skipReasons?: Record<string, number>
  /** 为 true 时忽略 mute，强制弹窗（例如极高危之外的特殊场景） */
  force?: boolean
}

export type GlobalConfirmResult = {
  confirmed: boolean
  policyInvalid?: boolean
  policyLimited?: boolean
}

export type GlobalConfirmState = {
  open: boolean
  title: string
  channelLabel: string
  scopeText: string
  count: number
  consequence: string
  policyLines: string[]
  requireTypedConfirm: boolean
  danger: boolean
  confirmText: string
  cancelText: string
  muteOptions: Array<{ value: ConfirmMuteMode; label: string }>
  showPolicy: boolean
  policyInvalid: boolean
  policyLimited: boolean
}

type Resolver = (value: GlobalConfirmResult) => void

const state = ref<GlobalConfirmState>({
  open: false,
  title: '确认操作',
  channelLabel: '',
  scopeText: '',
  count: 0,
  consequence: '',
  policyLines: [],
  requireTypedConfirm: false,
  danger: false,
  confirmText: '确认',
  cancelText: '取消',
  muteOptions: [],
  showPolicy: false,
  policyInvalid: false,
  policyLimited: false,
})

let pendingAction: AccountGlobalAction | null = null
let pendingScope: AccountGlobalScope | null = null
let resolver: Resolver | null = null
let askQueue: Promise<unknown> = Promise.resolve()

function buildMuteOptions(action: AccountGlobalAction, scope: AccountGlobalScope, policyLimited?: boolean) {
  const options: Array<{ value: ConfirmMuteMode; label: string }> = [
    { value: 'always', label: '每次都提醒（默认）' },
  ]
  if (canMuteThreeDays(action, scope, policyLimited)) {
    options.push({ value: '3days', label: '3 天内不再提醒此项' })
  }
  if (canMuteForever(action, scope, policyLimited)) {
    options.push({ value: 'forever', label: '不再提醒此项' })
  }
  return options
}

function defaultConfirmText(action: AccountGlobalAction, danger: boolean) {
  if (action === 'delete') return '确认删除'
  if (action === 'inspect') return '开始巡检'
  if (action === 'refresh') return '开始刷新'
  if (action === 'relogin') return '确认重登'
  return danger ? '确认' : '继续'
}

export function useAccountGlobalConfirm() {
  function ask(options: GlobalConfirmAskOptions): Promise<GlobalConfirmResult> {
    const run = () => new Promise<GlobalConfirmResult>((resolve) => {
      const {
        action,
        scope,
        count,
        channelLabel,
        force = false,
      } = options

      const isInspect = action === 'inspect'
      const policyLimited = isInspect ? Boolean(options.autoRemoveRateLimited) : undefined

      if (!force && isConfirmMuted(action, scope, policyLimited)) {
        resolve({
          confirmed: true,
          policyInvalid: options.autoRemoveInvalid ?? undefined,
          policyLimited: options.autoRemoveRateLimited ?? undefined,
        })
        return
      }

      const requireTyped = requiresDeleteTypedConfirm(action, scope)
      const danger = options.danger ?? (action === 'delete')
      const consequence = options.consequence ?? consequenceText(action, {
        autoRemoveInvalid: options.autoRemoveInvalid,
        autoRemoveRateLimited: options.autoRemoveRateLimited,
        reloginCan: options.reloginCan,
        reloginSkip: options.reloginSkip,
        skipReasons: options.skipReasons,
      })

      pendingAction = action
      pendingScope = scope
      resolver = resolve
      state.value = {
        open: true,
        title: options.title || actionTitle(action),
        channelLabel,
        scopeText: options.scopeText || scopeLabel(scope),
        count: Math.max(0, Number(count) || 0),
        consequence: isInspect ? '' : consequence,
        policyLines: options.policyLines || [],
        requireTypedConfirm: requireTyped,
        danger,
        confirmText: options.confirmText || defaultConfirmText(action, danger),
        cancelText: options.cancelText || '取消',
        muteOptions: requireTyped ? [] : buildMuteOptions(action, scope, policyLimited),
        showPolicy: isInspect,
        policyInvalid: isInspect ? Boolean(options.autoRemoveInvalid) : false,
        policyLimited: isInspect ? Boolean(options.autoRemoveRateLimited) : false,
      }
    })

    const result = askQueue.then(run, run)
    askQueue = result.then(
      () => undefined,
      () => undefined,
    )
    return result
  }

  function confirm(payload?: { muteMode?: ConfirmMuteMode; policyInvalid?: boolean; policyLimited?: boolean }): GlobalConfirmResult {
    const action = pendingAction
    const scope = pendingScope
    const muteMode = payload?.muteMode || 'always'
    const policyLimited = action === 'inspect' ? payload?.policyLimited : undefined
    if (action && scope && muteMode !== 'always' && !requiresDeleteTypedConfirm(action, scope)) {
      setConfirmMute(action, scope, muteMode, policyLimited)
    }
    state.value = { ...state.value, open: false }
    const resolve = resolver
    resolver = null
    pendingAction = null
    pendingScope = null
    const result: GlobalConfirmResult = {
      confirmed: true,
      policyInvalid: payload?.policyInvalid,
      policyLimited: payload?.policyLimited,
    }
    resolve?.(result)
    return result
  }

  function cancel() {
    state.value = { ...state.value, open: false }
    const resolve = resolver
    resolver = null
    pendingAction = null
    pendingScope = null
    resolve?.({ confirmed: false })
  }

  return {
    state,
    ask,
    confirm,
    cancel,
  }
}
