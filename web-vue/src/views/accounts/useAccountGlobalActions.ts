import { computed, ref, type Ref } from 'vue'
import {
  accountsApi,
  type AccountInspectResult,
  type AccountTaskTier,
} from '@/api/accounts'
import { useSettingsStore } from '@/stores/settings'
import { useToast } from '@/composables/useToast'
import { useAccountGlobalConfirm } from '@/composables/useAccountGlobalConfirm'
import {
  normalizeErrorMessage,
  type AccountGlobalAction,
  type AccountGlobalScope,
  type BulkProgressKind,
  type SetErrorFn,
} from './accountPageShared'
import { resolveSelectedTier } from './accountTaskLabels'
import type { UseAccountTaskProgressReturn } from './useAccountTaskProgress'

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
  /** 兼容旧签名；统一进度由 taskProgress 接管 */
  openBulkProgress?: (title: string, total: number, kind: BulkProgressKind) => void
  refreshProgress?: Ref<unknown>
  batchBusy?: Ref<boolean>
  batchActionLabel?: Ref<string>
  bulkStopRequested?: Ref<boolean>
  refreshAccountsWithProgress: (
    accountIds: string[],
    title: string,
    options?: { skipConfirm?: boolean; tier?: AccountTaskTier },
  ) => Promise<void>
  exportAccounts: (scope: 'selected' | 'all' | 'auto') => Promise<void>
  taskProgress: UseAccountTaskProgressReturn
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
    refreshAccountsWithProgress,
    exportAccounts,
    taskProgress,
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
  const pendingInspectScopeText = ref('')
  /** 兼容旧字段：停止态由 taskProgress 推导 */
  const inspectStopRequested = computed(() => {
    const heavy = taskProgress.heavyTask.value
    return Boolean(
      heavy
      && String(heavy.type) === 'account_inspect'
      && heavy.cancelRequested,
    )
  })

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

  /** 按范围拿账号 token（selected / filter / channel / all 统一走 ids 接口） */
  async function resolveTokens(scope: AccountGlobalScope): Promise<string[]> {
    if (scope === 'selected') return selectedIds.value.filter(Boolean)
    const params = scope === 'all'
      ? { keyword: '', status: 'all' as const, group_id: 'all', source_type: 'all' }
      : scope === 'channel'
        ? { source_type: sourceFilter.value || 'all' }
        : filterParams(true)
    const { tokens } = await accountsApi.fetchAccountIds(params)
    return tokens
  }

  function scopeTier(scope: AccountGlobalScope, count: number): AccountTaskTier {
    // 顶栏范围任务一律 heavy；仅 selected 按数量判定
    if (scope === 'selected') return resolveSelectedTier(count)
    return 'heavy'
  }

  // ── 刷新额度 ─────────────────────────────────────────────────────
  async function runGlobalRefresh(scope: AccountGlobalScope) {
    const count = scopeCount(scope)
    if (!count) {
      toast.warning('没有可刷新的账号')
      return
    }
    const res = await confirm.ask({
      action: 'refresh',
      scope,
      count,
      channelLabel: channelLabel.value,
    })
    if (!res.confirmed) return
    try {
      const tokens = await resolveTokens(scope)
      if (!tokens.length) {
        toast.warning('没有可刷新的账号')
        return
      }
      await refreshAccountsWithProgress(
        tokens,
        `刷新${scopeLabelText(scope)}账号信息和额度`,
        { skipConfirm: true, tier: scopeTier(scope, tokens.length) },
      )
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
    const res = await confirm.ask({
      action: 'delete',
      scope,
      count,
      channelLabel: channelLabel.value,
    })
    if (!res.confirmed) return

    let tokens: string[]
    try {
      tokens = await resolveTokens(scope)
    } catch (error) {
      setError('获取账号列表失败', error)
      return
    }
    if (!tokens.length) {
      toast.warning('没有可删除的账号')
      return
    }

    const title = `删除${scopeLabelText(scope)}账号`
    const tier = scopeTier(scope, tokens.length)
    await taskProgress.submitAndTrack({
      title,
      tier,
      type: 'account_delete',
      submit: async () => {
        try {
          const started = await accountsApi.submitDeleteTask(tokens, tier)
          return {
            task_id: started.task_id,
            total: started.total ?? tokens.length,
            type: 'account_delete',
          }
        } catch (error) {
          // 后端未就绪：同步分批删除（无统一任务条）
          if (/404|not found|405/i.test(normalizeErrorMessage(error))) {
            let success = 0
            const errors: string[] = []
            const batchSize = 20
            for (let index = 0; index < tokens.length; index += batchSize) {
              const batch = tokens.slice(index, index + batchSize)
              try {
                const result = await accountsApi.bulkDelete(batch)
                success += Number(result?.success_count ?? (batch.length - (result?.errors?.length || 0)))
                if (Array.isArray(result?.errors)) errors.push(...result.errors.filter(Boolean))
              } catch (batchError) {
                errors.push(normalizeErrorMessage(batchError))
              }
            }
            await loadData({ silentErrorToast: true })
            clearSelection()
            if (errors.length) {
              toast.warning(`删除完成，成功 ${success} 个，失败 ${errors.length} 个`)
            } else {
              toast.success(`已删除 ${success} 个账号`)
            }
            return { task_id: '', total: tokens.length, type: 'account_delete' }
          }
          throw error
        }
      },
    })
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

    const settingsStore = useSettingsStore()
    if (!settingsStore.settings) {
      try {
        await settingsStore.loadSettings()
      } catch {
        // 读取失败时用 null 兜底
      }
    }
    const autoInvalid = settingsStore.settings ? Boolean(settingsStore.settings.auto_remove_invalid_accounts) : null
    const autoLimited = settingsStore.settings ? Boolean(settingsStore.settings.auto_remove_rate_limited_accounts) : null

    const res = await confirm.ask({
      action: 'inspect',
      scope,
      count,
      channelLabel: channelLabel.value,
      autoRemoveInvalid: autoInvalid,
      autoRemoveRateLimited: autoLimited,
    })
    if (!res.confirmed) return

    if (res.policyInvalid != null || res.policyLimited != null) {
      try {
        await settingsStore.updateSettingsPatch({
          auto_remove_invalid_accounts: Boolean(res.policyInvalid),
          auto_remove_rate_limited_accounts: Boolean(res.policyLimited),
        })
      } catch (error) {
        setError('保存巡检策略失败', error)
        return
      }
    }

    const title = `巡检${scopeLabelText(scope)}账号`
    const filter = filterParams(true)
    const params = scope === 'filter'
      ? filter
      : scope === 'channel'
        ? { keyword: '', status: 'all' as const, group_id: 'all', source_type: sourceFilter.value || 'all' }
        : { keyword: '', status: 'all' as const, group_id: 'all', source_type: 'all' }

    const ok = await taskProgress.submitAndTrack({
      title,
      tier: 'heavy',
      type: 'account_inspect',
      submit: async () => {
        const started = await accountsApi.inspectAccounts({
          scope,
          keyword: params.keyword || '',
          status: params.status || 'all',
          group_id: params.group_id || 'all',
          source_type: params.source_type || 'all',
          tier: 'heavy',
        })
        return {
          task_id: started.task_id,
          total: started.total ?? count,
          type: 'account_inspect',
        }
      },
    })

    if (ok) {
      pendingInspectScopeText.value = scopeLabelText(scope)
    }
  }

  /** 从当前进度任务打开巡检摘要（终态后） */
  function openInspectSummaryFromTask() {
    const task = taskProgress.heavyTask.value
    if (!task || String(task.type) !== 'account_inspect') return
    if (task.uiStatus !== 'completed' && task.uiStatus !== 'stopped') return
    const result = (task.result || {}) as AccountInspectResult
    inspectSummary.value = {
      ...result,
      scopeText: pendingInspectScopeText.value || '巡检',
    }
    showInspectSummary.value = true
  }

  /** 请求停止巡检：走统一 cancel */
  async function requestStopInspect() {
    const heavy = taskProgress.heavyTask.value
    if (!heavy || String(heavy.type) !== 'account_inspect') return
    await taskProgress.requestStop(heavy.tier)
  }

  function closeInspectSummary() {
    showInspectSummary.value = false
  }

  // ── 批量重置（selected）─────────────────────────────────────────
  async function runResetSelected() {
    const ids = selectedIds.value.filter(Boolean)
    if (!ids.length) {
      toast.warning('请先选择账号')
      return
    }
    const title = '批量重置账号状态'
    const tier = resolveSelectedTier(ids.length)
    await taskProgress.submitAndTrack({
      title,
      tier,
      type: 'account_reset',
      submit: async () => {
        try {
          const started = await accountsApi.submitStatusTask(ids, 'reset', tier)
          return {
            task_id: started.task_id,
            total: started.total ?? ids.length,
            type: 'account_reset',
          }
        } catch (error) {
          if (/404|not found|405/i.test(normalizeErrorMessage(error))) {
            let success = 0
            let failed = 0
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
            return { task_id: '', total: ids.length, type: 'account_reset' }
          }
          throw error
        }
      },
    })
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
    const res = await confirm.ask({
      action: 'relogin',
      scope: 'selected',
      count: precheck.can,
      channelLabel: channelLabel.value,
      reloginCan: precheck.can,
      reloginSkip: precheck.skip,
      skipReasons: precheck.skip_reasons,
    })
    if (!res.confirmed) return

    const title = '批量重新登录账号'
    const canTokens = precheck.can_tokens?.length ? precheck.can_tokens : ids
    const tier = resolveSelectedTier(canTokens.length)
    await taskProgress.submitAndTrack({
      title,
      tier,
      type: 'account_relogin',
      submit: async () => {
        const started = await accountsApi.reloginBatch(canTokens, tier)
        return {
          task_id: started.task_id,
          total: started.total ?? canTokens.length,
          type: 'account_relogin',
        }
      },
    })
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
    inspectStopRequested,
    closeInspectSummary,
    openInspectSummaryFromTask,
    runGlobalRefresh,
    runGlobalDelete,
    runInspect,
    requestStopInspect,
    runReloginSelected,
    runResetSelected,
    runExport,
  }
}

export type { AccountGlobalAction }
