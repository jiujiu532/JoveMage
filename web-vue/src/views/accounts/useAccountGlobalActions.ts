import { computed, ref, type Ref } from 'vue'
import { accountsApi } from '@/api/accounts'
import type { AccountInspectResult, AccountRefreshProgress } from '@/api/accounts'
import { settingsApi } from '@/api/settings'
import { useToast } from '@/composables/useToast'
import { useAccountGlobalConfirm } from '@/composables/useAccountGlobalConfirm'
import {
  normalizeErrorMessage,
  REFRESH_BATCH_SIZE,
  type AccountGlobalAction,
  type AccountGlobalScope,
  type SetErrorFn,
} from './accountPageShared'

export type UseAccountGlobalActionsOptions = {
  setError: SetErrorFn
  loadData: (options?: { silentErrorToast?: boolean }) => Promise<void>
  keyword: Ref<string>
  statusFilter: Ref<string>
  groupFilter: Ref<string>
  sourceFilter: Ref<string>
  accountListTotal: Ref<number>
  accountAllTotal: Ref<number>
  selectedIds: Ref<string[]>
  clearSelection: () => void
  openBulkProgress: (title: string, total: number, kind: 'refresh' | 'mutation' | 'inspect') => void
  refreshProgress: Ref<AccountRefreshProgress | null>
  batchBusy: Ref<boolean>
  batchActionLabel: Ref<string>
  bulkStopRequested: Ref<boolean>
  refreshAccountsWithProgress: (accountIds: string[], title: string) => Promise<void>
  refreshAllAccounts: () => Promise<void>
  exportAccounts: (scope: 'selected' | 'all' | 'auto') => Promise<void>
}

/** 巡检结果摘要弹层状态 */
export type InspectSummary = AccountInspectResult & { scopeText: string }

/**
 * 顶栏全局批量操作（一键巡检 / 刷新额度 / 清理 / 导出四档）。
 * 与底部批量条(selected)解耦：按 filter/channel/all 拉 ids 或走服务端任务。
 */
export function useAccountGlobalActions(options: UseAccountGlobalActionsOptions) {
  const {
    setError,
    loadData,
    keyword,
    statusFilter,
    groupFilter,
    sourceFilter,
    accountListTotal,
    accountAllTotal,
    selectedIds,
    clearSelection,
    openBulkProgress,
    refreshProgress,
    batchBusy,
    batchActionLabel,
    bulkStopRequested,
    refreshAccountsWithProgress,
    refreshAllAccounts,
    exportAccounts,
  } = options
  const toast = useToast()
  const confirm = useAccountGlobalConfirm()

  const isFireflyChannel = computed(() => sourceFilter.value === 'firefly')
  const channelLabel = computed(() => (
    sourceFilter.value === 'firefly'
      ? 'Firefly'
      : sourceFilter.value === 'chatgpt'
        ? 'ChatGPT'
        : '全部渠道'
  ))

  const inspectSummary = ref<InspectSummary | null>(null)
  const showInspectSummary = ref(false)

  function scopeCount(scope: AccountGlobalScope): number {
    if (scope === 'selected') return selectedIds.value.length
    if (scope === 'channel' || scope === 'all') return accountAllTotal.value || accountListTotal.value
    return accountListTotal.value
  }

  function filterParams(includeSource = true) {
    return {
      keyword: keyword.value || undefined,
      status: (statusFilter.value || 'all') as 'all' | 'normal' | 'limited' | 'abnormal' | 'disabled',
      group_id: groupFilter.value || 'all',
      source_type: includeSource ? (sourceFilter.value || 'all') : 'all',
    }
  }

  /** 按范围拿账号 token；all 返回 null 表示交给全量接口 */
  async function resolveTokens(scope: AccountGlobalScope): Promise<string[] | null> {
    if (scope === 'selected') return selectedIds.value.filter(Boolean)
    if (scope === 'all') return null
    const params = scope === 'channel' ? { source_type: sourceFilter.value || 'all' } : filterParams(true)
    const { tokens } = await accountsApi.fetchAccountIds(params)
    return tokens
  }

  // ── 刷新额度 ─────────────────────────────────────────────────────
  async function runGlobalRefresh(scope: AccountGlobalScope) {
    const count = scopeCount(scope)
    if (!count) {
      toast.warning('没有可刷新的账号')
      return
    }
    const ok = await confirm.ask({
      action: 'refresh',
      scope,
      count,
      channelLabel: channelLabel.value,
    })
    if (!ok) return
    if (scope === 'all') {
      await refreshAllAccounts()
      return
    }
    try {
      const tokens = await resolveTokens(scope)
      if (!tokens || !tokens.length) {
        toast.warning('没有可刷新的账号')
        return
      }
      await refreshAccountsWithProgress(tokens, `刷新${scopeLabelText(scope)}账号信息和额度`)
    } catch (error) {
      setError('刷新失败', error)
    }
  }

  // ── 清理删除 ─────────────────────────────────────────────────────
  async function runGlobalDelete(scope: AccountGlobalScope) {
    const count = scopeCount(scope)
    if (!count) {
      toast.warning('没有可删除的账号')
      return
    }
    const ok = await confirm.ask({
      action: 'delete',
      scope,
      count,
      channelLabel: channelLabel.value,
    })
    if (!ok) return

    let tokens: string[] | null
    try {
      tokens = await resolveTokens(scope)
    } catch (error) {
      setError('获取账号列表失败', error)
      return
    }
    if (!tokens || !tokens.length) {
      toast.warning('没有可删除的账号')
      return
    }

    const title = `删除${scopeLabelText(scope)}账号`
    openBulkProgress(title, tokens.length, 'mutation')
    batchBusy.value = true
    batchActionLabel.value = title
    let success = 0
    const errors: string[] = []
    try {
      for (let index = 0; index < tokens.length; index += REFRESH_BATCH_SIZE) {
        if (bulkStopRequested.value) break
        const batch = tokens.slice(index, index + REFRESH_BATCH_SIZE)
        try {
          const result = await accountsApi.bulkDelete(batch)
          success += Number(result?.success_count ?? (batch.length - (result?.errors?.length || 0)))
          if (Array.isArray(result?.errors)) errors.push(...result.errors.filter(Boolean))
        } catch (error) {
          errors.push(normalizeErrorMessage(error))
        } finally {
          refreshProgress.value = {
            ...(refreshProgress.value || { total: tokens.length }),
            total: tokens.length,
            processed: Math.min(tokens.length, index + batch.length),
            done: index + batch.length >= tokens.length,
            total_quota: 0,
          }
        }
      }
      refreshProgress.value = {
        ...(refreshProgress.value || { total: tokens.length }),
        total: tokens.length,
        processed: tokens.length,
        done: true,
        total_quota: 0,
      }
      await loadData({ silentErrorToast: true })
      clearSelection()
      if (errors.length) {
        toast.warning(`删除完成，成功 ${success} 个，失败 ${errors.length} 个`)
      } else {
        toast.success(`已删除 ${success} 个账号`)
      }
    } finally {
      batchBusy.value = false
      batchActionLabel.value = ''
    }
  }

  // ── 一键巡检 ─────────────────────────────────────────────────────
  async function runInspect(scope: 'filter' | 'channel' | 'all') {
    if (isFireflyChannel.value) {
      toast.warning('Firefly 渠道巡检二期开放')
      return
    }
    const count = scopeCount(scope)
    if (!count) {
      toast.warning('没有可巡检的账号')
      return
    }

    // 读策略开关用于确认框展示（只读，改开关去设置）
    let autoInvalid: boolean | null = null
    let autoLimited: boolean | null = null
    try {
      const settings = await settingsApi.get()
      autoInvalid = Boolean(settings.auto_remove_invalid_accounts)
      autoLimited = Boolean(settings.auto_remove_rate_limited_accounts)
    } catch {
      autoInvalid = null
      autoLimited = null
    }

    const ok = await confirm.ask({
      action: 'inspect',
      scope,
      count,
      channelLabel: channelLabel.value,
      autoRemoveInvalid: autoInvalid,
      autoRemoveRateLimited: autoLimited,
    })
    if (!ok) return

    const title = `巡检${scopeLabelText(scope)}账号`
    openBulkProgress(title, count, 'inspect')
    batchBusy.value = true
    batchActionLabel.value = title
    try {
      const filter = filterParams(true)
      const params = scope === 'filter'
        ? filter
        : scope === 'channel'
          ? { keyword: '', status: 'all' as const, group_id: 'all', source_type: sourceFilter.value || 'all' }
          : { keyword: '', status: 'all' as const, group_id: 'all', source_type: 'all' }
      const started = await accountsApi.inspectAccounts({
        scope,
        keyword: params.keyword || '',
        status: params.status || 'all',
        group_id: params.group_id || 'all',
        source_type: params.source_type || 'all',
      })
      let task = await accountsApi.fetchTaskStatus(started.task_id)
      while (task.status === 'running') {
        refreshProgress.value = {
          total: Number(task.total || count),
          processed: Number(task.progress || 0),
          done: false,
          total_quota: 0,
        }
        await new Promise((resolve) => window.setTimeout(resolve, 900))
        task = await accountsApi.fetchTaskStatus(started.task_id)
      }
      const result = (task.result || {}) as AccountInspectResult
      refreshProgress.value = {
        total: Number(result.total ?? count),
        processed: Number(result.processed ?? result.total ?? count),
        done: true,
        total_quota: 0,
      }
      await loadData({ silentErrorToast: true })
      inspectSummary.value = { ...result, scopeText: scopeLabelText(scope) }
      showInspectSummary.value = true
      if (task.status === 'failed') {
        setError('巡检失败', (task.error as string) || '巡检任务失败')
      }
    } catch (error) {
      refreshProgress.value = {
        ...(refreshProgress.value || { total: count, processed: 0 }),
        total: count,
        done: true,
        error: normalizeErrorMessage(error),
        total_quota: 0,
      }
      setError('巡检失败', error)
      await loadData({ silentErrorToast: true })
    } finally {
      batchBusy.value = false
      batchActionLabel.value = ''
    }
  }

  function closeInspectSummary() {
    showInspectSummary.value = false
  }

  // ── 批量重置（selected，本地状态复位，不探活）─────────────────────
  async function runResetSelected() {
    const ids = selectedIds.value.filter(Boolean)
    if (!ids.length) {
      toast.warning('请先选择账号')
      return
    }
    const title = '批量重置账号状态'
    batchBusy.value = true
    batchActionLabel.value = title
    let success = 0
    let failed = 0
    try {
      for (const id of ids) {
        try {
          await accountsApi.resetAccountState(id)
          success += 1
        } catch {
          failed += 1
        }
      }
      await loadData({ silentErrorToast: true })
      clearSelection()
      if (failed > 0) {
        toast.warning(`重置完成，成功 ${success} 个，失败 ${failed} 个`)
      } else {
        toast.success(`已重置 ${success} 个账号状态`)
      }
    } finally {
      batchBusy.value = false
      batchActionLabel.value = ''
    }
  }

  // ── 批量重登（selected，带预检）──────────────────────────────────
  async function runReloginSelected(): Promise<void> {
    const ids = selectedIds.value.filter(Boolean)
    if (!ids.length) {
      toast.warning('请先选择账号')
      return
    }
    if (isFireflyChannel.value) {
      toast.warning('Firefly 账号不支持重登')
      return
    }
    let precheck
    try {
      precheck = await accountsApi.reloginPrecheck(ids)
    } catch (error) {
      setError('重登预检失败', error)
      return
    }
    if (!precheck.can) {
      const reasons = Object.entries(precheck.skip_reasons)
        .filter(([, count]) => count > 0)
        .map(([reason, count]) => `${reason} ${count}`)
        .join('；')
      toast.warning(`没有可重登的账号${reasons ? `（${reasons}）` : ''}`)
      return
    }
    const ok = await confirm.ask({
      action: 'relogin',
      scope: 'selected',
      count: precheck.can,
      channelLabel: channelLabel.value,
      reloginCan: precheck.can,
      reloginSkip: precheck.skip,
      skipReasons: precheck.skip_reasons,
    })
    if (!ok) return

    const title = '批量重新登录账号'
    batchBusy.value = true
    batchActionLabel.value = title
    try {
      const canTokens = precheck.can_tokens?.length ? precheck.can_tokens : ids
      const started = await accountsApi.reloginBatch(canTokens)
      let task = await accountsApi.fetchTaskStatus(started.task_id)
      while (task.status === 'running') {
        refreshProgress.value = {
          total: Number(task.total || started.total || canTokens.length),
          processed: Number(task.progress || 0),
          done: false,
          total_quota: 0,
        }
        await new Promise((resolve) => window.setTimeout(resolve, 900))
        task = await accountsApi.fetchTaskStatus(started.task_id)
      }
      const result = (task.result || {}) as { success?: number; errors?: unknown[] }
      const success = Number(result.success || 0)
      const failed = Array.isArray(result.errors) ? result.errors.length : 0
      await loadData({ silentErrorToast: true })
      clearSelection()
      if (failed > 0) {
        toast.warning(`重登完成，成功 ${success} 个，失败 ${failed} 个`)
      } else {
        toast.success(`重登完成，共 ${success} 个`)
      }
    } catch (error) {
      setError('批量重新登录失败', error)
    } finally {
      batchBusy.value = false
      batchActionLabel.value = ''
    }
  }

  // ── 导出四档 ─────────────────────────────────────────────────────
  async function runExport(scope: AccountGlobalScope) {
    if (scope === 'selected') {
      await exportAccounts('selected')
      return
    }
    if (scope === 'all') {
      await exportAccounts('all')
      return
    }
    // filter / channel：拉 tokens 后用 selected 路径导出
    const count = scopeCount(scope)
    if (!count) {
      toast.warning('暂无可导出的账号')
      return
    }
    try {
      const tokens = await resolveTokens(scope)
      if (!tokens || !tokens.length) {
        toast.warning('暂无可导出的账号')
        return
      }
      const { saveBlob } = await import('@/lib/downloads')
      const { createExportFilename } = await import('./accountPageShared')
      const blob = await accountsApi.exportAccounts(tokens, 'json')
      saveBlob(blob, createExportFilename('json'))
      toast.success(`已导出 ${tokens.length} 个账号认证`)
    } catch (error) {
      setError('导出失败', error)
    }
  }

  function scopeLabelText(scope: AccountGlobalScope): string {
    switch (scope) {
      case 'selected': return '已勾选'
      case 'filter': return '当前筛选'
      case 'channel': return '当前渠道'
      case 'all': return '全部渠道'
      default: return String(scope)
    }
  }

  return {
    confirm,
    isFireflyChannel,
    channelLabel,
    scopeCount,
    inspectSummary,
    showInspectSummary,
    closeInspectSummary,
    runGlobalRefresh,
    runGlobalDelete,
    runInspect,
    runReloginSelected,
    runResetSelected,
    runExport,
  }
}

export type { AccountGlobalAction }
