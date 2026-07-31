import { computed, ref, type Ref } from 'vue'
import { accountsApi } from '@/api/accounts'
import type { Account, AccountRefreshProgress } from '@/api/accounts'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useToast } from '@/composables/useToast'
import {
  normalizeErrorMessage,
  REFRESH_BATCH_SIZE,
  type BulkAction,
  type BulkProgressKind,
  type SetErrorFn,
} from './accountPageShared'

export type UseAccountBulkActionsOptions = {
  setError: SetErrorFn
  loadData: (options?: { silentErrorToast?: boolean }) => Promise<void>
  accounts: Ref<Account[]>
  accountListTotal: Ref<number>
  accountAllTotal: Ref<number>
  selectedIds: Ref<string[]>
  clearSelection: () => void
}

/**
 * 批量操作：刷新/启用禁用/删除/重登 + 进度条状态。
 */
export function useAccountBulkActions(options: UseAccountBulkActionsOptions) {
  const {
    setError,
    loadData,
    accounts,
    accountListTotal,
    accountAllTotal,
    selectedIds,
    clearSelection,
  } = options
  const toast = useToast()
  const confirmDialog = useConfirmDialog()

  const batchBusy = ref(false)
  const batchActionLabel = ref('')
  const showRefreshProgress = ref(false)
  const refreshProgressTitle = ref('')
  const refreshProgress = ref<AccountRefreshProgress | null>(null)
  const refreshProgressKind = ref<BulkProgressKind>('refresh')
  const bulkStopRequested = ref(false)

  const refreshProgressPercent = computed(() => {
    const progress = refreshProgress.value
    const total = Math.max(0, Number(progress?.total || 0))
    if (total <= 0) return 0
    return Math.min(100, Math.round((Math.max(0, Number(progress?.processed || 0)) / total) * 100))
  })

  const refreshProgressMetricLabel = computed(() => (
    refreshProgressKind.value === 'refresh' ? '图片总额度' : '处理账号'
  ))

  const refreshProgressMetricValue = computed(() => {
    const progress = refreshProgress.value
    if (refreshProgressKind.value === 'refresh') return progress?.total_quota ?? '-'
    return `${progress?.processed || 0} 个`
  })

  const refreshProgressStatusText = computed(() => {
    const progress = refreshProgress.value
    if (progress?.error) return '失败'
    if (progress?.done) return bulkStopRequested.value ? '已停止' : '已完成'
    if (bulkStopRequested.value) return '停止中'
    if (refreshProgressKind.value === 'refresh') return '刷新中'
    return '处理中'
  })

  const canStopRefreshProgress = computed(() => (
    showRefreshProgress.value && batchBusy.value && !refreshProgress.value?.done
  ))

  function openBulkProgress(title: string, total: number, kind: BulkProgressKind) {
    bulkStopRequested.value = false
    showRefreshProgress.value = true
    refreshProgressTitle.value = title
    refreshProgressKind.value = kind
    refreshProgress.value = {
      total,
      processed: 0,
      done: false,
      error: null,
      total_quota: kind === 'refresh' ? 0 : undefined,
      result: null,
    }
  }

  function requestStopRefreshProgress() {
    if (!canStopRefreshProgress.value) return
    bulkStopRequested.value = true
    toast.info('已请求停止，当前批次完成后会停止后续批次')
  }

  function closeRefreshProgress() {
    if (!refreshProgress.value?.done && batchBusy.value) return
    showRefreshProgress.value = false
  }

  async function refreshAccountsWithProgress(accountIds: string[], title: string) {
    const targetIds = Array.from(new Set(accountIds.filter(Boolean)))
    if (!targetIds.length) {
      toast.warning('没有可刷新的账号')
      return
    }

    const confirmed = await confirmDialog.ask({
      title,
      message: `即将按每批 ${REFRESH_BATCH_SIZE} 个刷新 ${targetIds.length} 个账号的信息和额度，是否继续？`,
      confirmText: '开始刷新',
      cancelText: '取消',
    })
    if (!confirmed) return

    openBulkProgress(title, targetIds.length, 'refresh')
    batchBusy.value = true
    batchActionLabel.value = title
    let processedOffset = 0
    let failedCount = 0
    const errors: string[] = []

    try {
      for (let index = 0; index < targetIds.length; index += REFRESH_BATCH_SIZE) {
        if (bulkStopRequested.value) break
        const batch = targetIds.slice(index, index + REFRESH_BATCH_SIZE)
        const result = await accountsApi.refreshAccountsWithProgress(batch, (progress) => {
          refreshProgress.value = {
            ...progress,
            total: targetIds.length,
            processed: Math.min(targetIds.length, processedOffset + Number(progress.processed || 0)),
            done: false,
          }
        })

        const batchProgress = result.progress
        const batchErrors = Array.isArray(batchProgress?.result?.errors)
          ? batchProgress.result.errors
          : []
        failedCount += batchErrors.length
        errors.push(...batchErrors.map((entry) => (
          typeof entry === 'string'
            ? entry
            : [entry.token, entry.error].filter(Boolean).join(': ')
        )).filter(Boolean))
        processedOffset += batch.length
        refreshProgress.value = {
          ...(batchProgress || refreshProgress.value || {}),
          total: targetIds.length,
          processed: Math.min(targetIds.length, processedOffset),
          done: processedOffset >= targetIds.length,
        }
        if (bulkStopRequested.value) break
      }

      await loadData({ silentErrorToast: true })
      const stopped = bulkStopRequested.value && processedOffset < targetIds.length
      refreshProgress.value = {
        ...(refreshProgress.value || { total: targetIds.length, processed: processedOffset }),
        total: targetIds.length,
        processed: stopped ? Math.min(targetIds.length, processedOffset) : targetIds.length,
        done: true,
      }
      if (stopped) {
        toast.warning(`${title}已停止，已处理 ${processedOffset}/${targetIds.length} 个账号`)
      } else if (failedCount > 0) {
        toast.warning(`${title}完成，失败 ${failedCount} 个${errors[0] ? `：${errors[0]}` : ''}`)
      } else {
        toast.success(`${title}完成，共刷新 ${targetIds.length} 个账号`)
      }
    } catch (error) {
      refreshProgress.value = {
        ...(refreshProgress.value || { total: targetIds.length, processed: processedOffset }),
        total: targetIds.length,
        processed: Math.min(targetIds.length, processedOffset),
        done: true,
        error: normalizeErrorMessage(error),
      }
      setError(`${title}失败`, error)
      await loadData({ silentErrorToast: true })
    } finally {
      batchBusy.value = false
      batchActionLabel.value = ''
    }
  }

  async function refreshAllAccountsServerPageSafe() {
    const title = '刷新所有账号信息和额度'
    const totalHint = accountAllTotal.value || accountListTotal.value || accounts.value.length
    if (!totalHint) {
      toast.warning('没有可刷新的账号')
      return
    }

    const confirmed = await confirmDialog.ask({
      title,
      message: `即将刷新全部 ${totalHint} 个账号的信息和额度，可能触发大量外部 ChatGPT 请求。是否继续？`,
      confirmText: '开始刷新',
      cancelText: '取消',
    })
    if (!confirmed) return

    openBulkProgress(title, totalHint, 'refresh')
    batchBusy.value = true
    batchActionLabel.value = title
    try {
      const result = await accountsApi.refreshAllAccountsWithProgress((progress) => {
        refreshProgress.value = {
          ...progress,
          total: Number(progress.total || totalHint),
          processed: Number(progress.processed || 0),
          done: false,
        }
      })
      const progress = result.progress
      const errors = Array.isArray(progress?.result?.errors) ? progress.result.errors : []
      refreshProgress.value = {
        ...(progress || refreshProgress.value || { total: totalHint }),
        total: Number(progress?.total || totalHint),
        processed: Number(progress?.processed || progress?.total || totalHint),
        done: true,
      }
      await loadData({ silentErrorToast: true })
      if (errors.length > 0) {
        toast.warning(`${title}完成，失败 ${errors.length} 个`)
      } else {
        toast.success(`${title}完成`)
      }
    } catch (error) {
      refreshProgress.value = {
        ...(refreshProgress.value || { total: totalHint, processed: 0 }),
        done: true,
        error: normalizeErrorMessage(error),
      }
      setError(`${title}失败`, error)
      await loadData({ silentErrorToast: true })
    } finally {
      batchBusy.value = false
      batchActionLabel.value = ''
    }
  }

  async function refreshAllAccounts() {
    await refreshAllAccountsServerPageSafe()
  }

  async function refreshSelectedAccounts() {
    await refreshAccountsWithProgress(selectedIds.value, '刷新选中账号信息和额度')
  }

  async function runBulkMutationWithProgress(
    title: string,
    targetIds: string[],
    mutateAccounts: (accountIds: string[]) => Promise<{ success_count?: number; updated?: number; removed?: number; errors?: string[] }>,
  ) {
    openBulkProgress(title, targetIds.length, 'mutation')
    batchBusy.value = true
    batchActionLabel.value = title
    let successCount = 0
    const errors: string[] = []
    const processedIds: string[] = []

    try {
      for (let index = 0; index < targetIds.length; index += REFRESH_BATCH_SIZE) {
        if (bulkStopRequested.value) break
        const batch = targetIds.slice(index, index + REFRESH_BATCH_SIZE)
        try {
          const result = await mutateAccounts(batch)
          const batchErrors = Array.isArray(result?.errors) ? result.errors.filter(Boolean) : []
          const batchSuccess = Number(result?.success_count ?? result?.updated ?? result?.removed ?? (batch.length - batchErrors.length))
          successCount += Math.max(0, Math.min(batch.length, batchSuccess || 0))
          errors.push(...batchErrors)
        } catch (error) {
          errors.push(`${batch[0]} 等 ${batch.length} 个账号：${normalizeErrorMessage(error)}`)
        } finally {
          processedIds.push(...batch)
          const processed = Math.min(targetIds.length, processedIds.length)
          refreshProgress.value = {
            ...(refreshProgress.value || { total: targetIds.length }),
            total: targetIds.length,
            processed,
            done: processed >= targetIds.length,
            total_quota: 0,
          }
        }
      }

      const processed = Math.min(targetIds.length, processedIds.length)
      const stopped = bulkStopRequested.value && processed < targetIds.length
      refreshProgress.value = {
        ...(refreshProgress.value || { total: targetIds.length, processed }),
        total: targetIds.length,
        processed,
        done: true,
        total_quota: 0,
      }
      return { success_count: successCount, errors, stopped, processed, processed_ids: processedIds }
    } finally {
      batchBusy.value = false
      batchActionLabel.value = ''
    }
  }

  async function runBulkAction(
    action: BulkAction,
    ids?: string[]
  ) {
    const targetIds = (ids || selectedIds.value).filter(Boolean)
    if (!targetIds.length) {
      toast.warning('请先选择账号')
      return
    }

    if (action === 'refresh') {
      await refreshAccountsWithProgress(targetIds, '批量刷新账号信息和额度')
      return
    }

    const actionMeta = {
      refresh: { title: '批量刷新账号信息', confirmText: '确认刷新', successText: '批量刷新完成' },
      relogin: { title: '批量重新登录账号', confirmText: '确认重登', successText: '批量重新登录完成' },
      reset: { title: '批量重置账号状态', confirmText: '确认重置', successText: '批量重置完成' },
      enable: { title: '批量启用账号', confirmText: '确认启用', successText: '批量启用完成' },
      disable: { title: '批量禁用账号', confirmText: '确认禁用', successText: '批量禁用完成' },
      delete: { title: '批量删除账号', confirmText: '确认删除', successText: '批量删除完成' },
    }[action]

    const confirmed = await confirmDialog.ask({
      title: actionMeta.title,
      message: `确认对选中的 ${targetIds.length} 个账号执行该操作吗？`,
      confirmText: actionMeta.confirmText,
      cancelText: '取消',
    })
    if (!confirmed) return

    try {
      let res: { success_count: number; errors: string[]; stopped?: boolean; processed?: number; processed_ids?: string[] }
      if (action === 'enable') {
        res = await runBulkMutationWithProgress(actionMeta.title, targetIds, accountsApi.bulkEnable)
      } else if (action === 'disable') {
        res = await runBulkMutationWithProgress(actionMeta.title, targetIds, accountsApi.bulkDisable)
      } else if (action === 'delete') {
        res = await runBulkMutationWithProgress(actionMeta.title, targetIds, accountsApi.bulkDelete)
      } else if (action === 'relogin') {
        batchBusy.value = true
        batchActionLabel.value = actionMeta.title
        const started = await accountsApi.reloginBatch(targetIds)
        let task = await accountsApi.fetchTaskStatus(started.task_id)
        while (task.status === 'running') {
          refreshProgress.value = {
            total: Number(task.total || started.total || targetIds.length),
            processed: Number(task.progress || 0),
            done: false,
            total_quota: 0,
          }
          await new Promise(resolve => window.setTimeout(resolve, 900))
          task = await accountsApi.fetchTaskStatus(started.task_id)
        }
        const result = task.result || {}
        res = {
          success_count: Number(result.success || 0),
          errors: Array.isArray(result.errors) ? result.errors.map(item => JSON.stringify(item)) : [],
        }
      } else {
        res = await runBulkMutationWithProgress(actionMeta.title, targetIds, accountsApi.bulkEnable)
      }

      const errors = Array.isArray(res.errors) ? res.errors.filter(Boolean) : []
      if (res.stopped) {
        toast.warning(`${actionMeta.title}已停止，已处理 ${res.processed || 0}/${targetIds.length} 个账号`)
      } else if (errors.length > 0) {
        toast.warning(`${actionMeta.successText}，成功 ${res.success_count} 个，失败 ${errors.length} 个`)
      } else {
        toast.success(`${actionMeta.successText}，共 ${res.success_count} 个`)
      }
      if (action === 'delete') {
        const deletedIds = res.stopped ? (res.processed_ids || []) : targetIds
        selectedIds.value = selectedIds.value.filter((id) => !deletedIds.includes(id))
      }
      await loadData({ silentErrorToast: true })
      if (action !== 'delete' && res.stopped) {
        const processedIds = new Set(res.processed_ids || [])
        selectedIds.value = selectedIds.value.filter((id) => !processedIds.has(id))
      } else if (action !== 'delete') {
        clearSelection()
      }
    } catch (error) {
      setError(`${actionMeta.title}失败`, error)
    }
  }

  return {
    batchBusy,
    batchActionLabel,
    showRefreshProgress,
    refreshProgressTitle,
    refreshProgress,
    refreshProgressKind,
    bulkStopRequested,
    refreshProgressPercent,
    refreshProgressMetricLabel,
    refreshProgressMetricValue,
    refreshProgressStatusText,
    canStopRefreshProgress,
    openBulkProgress,
    requestStopRefreshProgress,
    closeRefreshProgress,
    refreshAccountsWithProgress,
    refreshAllAccounts,
    refreshSelectedAccounts,
    runBulkAction,
  }
}
