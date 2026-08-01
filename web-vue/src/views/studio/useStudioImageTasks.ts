import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'
import {
  imageTasksApi,
  isImageTaskTerminal,
  taskPrimaryMessage,
  type ImageTask,
} from '@/api/imageTasks'
import {
  getJsonPreference,
  preferenceKeys,
  setJsonPreference,
} from '@/lib/preferences'
import type {
  StudioConversation,
  StudioConversationBadgeState,
  StudioMessage,
} from '@/components/studio/types'
import { cleanText } from './useStudioPersistence'

export type StudioImageTasksOptions = {
  conversations: Ref<StudioConversation[]>
  activeConversation: ComputedRef<StudioConversation | null>
  /** 页面是否处于激活态；轮询/刷新在非激活时直接跳过 */
  isStudioActive: () => boolean
  touchConversation: (conversation: StudioConversation) => void
  markConversationNotice: (conversationId: string, state: StudioConversationBadgeState) => void
  /** 刷新失败时回写到 composerError */
  setComposerError: (message: string) => void
  clearComposerError?: () => void
  errorMessage: (error: unknown, fallback: string) => string
}

/**
 * Studio 图片任务：拉取/合并/状态同步 + 防抖刷新与轮询 timer。
 * 不拥有会话列表本身，通过回调回写消息状态与角标。
 */
export function useStudioImageTasks(options: StudioImageTasksOptions) {
  const {
    conversations,
    activeConversation,
    isStudioActive,
    touchConversation,
    markConversationNotice,
    setComposerError,
    clearComposerError,
    errorMessage,
  } = options

  const imageTasks = ref<ImageTask[]>([])
  const isFetchingTasks = ref(false)

  let imagePollTimer: number | null = null
  let imageRefreshTimer: number | null = null
  let imageRefreshQueued = false
  let imageRefreshQueuedForce = false
  let lastSuccessfulImageRefreshSignature = ''

  const taskById = computed(() => new Map(imageTasks.value.map((task) => [task.id, task])))

  const activeImageTaskIds = computed(() => {
    const ids = (activeConversation.value?.messages.map((message) => message.taskId).filter((id): id is string => Boolean(id)) || [])
    return Array.from(new Set(ids)).slice(0, 80)
  })

  const conversationTaskState = computed(() => {
    const pendingIds = new Set<string>()
    const runningCounts: Record<string, number> = {}
    conversations.value.forEach((conversation) => {
      let running = 0
      conversation.messages.forEach((message) => {
        // 图像/视频异步任务共用轮询骨架
        if ((message.mode === 'image' || message.mode === 'video') && isImageMessageRunning(message)) {
          running += 1
          if (message.taskId) pendingIds.add(message.taskId)
        } else if (message.status === 'sending' || message.status === 'streaming') {
          running += 1
        }
      })
      if (running > 0) runningCounts[conversation.id] = running
    })
    return {
      pendingImageTaskIds: Array.from(pendingIds).slice(0, 160),
      runningCounts,
    }
  })

  const pendingImageTaskIds = computed(() => conversationTaskState.value.pendingImageTaskIds)
  const requestedImageTaskIds = computed(() => Array.from(new Set([
    ...activeImageTaskIds.value,
    ...pendingImageTaskIds.value,
  ])).slice(0, 180))
  const activeRunningTaskCount = computed(() => (
    activeConversation.value ? (conversationTaskState.value.runningCounts[activeConversation.value.id] || 0) : 0
  ))

  watch(requestedImageTaskIds, () => scheduleImageTaskRefresh())
  watch(pendingImageTaskIds, scheduleImagePoll)

  function isImageMessageRunning(message: StudioMessage) {
    if (!message.taskId) return message.status === 'queued' || message.status === 'running'
    const task = taskById.value.get(message.taskId)
    if (task) return !isImageTaskTerminal(task)
    return message.status === 'queued' || message.status === 'running'
  }

  function storedImageTaskIds() {
    const ids = getJsonPreference<unknown[]>(preferenceKeys.imageTaskLocalIds, [])
    return Array.isArray(ids) ? ids.map((id) => cleanText(id)).filter(Boolean) : []
  }

  function rememberImageTaskId(taskId: string) {
    if (!taskId) return
    const ids = Array.from(new Set([taskId, ...storedImageTaskIds()])).slice(0, 160)
    setJsonPreference(preferenceKeys.imageTaskLocalIds, ids)
  }

  async function refreshImageTasks(force = false) {
    if (!isStudioActive()) return
    if (isFetchingTasks.value) {
      imageRefreshQueued = true
      imageRefreshQueuedForce = imageRefreshQueuedForce || force
      return
    }
    const ids = requestedImageTaskIds.value.filter((id): id is string => Boolean(id))
    const signature = ids.join('\0')
    if (!force && signature && signature === lastSuccessfulImageRefreshSignature) return
    if (!ids.length) {
      imageTasks.value = []
      lastSuccessfulImageRefreshSignature = ''
      return
    }
    isFetchingTasks.value = true
    try {
      const response = await imageTasksApi.list(ids)
      mergeImageTasks(response.items)
      markMissingImageTasks(response.missing_ids)
      syncImageMessageStatuses()
      clearComposerError?.()
      lastSuccessfulImageRefreshSignature = signature
    } catch (error) {
      setComposerError(errorMessage(error, '刷新图片任务失败'))
      lastSuccessfulImageRefreshSignature = ''
    } finally {
      isFetchingTasks.value = false
      scheduleImagePoll()
      if (imageRefreshQueued) {
        const queuedForce = imageRefreshQueuedForce
        imageRefreshQueued = false
        imageRefreshQueuedForce = false
        scheduleImageTaskRefresh(0, queuedForce)
      }
    }
  }

  function mergeImageTasks(items: ImageTask[]) {
    const map = new Map(imageTasks.value.map((task) => [task.id, task]))
    items.filter((task) => task.id).forEach((task) => map.set(task.id, task))
    imageTasks.value = Array.from(map.values())
    lastSuccessfulImageRefreshSignature = ''
  }

  function markMissingImageTasks(taskIds: string[]) {
    const missing = new Set(taskIds.filter(Boolean))
    if (!missing.size) return
    conversations.value.forEach((conversation) => {
      conversation.messages.forEach((message) => {
        if (!message.taskId || !missing.has(message.taskId)) return
        if (message.status === 'done' || message.status === 'error') return
        message.status = 'error'
        message.error = message.mode === 'video' ? '视频任务已过期或不存在' : '图片任务已过期或不存在'
        touchConversation(conversation)
        markConversationNotice(conversation.id, 'error')
      })
    })
  }

  function syncImageMessageStatuses() {
    conversations.value.forEach((conversation) => {
      let changed = false
      conversation.messages.forEach((message) => {
        if (!message.taskId) return
        const task = taskById.value.get(message.taskId)
        if (!task) return
        const previousStatus = message.status
        if (task.status === 'success') {
          message.status = 'done'
          if (previousStatus !== 'done') markConversationNotice(conversation.id, 'done')
        } else if (task.status === 'error') {
          message.status = 'error'
          const fallback = message.mode === 'video' ? '视频任务失败' : '图片任务失败'
          message.error = taskPrimaryMessage(task) || task.error || fallback
          if (previousStatus !== 'error') markConversationNotice(conversation.id, 'error')
        } else {
          message.status = 'running'
        }
        if (message.status !== previousStatus) changed = true
      })
      if (changed) touchConversation(conversation)
    })
  }

  function scheduleImagePoll() {
    if (imagePollTimer !== null) {
      window.clearTimeout(imagePollTimer)
      imagePollTimer = null
    }
    if (!isStudioActive()) return
    if (!pendingImageTaskIds.value.length) return
    imagePollTimer = window.setTimeout(() => {
      imagePollTimer = null
      void refreshImageTasks(true)
    }, 4000)
  }

  function scheduleImageTaskRefresh(delay = 120, force = false) {
    if (!isStudioActive()) return
    if (imageRefreshTimer !== null) {
      window.clearTimeout(imageRefreshTimer)
    }
    imageRefreshTimer = window.setTimeout(() => {
      imageRefreshTimer = null
      void refreshImageTasks(force)
    }, delay)
  }

  function clearImagePollTimer() {
    if (imagePollTimer !== null) {
      window.clearTimeout(imagePollTimer)
      imagePollTimer = null
    }
  }

  function clearImageRefreshTimer() {
    if (imageRefreshTimer !== null) {
      window.clearTimeout(imageRefreshTimer)
      imageRefreshTimer = null
    }
  }

  function clearImageTimers() {
    clearImagePollTimer()
    clearImageRefreshTimer()
  }

  return {
    imageTasks,
    isFetchingTasks,
    taskById,
    activeImageTaskIds,
    pendingImageTaskIds,
    requestedImageTaskIds,
    conversationTaskState,
    activeRunningTaskCount,
    isImageMessageRunning,
    refreshImageTasks,
    mergeImageTasks,
    rememberImageTaskId,
    scheduleImagePoll,
    scheduleImageTaskRefresh,
    clearImagePollTimer,
    clearImageRefreshTimer,
    clearImageTimers,
  }
}
