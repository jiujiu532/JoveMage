import { computed, type Ref } from 'vue'
import { accountsApi, type AccountTaskTier } from '@/api/accounts'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useToast } from '@/composables/useToast'
import {
  normalizeErrorMessage,
  type BulkAction,
  type BulkProgressKind,
  type SetErrorFn,
} from './accountPageShared'
import { resolveSelectedTier } from './accountTaskLabels'
import type { UseAccountTaskProgressReturn } from './useAccountTaskProgress'

export type UseAccountBulkActionsOptions = {
  setError: SetErrorFn
  loadData: (options?: { silentErrorToast?: boolean }) => Promise<void>
  selectedIds: Ref<string[]>
  clearSelection: () => void
  /** 统一任务进度（双档位 + 轮询） */
  taskProgress: UseAccountTaskProgressReturn
}

/**
 * 批量操作：刷新/启用禁用/删除/重登 → 提交后端任务 + 统一进度跟踪。
 * 确认框仍在提交前；跑起来后的停止/最小化由 taskProgress 负责。
 */
export function useAccountBulkActions(options: UseAccountBulkActionsOptions) {
  const {
    setError,
    selectedIds,
    clearSelection,
    loadData,
    taskProgress,
  } = options
  const toast = useToast()
  const confirmDialog = useConfirmDialog()

  const {
    batchBusy,
    batchActionLabel,
    submitAndTrack,
  } = taskProgress

  // 兼容 Accounts.vue / 旧字段：进度窗由 taskProgress 驱动
  const showRefreshProgress = taskProgress.modalOpen
  const refreshProgressTitle = computed(() => taskProgress.modalTask.value?.title || '')
  const refreshProgress = computed(() => {
    const task = taskProgress.modalTask.value
    if (!task) return null
    return {
      total: task.total,
      processed: task.progress,
      done: task.uiStatus === 'completed' || task.uiStatus === 'stopped' || task.uiStatus === 'failed',
      error: task.error || null,
      total_quota: 0 as number | undefined,
      result: task.result,
    }
  })
  const refreshProgressKind = computed<BulkProgressKind>(() => {
    const type = String(taskProgress.modalTask.value?.type || '')
    if (type === 'account_inspect') return 'inspect'
    if (type === 'account_refresh') return 'refresh'
    return 'mutation'
  })
  const bulkStopRequested = computed(() => Boolean(taskProgress.modalTask.value?.cancelRequested))
  const refreshProgressPercent = computed(() => {
    const task = taskProgress.modalTask.value
    if (!task || !task.total) return 0
    return Math.min(100, Math.round((task.progress / task.total) * 100))
  })
  const refreshProgressMetricLabel = computed(() => (
    refreshProgressKind.value === 'refresh' ? '图片总额度' : '处理账号'
  ))
  const refreshProgressMetricValue = computed(() => {
    const task = taskProgress.modalTask.value
    if (!task) return '-'
    return `${task.progress} 个`
  })
  const refreshProgressStatusText = computed(() => taskProgress.modalStatusText.value)
  const canStopRefreshProgress = computed(() => taskProgress.canCancelModal.value)

  function openBulkProgress(_title: string, _total: number, _kind: BulkProgressKind) {
    // 兼容旧调用点（绑定分组等本地快操作）；统一任务不再走此路径
  }

  async function requestStopRefreshProgress() {
    await taskProgress.requestStopModal()
  }

  function closeRefreshProgress() {
    taskProgress.closeModal()
  }

  async function refreshAccountsWithProgress(
    accountIds: string[],
    title: string,
    options?: { skipConfirm?: boolean; tier?: AccountTaskTier },
  ) {
    const targetIds = Array.from(new Set(accountIds.filter(Boolean)))
    if (!targetIds.length) {
      toast.warning('没有可刷新的账号')
      return
    }

    if (!options?.skipConfirm) {
      const confirmed = await confirmDialog.ask({
        title,
        message: `即将刷新 ${targetIds.length} 个账号的信息和额度（后端分批，可停止），是否继续？`,
        confirmText: '开始刷新',
        cancelText: '取消',
      })
      if (!confirmed) return
    }

    const tier = options?.tier || resolveSelectedTier(targetIds.length)
    await submitAndTrack({
      title,
      tier,
      type: 'account_refresh',
      submit: async () => {
        const started = await accountsApi.submitRefreshTask(targetIds, tier)
        if (!started.task_id && started.progress_id) {
          throw new Error('刷新接口尚未任务化（仅 progress_id），请等待后端 P0-3')
        }
        return {
          task_id: started.task_id,
          total: started.total ?? targetIds.length,
          type: 'account_refresh',
        }
      },
    })
  }

  async function refreshAllAccounts() {
    const title = '刷新所有账号信息和额度'
    try {
      const { tokens } = await accountsApi.fetchAccountIds({
        keyword: '',
        status: 'all',
        group_id: 'all',
        source_type: 'all',
      })
      if (!tokens.length) {
        toast.warning('没有可刷新的账号')
        return
      }
      await refreshAccountsWithProgress(tokens, title, { tier: 'heavy' })
    } catch (error) {
      setError(`${title}失败`, error)
    }
  }

  async function refreshSelectedAccounts() {
    await refreshAccountsWithProgress(selectedIds.value, '刷新选中账号信息和额度')
  }

  async function runStatusOrDeleteFallback(
    action: 'enable' | 'disable' | 'reset' | 'delete',
    targetIds: string[],
    title: string,
  ) {
    if (action === 'delete') {
      const result = await accountsApi.bulkDelete(targetIds)
      const errors = Array.isArray(result?.errors) ? result.errors.filter(Boolean) : []
      if (errors.length) {
        toast.warning(`${title}完成，成功 ${result.success_count ?? 0}，失败 ${errors.length}`)
      } else {
        toast.success(`${title}完成，共 ${result.success_count ?? targetIds.length} 个`)
      }
      clearSelection()
      await loadData({ silentErrorToast: true })
      return
    }
    if (action === 'enable') {
      const result = await accountsApi.bulkEnable(targetIds)
      toast.success(`${title}完成，共 ${result.success_count ?? targetIds.length} 个`)
    } else if (action === 'disable') {
      const result = await accountsApi.bulkDisable(targetIds)
      toast.success(`${title}完成，共 ${result.success_count ?? targetIds.length} 个`)
    } else {
      let success = 0
      for (const id of targetIds) {
        try {
          await accountsApi.resetAccountState(id)
          success += 1
        } catch {
          // ignore single
        }
      }
      toast.success(`已重置 ${success} 个账号状态`)
    }
    clearSelection()
    await loadData({ silentErrorToast: true })
  }

  async function runBulkAction(
    action: BulkAction,
    ids?: string[],
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
      refresh: { title: '批量刷新账号信息', confirmText: '确认刷新', type: 'account_refresh' as const },
      relogin: { title: '批量重新登录账号', confirmText: '确认重登', type: 'account_relogin' as const },
      reset: { title: '批量重置账号状态', confirmText: '确认重置', type: 'account_reset' as const },
      enable: { title: '批量启用账号', confirmText: '确认启用', type: 'account_enable' as const },
      disable: { title: '批量禁用账号', confirmText: '确认禁用', type: 'account_disable' as const },
      delete: { title: '批量删除账号', confirmText: '确认删除', type: 'account_delete' as const },
    }[action]

    const confirmed = await confirmDialog.ask({
      title: actionMeta.title,
      message: `确认对选中的 ${targetIds.length} 个账号执行该操作吗？`,
      confirmText: actionMeta.confirmText,
      cancelText: '取消',
    })
    if (!confirmed) return

    const tier = resolveSelectedTier(targetIds.length)

    if (action === 'relogin') {
      await submitAndTrack({
        title: actionMeta.title,
        tier,
        type: 'account_relogin',
        submit: async () => {
          const started = await accountsApi.reloginBatch(targetIds, tier)
          return {
            task_id: started.task_id,
            total: started.total ?? targetIds.length,
            type: 'account_relogin',
          }
        },
      })
      return
    }

    if (action === 'delete') {
      await submitAndTrack({
        title: actionMeta.title,
        tier,
        type: 'account_delete',
        submit: async () => {
          try {
            const started = await accountsApi.submitDeleteTask(targetIds, tier)
            return {
              task_id: started.task_id,
              total: started.total ?? targetIds.length,
              type: 'account_delete',
            }
          } catch (error) {
            if (/404|not found|405/i.test(normalizeErrorMessage(error))) {
              await runStatusOrDeleteFallback('delete', targetIds, actionMeta.title)
              return { task_id: '', total: targetIds.length, type: 'account_delete' }
            }
            throw error
          }
        },
      })
      return
    }

    // enable / disable / reset
    const statusAction = action === 'enable' ? 'enable' : action === 'disable' ? 'disable' : 'reset'
    await submitAndTrack({
      title: actionMeta.title,
      tier,
      type: actionMeta.type,
      submit: async () => {
        try {
          const started = await accountsApi.submitStatusTask(targetIds, statusAction, tier)
          return {
            task_id: started.task_id,
            total: started.total ?? targetIds.length,
            type: actionMeta.type,
          }
        } catch (error) {
          if (/404|not found|405/i.test(normalizeErrorMessage(error))) {
            await runStatusOrDeleteFallback(statusAction, targetIds, actionMeta.title)
            return { task_id: '', total: targetIds.length, type: actionMeta.type }
          }
          throw error
        }
      },
    })
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
