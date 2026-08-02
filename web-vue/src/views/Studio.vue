<template>
  <div class="studio-workspace" :class="{ 'is-fullscreen': isFullscreen }" :style="workspaceStyle">
    <div class="studio-sidebar-wrap">
      <StudioHistoryPanel
        :conversations="conversations"
        :active-conversation-id="activeConversationId"
        :badges="conversationBadges"
        @create="createConversation"
        @select="selectConversation"
        @rename="renameConversation"
        @delete="deleteConversation"
        @clear="confirmClearHistory"
        @reorder="reorderConversation"
      />

      <div
        class="studio-history-resizer"
        role="separator"
        aria-orientation="vertical"
        title="拖动调整历史栏宽度"
        @pointerdown="startSidebarResize"
      ></div>
    </div>

    <main class="studio-main">
      <div class="chat-header-bar">
        <div class="chat-header-title">
          <Button
            size="sm"
            variant="ghost"
            icon-only
            root-class="chat-header-icon lg:hidden"
            title="打开会话列表"
            aria-label="打开会话列表"
            @click="isMobileHistoryOpen = true"
          >
            <Icon icon="lucide:panel-left-open" class="h-4 w-4" />
          </Button>
          <div class="min-w-0">
            <div class="chat-header-name">{{ activeConversation?.title || '新对话' }}</div>
            <div class="chat-header-subtitle">{{ activeHeaderSubtitle }}</div>
          </div>
        </div>

        <div class="chat-header-actions">
          <Button size="sm" variant="outline" root-class="chat-header-action-button" @click="createConversation()">
            <Icon icon="lucide:plus" class="h-3.5 w-3.5" />
            <span class="chat-header-action-label hidden sm:inline">新对话</span>
          </Button>
          <Button
            size="sm"
            variant="outline"
            root-class="chat-header-action-button"
            :disabled="!activeConversation?.messages.length"
            @click="clearCurrentConversation"
          >
            <Icon icon="lucide:trash-2" class="h-3.5 w-3.5" />
            <span class="chat-header-action-label hidden sm:inline">清空</span>
          </Button>
          <Button
            size="sm"
            variant="ghost"
            icon-only
            root-class="chat-header-action-button"
            :title="isFullscreen ? '退出全屏' : '全屏'"
            :aria-label="isFullscreen ? '退出全屏' : '全屏'"
            @click="toggleFullscreen"
          >
            <Icon :icon="isFullscreen ? 'lucide:minimize-2' : 'lucide:maximize-2'" class="h-4 w-4" />
          </Button>
        </div>
      </div>

      <StudioMessageList
        ref="messageListRef"
        :conversation="activeConversation"
        :conversations-count="conversations.length"
        :tasks="imageTasks"
        :fullscreen="isFullscreen"
        @create="createConversation"
        @open-history="isMobileHistoryOpen = true"
        @toggle-fullscreen="toggleFullscreen"
        @retry="retryMessage"
        @edit="editMessage"
        @resend="resendMessage"
        @retry-assistant="retryAssistantMessage"
        @delete-message="deleteMessage"
        @copy-message="copyText"
        @preview="openPreview"
        @compare-image="openImageCompare"
      />

      <StudioComposer
        v-model:mode="composeMode"
        v-model:text="composerText"
        v-model:chat-model="chatModel"
        v-model:chat-reasoning-effort="chatReasoningEffort"
        :image-form="imageForm"
        :video-model="videoModel"
        :chat-model-options="chatModelOptions"
        :image-model-options="imageModelOptions"
        :video-model-options="videoModelOptions"
        :image-upscale-enabled="imageUpscaleEnabled"
        :references="referencePreviews"
        :is-sending="isSending"
        :is-streaming="isStreaming"
        :is-editing="Boolean(editingMessageId)"
        :error="composerError"
        @update:image-model="imageForm.model = $event"
        @update:video-model="videoModel = $event"
        @update:image-size="imageForm.size = $event"
        @update:image-quality="imageForm.quality = $event"
        @update:image-count="imageForm.n = $event"
        @submit="sendMessage"
        @stop="stopStreaming"
        @cancel-edit="cancelMessageEdit"
        @add-files="appendFiles"
        @remove-reference="removeReference"
        @clear-references="clearReferences"
        @preview-reference="previewReference"
        @open-prompts="openPromptPicker"
      />
    </main>

    <StudioMobileHistory
      :open="isMobileHistoryOpen"
      :conversations="conversations"
      :active-conversation-id="activeConversationId"
      :badges="conversationBadges"
      @close="isMobileHistoryOpen = false"
      @select="selectConversation"
      @delete="deleteConversation"
    />

    <StudioLightbox
      :preview="previewImage"
      @close="previewImage = null"
      @copy="copyText"
      @download="downloadPreviewImage"
    />
    <StudioImageCompareModal
      :compare="comparePreview"
      @close="comparePreview = null"
    />
    <StudioPromptPicker
      v-if="isPromptPickerOpen"
      :open="isPromptPickerOpen"
      @close="isPromptPickerOpen = false"
      @select="applyPromptTemplate"
    />
  </div>
</template>

<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { Button } from 'nanocat-ui'
import { computed, defineAsyncComponent, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, reactive, ref, watch } from 'vue'
import { imageTasksApi } from '@/api/imageTasks'
import { streamChatCompletion } from '@/api/chatStream'
import { debugApi, type DebugChatMessage, type DebugSearchResult } from '@/api/debug'
import {
  DEFAULT_IMAGE_MODEL,
  DEFAULT_IMAGE_QUALITY,
  DEFAULT_IMAGE_SIZE,
  DEFAULT_VIDEO_MODEL,
  isImageSizeSupportedByModel,
  normalizeImageCount,
  type ImageTask,
} from '@/api/imageTasks'
import { useModelCatalog } from '@/composables/useModelCatalog'
import { useSettingsStore } from '@/stores/settings'
import { useClipboard } from '@/composables/useClipboard'
import { useToast } from '@/composables/useToast'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useMediaQuery } from '@/composables/useMediaQuery'
import { MQ } from '@/lib/breakpoints'
import {
  getBooleanPreference,
  getNumberPreference,
  getStringPreference,
  preferenceKeys,
  setBooleanPreference,
  setNumberPreference,
  setStringPreference,
} from '@/lib/preferences'
import { downloadUrlAsFile } from '@/lib/downloads'
import { preloadPromptLibrary } from '@/composables/usePromptLibraryRuntime'
import type { PromptLibraryItem } from '@/api/prompts'
import StudioComposer from '@/components/studio/StudioComposer.vue'
import StudioHistoryPanel from '@/components/studio/StudioHistoryPanel.vue'
import type {
  StudioComposeMode,
  StudioConversation,
  StudioConversationBadge,
  StudioImageComparePreview,
  StudioImageForm,
  StudioMessage,
  StudioPreviewImage,
  StudioReference,
} from '@/components/studio/types'
import {
  useStudioPersistence,
  createId,
  normalizeSearchImageGroups,
  extractSearchImageGroupsFromText,
  normalizeSearchSources,
  cleanSearchAnswer,
  linkSearchCitations,
} from '@/views/studio/useStudioPersistence'
import { useStudioImageTasks } from '@/views/studio/useStudioImageTasks'

defineOptions({ name: 'Studio' })

const StudioLightbox = defineAsyncComponent(() => import('@/components/studio/StudioLightbox.vue'))
const StudioImageCompareModal = defineAsyncComponent(() => import('@/components/studio/StudioImageCompareModal.vue'))
const StudioMessageList = defineAsyncComponent(() => import('@/components/studio/StudioMessageList.vue'))
const StudioMobileHistory = defineAsyncComponent(() => import('@/components/studio/StudioMobileHistory.vue'))
const StudioPromptPicker = defineAsyncComponent(() => import('@/components/studio/StudioPromptPicker.vue'))

const settingsStore = useSettingsStore()
const toast = useToast()
const { copy } = useClipboard()
const confirmDialog = useConfirmDialog()
const { catalog, chatModels, imageModels, videoModels, loadModelCatalog } = useModelCatalog(() => settingsStore.settings)

const defaultSidebarWidth = 244
const composeMode = ref<StudioComposeMode>(normalizeMode(getStringPreference(preferenceKeys.studioActiveMode, 'image')))
const composerText = ref('')
const composerError = ref('')
const editingMessageId = ref('')
const isSending = ref(false)
const isStreaming = ref(false)
/** PC 不自动全屏；仅窄屏恢复上次全屏偏好。手动点全屏仍会写入偏好。 */
const isNarrowStudio = useMediaQuery(MQ.notDesktop)
const isFullscreen = ref(false)
const isMobileHistoryOpen = ref(false)
const sidebarWidth = ref(getNumberPreference(preferenceKeys.studioSidebarWidth, defaultSidebarWidth, { min: 220, max: 380 }))
type StudioMessageListExpose = { scrollToBottom: () => Promise<void> | void }
const messageListRef = ref<StudioMessageListExpose | null>(null)

const chatModel = ref(getStringPreference(preferenceKeys.studioChatModel, 'auto') || 'auto')
const chatReasoningEffort = ref(getStringPreference(preferenceKeys.studioChatReasoningEffort, ''))
const imageForm = reactive<StudioImageForm>({
  model: getStringPreference(preferenceKeys.studioImageModel, DEFAULT_IMAGE_MODEL) || DEFAULT_IMAGE_MODEL,
  size: DEFAULT_IMAGE_SIZE,
  quality: DEFAULT_IMAGE_QUALITY,
  n: 1,
})
const videoModel = ref(getStringPreference(preferenceKeys.studioVideoModel, DEFAULT_VIDEO_MODEL) || DEFAULT_VIDEO_MODEL)

const {
  conversations,
  activeConversationId,
  conversationNotices,
  schedulePersistConversations,
  flushAllPersistence,
  markConversationNotice,
  clearConversationNotice,
} = useStudioPersistence()

const selectedFiles = ref<File[]>([])
const referencePreviews = ref<StudioReference[]>([])
const previewImage = ref<StudioPreviewImage | null>(null)
const comparePreview = ref<StudioImageComparePreview | null>(null)
const isPromptPickerOpen = ref(false)

let streamController: AbortController | null = null
let sidebarResizeStartX = 0
let sidebarResizeStartWidth = defaultSidebarWidth
let scrollFrameId: number | null = null
let scrollScheduled = false
let scrollRequestToken = 0
let pendingConversationSelectId = ''
let conversationSelectFrameId: number | null = null
let hasActivatedOnce = false
let isStudioActive = true

const workspaceStyle = computed(() => ({
  '--studio-history-width': `${sidebarWidth.value}px`,
}))
const activeConversation = computed(() => {
  return conversations.value.find((conversation) => conversation.id === activeConversationId.value)
    || conversations.value[0]
    || null
})

const {
  imageTasks,
  conversationTaskState,
  activeRunningTaskCount,
  refreshImageTasks,
  mergeImageTasks,
  rememberImageTaskId,
  scheduleImagePoll,
  clearImageTimers,
} = useStudioImageTasks({
  conversations,
  activeConversation,
  isStudioActive: () => isStudioActive,
  touchConversation: (conversation) => touchConversation(conversation),
  markConversationNotice,
  setComposerError: (message) => { composerError.value = message },
  clearComposerError: () => { composerError.value = '' },
  errorMessage,
})

const activeHeaderSubtitle = computed(() => {
  if (isStreaming.value) return '正在回复'
  if (isSending.value) {
    if (composeMode.value === 'search') return '正在搜索'
    if (composeMode.value === 'image') return '正在提交图片'
    if (composeMode.value === 'video') return '正在提交视频'
    return '正在请求'
  }
  if (activeRunningTaskCount.value > 0) return `任务处理中 ${activeRunningTaskCount.value}`
  const count = activeConversation.value?.messages.length || 0
  return count ? `${count} 条消息` : '准备就绪'
})
const conversationBadges = computed<Record<string, StudioConversationBadge>>(() => {
  const badges: Record<string, StudioConversationBadge> = {}
  conversations.value.forEach((conversation) => {
    const running = conversationTaskState.value.runningCounts[conversation.id] || 0
    if (running > 0) {
      badges[conversation.id] = {
        state: 'running',
        label: `处理中 ${running}`,
        count: running,
      }
      return
    }
    const notice = conversationNotices.value[conversation.id]
    if (notice === 'done') {
      badges[conversation.id] = { state: 'done', label: '已完成' }
    } else if (notice === 'error') {
      badges[conversation.id] = { state: 'error', label: '失败' }
    }
  })
  return badges
})
const chatModelOptions = computed(() => uniqueStrings(['auto', ...chatModels.value]))
const imageModelOptions = computed(() => uniqueStrings([imageForm.model, DEFAULT_IMAGE_MODEL, ...imageModels.value]))
const videoModelOptions = computed(() => {
  // 有运行时视频模型时带上当前选择；一个都没有则不硬塞默认（视频能力已关闭，避免提交后 503）
  const runtime = videoModels.value
  if (runtime.length > 0) {
    return uniqueStrings([videoModel.value, ...runtime])
  }
  return []
})
const imageUpscaleEnabled = computed(() => Boolean(catalog.value?.capabilities?.image_upscale))

watch(composeMode, (mode) => setStringPreference(preferenceKeys.studioActiveMode, mode))
watch(chatModel, (model) => setStringPreference(preferenceKeys.studioChatModel, model || 'auto'))
watch(chatReasoningEffort, (effort) => setStringPreference(preferenceKeys.studioChatReasoningEffort, effort || ''))
watch(isNarrowStudio, (narrow) => {
  // 回到桌面宽度时强制退出全屏，避免壳层被 fixed 盖住（不写偏好，以免覆盖手机端全屏选择）
  if (!narrow && isFullscreen.value) {
    isFullscreen.value = false
  }
})
watch(sidebarWidth, (value) => setNumberPreference(preferenceKeys.studioSidebarWidth, value))
watch(() => imageForm.model, (model) => {
  setStringPreference(preferenceKeys.studioImageModel, model || DEFAULT_IMAGE_MODEL)
  if (!isImageSizeSupportedByModel(imageForm.size, model, imageUpscaleEnabled.value)) imageForm.size = DEFAULT_IMAGE_SIZE
})
watch(videoModel, (model) => {
  setStringPreference(preferenceKeys.studioVideoModel, model || DEFAULT_VIDEO_MODEL)
})
watch(imageUpscaleEnabled, (upscaleEnabled) => {
  if (!isImageSizeSupportedByModel(imageForm.size, imageForm.model, upscaleEnabled)) imageForm.size = DEFAULT_IMAGE_SIZE
})
// catalog 刷新后：若当前视频模型不在列表里，落到第一个可用
watch(videoModelOptions, (options) => {
  if (!options.length) return
  if (!options.includes(videoModel.value)) {
    videoModel.value = options[0]
  }
})

function normalizeMode(value: string): StudioComposeMode {
  if (value === 'chat' || value === 'search' || value === 'video') return value
  return 'image'
}

function uniqueStrings(values: string[]) {
  return values.map((value) => String(value || '').trim()).filter((value, index, arr) => value && arr.indexOf(value) === index)
}

function buildTitle(content: string) {
  const title = content.trim().replace(/\s+/g, ' ')
  return title.length > 18 ? `${title.slice(0, 18)}...` : title || '新对话'
}

function ensureConversation(content = '') {
  if (activeConversation.value) return activeConversation.value
  return createConversation(content)
}

function createConversation(seed = '') {
  cancelPendingConversationSelection()
  cancelMessageEdit(false)
  const seedText = typeof seed === 'string' ? seed : ''
  const now = new Date().toISOString()
  const conversation: StudioConversation = {
    id: createId('studio'),
    title: seedText ? buildTitle(seedText) : '新对话',
    createdAt: now,
    updatedAt: now,
    messages: [],
  }
  conversations.value = [conversation, ...conversations.value]
  activeConversationId.value = conversation.id
  isMobileHistoryOpen.value = false
  scheduleScrollToBottom()
  return conversation
}

function selectConversation(id: string) {
  if (!id || (activeConversationId.value === id && !pendingConversationSelectId)) return
  pendingConversationSelectId = id
  if (conversationSelectFrameId !== null) return
  conversationSelectFrameId = window.requestAnimationFrame(() => {
    conversationSelectFrameId = null
    const nextId = pendingConversationSelectId
    pendingConversationSelectId = ''
    applyConversationSelection(nextId)
  })
}

function applyConversationSelection(id: string) {
  if (!id || activeConversationId.value === id) return
  if (!conversations.value.some((conversation) => conversation.id === id)) return
  cancelMessageEdit(false)
  activeConversationId.value = id
  clearConversationNotice(id)
  composerError.value = ''
}

function cancelPendingConversationSelection() {
  pendingConversationSelectId = ''
  if (conversationSelectFrameId !== null) {
    window.cancelAnimationFrame(conversationSelectFrameId)
    conversationSelectFrameId = null
  }
}

function renameConversation(id: string, title: string) {
  const conversation = conversations.value.find((item) => item.id === id)
  if (!conversation) return
  const nextTitle = title.trim()
  conversation.title = nextTitle || '新对话'
  touchConversation(conversation)
}

function reorderConversation(sourceId: string, targetId: string) {
  if (!sourceId || !targetId || sourceId === targetId) return
  const sourceIndex = conversations.value.findIndex((item) => item.id === sourceId)
  const targetIndex = conversations.value.findIndex((item) => item.id === targetId)
  if (sourceIndex < 0 || targetIndex < 0) return
  const next = conversations.value.slice()
  const [moved] = next.splice(sourceIndex, 1)
  next.splice(targetIndex, 0, moved)
  conversations.value = next
  schedulePersistConversations()
}

async function deleteConversation(id: string) {
  cancelPendingConversationSelection()
  const conversation = conversations.value.find((item) => item.id === id)
  if (!conversation) return
  const ok = await confirmDialog.ask({
    title: '删除对话',
    message: `确定删除“${conversation.title || '未命名对话'}”吗？本地历史会被移除。`,
    confirmText: '删除',
    cancelText: '取消',
  })
  if (!ok) return
  conversations.value = conversations.value.filter((item) => item.id !== id)
  clearConversationNotice(id)
  if (activeConversationId.value === id) activeConversationId.value = conversations.value[0]?.id || ''
  if (!conversations.value.length) createConversation()
  schedulePersistConversations()
}

async function confirmClearHistory() {
  cancelPendingConversationSelection()
  if (!conversations.value.length) return
  const ok = await confirmDialog.ask({
    title: '清空历史',
    message: '确定清空本地对话画图历史吗？已生成的图片文件不会删除。',
    confirmText: '清空',
    cancelText: '取消',
  })
  if (!ok) return
  cancelMessageEdit()
  conversations.value = []
  imageTasks.value = []
  conversationNotices.value = {}
  activeConversationId.value = ''
  createConversation()
}

async function clearCurrentConversation() {
  const conversation = activeConversation.value
  if (!conversation?.messages.length) return
  const ok = await confirmDialog.ask({
    title: '清空当前对话',
    message: `确定清空“${conversation.title || '未命名对话'}”中的消息吗？`,
    confirmText: '清空',
    cancelText: '取消',
  })
  if (!ok) return
  cancelMessageEdit()
  const taskIds = new Set(
    conversation.messages.map((message) => message.taskId).filter((id): id is string => Boolean(id)),
  )
  conversation.messages = []
  conversation.title = '新对话'
  clearConversationNotice(conversation.id)
  touchConversation(conversation)
  // 只清当前会话关联任务，保留其它会话的图任务缓存
  if (taskIds.size) {
    imageTasks.value = imageTasks.value.filter((task) => !taskIds.has(task.id))
  }
  composerError.value = ''
  scheduleScrollToBottom()
}

function deleteMessage(messageId: string) {
  const conversation = activeConversation.value
  if (!conversation) return
  if (editingMessageId.value === messageId) cancelMessageEdit()
  conversation.messages = conversation.messages.filter((message) => message.id !== messageId)
  touchConversation(conversation)
}

function retryMessage(message: StudioMessage) {
  cancelMessageEdit(false)
  fillComposerFromMessage(message)
}

function editMessage(message: StudioMessage) {
  const target = findConversationMessage(message.id)
  if (!target || target.message.role !== 'user') return
  activeConversationId.value = target.conversation.id
  editingMessageId.value = message.id
  composerText.value = target.message.content
  composeMode.value = target.message.mode
  composerError.value = ''
  clearReferences()
  scheduleScrollToBottom()
}

async function resendMessage(message: StudioMessage) {
  if (isSending.value || isStreaming.value) return
  cancelMessageEdit(false)
  fillComposerFromMessage(message)
  await nextTick()
  await sendMessage()
}

async function retryAssistantMessage(message: StudioMessage) {
  if (isSending.value || isStreaming.value) return
  const target = findConversationMessage(message.id)
  if (!target) return
  const { conversation, index } = target
  const previousUserMessage = conversation.messages
    .slice(0, index)
    .reverse()
    .find((item) => item.role === 'user' && item.content.trim())
  if (!previousUserMessage) return
  activeConversationId.value = conversation.id
  conversation.messages = conversation.messages.slice(0, index)
  composerError.value = ''
  clearConversationNotice(conversation.id)
  touchConversation(conversation)
  isSending.value = true
  try {
    if (previousUserMessage.mode === 'chat') {
      await sendTextMessage(conversation)
    } else if (previousUserMessage.mode === 'search') {
      await sendSearchMessage(conversation, previousUserMessage.content)
    } else if (previousUserMessage.mode === 'video') {
      await sendImageMessage(conversation, previousUserMessage.content, [], 'video')
    } else {
      await sendImageMessage(conversation, previousUserMessage.content, [], 'image')
    }
  } catch (error) {
    const mode = previousUserMessage.mode
    const retryError = errorMessage(error, modeRetryErrorFallback(mode))
    composerError.value = retryError
    markConversationNotice(conversation.id, 'error')
    addMessage(conversation, {
      role: 'assistant',
      mode,
      content: retryError,
      status: 'error',
      error: retryError,
    })
  } finally {
    isSending.value = false
    scheduleScrollToBottom()
  }
}

function findConversationMessage(messageId: string) {
  if (!messageId) return null
  for (const conversation of conversations.value) {
    const index = conversation.messages.findIndex((item) => item.id === messageId)
    if (index >= 0) return { conversation, index, message: conversation.messages[index] }
  }
  return null
}

function cancelMessageEdit(clearComposer = true) {
  editingMessageId.value = ''
  composerError.value = ''
  if (clearComposer) composerText.value = ''
}

function fillComposerFromMessage(message: StudioMessage) {
  composerText.value = message.content
  composeMode.value = message.mode
  if (message.mode === 'video' && message.model) {
    videoModel.value = message.model
  } else if (message.mode === 'image' && message.model) {
    imageForm.model = message.model
  }
  composerError.value = ''
}


function addMessage(conversation: StudioConversation, message: Omit<StudioMessage, 'id' | 'createdAt'>) {
  const next: StudioMessage = {
    id: createId('message'),
    createdAt: new Date().toISOString(),
    ...message,
  }
  conversation.messages.push(next)
  const inserted = conversation.messages[conversation.messages.length - 1] || next
  touchConversation(conversation)
  if (conversation.title === '新对话' && message.role === 'user') {
    conversation.title = buildTitle(message.content)
  }
  scheduleScrollToBottom()
  return inserted
}

function touchConversation(conversation: StudioConversation) {
  conversation.updatedAt = new Date().toISOString()
  schedulePersistConversations()
}


async function sendMessage() {
  const content = composerText.value.trim()
  if (!content || isSending.value || isStreaming.value) return

  composerError.value = ''
  if (editingMessageId.value) {
    await sendEditedMessage(content)
    return
  }
  const conversation = ensureConversation(content)
  const mode = composeMode.value
  const files = selectedFiles.value.slice(0, 8)
  addMessage(conversation, {
    role: 'user',
    mode,
    content,
    status: 'done',
    attachments: mode === 'image' && referencePreviews.value.length ? referencePreviews.value.map((file) => file.name) : undefined,
  })
  composerText.value = ''
  isSending.value = true

  try {
    if (mode === 'chat') {
      await sendTextMessage(conversation)
    } else if (mode === 'search') {
      await sendSearchMessage(conversation, content)
    } else if (mode === 'video') {
      // 视频模式：无参考图；任务管线复用图像任务 API（上游按模型路由 video）
      await sendImageMessage(conversation, content, [], 'video')
      clearReferences()
    } else {
      await sendImageMessage(conversation, content, files, 'image')
      clearReferences()
    }
  } catch (error) {
    const message = errorMessage(error, modeRequestErrorFallback(mode))
    composerError.value = message
    markConversationNotice(conversation.id, 'error')
    addMessage(conversation, {
      role: 'assistant',
      mode,
      content: message,
      status: 'error',
      error: message,
    })
  } finally {
    isSending.value = false
    scheduleScrollToBottom()
  }
}

async function sendEditedMessage(content: string) {
  const target = findConversationMessage(editingMessageId.value)
  if (!target || target.message.role !== 'user') {
    editingMessageId.value = ''
    return
  }

  const { conversation, index, message } = target
  const mode = composeMode.value
  const files = selectedFiles.value.slice(0, 8)
  const editedMessage: StudioMessage = {
    ...message,
    mode,
    content,
    status: 'done',
    error: undefined,
    attachments: mode === 'image' && referencePreviews.value.length ? referencePreviews.value.map((file) => file.name) : undefined,
  }

  activeConversationId.value = conversation.id
  conversation.messages = [
    ...conversation.messages.slice(0, index),
    editedMessage,
  ]
  if (!conversation.messages.slice(0, index).some((item) => item.role === 'user')) {
    conversation.title = buildTitle(content)
  }
  editingMessageId.value = ''
  composerText.value = ''
  composerError.value = ''
  clearConversationNotice(conversation.id)
  touchConversation(conversation)
  isSending.value = true

  try {
    if (mode === 'chat') {
      await sendTextMessage(conversation)
    } else if (mode === 'search') {
      await sendSearchMessage(conversation, content)
    } else if (mode === 'video') {
      await sendImageMessage(conversation, content, [], 'video')
      clearReferences()
    } else {
      await sendImageMessage(conversation, content, files, 'image')
      clearReferences()
    }
  } catch (error) {
    const messageText = errorMessage(error, modeRequestErrorFallback(mode))
    composerError.value = messageText
    markConversationNotice(conversation.id, 'error')
    addMessage(conversation, {
      role: 'assistant',
      mode,
      content: messageText,
      status: 'error',
      error: messageText,
    })
  } finally {
    isSending.value = false
    scheduleScrollToBottom()
  }
}

async function sendTextMessage(conversation: StudioConversation) {
  const assistantMessage = addMessage(conversation, {
    role: 'assistant',
    mode: 'chat',
    content: '',
    status: 'streaming',
    model: chatModel.value,
  })
  const controller = new AbortController()
  streamController = controller
  isStreaming.value = true
  let pendingDelta = ''
  let deltaFrameId: number | null = null
  const flushPendingDelta = () => {
    if (deltaFrameId !== null) {
      window.cancelAnimationFrame(deltaFrameId)
      deltaFrameId = null
    }
    if (!pendingDelta) return
    assistantMessage.content += pendingDelta
    pendingDelta = ''
    touchConversation(conversation)
    scheduleScrollToBottom()
  }
  const scheduleDeltaFlush = (delta: string) => {
    pendingDelta += delta
    if (deltaFrameId !== null) return
    deltaFrameId = window.requestAnimationFrame(() => {
      deltaFrameId = null
      flushPendingDelta()
    })
  }

  try {
    await streamChatCompletion({
      model: chatModel.value,
      messages: buildChatMessages(conversation, assistantMessage.id),
      reasoningEffort: chatReasoningEffort.value,
      signal: controller.signal,
      onDelta: (delta) => {
        scheduleDeltaFlush(delta)
      },
    })
    flushPendingDelta()
    assistantMessage.status = 'done'
    if (!assistantMessage.content.trim()) assistantMessage.content = '上游没有返回内容。'
    markConversationNotice(conversation.id, 'done')
  } catch (error) {
    flushPendingDelta()
    if (controller.signal.aborted) {
      assistantMessage.status = 'done'
      if (!assistantMessage.content.trim()) assistantMessage.content = '已停止。'
      markConversationNotice(conversation.id, 'done')
      return
    }
    const message = errorMessage(error, '对话请求失败')
    assistantMessage.status = 'error'
    assistantMessage.error = message
    assistantMessage.content = assistantMessage.content.trim() ? `${assistantMessage.content}\n\n${message}` : message
    markConversationNotice(conversation.id, 'error')
  } finally {
    flushPendingDelta()
    isStreaming.value = false
    streamController = null
    touchConversation(conversation)
  }
}

function buildChatMessages(conversation: StudioConversation, currentAssistantId: string): DebugChatMessage[] {
  return conversation.messages
    .filter((message) => {
      if (message.id === currentAssistantId) return false
      if (message.error) return false
      if (!message.content.trim()) return false
      if (message.role === 'assistant' && message.mode !== 'chat' && message.mode !== 'search') return false
      return true
    })
    .map((message): DebugChatMessage => ({
      role: message.role === 'assistant' ? 'assistant' : 'user',
      content: buildChatContextContent(message),
    }))
    .slice(-32)
}

function buildChatContextContent(message: StudioMessage) {
  if (message.role === 'user' && message.mode === 'image') return `画图请求：${message.content}`
  if (message.role === 'user' && message.mode === 'video') return `视频请求：${message.content}`
  if (message.role === 'user' && message.mode === 'search') return `搜索请求：${message.content}`
  return message.content
}

async function sendSearchMessage(conversation: StudioConversation, prompt: string) {
  const assistantMessage = addMessage(conversation, {
    role: 'assistant',
    mode: 'search',
    content: '正在搜索...',
    status: 'sending',
    model: 'search',
  })

  try {
    const result = await debugApi.search(prompt)
    const sources = normalizeSearchSources(result.sources)
    assistantMessage.searchSources = sources
    assistantMessage.searchImageGroups = normalizeSearchImageGroups(result.image_groups) || extractSearchImageGroupsFromText(result.answer)
    assistantMessage.content = formatSearchResult(result, assistantMessage.id, sources?.length || 0)
    assistantMessage.status = 'done'
    markConversationNotice(conversation.id, 'done')
  } catch (error) {
    const message = errorMessage(error, '搜索请求失败')
    assistantMessage.status = 'error'
    assistantMessage.content = message
    assistantMessage.error = message
    composerError.value = message
    markConversationNotice(conversation.id, 'error')
  } finally {
    touchConversation(conversation)
    scheduleScrollToBottom()
  }
}

function formatSearchResult(result: DebugSearchResult, ownerId: string, sourceCount: number) {
  const answer = cleanSearchAnswer(result.answer) || '搜索完成，但上游没有返回摘要。'
  return linkSearchCitations(answer, ownerId, sourceCount)
}


async function sendImageMessage(
  conversation: StudioConversation,
  prompt: string,
  files: File[],
  mode: Extract<StudioComposeMode, 'image' | 'video'> = 'image',
) {
  const isVideo = mode === 'video'
  const selectedModel = isVideo
    ? (videoModel.value || DEFAULT_VIDEO_MODEL)
    : (imageForm.model || DEFAULT_IMAGE_MODEL)
  const assistantMessage = addMessage(conversation, {
    role: 'assistant',
    mode,
    content: isVideo
      ? '视频任务已提交'
      : (files.length ? '图像编辑任务已提交' : '图片任务已提交'),
    status: 'queued',
    model: selectedModel,
    imageSize: isVideo ? undefined : imageForm.size,
    imageCount: isVideo ? undefined : normalizeImageCount(imageForm.n),
  })

  let task: ImageTask
  try {
    // 视频模式不走图生图；图像模式有参考图才 createEdit
    // 后端 image_task_service 会按 is_firefly_video_model 路由到 /v1/videos/generations
    task = (!isVideo && files.length)
      ? await imageTasksApi.createEdit({
        prompt,
        files,
        model: selectedModel,
        n: normalizeImageCount(imageForm.n),
        size: imageForm.size,
        quality: imageForm.quality || DEFAULT_IMAGE_QUALITY,
      })
      : await imageTasksApi.createGeneration({
        prompt,
        model: selectedModel,
        n: isVideo ? 1 : normalizeImageCount(imageForm.n),
        size: isVideo ? undefined : imageForm.size,
        quality: isVideo ? undefined : (imageForm.quality || DEFAULT_IMAGE_QUALITY),
      })
  } catch (error) {
    const message = errorMessage(error, isVideo ? '视频任务提交失败' : '图片任务提交失败')
    assistantMessage.status = 'error'
    assistantMessage.content = message
    assistantMessage.error = message
    composerError.value = message
    touchConversation(conversation)
    markConversationNotice(conversation.id, 'error')
    return
  }

  assistantMessage.taskId = task.id
  assistantMessage.status = 'running'
  touchConversation(conversation)
  rememberImageTaskId(task.id)
  mergeImageTasks([task])
  toast.success(isVideo ? '视频任务已提交' : '图片任务已提交')
  scheduleImagePoll()
}

function stopStreaming() {
  streamController?.abort()
}

function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value
  // 仅用户手动切换时持久化，布局强制退出不写偏好
  setBooleanPreference(preferenceKeys.studioFullscreen, isFullscreen.value)
  void nextTick(scrollToBottom)
}


function modeRequestErrorFallback(mode: StudioComposeMode) {
  if (mode === 'image') return '图片生成失败'
  if (mode === 'video') return '视频生成失败'
  if (mode === 'search') return '搜索请求失败'
  return '对话请求失败'
}

function modeRetryErrorFallback(mode: StudioComposeMode) {
  if (mode === 'image') return '图片重新生成失败'
  if (mode === 'video') return '视频重新生成失败'
  if (mode === 'search') return '搜索重新请求失败'
  return '对话重新生成失败'
}

function errorMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) return error.message
  if (error && typeof error === 'object' && 'message' in error) return String((error as { message?: unknown }).message || fallback)
  return fallback
}

function isImageFile(file: File) {
  return file.type.startsWith('image/') || /\.(avif|bmp|gif|heic|heif|ico|jpe?g|png|svg|tiff?|webp)$/i.test(file.name)
}

function readFileAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(new Error('读取参考图失败'))
    reader.readAsDataURL(file)
  })
}

async function appendFiles(files: File[]) {
  const imageFiles = files.filter(isImageFile).slice(0, Math.max(0, 8 - selectedFiles.value.length))
  if (!imageFiles.length) return
  for (const file of imageFiles) {
    selectedFiles.value.push(file)
    referencePreviews.value.push({
      id: createId('source'),
      name: file.name || '参考图',
      type: file.type || 'image/png',
      size: file.size,
      dataUrl: await readFileAsDataUrl(file),
    })
  }
  composeMode.value = 'image'
}

function removeReference(index: number) {
  selectedFiles.value.splice(index, 1)
  referencePreviews.value.splice(index, 1)
}

function clearReferences() {
  selectedFiles.value = []
  referencePreviews.value = []
}

function previewReference(reference: StudioReference) {
  if (!reference.dataUrl) return
  previewImage.value = {
    src: reference.dataUrl,
    name: reference.name,
  }
}

function openPreview(src: string, name: string, localPath = '') {
  if (!src) return
  previewImage.value = { src, name, localPath }
}

function openPromptPicker() {
  isPromptPickerOpen.value = true
}

function applyPromptTemplate(prompt: PromptLibraryItem) {
  composerText.value = prompt.prompt
  if (composeMode.value === 'image') {
    if (prompt.image_model) imageForm.model = prompt.image_model
    if (prompt.image_size) imageForm.size = prompt.image_size
    if (prompt.image_count && prompt.image_count > 0) imageForm.n = prompt.image_count
  }
  isPromptPickerOpen.value = false
}

function openImageCompare(before: StudioPreviewImage, after: StudioPreviewImage) {
  if (!before?.src || !after?.src) return
  comparePreview.value = { before, after }
}

async function copyText(value: string) {
  if (!value) return
  try {
    await navigator.clipboard.writeText(value)
    toast.success('已复制')
  } catch {
    toast.error('复制失败')
  }
}

async function downloadPreviewImage() {
  if (!previewImage.value) return
  try {
    await downloadUrlAsFile(previewImage.value.src, previewImage.value.name || 'image.png', { localPath: previewImage.value.localPath })
    toast.success('已开始下载')
  } catch (error: any) {
    toast.error(`下载失败：${error.message || '无法读取图片文件'}`)
  }
}

function scrollToBottom() {
  void messageListRef.value?.scrollToBottom()
}

function scheduleScrollToBottom() {
  if (!isStudioActive) return
  if (scrollScheduled) return
  const requestToken = ++scrollRequestToken
  scrollScheduled = true
  void nextTick(() => {
    if (scrollFrameId !== null) return
    scrollFrameId = window.requestAnimationFrame(() => {
      scrollFrameId = null
      scrollScheduled = false
      if (requestToken !== scrollRequestToken || !isStudioActive) return
      scrollToBottom()
    })
  })
}

function startSidebarResize(event: PointerEvent) {
  event.preventDefault()
  ;(event.currentTarget as HTMLElement | null)?.setPointerCapture?.(event.pointerId)
  sidebarResizeStartX = event.clientX
  sidebarResizeStartWidth = sidebarWidth.value
  document.body.classList.add('studio-resizing')
  window.addEventListener('pointermove', handleSidebarResize)
  window.addEventListener('pointerup', stopSidebarResize, { once: true })
  window.addEventListener('pointercancel', stopSidebarResize, { once: true })
}

function handleSidebarResize(event: PointerEvent) {
  const nextWidth = sidebarResizeStartWidth + event.clientX - sidebarResizeStartX
  sidebarWidth.value = Math.min(380, Math.max(220, Math.round(nextWidth)))
}

function stopSidebarResize() {
  document.body.classList.remove('studio-resizing')
  window.removeEventListener('pointermove', handleSidebarResize)
  window.removeEventListener('pointerup', stopSidebarResize)
  window.removeEventListener('pointercancel', stopSidebarResize)
}

function cancelScheduledScroll() {
  scrollRequestToken += 1
  if (scrollFrameId !== null) {
    window.cancelAnimationFrame(scrollFrameId)
    scrollFrameId = null
  }
  scrollScheduled = false
}

function stopTransientStudioUi() {
  stopSidebarResize()
  cancelPendingConversationSelection()
  cancelScheduledScroll()
}

function ensureActiveConversation() {
  if (!conversations.value.length) {
    createConversation()
  } else if (!activeConversationId.value || !conversations.value.some((item) => item.id === activeConversationId.value)) {
    activeConversationId.value = conversations.value[0]?.id || ''
  }
}

function initializeStudio() {
  ensureActiveConversation()
  if (!settingsStore.settings && !settingsStore.isLoading) {
    void settingsStore.loadSettings()
  }
  void loadModelCatalog()
  void refreshImageTasks()
  void preloadPromptLibrary()
  scheduleScrollToBottom()
}

function activateStudio() {
  isStudioActive = true
  void refreshImageTasks()
  scheduleImagePoll()
  scheduleScrollToBottom()
}

function deactivateStudio() {
  isStudioActive = false
  clearImageTimers()
  stopTransientStudioUi()
  flushAllPersistence()
}

function disposeStudio() {
  deactivateStudio()
  streamController?.abort()
}

onMounted(() => {
  // useMediaQuery 已在 setup 注册，此处 matches 已同步；仅手机端恢复全屏偏好
  if (isNarrowStudio.value && getBooleanPreference(preferenceKeys.studioFullscreen, false)) {
    isFullscreen.value = true
  }
  initializeStudio()
})

onActivated(() => {
  if (!hasActivatedOnce) {
    hasActivatedOnce = true
    return
  }
  activateStudio()
})

onDeactivated(() => {
  deactivateStudio()
})

onBeforeUnmount(() => {
  disposeStudio()
})
</script>

<style scoped>
.studio-workspace {
  --studio-content-width: min(100%, 88rem);
  --ui-card-border: hsl(var(--border));
  --ui-card-bg: hsl(var(--card));
  --ui-panel-border: hsl(var(--border));
  --ui-panel-bg: hsl(var(--card));
  --ui-control-border: hsl(var(--border));
  --ui-control-bg: hsl(var(--background));
  --ui-control-hover-bg: hsl(var(--secondary));
  --ui-control-hover-border: hsl(var(--foreground) / 0.16);
  --ui-fg-strong: hsl(var(--foreground));
  --ui-fg-muted: hsl(var(--muted-foreground));
  --ui-fg-subtle: hsl(var(--muted-foreground));
  --ui-accent: hsl(var(--foreground));
  --ui-accent-soft: hsl(var(--secondary));
  --ui-accent-strong: hsl(var(--foreground));
  --ui-accent-border: hsl(var(--border));
  --ui-accent-border-strong: hsl(var(--foreground) / 0.22);
  --ui-accent-ring: hsl(var(--foreground) / 0.10);
  --ui-active-border: hsl(var(--foreground) / 0.22);
  --ui-active-bg: hsl(var(--secondary));
  --ui-active-fg: hsl(var(--foreground));
  --ui-divider: hsl(var(--border));
  --ui-danger-fg: rgb(220 38 38);
  --ui-danger-bg: rgb(254 242 242 / 0.88);
  --ui-danger-border: rgb(248 113 113 / 0.35);
  --ui-duration-fast: 150ms;
  --ui-duration-normal: 220ms;
  --ui-ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  display: grid;
  box-sizing: border-box;
  /* immersive 父级已满高：用 100% 填内容区，避免 calc(100dvh-11rem) 在壳内再扣一次产生底部空白 */
  height: 100%;
  min-height: 0;
  grid-template-columns: var(--studio-history-width) minmax(0, 1fr);
  gap: 0.75rem;
  overflow: hidden;
}

.studio-workspace.is-fullscreen {
  position: fixed;
  inset: 0;
  z-index: 180;
  height: 100dvh;
  min-height: 0;
  background: hsl(var(--background));
  padding-top: max(1rem, env(safe-area-inset-top, 0px));
  padding-right: max(1.25rem, env(safe-area-inset-right, 0px));
  padding-bottom: max(1.25rem, env(safe-area-inset-bottom, 0px));
  padding-left: max(1.25rem, env(safe-area-inset-left, 0px));
}

.studio-sidebar-wrap {
  position: relative;
  min-width: 0;
  min-height: 0;
}

.studio-history-resizer {
  display: none;
  position: absolute;
  top: 0;
  right: -0.5rem;
  bottom: 0;
  z-index: 10;
  width: 0.75rem;
  cursor: col-resize;
  border-radius: var(--radius);
  touch-action: none;
  transition: background 0.15s;
}

.studio-history-resizer::before {
  position: absolute;
  top: 0.75rem;
  bottom: 0.75rem;
  left: 50%;
  width: 2px;
  transform: translateX(-50%);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--bauhaus-ink) 55%, transparent);
  content: '';
  opacity: 0;
  transition: opacity 0.15s, background 0.15s;
}

.studio-history-resizer:hover {
  background: transparent;
}

.studio-history-resizer:hover::before,
:global(.studio-resizing) .studio-history-resizer::before {
  background: var(--bauhaus-blue);
  opacity: 1;
}

.studio-main {
  position: relative;
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  border: 2px solid var(--bauhaus-ink, hsl(var(--border)));
  border-radius: var(--radius);
  background: hsl(var(--card) / 0.88);
  box-shadow: var(--shadow-hard-sm);
}

html[data-theme='dark'] .studio-main {
  box-shadow: var(--shadow-hard-soft);
}

.chat-header-bar {
  display: flex;
  min-height: 3.5rem;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  border-bottom: 1px solid hsl(var(--border));
  background: hsl(var(--card) / 0.84);
  padding: 0.625rem 0.875rem;
}

.chat-header-title {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.5rem;
}

.chat-header-name {
  min-width: 0;
  max-width: min(32rem, 48vw);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: hsl(var(--foreground));
  font-size: 0.875rem;
  font-weight: 700;
}

.chat-header-subtitle {
  margin-top: 0.125rem;
  color: hsl(var(--muted-foreground));
  font-size: 0.75rem;
  line-height: 1rem;
}

.chat-header-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 0.375rem;
}

.chat-header-action-button,
.chat-header-icon {
  border-radius: var(--radius);
}

:global(.studio-resizing) {
  cursor: col-resize;
  user-select: none;
}

@media (min-width: 1024px) {
  .studio-history-resizer {
    display: block;
  }
}

@media (max-width: 1023px) {
  .studio-workspace {
    height: 100%;
    min-height: 0;
    grid-template-columns: minmax(0, 1fr);
  }

  .studio-sidebar-wrap {
    display: none;
  }

  .studio-workspace.is-fullscreen {
    height: 100dvh;
  }

  .chat-header-name {
    max-width: 42vw;
  }

  .chat-header-bar {
    min-height: 3.15rem;
    padding: 0.5rem 0.7rem;
  }

}
</style>
