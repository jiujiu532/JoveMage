<template>
  <section class="studio-chat-panel" :class="{ 'is-fullscreen': fullscreen }">
    <div ref="scrollEl" class="studio-chat-scroll custom-scrollbar" @scroll="handleScroll">
      <div v-if="!displayedConversation || !displayedConversation.messages.length" class="studio-chat-empty">
        <h1>对话画图</h1>
        <p>输入文字可以直接对话；切到画图后，在同一个窗口里生成图片、上传参考图和继续编辑。</p>
      </div>

      <div v-else class="studio-turns">
        <div v-if="hiddenMessageCount > 0" class="studio-load-earlier-row">
          <button type="button" class="studio-load-earlier-button" @click="showOlderMessages">
            显示更早消息（{{ hiddenMessageCount }} 条）
          </button>
        </div>

        <article
          v-for="message in messageViews"
          :key="message.id"
          v-memo="[message.memoKey]"
          class="chat-message-row"
          :class="message.role === 'user' ? 'is-user' : 'is-assistant'"
        >
          <div
            class="chat-message-container"
            :class="[
              message.role === 'user' ? 'is-user' : 'is-assistant',
              message.isImageMessage ? 'is-image-message' : '',
              message.isPendingImageMessage ? 'is-pending-image-message' : '',
            ]"
          >
            <div
              class="chat-message-avatar"
              :class="message.role === 'user' ? 'chat-message-avatar-user' : 'chat-message-avatar-assistant'"
              aria-hidden="true"
            >
              <!-- ChatGPT / OpenAI mark -->
              <svg
                v-if="message.role === 'assistant'"
                class="chat-message-avatar-mark"
                viewBox="0 0 24 24"
                width="16"
                height="16"
                fill="currentColor"
              >
                <path d="M22.282 9.821a5.985 5.985 0 0 0-.516-4.91 6.046 6.046 0 0 0-6.51-2.9A6.065 6.065 0 0 0 4.981 4.18a5.985 5.985 0 0 0-3.998 2.9 6.046 6.046 0 0 0 .743 7.097 5.98 5.98 0 0 0 .51 4.911 6.051 6.051 0 0 0 6.515 2.9A5.985 5.985 0 0 0 13.26 24a6.056 6.056 0 0 0 5.772-4.206 5.99 5.99 0 0 0 3.997-2.9 6.056 6.056 0 0 0-.747-7.073zM13.26 22.43a4.476 4.476 0 0 1-2.876-1.04l.141-.081 4.779-2.758a.795.795 0 0 0 .392-.681v-6.737l2.02 1.168a.071.071 0 0 1 .038.052v5.583a4.504 4.504 0 0 1-4.494 4.494zM3.6 18.304a4.47 4.47 0 0 1-.535-3.014l.142.085 4.783 2.759a.771.771 0 0 0 .78 0l5.843-3.369v2.332a.08.08 0 0 1-.033.062L9.74 19.95a4.5 4.5 0 0 1-6.14-1.646zM2.34 7.896a4.485 4.485 0 0 1 2.366-1.973V11.6a.766.766 0 0 0 .388.676l5.815 3.355-2.02 1.168a.076.076 0 0 1-.071 0l-4.83-2.786A4.504 4.504 0 0 1 2.34 7.872zm16.597 3.855l-5.833-3.387L15.119 7.2a.076.076 0 0 1 .071 0l4.83 2.791a4.494 4.494 0 0 1-.676 8.105v-5.678a.79.79 0 0 0-.407-.667zm2.01-3.023l-.141-.085-4.774-2.782a.776.776 0 0 0-.785 0L9.409 9.23V6.897a.066.066 0 0 1 .028-.061l4.83-2.787a4.5 4.5 0 0 1 6.68 4.66zm-12.64 4.135l-2.02-1.164a.08.08 0 0 1-.038-.057V6.075a4.5 4.5 0 0 1 7.375-3.453l-.142.08L8.704 5.46a.795.795 0 0 0-.393.681zm1.097-2.365 2.602-1.5 2.607 1.5v2.999l-2.597 1.5-2.607-1.5z" />
              </svg>
              <!-- Bauhaus user monogram -->
              <svg
                v-else
                class="chat-message-avatar-mark"
                viewBox="0 0 24 24"
                width="15"
                height="15"
                fill="none"
              >
                <circle cx="12" cy="8.2" r="3.4" fill="currentColor" />
                <path d="M5.2 19.2c.7-3.4 3.2-5.2 6.8-5.2s6.1 1.8 6.8 5.2" stroke="currentColor" stroke-width="2.2" stroke-linecap="square" />
              </svg>
            </div>

            <div class="chat-message-main">
              <div class="chat-message-bubble-wrap">
                <div
                  class="chat-message-bubble"
                  :class="[
                    message.role === 'user' ? 'chat-message-bubble-user' : 'chat-message-bubble-assistant',
                    message.isImageMessage ? 'chat-message-bubble-image' : '',
                    message.isPendingImageMessage ? 'chat-message-bubble-image-pending' : '',
                    message.status === 'error' ? 'chat-message-bubble-error' : '',
                  ]"
                  :style="message.imagePreviewStyle"
                >
                  <div
                    class="chat-message-content"
                    :class="{
                      'is-collapsible': message.isCollapsible,
                      'is-collapsed': message.isCollapsed,
                    }"
                  >
                    <template v-if="message.role === 'user'">
                      <p v-if="message.content" class="studio-user-prompt">{{ message.content }}</p>
                      <div v-if="message.attachments?.length" class="studio-attachment-line">
                        <Icon icon="lucide:paperclip" class="h-3.5 w-3.5" />
                        {{ message.attachments.join('、') }}
                      </div>
                    </template>

                    <template v-else-if="message.mode !== 'image'">
                      <StudioMarkdownContent
                        v-if="message.content || message.status === 'streaming'"
                        :content="message.content || ' '"
                        @citation-click="scrollToCitationSource"
                      />
                      <span v-if="message.status === 'streaming'" class="studio-cursor"></span>
                      <p v-if="message.error && !message.content.includes(message.error)" class="studio-error-text">
                        {{ message.error }}
                      </p>
                      <button
                        v-if="message.mode === 'search' && message.searchSources?.length"
                        type="button"
                        class="studio-search-source-chip"
                        @click="openSearchSourcePanel(message)"
                      >
                        <Icon icon="lucide:link" class="studio-search-source-chip-icon h-3.5 w-3.5" />
                        <span class="studio-search-source-chip-label">参考来源</span>
                        <strong>{{ message.searchSources.length }}</strong>
                        <small>查看</small>
                      </button>
                      <div v-if="message.mode === 'search' && message.searchImageGroups?.length" class="studio-search-image-groups">
                        <div
                          v-for="(group, groupIndex) in message.searchImageGroups"
                          :key="`${message.id}-image-group-${groupIndex}`"
                          class="studio-search-image-group"
                        >
                          <span class="studio-search-image-group-title">
                            <Icon icon="lucide:image" class="h-3.5 w-3.5" />
                            图片参考<span v-if="group.aspectRatio"> {{ group.aspectRatio }}</span>
                          </span>
                          <span class="studio-search-image-group-queries">
                            <span v-for="query in group.queries" :key="query" class="studio-search-image-query">{{ query }}</span>
                          </span>
                        </div>
                      </div>
                    </template>

                    <template v-else>
                      <template v-if="!message.task || message.task.status === 'queued' || message.task.status === 'running'">
                        <div class="studio-result-block studio-result-block-pending">
                          <div class="studio-result-grid" :class="{ 'is-single': message.imageSlotCount <= 1 }">
                            <div
                              v-for="slot in message.pendingSlots"
                              :key="`${message.id}-pending-${slot}`"
                              class="studio-result-item"
                            >
                              <div class="studio-result-media studio-result-placeholder">
                                <Icon icon="lucide:loader-circle" class="h-5 w-5 animate-spin" />
                                <span>正在处理图片</span>
                                <small>{{ message.imagePendingStageText }}</small>
                              </div>
                              <div v-if="message.imageSlotCount > 1" class="studio-result-caption">
                                <span>图片 {{ slot + 1 }}</span>
                              </div>
                            </div>
                          </div>
                        </div>
                      </template>

                      <template v-else>
                        <div v-if="message.task?.status === 'error'" class="studio-image-status is-error">
                          <Icon icon="lucide:circle-alert" class="h-4 w-4" />
                          <span>{{ message.primaryMessage || '上游没有返回可用图片。' }}</span>
                        </div>

                        <div v-else class="studio-result-block">
                          <div class="studio-result-grid" :class="{ 'is-single': message.assets.length <= 1 }">
                            <div
                              v-for="(asset, assetIndex) in message.assets"
                              :key="`${message.id}-${assetIndex}`"
                              class="studio-result-item"
                            >
                              <button
                                type="button"
                                class="studio-result-media"
                                :class="{ 'has-image': Boolean(assetUrl(asset)) }"
                                @click="emit('preview', assetUrl(asset), `结果 ${assetIndex + 1}`, String(asset.path || ''))"
                              >
                                <img v-if="assetUrl(asset)" :src="assetUrl(asset)" :alt="`结果 ${assetIndex + 1}`" loading="lazy" />
                                <span v-else>无图片 URL</span>
                              </button>
                              <div v-if="message.assets.length > 1" class="studio-result-caption">
                                <span>结果 {{ assetIndex + 1 }}</span>
                                <button
                                  v-if="assetIndex > 0"
                                  type="button"
                                  class="chat-input-action studio-result-compare"
                                  title="对比结果 1"
                                  aria-label="对比结果 1"
                                  @click.stop="emitCompareImage(message, 0, assetIndex)"
                                >
                                  <Icon icon="lucide:columns-2" class="h-3.5 w-3.5" />
                                  <span>对比</span>
                                </button>
                              </div>
                            </div>
                          </div>
                        </div>
                      </template>
                    </template>
                  </div>

                  <button
                    v-if="message.isCollapsible"
                    type="button"
                    class="chat-message-expand"
                    @click.stop="toggleMessageExpanded(message)"
                  >
                    {{ message.isCollapsed ? '展开全部' : '收起' }}
                    <Icon :icon="message.isCollapsed ? 'lucide:chevron-down' : 'lucide:chevron-up'" class="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>

              <div class="chat-message-actions">
                <button
                  v-for="action in messageActions(message)"
                  :key="action.key"
                  type="button"
                  class="chat-input-action chat-message-action"
                  :class="{ 'chat-message-action-danger': action.danger }"
                  :title="action.label"
                  :aria-label="action.label"
                  @click="handleMessageAction(action.key, message)"
                >
                  <span class="icon"><Icon :icon="action.icon" class="h-3.5 w-3.5" /></span>
                  <span class="text">{{ action.label }}</span>
                </button>
              </div>
            </div>
          </div>
        </article>
      </div>
    </div>

    <button
      v-if="showScrollLatest"
      type="button"
      class="studio-scroll-latest"
      aria-label="滚动到最新消息"
      title="滚动到最新消息"
      @click="scrollToBottom"
    >
      <Icon icon="lucide:arrow-down" class="h-5 w-5" />
    </button>

    <Transition name="studio-search-drawer-fade">
      <div
        v-if="activeSearchSourceMessage"
        class="studio-search-drawer-backdrop"
        @click="closeSearchSourcePanel"
      ></div>
    </Transition>

    <Transition name="studio-search-drawer-slide">
      <aside
        v-if="activeSearchSourceMessage"
        class="studio-search-drawer"
        role="dialog"
        aria-label="参考来源"
      >
        <header class="studio-search-drawer-header">
          <div>
            <strong>参考来源</strong>
            <small>{{ activeSearchSourceMessage.searchSources?.length || 0 }} 条网页结果</small>
          </div>
          <button
            type="button"
            class="studio-search-drawer-close"
            aria-label="关闭参考来源"
            title="关闭"
            @click="closeSearchSourcePanel"
          >
            <Icon icon="lucide:x" class="h-4 w-4" />
          </button>
        </header>

        <div class="studio-search-drawer-body custom-scrollbar">
          <a
            v-for="(source, sourceIndex) in activeSearchSourceMessage.searchSources"
            :key="`${activeSearchSourceMessage.id}-panel-source-${sourceIndex}`"
            :id="searchSourceDomId(activeSearchSourceMessage.id, sourceIndex)"
            class="studio-search-source-card"
            :class="{ 'is-static': !source.url, 'is-highlighted': highlightedSearchSourceId === searchSourceDomId(activeSearchSourceMessage.id, sourceIndex) }"
            :href="source.url || undefined"
            :target="source.url ? '_blank' : undefined"
            :rel="source.url ? 'noreferrer' : undefined"
            @click="!source.url && $event.preventDefault()"
          >
            <span class="studio-search-source-index">{{ sourceIndex + 1 }}</span>
            <span class="studio-search-source-body">
              <strong>{{ sourceTitle(source, sourceIndex) }}</strong>
              <small v-if="sourceHost(source.url)">{{ sourceHost(source.url) }}</small>
              <em v-if="source.snippet">{{ source.snippet }}</em>
            </span>
            <Icon v-if="source.url" icon="lucide:external-link" class="studio-search-source-open h-3.5 w-3.5" />
          </a>
        </div>
      </aside>
    </Transition>
  </section>
</template>

<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, ref, shallowRef, watch, type CSSProperties } from 'vue'
import {
  imageAssetUrl,
  imageTaskProgressLabel,
  parseImageSize,
  taskPrimaryMessage,
  type ImageTask,
  type ImageTaskAsset,
} from '@/api/imageTasks'
import type { StudioConversation, StudioMessage, StudioPreviewImage, StudioSearchImageGroup, StudioSearchSource } from './types'

const StudioMarkdownContent = defineAsyncComponent(() => import('./StudioMarkdownContent.vue'))

const props = defineProps<{
  conversation: StudioConversation | null
  conversationsCount: number
  tasks: ImageTask[]
  fullscreen: boolean
}>()

const emit = defineEmits<{
  create: []
  'open-history': []
  'toggle-fullscreen': []
  retry: [message: StudioMessage]
  edit: [message: StudioMessage]
  resend: [message: StudioMessage]
  'retry-assistant': [message: StudioMessage]
  'delete-message': [messageId: string]
  'copy-message': [content: string]
  preview: [src: string, name: string, localPath?: string]
  'compare-image': [before: StudioPreviewImage, after: StudioPreviewImage]
}>()

type MessageActionKey = 'copy' | 'edit' | 'resend' | 'fill' | 'retry' | 'delete'
interface MessageAction {
  key: MessageActionKey
  label: string
  icon: string
  danger?: boolean
}

type StudioMessageView = StudioMessage & {
  memoKey: string
  task?: ImageTask
  assets: ImageTaskAsset[]
  isImageMessage: boolean
  isPendingImageMessage: boolean
  imageSlotCount: number
  pendingSlots: number[]
  imagePendingStageText: string
  primaryMessage: string
  imagePreviewStyle?: CSSProperties
  isCollapsible: boolean
  isCollapsed: boolean
}

type MessageViewSignatureValue = string | number | boolean | null | undefined
type MessageViewSignature = MessageViewSignatureValue[]

const INITIAL_MESSAGE_LIMIT = 32
const MESSAGE_BATCH_SIZE = 24
const MAX_MESSAGE_VIEW_CACHE_SIZE = 480
const MAX_STRING_SIGNATURE_CACHE_SIZE = 480

const scrollEl = ref<HTMLElement | null>(null)
const showScrollLatest = ref(false)
const visibleMessageLimit = ref(INITIAL_MESSAGE_LIMIT)
const expandedMessageIds = ref<Set<string>>(new Set())
const collapsedMessageIds = ref<Set<string>>(new Set())
const highlightedSearchSourceId = ref('')
const searchPanelMessageId = ref('')
const displayedConversation = shallowRef<StudioConversation | null>(props.conversation)
const messageViewCache = new Map<string, { signature: MessageViewSignature; revision: number; view: StudioMessageView }>()
const stringSignatureCache = new Map<string, { value: string; signature: string }>()
let conversationRenderFrameId: number | null = null
let conversationRenderToken = 0
let scrollLatestFrameId: number | null = null
let scrollLatestToken = 0
let searchSourceHighlightTimer: number | null = null

const taskById = computed(() => new Map(props.tasks.map((task) => [task.id, task])))
const allMessages = computed(() => displayedConversation.value?.messages || [])
const visibleMessages = computed(() => {
  const messages = allMessages.value
  if (messages.length <= visibleMessageLimit.value) return messages
  const recentStart = Math.max(0, messages.length - visibleMessageLimit.value)
  return messages.filter((message, index) => index >= recentStart || isLiveMessage(message))
})
const hiddenMessageCount = computed(() => Math.max(0, allMessages.value.length - visibleMessages.value.length))
const messageViews = computed(() => {
  return visibleMessages.value.map((message) => buildMessageView(message))
})
const activeSearchSourceMessage = computed(() => {
  if (!searchPanelMessageId.value) return null
  return allMessages.value.find((message) => message.id === searchPanelMessageId.value && message.searchSources?.length) || null
})

function buildMessageView(message: StudioMessage): StudioMessageView {
  const task = message.taskId ? taskById.value.get(message.taskId) : undefined
  const assets = task?.data?.length ? task.data.filter((asset) => Boolean(assetUrl(asset))) : []
  const isImageMessage = message.role === 'assistant' && message.mode === 'image'
  const imageSlotCount = computeImageSlotCount(message, task, assets.length)
  const isCollapsible = computeIsCollapsibleMessage(message)
  const isCollapsed = isCollapsible ? computeIsMessageCollapsed(message) : false
  const signature = messageViewSignature(message, task, assets, imageSlotCount, isCollapsed, isCollapsible)
  const cached = messageViewCache.get(message.id)
  if (cached && sameMessageViewSignature(cached.signature, signature)) {
    messageViewCache.delete(message.id)
    messageViewCache.set(message.id, cached)
    return cached.view
  }
  const revision = (cached?.revision || 0) + 1
  const view: StudioMessageView = {
    ...message,
    memoKey: `${message.id}:${revision}`,
    task,
    assets,
    isImageMessage,
    isPendingImageMessage: isImageMessage && (!task || (task.status !== 'success' && task.status !== 'error' && assets.length === 0)),
    imageSlotCount,
    pendingSlots: Array.from({ length: imageSlotCount }, (_, index) => index),
    imagePendingStageText: imageTaskProgressLabel(task),
    primaryMessage: taskPrimaryMessage(task),
    imagePreviewStyle: isImageMessage ? buildImagePreviewStyle(message, task, imageSlotCount) : undefined,
    isCollapsible,
    isCollapsed,
  }
  messageViewCache.set(message.id, { signature, revision, view })
  trimStringKeyCache(messageViewCache, MAX_MESSAGE_VIEW_CACHE_SIZE)
  return view
}

function messageViewSignature(
  message: StudioMessage,
  task: ImageTask | undefined,
  assets: ImageTaskAsset[],
  imageSlotCount: number,
  isCollapsed: boolean,
  isCollapsible: boolean,
): MessageViewSignature {
  return [
    message.id,
    message.role,
    message.mode,
    compactStringSignature(message.content, `${message.id}:content`),
    message.createdAt,
    message.status,
    message.model,
    message.imageSize,
    message.imageCount,
    message.taskId,
    compactStringSignature(message.error, `${message.id}:error`),
    arraySignature(message.attachments),
    searchSourcesSignature(message.searchSources, message.id),
    searchImageGroupsSignature(message.searchImageGroups, message.id),
    imageSlotCount,
    isCollapsible,
    isCollapsed,
    task?.id,
    task?.status,
    task?.mode,
    task?.model,
    task?.n,
    task?.size,
    task?.quality,
    task?.stage,
    task?.progress,
    task?.upstream_request_id,
    task?.blocked,
    task?.tool_invoked,
    compactStringSignature(task?.error, `${task?.id || message.taskId}:error`),
    compactStringSignature(task?.reason, `${task?.id || message.taskId}:reason`),
    compactStringSignature(task?.upstream_message_preview, `${task?.id || message.taskId}:preview`),
    compactStringSignature(task?.terminal_message, `${task?.id || message.taskId}:terminal`),
    compactStringSignature(task?.upstream_error, `${task?.id || message.taskId}:upstream`),
    compactStringSignature(task?.raw_error, `${task?.id || message.taskId}:raw`),
    assets.length,
    ...assets.map((asset, index) => assetSignature(asset, task?.id || message.taskId || message.id, index)),
  ]
}

function sameMessageViewSignature(left: MessageViewSignature, right: MessageViewSignature) {
  if (left.length !== right.length) return false
  return left.every((value, index) => value === right[index])
}

function arraySignature(values: string[] | undefined) {
  if (!values?.length) return ''
  return values.map((value) => compactStringSignature(value)).join('\u001f')
}

function searchSourcesSignature(sources: StudioSearchSource[] | undefined, ownerId: string) {
  if (!sources?.length) return ''
  return sources
    .map((source, index) => [
      index,
      compactStringSignature(source.title, `${ownerId}:search:${index}:title`),
      compactStringSignature(source.url, `${ownerId}:search:${index}:url`),
      compactStringSignature(source.snippet, `${ownerId}:search:${index}:snippet`),
    ].join('\u001e'))
    .join('\u001f')
}

function searchImageGroupsSignature(groups: StudioSearchImageGroup[] | undefined, ownerId: string) {
  if (!groups?.length) return ''
  return groups
    .map((group, index) => [
      index,
      compactStringSignature(group.aspectRatio, `${ownerId}:image-group:${index}:aspect`),
      group.numPerQuery || '',
      arraySignature(group.queries),
    ].join('\u001e'))
    .join('\u001f')
}

function assetSignature(asset: ImageTaskAsset, ownerId: string, index: number) {
  return [
    compactStringSignature(asset.url, `${ownerId}:asset:${index}:url`),
    compactStringSignature(asset.path, `${ownerId}:asset:${index}:path`),
    compactStringSignature(asset.b64_json, `${ownerId}:asset:${index}:b64`),
  ].join('\u001f')
}

function compactStringSignature(value: unknown, cacheKey = '') {
  const text = String(value ?? '')
  if (!text) return ''
  if (text.length <= 192) return text
  if (cacheKey) {
    const cached = stringSignatureCache.get(cacheKey)
    if (cached?.value === text) {
      stringSignatureCache.delete(cacheKey)
      stringSignatureCache.set(cacheKey, cached)
      return cached.signature
    }
    const signature = createLongStringSignature(text)
    stringSignatureCache.set(cacheKey, { value: text, signature })
    trimStringKeyCache(stringSignatureCache, MAX_STRING_SIGNATURE_CACHE_SIZE)
    return signature
  }
  return createLongStringSignature(text)
}

function createLongStringSignature(value: string) {
  return `${value.length}:${hashString(value)}:${value.slice(0, 24)}:${value.slice(-24)}`
}

function hashString(value: string) {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(36)
}

watch(() => props.conversation, (conversation, previousConversation) => {
  if (conversation?.id === previousConversation?.id) {
    displayedConversation.value = conversation
    return
  }
  scheduleConversationRender(conversation)
})

watch(() => displayedConversation.value?.id, () => {
  visibleMessageLimit.value = INITIAL_MESSAGE_LIMIT
  showScrollLatest.value = false
  closeSearchSourcePanel()
  scheduleScrollToLatest()
})

function assetUrl(asset: ImageTaskAsset) {
  return imageAssetUrl(asset)
}

function emitCompareImage(message: StudioMessageView, beforeIndex: number, afterIndex: number) {
  const beforeAsset = message.assets[beforeIndex]
  const afterAsset = message.assets[afterIndex]
  const beforeSrc = beforeAsset ? assetUrl(beforeAsset) : ''
  const afterSrc = afterAsset ? assetUrl(afterAsset) : ''
  if (!beforeSrc || !afterSrc) return
  emit('compare-image', { src: beforeSrc, name: `结果 ${beforeIndex + 1}` }, { src: afterSrc, name: `结果 ${afterIndex + 1}` })
}

function isLiveMessage(message: StudioMessage) {
  if (message.status === 'sending' || message.status === 'streaming' || message.status === 'queued' || message.status === 'running') {
    return true
  }
  if (!message.taskId) return false
  const task = taskById.value.get(message.taskId)
  return Boolean(task && task.status !== 'success' && task.status !== 'error')
}

function computeImageSlotCount(message: StudioMessage, task: ImageTask | undefined, assetCount: number) {
  const taskCount = Number(task?.n)
  const messageCount = Number(message.imageCount)
  if (task?.status === 'success' && assetCount > 0) {
    return Math.min(4, Math.max(1, assetCount))
  }
  const count = Math.max(
    1,
    Number.isFinite(taskCount) ? taskCount : 0,
    Number.isFinite(messageCount) ? messageCount : 0,
  )
  return Math.min(4, Math.max(1, Math.trunc(count)))
}

function buildImagePreviewStyle(message: StudioMessage, task: ImageTask | undefined, imageSlotCount: number): CSSProperties {
  const parsed = parseImageSize(task?.size || message.imageSize || '')
  const aspectRatio = parsed ? `${parsed.width} / ${parsed.height}` : '1 / 1'
  return {
    '--studio-image-aspect-ratio': aspectRatio,
    '--studio-image-grid-columns': String(Math.min(2, imageSlotCount)),
  } as CSSProperties
}

function sourceTitle(source: StudioSearchSource, index: number) {
  return source.title?.trim() || source.url?.trim() || `来源 ${index + 1}`
}

function sourceHost(url: string | undefined) {
  const value = String(url || '').trim()
  if (!value) return ''
  try {
    return new URL(value).host.replace(/^www\./, '')
  } catch {
    return ''
  }
}

function searchSourceDomId(messageId: string, sourceIndex: number) {
  return `studio-search-source-${messageId.replace(/[^a-zA-Z0-9_-]/g, '-')}-${sourceIndex + 1}`
}

function openSearchSourcePanel(message: StudioMessage, sourceIndex?: number) {
  openSearchSourcePanelById(message.id, sourceIndex)
}

function closeSearchSourcePanel() {
  searchPanelMessageId.value = ''
  highlightedSearchSourceId.value = ''
  if (searchSourceHighlightTimer !== null) {
    window.clearTimeout(searchSourceHighlightTimer)
    searchSourceHighlightTimer = null
  }
}

function openSearchSourcePanelById(messageId: string, sourceIndex?: number) {
  searchPanelMessageId.value = messageId
  if (sourceIndex === undefined) {
    highlightedSearchSourceId.value = ''
    return
  }
  highlightSearchSource(messageId, sourceIndex)
}

function scrollToCitationSource(href: string) {
  const match = String(href || '').match(/^studio-citation:([^:]+):(\d+)$/)
  if (!match) return
  const messageId = decodeURIComponent(match[1] || '')
  const sourceIndex = Number(match[2]) - 1
  if (!messageId || !Number.isInteger(sourceIndex) || sourceIndex < 0) return
  openSearchSourcePanelById(messageId, sourceIndex)
}

function highlightSearchSource(messageId: string, sourceIndex: number) {
  const targetId = searchSourceDomId(messageId, sourceIndex)
  highlightedSearchSourceId.value = targetId
  void nextTick(() => {
    const target = document.getElementById(targetId)
    target?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
  if (searchSourceHighlightTimer !== null) window.clearTimeout(searchSourceHighlightTimer)
  searchSourceHighlightTimer = window.setTimeout(() => {
    if (highlightedSearchSourceId.value === targetId) highlightedSearchSourceId.value = ''
    searchSourceHighlightTimer = null
  }, 1600)
}

function trimStringKeyCache<T>(cache: Map<string, T>, maxSize: number) {
  while (cache.size > maxSize) {
    const firstKey = cache.keys().next().value
    if (!firstKey) break
    cache.delete(firstKey)
  }
}

function scheduleConversationRender(conversation: StudioConversation | null) {
  const token = ++conversationRenderToken
  if (conversationRenderFrameId !== null) {
    window.cancelAnimationFrame(conversationRenderFrameId)
  }
  conversationRenderFrameId = window.requestAnimationFrame(() => {
    conversationRenderFrameId = null
    if (token !== conversationRenderToken) return
    displayedConversation.value = conversation
  })
}

function scheduleScrollToLatest() {
  const token = ++scrollLatestToken
  if (scrollLatestFrameId !== null) {
    window.cancelAnimationFrame(scrollLatestFrameId)
  }
  scrollLatestFrameId = window.requestAnimationFrame(() => {
    scrollLatestFrameId = null
    if (token !== scrollLatestToken) return
    scrollToBottom()
    window.requestAnimationFrame(() => {
      if (token === scrollLatestToken) scrollToBottom()
    })
  })
}

onBeforeUnmount(() => {
  if (conversationRenderFrameId !== null) {
    window.cancelAnimationFrame(conversationRenderFrameId)
    conversationRenderFrameId = null
  }
  if (scrollLatestFrameId !== null) {
    window.cancelAnimationFrame(scrollLatestFrameId)
    scrollLatestFrameId = null
  }
  if (searchSourceHighlightTimer !== null) {
    window.clearTimeout(searchSourceHighlightTimer)
    searchSourceHighlightTimer = null
  }
})

function isTextLikeMessage(message: StudioMessage) {
  return message.role === 'user' || message.mode !== 'image' || message.status === 'error'
}

function computeIsCollapsibleMessage(message: StudioMessage) {
  if (!isTextLikeMessage(message)) return false
  const content = String(message.content || message.error || '')
  if (!content.trim()) return false
  return content.length > 420 || content.split(/\r?\n/).length > 8
}

function computeIsMessageCollapsed(message: StudioMessage) {
  if (message.role === 'assistant') return collapsedMessageIds.value.has(message.id)
  return !expandedMessageIds.value.has(message.id)
}

function toggleMessageExpanded(message: StudioMessage) {
  if (message.role === 'assistant') {
    const next = new Set(collapsedMessageIds.value)
    if (next.has(message.id)) next.delete(message.id)
    else next.add(message.id)
    collapsedMessageIds.value = next
    return
  }
  const next = new Set(expandedMessageIds.value)
  if (next.has(message.id)) next.delete(message.id)
  else next.add(message.id)
  expandedMessageIds.value = next
}

async function showOlderMessages() {
  const el = scrollEl.value
  const previousHeight = el?.scrollHeight || 0
  const previousTop = el?.scrollTop || 0
  visibleMessageLimit.value = Math.min(allMessages.value.length, visibleMessageLimit.value + MESSAGE_BATCH_SIZE)
  await nextTick()
  if (!el) return
  el.scrollTop = previousTop + Math.max(0, el.scrollHeight - previousHeight)
}

function messageActions(message: StudioMessage): MessageAction[] {
  const actions: MessageAction[] = []
  if (message.content) actions.push({ key: 'copy', label: '复制', icon: 'lucide:copy' })
  if (message.role === 'user') {
    if (message.content) actions.push({ key: 'edit', label: '编辑', icon: 'lucide:pencil' })
    actions.push({ key: 'resend', label: '重发', icon: 'lucide:refresh-cw' })
    if (message.content) actions.push({ key: 'fill', label: '填入', icon: 'lucide:clipboard-paste' })
  } else if (message.mode !== 'image' || message.status === 'error') {
    actions.push({ key: 'retry', label: '重试', icon: 'lucide:refresh-cw' })
  }
  actions.push({ key: 'delete', label: '删除', icon: 'lucide:trash-2', danger: true })
  return actions
}

function handleMessageAction(action: MessageActionKey, message: StudioMessage) {
  if (action === 'copy') emit('copy-message', message.content)
  else if (action === 'edit') emit('edit', message)
  else if (action === 'resend') emit('resend', message)
  else if (action === 'fill') emit('retry', message)
  else if (action === 'retry') emit('retry-assistant', message)
  else if (action === 'delete') emit('delete-message', message.id)
}

function handleScroll() {
  const el = scrollEl.value
  if (!el) return
  showScrollLatest.value = el.scrollHeight - el.scrollTop - el.clientHeight > 160
}

function scrollToBottom() {
  const el = scrollEl.value
  if (!el) return
  el.scrollTop = el.scrollHeight
  showScrollLatest.value = false
}

defineExpose({
  scrollToBottom: () => nextTick(scrollToBottom),
})
</script>

<style scoped>
.studio-chat-panel {
  position: relative;
  display: flex;
  min-height: 0;
  flex: 1 1 auto;
  flex-direction: column;
  --studio-image-slot-size: clamp(15rem, 34vw, 26rem);
  --studio-image-aspect-ratio: 1 / 1;
  --studio-image-grid-columns: 1;
}

.studio-chat-scroll {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 1rem clamp(0.85rem, 1.6vw, 1.35rem) calc(var(--studio-composer-height, 10rem) + 1rem);
}

.studio-chat-empty {
  display: flex;
  min-height: calc(100% - 1rem);
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: clamp(2rem, 7vh, 5rem) 1rem 1rem;
  text-align: center;
}

.studio-chat-panel.is-fullscreen .studio-chat-empty {
  padding-top: clamp(3rem, 10vh, 7rem);
}

.studio-chat-empty h1 {
  color: hsl(var(--foreground));
  font-size: clamp(1.8rem, 5vw, 3.2rem);
  font-weight: 700;
  letter-spacing: 0;
}

.studio-chat-empty p {
  margin-top: 0.875rem;
  max-width: 34rem;
  color: hsl(var(--muted-foreground));
  font-size: 0.875rem;
  line-height: 1.8;
}

.studio-turns {
  margin: 0 auto;
  display: flex;
  width: 100%;
  max-width: var(--studio-content-width, min(100%, 88rem));
  flex-direction: column;
  gap: 1.55rem;
  padding-bottom: 0.5rem;
}

.studio-load-earlier-row {
  display: flex;
  justify-content: center;
}

.studio-load-earlier-button {
  display: inline-flex;
  min-height: 2rem;
  align-items: center;
  justify-content: center;
  border: 2px solid var(--bauhaus-line-soft, var(--ui-control-border, hsl(var(--border))));
  border-radius: var(--radius);
  background: var(--ui-control-bg, hsl(var(--background)));
  color: var(--ui-fg-muted, hsl(var(--muted-foreground)));
  padding: 0.35rem 0.875rem;
  font-size: 0.75rem;
  font-weight: 650;
  transition: border-color 0.15s, background 0.15s, color 0.15s;
}

.studio-load-earlier-button:hover,
.studio-load-earlier-button:focus-visible {
  border-color: var(--bauhaus-ink, var(--ui-control-hover-border, hsl(var(--foreground) / 0.18)));
  background: var(--ui-control-hover-bg, hsl(var(--secondary)));
  color: var(--ui-fg-strong, hsl(var(--foreground)));
}

.chat-message-row {
  display: flex;
  width: 100%;
}

.chat-message-row.is-user {
  justify-content: flex-end;
}

.chat-message-row.is-assistant {
  justify-content: flex-start;
}

.chat-message-container {
  display: flex;
  min-width: 0;
  max-width: 100%;
  width: fit-content;
  align-items: flex-start;
  gap: 0.7rem;
}

.chat-message-container.is-pending-image-message {
  width: fit-content;
  min-width: 0;
  max-width: 100%;
}

.chat-message-container.is-user {
  flex-direction: row-reverse;
  max-width: min(100%, 40rem);
}

.chat-message-container.is-assistant {
  flex-direction: row;
  width: 100%;
  max-width: 100%;
}

.chat-message-container.is-assistant.is-image-message {
  width: fit-content;
  max-width: 100%;
}

.chat-message-main {
  display: flex;
  min-width: 0;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 0.28rem;
}

.chat-message-container.is-user .chat-message-main {
  align-items: flex-end;
}

.chat-message-container.is-assistant .chat-message-main {
  align-items: flex-start;
}

.chat-message-avatar {
  display: flex;
  width: 2rem;
  height: 2rem;
  flex: 0 0 2rem;
  align-items: center;
  justify-content: center;
  margin-top: 0.15rem;
  border: 2px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: 999px;
  box-shadow: 2px 2px 0 0 var(--bauhaus-ink, #2d2d2d);
  color: #fff;
  overflow: hidden;
}

.chat-message-avatar-mark {
  display: block;
  flex: 0 0 auto;
}

.chat-message-avatar-assistant {
  background: #10a37f;
  border-color: var(--bauhaus-ink, #2d2d2d);
  color: #fff;
}

.chat-message-avatar-user {
  background: var(--bauhaus-blue, #2d5da1);
  border-color: var(--bauhaus-ink, #2d2d2d);
  color: #fff;
}

html[data-theme='dark'] .chat-message-avatar {
  box-shadow: 2px 2px 0 0 color-mix(in srgb, var(--bauhaus-ink, #e8e4dc) 55%, transparent);
}

html[data-theme='dark'] .chat-message-avatar-assistant {
  background: #0f8f6f;
}

html[data-theme='dark'] .chat-message-avatar-user {
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 88%, #000);
}

.chat-message-actions {
  display: flex;
  min-width: 0;
  max-width: min(26rem, calc(100vw - 8rem));
  flex-wrap: wrap;
  align-items: center;
  gap: 0.2rem;
  opacity: 1;
  transition: opacity var(--ui-duration-normal, 180ms) var(--ui-ease-out, ease);
}

.chat-message-container.is-user .chat-message-actions {
  justify-content: flex-end;
}

@media (min-width: 640px) {
  .chat-message-actions {
    pointer-events: none;
    opacity: 0;
  }

  .chat-message-container:hover .chat-message-actions,
  .chat-message-container:focus-within .chat-message-actions {
    pointer-events: auto;
    opacity: 1;
  }
}

.chat-input-action {
  display: inline-flex;
  box-sizing: border-box;
  min-height: 1.625rem;
  height: 1.625rem;
  align-items: center;
  justify-content: center;
  gap: 0.3125rem;
  overflow: hidden;
  border: 2px solid transparent;
  border-radius: var(--radius);
  background: transparent;
  color: var(--ui-fg-muted, hsl(var(--muted-foreground)));
  padding: 0.25rem 0.625rem;
  font-size: 0.75rem;
  font-weight: 600;
  line-height: 1;
  transition: border-color 0.15s, background 0.15s, color 0.15s;
}

.chat-input-action:hover,
.chat-input-action:focus-visible {
  border-color: var(--bauhaus-ink, var(--ui-control-hover-border, hsl(var(--foreground) / 0.18)));
  background: var(--ui-control-hover-bg, hsl(var(--secondary)));
  color: var(--ui-fg-strong, hsl(var(--foreground)));
}

.chat-input-action .icon {
  display: inline-flex;
  width: 1rem;
  height: 1rem;
  flex: 0 0 1rem;
  align-items: center;
  justify-content: center;
  line-height: 0;
}

.chat-input-action .text {
  display: inline-block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  pointer-events: none;
}

.chat-message-action {
  width: 1.85rem;
  min-width: 1.85rem;
  height: 1.85rem;
  min-height: 1.85rem;
  padding: 0.25rem;
}

.chat-message-action .text {
  display: none;
}

.chat-message-action-danger:hover,
.chat-message-action-danger:focus-visible {
  border-color: var(--ui-danger-border, rgb(248 113 113 / 0.32));
  background: var(--ui-danger-bg, rgb(254 242 242 / 0.86));
  color: var(--ui-danger-fg, rgb(220 38 38));
}

.chat-message-bubble {
  max-width: 100%;
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  box-shadow: none;
  color: var(--ui-fg-strong, hsl(var(--foreground)));
  padding: 0.15rem 0;
  font-size: 0.9375rem;
  line-height: 1.7;
}

html[data-theme='dark'] .chat-message-bubble {
  border-color: transparent;
}

.chat-message-bubble-wrap {
  position: relative;
  max-width: 100%;
}

.chat-message-content {
  position: relative;
  max-width: 100%;
  overflow-wrap: anywhere;
}

.chat-message-content.is-collapsible {
  overflow: hidden;
  transition: max-height 0.18s ease;
}

.chat-message-content.is-collapsed {
  max-height: 12rem;
}

.chat-message-content.is-collapsed::after {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  height: 3.25rem;
  pointer-events: none;
  background: linear-gradient(180deg, transparent, var(--studio-bubble-fade-bg, hsl(var(--card))));
  content: '';
}

.chat-message-expand {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  margin-top: 0.5rem;
  border-radius: var(--radius);
  color: hsl(var(--muted-foreground));
  font-size: 0.75rem;
  font-weight: 650;
  line-height: 1;
  transition: color 0.15s, background 0.15s;
}

.chat-message-expand:hover,
.chat-message-expand:focus-visible {
  color: hsl(var(--foreground));
}

.chat-message-bubble-user {
  --studio-bubble-fade-bg: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 10%, hsl(var(--card)));
  border: 2px solid var(--bauhaus-ink, #2d2d2d);
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 10%, hsl(var(--card)));
  box-shadow: 3px 3px 0 0 var(--bauhaus-ink, #2d2d2d);
  padding: 0.7rem 0.95rem;
}

.chat-message-bubble-assistant {
  --studio-bubble-fade-bg: hsl(var(--background));
  border: 0;
  background: transparent;
  box-shadow: none;
  padding: 0.2rem 0 0;
}

.chat-message-bubble-image {
  width: fit-content;
  min-width: 0;
  border: 0;
  background: transparent;
  box-shadow: none;
  padding: 0;
}

.chat-message-bubble-image-pending {
  border: 2px solid var(--bauhaus-line-soft, hsl(var(--border)));
  background: hsl(var(--card));
  padding: 0.75rem;
}

.chat-message-bubble-error {
  --studio-bubble-fade-bg: rgb(254 242 242);
  border: 2px solid color-mix(in srgb, var(--bauhaus-red, #c0392b) 45%, #fff);
  background: color-mix(in srgb, var(--bauhaus-red, #c0392b) 8%, #fff);
  box-shadow: none;
  padding: 0.7rem 0.9rem;
}

html[data-theme='dark'] .chat-message-bubble-user {
  --studio-bubble-fade-bg: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 18%, hsl(var(--card)));
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 18%, hsl(var(--card)));
  box-shadow: 3px 3px 0 0 color-mix(in srgb, var(--bauhaus-ink, #e8e4dc) 45%, transparent);
}

html[data-theme='dark'] .chat-message-bubble-error {
  --studio-bubble-fade-bg: color-mix(in srgb, var(--bauhaus-red, #c0392b) 16%, hsl(var(--card)));
  border-color: color-mix(in srgb, var(--bauhaus-red, #c0392b) 50%, transparent);
  background: color-mix(in srgb, var(--bauhaus-red, #c0392b) 14%, hsl(var(--card)));
}

.studio-user-prompt {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.studio-attachment-line {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  margin-top: 0.45rem;
  color: hsl(var(--muted-foreground));
  font-size: 0.75rem;
}

.studio-search-source-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.42rem;
  margin-top: 0.65rem;
  border: 2px solid var(--bauhaus-line-soft, hsl(var(--primary) / 0.18));
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--bauhaus-blue) 12%, transparent);
  color: hsl(var(--foreground));
  padding: 0.34rem 0.68rem 0.34rem 0.5rem;
  font-size: 0.72rem;
  font-weight: 720;
  line-height: 1;
  box-shadow: none;
  transition: border-color 0.15s, background 0.15s, box-shadow 0.15s, transform 0.15s;
}

.studio-search-source-chip-icon {
  flex: 0 0 auto;
  color: var(--bauhaus-blue, hsl(var(--primary)));
}

.studio-search-source-chip-label {
  color: hsl(var(--foreground));
}

.studio-search-source-chip strong {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.15rem;
  height: 1.15rem;
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--bauhaus-blue) 16%, transparent);
  color: var(--bauhaus-blue, hsl(var(--primary)));
  font-size: 0.68rem;
  font-weight: 820;
}

.studio-search-source-chip small {
  border-left: 1px solid var(--bauhaus-line-soft, hsl(var(--primary) / 0.16));
  padding-left: 0.42rem;
  color: hsl(var(--muted-foreground));
  font-size: 0.68rem;
  font-weight: 780;
}

.studio-search-source-chip:hover,
.studio-search-source-chip:focus-visible {
  border-color: var(--bauhaus-ink, hsl(var(--primary) / 0.34));
  background: color-mix(in srgb, var(--bauhaus-blue) 18%, transparent);
  box-shadow: none;
  transform: none;
}

.studio-search-image-groups {
  display: grid;
  gap: 0.45rem;
  margin-top: 0.65rem;
}

.studio-search-image-group {
  display: grid;
  gap: 0.42rem;
  border: 2px solid var(--bauhaus-line-soft, hsl(var(--border) / 0.68));
  border-radius: var(--radius);
  background: hsl(var(--muted) / 0.32);
  padding: 0.56rem 0.62rem;
}

.studio-search-image-group-title {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  color: hsl(var(--foreground));
  font-size: 0.72rem;
  font-weight: 780;
  line-height: 1;
}

.studio-search-image-group-title svg {
  color: hsl(var(--primary));
}

.studio-search-image-group-queries {
  display: flex;
  flex-wrap: wrap;
  gap: 0.32rem;
}

.studio-search-image-query {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border: 2px solid var(--bauhaus-line-soft, hsl(var(--border) / 0.62));
  border-radius: var(--radius);
  background: hsl(var(--background) / 0.72);
  padding: 0.24rem 0.48rem;
  color: hsl(var(--muted-foreground));
  font-size: 0.68rem;
  font-weight: 650;
}

.studio-search-drawer-backdrop {
  position: absolute;
  inset: 0;
  z-index: 30;
  background: hsl(var(--background) / 0.42);
  backdrop-filter: blur(1px);
}

.studio-search-drawer {
  position: absolute;
  top: 0.75rem;
  right: 0.75rem;
  bottom: 0.75rem;
  z-index: 31;
  display: flex;
  width: min(25rem, calc(100% - 1.5rem));
  min-width: 0;
  flex-direction: column;
  overflow: hidden;
  border: 2px solid var(--bauhaus-ink, hsl(var(--border) / 0.82));
  border-radius: var(--radius);
  background: hsl(var(--card));
  box-shadow: var(--shadow-hard-lg);
}

html[data-theme='dark'] .studio-search-drawer {
  box-shadow: var(--shadow-hard-soft-lg, var(--shadow-hard-soft));
}

.studio-search-drawer-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  border-bottom: 2px solid var(--bauhaus-line-soft, hsl(var(--border) / 0.72));
  padding: 0.9rem 0.95rem 0.75rem;
}

.studio-search-drawer-header div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 0.2rem;
}

.studio-search-drawer-header strong {
  color: hsl(var(--foreground));
  font-size: 0.95rem;
  font-weight: 800;
}

.studio-search-drawer-header small {
  color: hsl(var(--muted-foreground));
  font-size: 0.72rem;
  font-weight: 650;
}

.studio-search-drawer-close {
  display: inline-flex;
  width: 2rem;
  height: 2rem;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border: 2px solid var(--bauhaus-line-soft, hsl(var(--border) / 0.72));
  border-radius: var(--radius);
  background: hsl(var(--background));
  color: hsl(var(--muted-foreground));
  transition: border-color 0.15s, background 0.15s, color 0.15s;
}

.studio-search-drawer-close:hover,
.studio-search-drawer-close:focus-visible {
  border-color: var(--bauhaus-ink, hsl(var(--foreground) / 0.18));
  background: hsl(var(--secondary));
  color: hsl(var(--foreground));
}

.studio-search-drawer-body {
  display: grid;
  min-height: 0;
  flex: 1;
  align-content: start;
  gap: 0.55rem;
  overflow-y: auto;
  padding: 0.75rem;
}

.studio-search-source-card {
  display: grid;
  min-width: 0;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: start;
  gap: 0.45rem;
  border: 2px solid var(--bauhaus-line-soft, hsl(var(--border) / 0.62));
  border-radius: var(--radius);
  background: hsl(var(--background) / 0.72);
  padding: 0.5rem 0.6rem;
  color: hsl(var(--foreground));
  text-decoration: none;
  transition: border-color 0.15s, background 0.15s, transform 0.15s, box-shadow 0.15s;
}

.studio-search-source-card:hover,
.studio-search-source-card:focus-visible {
  border-color: var(--bauhaus-ink, hsl(var(--foreground) / 0.2));
  background: hsl(var(--background));
  transform: none;
}

.studio-search-source-card.is-static {
  cursor: default;
}

.studio-search-source-card.is-highlighted {
  border-color: var(--bauhaus-blue, var(--ui-accent-border, hsl(var(--primary) / 0.35)));
  background: color-mix(in srgb, var(--bauhaus-blue) 10%, transparent);
  box-shadow: var(--shadow-hard-sm);
}

html[data-theme='dark'] .studio-search-source-card.is-highlighted {
  box-shadow: var(--shadow-hard-soft);
}

.studio-search-source-index {
  display: inline-flex;
  width: 1.35rem;
  height: 1.35rem;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius);
  background: hsl(var(--secondary));
  color: hsl(var(--muted-foreground));
  font-size: 0.72rem;
  font-weight: 800;
  line-height: 1;
}

.studio-search-source-body {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 0.14rem;
}

.studio-search-source-body strong,
.studio-search-source-body small,
.studio-search-source-body em {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.studio-search-source-body strong {
  font-size: 0.78rem;
  font-style: normal;
  font-weight: 750;
  line-height: 1.25;
}

.studio-search-source-body small {
  color: hsl(var(--muted-foreground));
  font-size: 0.68rem;
  font-weight: 650;
}

.studio-search-source-body em {
  color: hsl(var(--muted-foreground));
  font-size: 0.7rem;
  font-style: normal;
  line-height: 1.25;
}

.studio-search-drawer .studio-search-source-body strong,
.studio-search-drawer .studio-search-source-body em {
  white-space: normal;
}

.studio-search-drawer .studio-search-source-body strong {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.studio-search-drawer .studio-search-source-body em {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.studio-search-source-open {
  margin-top: 0.1rem;
  color: hsl(var(--muted-foreground));
}

.studio-search-drawer-fade-enter-active,
.studio-search-drawer-fade-leave-active,
.studio-search-drawer-slide-enter-active,
.studio-search-drawer-slide-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.studio-search-drawer-fade-enter-from,
.studio-search-drawer-fade-leave-to {
  opacity: 0;
}

.studio-search-drawer-slide-enter-from,
.studio-search-drawer-slide-leave-to {
  opacity: 0;
  transform: translateX(1rem);
}

@media (max-width: 720px) {
  .studio-search-drawer {
    right: 0.5rem;
    left: 0.5rem;
    width: auto;
  }
}

.chat-message-bubble :deep(a[href^='studio-citation:']) {
  display: inline-flex;
  min-width: 1.12rem;
  height: 1.12rem;
  align-items: center;
  justify-content: center;
  margin: 0 0.08rem;
  border: 1px solid var(--bauhaus-blue, var(--ui-accent-border, hsl(var(--primary) / 0.28)));
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--bauhaus-blue) 12%, transparent);
  color: var(--bauhaus-blue, var(--ui-accent-strong, hsl(var(--primary))));
  font-size: 0.68em;
  font-weight: 800;
  line-height: 1;
  text-decoration: none;
  vertical-align: super;
}

.chat-message-bubble :deep(a[href^='studio-citation:']:hover),
.chat-message-bubble :deep(a[href^='studio-citation:']:focus-visible) {
  border-color: var(--bauhaus-ink, var(--ui-accent-border, hsl(var(--primary) / 0.5)));
  background: color-mix(in srgb, var(--bauhaus-blue) 18%, transparent);
}

.chat-markdown {
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.chat-markdown :deep(> :first-child) {
  margin-top: 0;
}

.chat-markdown :deep(> :last-child) {
  margin-bottom: 0;
}

.chat-markdown :deep(p) {
  margin: 0.35rem 0;
}

.chat-markdown :deep(ul),
.chat-markdown :deep(ol) {
  margin: 0.55rem 0;
  padding-left: 1.25rem;
}

.chat-markdown :deep(ul) {
  list-style: disc;
}

.chat-markdown :deep(ol) {
  list-style: decimal;
}

.chat-markdown :deep(li) {
  margin: 0.25rem 0;
}

.chat-markdown :deep(blockquote) {
  margin: 0.75rem 0;
  border-left: 3px solid rgb(113 113 122 / 0.32);
  padding-left: 0.75rem;
  color: hsl(var(--muted-foreground));
}

.chat-markdown :deep(pre) {
  overflow-x: auto;
  overflow-wrap: normal;
  word-break: normal;
  border: 2px solid var(--bauhaus-line-soft, hsl(var(--border)));
  border-radius: var(--radius);
  background: hsl(var(--muted) / 0.45);
  padding: 0.75rem;
  font-size: 0.8125rem;
}

.chat-markdown :deep(code) {
  border-radius: var(--radius);
  background: hsl(var(--muted) / 0.55);
  padding: 0.1rem 0.25rem;
  font-size: 0.84em;
}

.chat-markdown :deep(pre code) {
  background: transparent;
  padding: 0;
}

.chat-markdown :deep(.studio-code-block) {
  margin: 0.75rem 0;
  overflow: hidden;
  border: 2px solid var(--bauhaus-ink, hsl(var(--border)));
  border-radius: var(--radius);
  background: hsl(var(--muted) / 0.36);
}

.chat-markdown :deep(.studio-code-header) {
  display: flex;
  min-height: 2.25rem;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  border-bottom: 2px solid var(--bauhaus-line-soft, hsl(var(--border)));
  background: hsl(var(--background) / 0.72);
  padding: 0.35rem 0.5rem 0.35rem 0.75rem;
  color: hsl(var(--muted-foreground));
  font-size: 0.72rem;
  font-weight: 650;
  line-height: 1;
}

.chat-markdown :deep(.studio-code-copy) {
  display: inline-flex;
  height: 1.55rem;
  align-items: center;
  justify-content: center;
  border: 2px solid transparent;
  border-radius: var(--radius);
  padding: 0 0.625rem;
  color: hsl(var(--muted-foreground));
  font-size: 0.72rem;
  font-weight: 650;
  line-height: 1;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}

.chat-markdown :deep(.studio-code-copy:hover),
.chat-markdown :deep(.studio-code-copy:focus-visible) {
  border-color: var(--bauhaus-ink, hsl(var(--foreground) / 0.14));
  background: hsl(var(--secondary));
  color: hsl(var(--foreground));
}

.chat-markdown :deep(.studio-code-pre) {
  margin: 0;
  overflow-x: auto;
  border: 0;
  border-radius: 0;
  background: transparent;
  padding: 0.75rem 0.875rem;
  color: hsl(var(--foreground));
  font-size: 0.78rem;
  line-height: 1.65;
}

.chat-markdown :deep(.studio-code-pre code) {
  display: block;
  min-width: max-content;
  background: transparent;
  padding: 0;
  font-family: var(--font-ui-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace);
}

.chat-markdown :deep(.hljs-comment),
.chat-markdown :deep(.hljs-quote) {
  color: #6b7280;
}

.chat-markdown :deep(.hljs-keyword),
.chat-markdown :deep(.hljs-selector-tag),
.chat-markdown :deep(.hljs-subst) {
  color: #7c3aed;
}

.chat-markdown :deep(.hljs-string),
.chat-markdown :deep(.hljs-doctag) {
  color: #047857;
}

.chat-markdown :deep(.hljs-number),
.chat-markdown :deep(.hljs-literal),
.chat-markdown :deep(.hljs-variable),
.chat-markdown :deep(.hljs-template-variable),
.chat-markdown :deep(.hljs-tag .hljs-attr) {
  color: #b45309;
}

.chat-markdown :deep(.hljs-title),
.chat-markdown :deep(.hljs-section),
.chat-markdown :deep(.hljs-selector-id) {
  color: #2563eb;
}

.chat-markdown :deep(.hljs-type),
.chat-markdown :deep(.hljs-class .hljs-title) {
  color: #0f766e;
}

.chat-markdown :deep(.hljs-tag),
.chat-markdown :deep(.hljs-name),
.chat-markdown :deep(.hljs-attribute) {
  color: #be123c;
}

.studio-error-text {
  margin-top: 0.45rem;
  color: rgb(190 18 60);
  font-size: 0.8125rem;
  line-height: 1.6;
}

.studio-cursor {
  display: inline-block;
  width: 0.45rem;
  height: 1rem;
  border-radius: var(--radius);
  background: var(--bauhaus-blue, hsl(var(--primary)));
  animation: studio-cursor 1s ease-in-out infinite;
}

@keyframes studio-cursor {
  0%, 100% { opacity: 0.2; }
  50% { opacity: 1; }
}

.studio-image-status {
  display: flex;
  min-width: 0;
  width: 100%;
  min-height: 3.25rem;
  align-items: center;
  gap: 0.5rem;
  color: hsl(var(--muted-foreground));
  font-size: 0.8125rem;
  line-height: 1.6;
}

.studio-image-status.is-error {
  align-items: flex-start;
  color: rgb(185 28 28);
}

.studio-result-block {
  display: inline-block;
  max-width: 100%;
}

.studio-result-grid {
  display: grid;
  width: fit-content;
  max-width: 100%;
  grid-template-columns: repeat(var(--studio-image-grid-columns), minmax(0, var(--studio-image-slot-size)));
  gap: 0.625rem;
}

.studio-result-grid.is-single {
  grid-template-columns: minmax(0, var(--studio-image-slot-size));
}

.studio-result-item {
  width: var(--studio-image-slot-size);
  min-width: 0;
}

.studio-result-grid.is-single .studio-result-item {
  width: var(--studio-image-slot-size);
}

.studio-result-media {
  display: flex;
  width: 100%;
  aspect-ratio: var(--studio-image-aspect-ratio);
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border: 2px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  background: hsl(var(--secondary) / 0.28);
  box-shadow: 3px 3px 0 0 var(--bauhaus-ink, #2d2d2d);
  color: inherit;
  cursor: zoom-in;
}

.studio-result-media.has-image {
  background: hsl(var(--card));
  padding: 0;
}

.studio-result-media img {
  display: block;
  width: 100%;
  height: 100%;
  max-width: none;
  max-height: none;
  border-radius: 0;
  object-fit: cover;
}

html[data-theme='dark'] .studio-result-media {
  box-shadow: 3px 3px 0 0 color-mix(in srgb, var(--bauhaus-ink, #e8e4dc) 45%, transparent);
}

.studio-result-media span {
  color: hsl(var(--muted-foreground));
  font-size: 0.8125rem;
}

.studio-result-placeholder {
  cursor: default;
  flex-direction: column;
  gap: 0.625rem;
  text-align: center;
}

.studio-result-placeholder svg {
  color: hsl(var(--muted-foreground));
}

.studio-result-placeholder span,
.studio-result-placeholder small {
  display: block;
  max-width: calc(100% - 1rem);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.studio-result-placeholder small {
  color: hsl(var(--muted-foreground) / 0.78);
  font-size: 0.75rem;
}

.studio-result-caption {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
  padding: 0.35rem 0.125rem 0;
  color: hsl(var(--muted-foreground));
  font-size: 0.75rem;
}

.studio-result-compare {
  height: 1.375rem;
  min-height: 1.375rem;
  padding: 0.15rem 0.5rem;
}

.studio-scroll-latest {
  position: absolute;
  left: 50%;
  bottom: calc(var(--studio-composer-height, 10rem) + 0.75rem);
  z-index: 30;
  display: inline-flex;
  width: 2.75rem;
  height: 2.75rem;
  transform: translateX(-50%);
  align-items: center;
  justify-content: center;
  border: 2px solid var(--bauhaus-ink, hsl(var(--border)));
  border-radius: var(--radius);
  background: hsl(var(--card) / 0.95);
  color: hsl(var(--foreground));
  box-shadow: var(--shadow-hard-sm);
  backdrop-filter: none;
}

html[data-theme='dark'] .studio-scroll-latest {
  box-shadow: var(--shadow-hard-soft);
}

/* 平板及以下：图槽收窄 + 强制单列（桌面 clamp 双列不动） */
@media (max-width: 1023px) {
  .studio-chat-panel {
    --studio-image-slot-size: min(14rem, calc(100vw - 5rem));
  }

  .studio-result-grid,
  .studio-result-grid.is-single {
    grid-template-columns: minmax(0, var(--studio-image-slot-size));
  }

  .studio-result-item,
  .studio-result-grid.is-single .studio-result-item {
    width: min(100%, var(--studio-image-slot-size));
    max-width: 100%;
  }
}

@media (max-width: 720px) {
  .studio-chat-scroll {
    padding: 0.65rem 0.65rem calc(var(--studio-composer-height, 9rem) + 0.65rem);
  }

  .studio-scroll-latest {
    bottom: calc(var(--studio-composer-height, 9rem) + 0.5rem);
  }

  .studio-turns {
    gap: 1rem;
  }

  .chat-message-container {
    max-width: 100%;
    gap: 0.45rem;
  }

  /* PC 仍为 min(100%, 40rem)；窄屏更贴边、为头像留白 */
  .chat-message-container.is-user {
    max-width: min(100%, calc(100vw - 4.25rem));
  }

  .chat-message-avatar {
    width: 1.65rem;
    height: 1.65rem;
    flex: 0 0 1.65rem;
    margin-top: 0.1rem;
  }

  .chat-message-avatar-mark {
    width: 12px;
    height: 12px;
  }

  .chat-message-bubble-user {
    padding: 0.55rem 0.75rem;
  }

  .chat-message-container.is-pending-image-message {
    width: fit-content;
    min-width: 0;
    max-width: 100%;
  }

  .studio-chat-panel {
    --studio-image-slot-size: min(14rem, calc(100vw - 5rem));
  }

  .chat-message-actions {
    max-width: calc(100vw - 5.5rem);
    overflow-x: auto;
    overflow-y: hidden;
    padding-bottom: 1px;
  }
}
</style>
