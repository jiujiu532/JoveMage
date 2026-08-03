import { computed, onUnmounted, ref, type Ref } from 'vue'
import {
  accountsApi,
  type AccountActiveTask,
  type AccountInspectResult,
  type AccountTaskTier,
  type AccountTaskType,
  type TaskStatus,
} from '@/api/accounts'
import { useToast } from '@/composables/useToast'
import { normalizeErrorMessage } from './accountPageShared'
import {
  isDeleteTaskType,
  isInspectTaskType,
  isTerminalUiStatus,
  resolveTaskUiStatus,
  taskStatusLabel,
  taskTypeLabel,
  type AccountTaskUiStatus,
} from './accountTaskLabels'

const POLL_INTERVAL_MS = 900
const FADE_OUT_MS = 5000

export type TrackedAccountTask = {
  taskId: string
  type: AccountTaskType
  tier: AccountTaskTier
  title: string
  status: string
  uiStatus: AccountTaskUiStatus
  progress: number
  total: number
  batchRemaining: number
  cancelRequested: boolean
  error: string
  result: Record<string, unknown> | null
  /** 顶栏条是否可见（failed 常驻；completed/stopped 约 5s 淡出） */
  stripVisible: boolean
  fading: boolean
}

export type UseAccountTaskProgressOptions = {
  loadData: (options?: { silentErrorToast?: boolean }) => Promise<void>
  clearSelection: () => void
  setError: (prefix: string, error: unknown, notify?: boolean) => void
}

type StartRemoteOptions = {
  taskId: string
  title: string
  tier: AccountTaskTier
  type?: AccountTaskType
  total?: number
  /** 提交后是否立即弹窗；恢复挂接时 false */
  openModal?: boolean
}

/**
 * 账号页统一任务进度：双档位顶栏条 + 可最小化进度窗 + active 恢复 + 终态收场。
 * 档位与状态映射见 .trellis/spec/backend/account-bulk-unified-task/05-progress-ui.md
 */
export function useAccountTaskProgress(options: UseAccountTaskProgressOptions) {
  const { loadData, clearSelection, setError } = options
  const toast = useToast()

  const heavyTask = ref<TrackedAccountTask | null>(null)
  const lightTask = ref<TrackedAccountTask | null>(null)
  const remoteModalOpen = ref(false)
  const modalTier = ref<AccountTaskTier>('heavy')
  const modalOpen = computed({
    get: () => remoteModalOpen.value || localProgressOpen.value,
    set: (open: boolean) => {
      if (open) {
        if (localProgress.value) localProgressOpen.value = true
        else remoteModalOpen.value = true
        return
      }
      if (localProgressOpen.value) {
        // 最小化本地进度：只关窗保留 busy
        localProgressOpen.value = false
        return
      }
      remoteModalOpen.value = false
    },
  })
  /** 非统一任务的本地快操作（如绑定分组/导入）占用底栏 busy */
  const localBusy = ref(false)
  const localBusyLabel = ref('')
  /** 本地进度（导入等前端分批，不占后端档位锁） */
  const localProgress = ref<{
    title: string
    total: number
    processed: number
    done: boolean
    error: string | null
    stopRequested: boolean
  } | null>(null)
  const localProgressOpen = ref(false)
  const localStopRequested = ref(false)

  const pollTimers: Partial<Record<AccountTaskTier, number>> = {}
  const fadeTimers: Partial<Record<AccountTaskTier, number>> = {}
  const handledTerminal = new Set<string>()

  const modalTask = computed(() => {
    // 本地进度窗打开时优先展示本地任务（导入等）
    if (localProgressOpen.value && localProgress.value) {
      const lp = localProgress.value
      return {
        taskId: 'local',
        type: 'local_mutation',
        tier: 'light' as AccountTaskTier,
        title: lp.title,
        status: lp.done ? (lp.error ? 'failed' : 'completed') : (lp.stopRequested ? 'running' : 'running'),
        uiStatus: (lp.error
          ? 'failed'
          : lp.done
            ? (lp.stopRequested ? 'stopped' : 'completed')
            : (lp.stopRequested ? 'stopping' : 'running')) as AccountTaskUiStatus,
        progress: lp.processed,
        total: lp.total,
        batchRemaining: 0,
        cancelRequested: lp.stopRequested,
        error: lp.error || '',
        result: null,
        stripVisible: false,
        fading: false,
      } satisfies TrackedAccountTask
    }
    return modalTier.value === 'light' ? lightTask.value : heavyTask.value
  })

  const heavyBusy = computed(() => {
    const task = heavyTask.value
    return Boolean(task && !isTerminalUiStatus(task.uiStatus))
  })
  const lightBusy = computed(() => {
    const task = lightTask.value
    return Boolean(task && !isTerminalUiStatus(task.uiStatus))
  })
  const anyBusy = computed(() => heavyBusy.value || lightBusy.value || localBusy.value)

  const batchBusy = anyBusy
  const batchActionLabel = computed(() => {
    if (localBusy.value && localBusyLabel.value) return localBusyLabel.value
    const running = [heavyTask.value, lightTask.value].filter(
      (task): task is TrackedAccountTask => Boolean(task && !isTerminalUiStatus(task.uiStatus)),
    )
    if (!running.length) return localBusyLabel.value || ''
    if (running.length === 1) return running[0].title
    return '批量任务进行中'
  })

  function setLocalBusy(busy: boolean, label = '') {
    localBusy.value = busy
    localBusyLabel.value = busy ? label : ''
  }

  /** 打开本地进度窗（导入等前端分批） */
  function openLocalProgress(title: string, total: number) {
    localStopRequested.value = false
    localProgress.value = {
      title,
      total,
      processed: 0,
      done: false,
      error: null,
      stopRequested: false,
    }
    localProgressOpen.value = true
    setLocalBusy(true, title)
  }

  function updateLocalProgress(patch: {
    processed?: number
    done?: boolean
    error?: string | null
    total?: number
  }) {
    if (!localProgress.value) return
    localProgress.value = {
      ...localProgress.value,
      ...patch,
      stopRequested: localStopRequested.value,
    }
    if (patch.done) {
      setLocalBusy(false)
    }
  }

  function requestStopLocalProgress() {
    if (!localProgress.value || localProgress.value.done) return
    localStopRequested.value = true
    localProgress.value = { ...localProgress.value, stopRequested: true }
    toast.info('已请求停止，当前批次完成后会停止后续批次')
  }

  function closeLocalProgress() {
    if (localProgress.value && !localProgress.value.done) return
    localProgressOpen.value = false
    localProgress.value = null
    localStopRequested.value = false
  }

  const modalBusy = computed(() => {
    if (localProgressOpen.value && localProgress.value) {
      return !localProgress.value.done
    }
    const task = modalTask.value
    return Boolean(task && !isTerminalUiStatus(task.uiStatus))
  })

  const canCancelModal = computed(() => {
    if (localProgressOpen.value && localProgress.value) {
      return !localProgress.value.done && !localProgress.value.stopRequested
    }
    const task = modalTask.value
    return Boolean(task && task.uiStatus === 'running' && !task.cancelRequested)
  })

  const canCloseModal = computed(() => {
    if (localProgressOpen.value && localProgress.value) {
      return localProgress.value.done
    }
    const task = modalTask.value
    return !task || isTerminalUiStatus(task.uiStatus)
  })

  const modalStatusText = computed(() => {
    const task = modalTask.value
    if (!task) return ''
    return taskStatusLabel(task.uiStatus, {
      batchRemaining: task.batchRemaining,
      kindHint: task.type === 'local_mutation' ? '处理中' : `${taskTypeLabel(task.type)}中`,
    })
  })

  const visibleStrips = computed(() => (
    // 顶栏常驻两条：重量 + 轻量；无任务时只返回 tier，组件显示「无任务」空态
    [
      heavyTask.value || ({ tier: 'heavy' as AccountTaskTier, isEmpty: true }),
      lightTask.value || ({ tier: 'light' as AccountTaskTier, isEmpty: true }),
    ]
  ))

  function slotOf(tier: AccountTaskTier): Ref<TrackedAccountTask | null> {
    return tier === 'light' ? lightTask : heavyTask
  }

  function clearPoll(tier: AccountTaskTier) {
    const timer = pollTimers[tier]
    if (timer) {
      window.clearTimeout(timer)
      delete pollTimers[tier]
    }
  }

  function clearFade(tier: AccountTaskTier) {
    const timer = fadeTimers[tier]
    if (timer) {
      window.clearTimeout(timer)
      delete fadeTimers[tier]
    }
  }

  function mapTask(
    snapshot: TaskStatus | AccountActiveTask,
    base?: Partial<TrackedAccountTask>,
  ): TrackedAccountTask {
    const type = String(
      (snapshot as TaskStatus).task_type
      || snapshot.type
      || base?.type
      || 'account_task',
    )
    const tier = (String(snapshot.tier || base?.tier || 'heavy') === 'light' ? 'light' : 'heavy') as AccountTaskTier
    const cancelRequested = Boolean(snapshot.cancel_requested || base?.cancelRequested)
    const uiStatus = resolveTaskUiStatus({
      status: snapshot.status,
      cancel_requested: cancelRequested,
      error: (snapshot as TaskStatus).error,
    })
    const errorText = String((snapshot as TaskStatus).error || base?.error || '')
    const result = ((snapshot as TaskStatus).result && typeof (snapshot as TaskStatus).result === 'object')
      ? (snapshot as TaskStatus).result as Record<string, unknown>
      : (base?.result || null)

    return {
      taskId: String(snapshot.task_id || base?.taskId || ''),
      type,
      tier,
      title: base?.title || `${taskTypeLabel(type)}任务`,
      status: String(snapshot.status || 'running'),
      uiStatus,
      progress: Math.max(0, Number(snapshot.progress || 0)),
      total: Math.max(0, Number(snapshot.total || base?.total || 0)),
      batchRemaining: Math.max(0, Number(snapshot.batch_remaining || 0)),
      cancelRequested,
      error: errorText,
      result,
      stripVisible: base?.stripVisible ?? true,
      fading: base?.fading ?? false,
    }
  }

  function applySnapshot(tier: AccountTaskTier, next: TrackedAccountTask) {
    const slot = slotOf(tier)
    const prev = slot.value
    slot.value = {
      ...next,
      title: next.title || prev?.title || `${taskTypeLabel(next.type)}任务`,
      stripVisible: prev?.stripVisible ?? next.stripVisible,
      fading: prev?.fading ?? false,
    }
  }

  async function handleTerminal(task: TrackedAccountTask) {
    if (!task.taskId || handledTerminal.has(task.taskId)) return
    handledTerminal.add(task.taskId)

    clearPoll(task.tier)

    try {
      await loadData({ silentErrorToast: true })
    } catch {
      // 终态刷新失败不阻断 UI
    }

    if (isDeleteTaskType(task.type)) {
      clearSelection()
    }

    if (task.uiStatus === 'stopped') {
      toast.warning(`已停止，已处理 ${task.progress}/${task.total || '?'}`)
    } else if (task.uiStatus === 'failed') {
      const message = task.error || '任务失败'
      toast.error(message)
    } else if (task.uiStatus === 'completed') {
      if (isInspectTaskType(task.type)) {
        // 巡检：不自动霸屏摘要；由调用方可选打开摘要
      } else {
        toast.success(`${task.title}完成（${task.progress}/${task.total || task.progress}）`)
      }
    }

    scheduleStripFade(task.tier, task.uiStatus)
  }

  function scheduleStripFade(tier: AccountTaskTier, uiStatus: AccountTaskUiStatus) {
    clearFade(tier)
    const slot = slotOf(tier)
    const current = slot.value
    if (!current) return

    if (uiStatus === 'failed') {
      // 失败条不自动消失
      slot.value = { ...current, stripVisible: true, fading: false }
      return
    }

    if (uiStatus === 'completed' || uiStatus === 'stopped') {
      slot.value = { ...current, stripVisible: true, fading: true }
      fadeTimers[tier] = window.setTimeout(() => {
        const latest = slotOf(tier).value
        if (!latest || latest.taskId !== current.taskId) return
        if (!isTerminalUiStatus(latest.uiStatus)) return
        slot.value = { ...latest, stripVisible: false, fading: false }
        if (modalOpen.value && modalTier.value === tier) {
          remoteModalOpen.value = false
        }
      }, FADE_OUT_MS)
    }
  }

  async function pollOnce(tier: AccountTaskTier) {
    const current = slotOf(tier).value
    if (!current?.taskId) return

    try {
      const snapshot = await accountsApi.fetchTaskStatus(current.taskId)
      const next = mapTask(snapshot, current)
      applySnapshot(tier, next)

      if (isTerminalUiStatus(next.uiStatus)) {
        await handleTerminal(next)
        return
      }
    } catch (error) {
      const message = normalizeErrorMessage(error)
      // 任务不存在：可能服务重启
      if (/not found|404/i.test(message)) {
        const slot = slotOf(tier)
        if (slot.value?.taskId === current.taskId) {
          slot.value = null
          clearPoll(tier)
          if (modalOpen.value && modalTier.value === tier) modalOpen.value = false
          toast.warning('上次任务已中断')
        }
        return
      }
    }

    pollTimers[tier] = window.setTimeout(() => {
      void pollOnce(tier)
    }, POLL_INTERVAL_MS)
  }

  function ensurePolling(tier: AccountTaskTier) {
    if (pollTimers[tier]) return
    void pollOnce(tier)
  }

  function startRemoteTask(opts: StartRemoteOptions) {
    const tier = opts.tier
    clearFade(tier)
    const existing = slotOf(tier).value
    const seeded = mapTask(
      {
        task_id: opts.taskId,
        type: opts.type || existing?.type || 'account_task',
        task_type: opts.type || existing?.type || 'account_task',
        tier,
        status: 'running',
        progress: 0,
        total: opts.total || existing?.total || 0,
        cancel_requested: false,
        batch_remaining: 0,
      },
      {
        title: opts.title,
        type: opts.type,
        tier,
        stripVisible: true,
        fading: false,
      },
    )
    handledTerminal.delete(opts.taskId)
    slotOf(tier).value = seeded
    if (opts.openModal !== false) {
      modalTier.value = tier
      remoteModalOpen.value = true
    }
    ensurePolling(tier)
  }

  /** 将 active 接口返回的任务挂到顶栏（不自动弹窗） */
  function attachActiveTask(active: AccountActiveTask, titleHint?: string) {
    const tier = (String(active.tier) === 'light' ? 'light' : 'heavy') as AccountTaskTier
    const type = String(active.type || 'account_task')
    startRemoteTask({
      taskId: active.task_id,
      title: titleHint || `${taskTypeLabel(type)}任务`,
      tier,
      type,
      total: active.total,
      openModal: false,
    })
    // 用 active 快照覆盖一次进度
    applySnapshot(tier, mapTask(active, slotOf(tier).value || undefined))
    ensurePolling(tier)
  }

  async function restoreActiveTasks() {
    try {
      const active = await accountsApi.fetchActiveAccountTasks()
      if (active.heavy) attachActiveTask(active.heavy)
      if (active.light) attachActiveTask(active.light)
    } catch (error) {
      // active 接口未就绪时静默；不影响页面
      if (!/404|not found/i.test(normalizeErrorMessage(error))) {
        // 其它错误也不阻塞进页
      }
    }
  }

  function openModalForTier(tier: AccountTaskTier) {
    const task = slotOf(tier).value
    if (!task) return
    modalTier.value = tier
    remoteModalOpen.value = true
    if (!isTerminalUiStatus(task.uiStatus)) {
      ensurePolling(tier)
    }
  }

  function minimizeModal() {
    if (localProgressOpen.value) {
      localProgressOpen.value = false
      return
    }
    remoteModalOpen.value = false
  }

  function closeModal() {
    if (localProgressOpen.value) {
      closeLocalProgress()
      return
    }
    const task = modalTask.value
    if (task && !isTerminalUiStatus(task.uiStatus)) return
    remoteModalOpen.value = false
    if (task && task.uiStatus !== 'failed') {
      // 关闭终态后按淡出规则处理条
      scheduleStripFade(task.tier, task.uiStatus)
    }
  }

  function dismissStrip(tier: AccountTaskTier) {
    clearFade(tier)
    const slot = slotOf(tier)
    const task = slot.value
    if (!task) return
    if (!isTerminalUiStatus(task.uiStatus)) return
    slot.value = { ...task, stripVisible: false, fading: false }
    if (modalOpen.value && modalTier.value === tier) remoteModalOpen.value = false
  }

  async function requestStop(tier: AccountTaskTier) {
    const task = slotOf(tier).value
    if (!task || task.uiStatus !== 'running' || task.cancelRequested) return
    try {
      const res = await accountsApi.cancelTask(task.taskId)
      applySnapshot(tier, {
        ...task,
        cancelRequested: true,
        uiStatus: 'stopping',
        batchRemaining: Math.max(0, Number(res.batch_remaining ?? task.batchRemaining)),
      })
      toast.info('已请求停止，当前批次完成后会停止后续批次')
      ensurePolling(tier)
    } catch (error) {
      setError('停止任务失败', error)
    }
  }

  async function requestStopModal() {
    if (localProgressOpen.value) {
      requestStopLocalProgress()
      return
    }
    const task = modalTask.value
    if (!task || task.taskId === 'local') return
    await requestStop(task.tier)
  }

  /**
   * 提交任务后的统一入口：409 冲突 toast，成功则跟踪进度。
   * submit() 应返回 { task_id, total?, type? }
   */
  async function submitAndTrack(opts: {
    title: string
    tier: AccountTaskTier
    type: AccountTaskType
    /**
     * 返回 task_id 开始轮询；
     * 若调用方已在 submit 内同步降级完成，可返回空 task_id（不弹窗、不轮询）。
     */
    submit: () => Promise<{ task_id: string; total?: number; type?: string }>
    openModal?: boolean
  }): Promise<boolean> {
    try {
      const started = await opts.submit()
      const taskId = String(started.task_id || '').trim()
      if (!taskId) {
        // 同步降级路径：业务已在 submit 内完成
        return true
      }
      startRemoteTask({
        taskId,
        title: opts.title,
        tier: opts.tier,
        type: (started.type as AccountTaskType) || opts.type,
        total: started.total,
        openModal: opts.openModal,
      })
      return true
    } catch (error) {
      const message = normalizeErrorMessage(error)
      if (/409|同档位|正在运行|conflict/i.test(message)) {
        toast.warning(message || '当前档位已有任务在运行')
        return false
      }
      setError(`${opts.title}失败`, error)
      return false
    }
  }

  /** 巡检结果摘要（从终态 result 读） */
  function readInspectResult(task: TrackedAccountTask | null): (AccountInspectResult & { scopeText?: string }) | null {
    if (!task || !isInspectTaskType(task.type) || !task.result) return null
    return task.result as AccountInspectResult
  }

  function dispose() {
    clearPoll('heavy')
    clearPoll('light')
    clearFade('heavy')
    clearFade('light')
  }

  onUnmounted(dispose)

  return {
    heavyTask,
    lightTask,
    modalOpen,
    modalTier,
    modalTask,
    modalBusy,
    canCancelModal,
    canCloseModal,
    modalStatusText,
    visibleStrips,
    heavyBusy,
    lightBusy,
    anyBusy,
    batchBusy,
    batchActionLabel,
    setLocalBusy,
    openLocalProgress,
    updateLocalProgress,
    requestStopLocalProgress,
    closeLocalProgress,
    localStopRequested,
    restoreActiveTasks,
    startRemoteTask,
    submitAndTrack,
    openModalForTier,
    minimizeModal,
    closeModal,
    dismissStrip,
    requestStop,
    requestStopModal,
    readInspectResult,
    dispose,
  }
}

export type UseAccountTaskProgressReturn = ReturnType<typeof useAccountTaskProgress>
