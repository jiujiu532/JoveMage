<template>
  <footer ref="composerShellRef" class="studio-composer-shell">
    <input
      ref="fileInputRef"
      type="file"
      accept="image/*"
      multiple
      class="hidden"
      @change="handleFileChange"
    />

    <form
      class="chat-input-panel"
      :class="{ 'is-dragging': isDragging }"
      @submit.prevent="$emit('submit')"
      @dragenter.prevent="isDragging = true"
      @dragover.prevent="isDragging = true"
      @dragleave="handleDragLeave"
      @drop.prevent="handleDrop"
      @click="textareaRef?.focus()"
    >
      <div class="chat-input-panel-shell">
        <div v-if="isEditing" class="chat-editing-bar" @click.stop>
          <div class="chat-editing-info">
            <Icon icon="lucide:pencil" class="h-3.5 w-3.5" />
            <span>正在编辑原消息，发送后会替换该消息并重新生成后续回复。</span>
          </div>
          <button type="button" class="chat-editing-cancel" @click="$emit('cancel-edit')">
            取消
          </button>
        </div>

        <div
          class="chat-input-panel-inner"
          :class="{ 'chat-input-panel-inner-attach': references.length }"
          @click="textareaRef?.focus()"
        >
          <div v-if="mode === 'image' && canEditImage && references.length" class="attach-images">
            <div v-for="(source, index) in references" :key="source.id" class="chat-attachment-preview">
              <button type="button" class="studio-reference-preview" :title="source.name" @click.stop="$emit('preview-reference', source)">
                <img v-if="source.dataUrl" :src="source.dataUrl" :alt="source.name" />
                <Icon v-else icon="lucide:image" class="h-5 w-5" />
              </button>
              <button type="button" class="chat-attachment-remove" :aria-label="`移除 ${source.name}`" @click.stop="$emit('remove-reference', index)">
                <Icon icon="lucide:x" class="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          <textarea
            ref="textareaRef"
            v-model="textValue"
            class="chat-input custom-scrollbar"
            rows="1"
            :placeholder="placeholderText"
            @input="resizeTextarea"
            @paste="handlePaste"
            @keydown.enter.exact.prevent="$emit('submit')"
          ></textarea>
        </div>

        <div class="chat-input-actions" @click.stop>
          <div class="chat-input-action-row">
            <button
              v-for="option in modeOptions"
              :key="option.value"
              type="button"
              class="chat-input-action"
              :class="{ 'chat-input-action-active': mode === option.value }"
              @click="modeValue = option.value"
            >
              <span class="icon">
                <Icon :icon="modeIcon(option.value)" class="h-3.5 w-3.5" />
              </span>
              <span class="text">{{ option.label }}</span>
            </button>

            <template v-if="mode === 'chat'">
              <div class="chat-select-wrap">
                <GroupedSelectMenu
                  v-model="chatModelValue"
                  :options="chatModelSelectOptions"
                  selected-indicator="none"
                  placement="top"
                />
              </div>
              <div class="chat-select-wrap chat-select-wrap--effort">
                <GroupedSelectMenu
                  v-model="chatReasoningEffortValue"
                  :options="chatReasoningEffortOptions"
                  selected-indicator="none"
                  placement="top"
                />
              </div>
            </template>

            <template v-else-if="mode === 'image' || mode === 'video'">
              <!-- 图生图 / 参考图：仅当启用渠道并集含 edit -->
              <button
                v-if="mode === 'image' && canEditImage"
                type="button"
                class="chat-input-action"
                :class="{ 'chat-input-action-active': references.length }"
                :disabled="isSending"
                @click="fileInputRef?.click()"
              >
                <span class="icon"><Icon icon="lucide:paperclip" class="h-3.5 w-3.5" /></span>
                <span class="text">{{ references.length ? '继续添加' : '参考图' }}</span>
              </button>
              <button
                v-if="mode === 'image'"
                type="button"
                class="chat-input-action"
                :disabled="isSending"
                @click.stop="handleOpenPrompts"
              >
                <span class="icon"><Icon icon="lucide:book-open" class="h-3.5 w-3.5" /></span>
                <span class="text">提示词</span>
              </button>
              <div class="chat-settings-anchor">
                <button
                  ref="settingsButtonRef"
                  type="button"
                  class="chat-input-action"
                  :class="{ 'chat-input-action-active': settingsOpen }"
                  @click.stop="toggleSettings"
                >
                  <span class="icon"><Icon icon="lucide:sliders-horizontal" class="h-3.5 w-3.5" /></span>
                  <span class="text">{{ mediaSummaryLabel }}</span>
                  <Icon icon="lucide:chevron-down" class="h-3.5 w-3.5" />
                </button>

                <div v-if="settingsOpen" class="studio-size-popover" @click.stop>
                  <div class="studio-size-section">
                    <div class="studio-size-label">模型</div>
                    <GroupedSelectMenu
                      v-if="mode === 'video'"
                      v-model="videoModelValue"
                      :groups="videoModelSelectGroups"
                      :options="videoModelSelectOptions"
                      selected-indicator="none"
                      show-group-labels
                      block
                    />
                    <GroupedSelectMenu
                      v-else
                      v-model="imageModelValue"
                      :groups="imageModelSelectGroups"
                      :options="imageModelSelectOptions"
                      selected-indicator="none"
                      show-group-labels
                      block
                    />
                  </div>
                  <div v-if="mode === 'image'" class="studio-size-section">
                    <div class="studio-size-label">质量</div>
                    <div class="studio-choice-grid is-quality">
                      <button
                        v-for="option in IMAGE_QUALITY_OPTIONS"
                        :key="option.value"
                        type="button"
                        class="studio-choice-button"
                        :class="{ 'is-active': imageForm.quality === option.value }"
                        @click="$emit('update:imageQuality', option.value)"
                      >
                        {{ option.label }}
                      </button>
                    </div>
                  </div>
                  <div v-if="mode === 'image'" class="studio-size-section">
                    <div class="studio-size-label">数量</div>
                    <div class="studio-choice-grid is-count">
                      <button
                        v-for="option in IMAGE_COUNT_OPTIONS"
                        :key="option.value"
                        type="button"
                        class="studio-choice-button"
                        :class="{ 'is-active': imageForm.n === option.value }"
                        @click="$emit('update:imageCount', option.value)"
                      >
                        {{ option.label }}
                      </button>
                    </div>
                  </div>
                  <div v-if="mode === 'image'" class="studio-size-section">
                    <div class="studio-size-label">比例</div>
                    <div class="studio-choice-grid is-ratio">
                      <button
                        v-for="option in ratioOptions"
                        :key="option.value"
                        type="button"
                        class="studio-choice-button"
                        :class="{ 'is-active': selectedRatio === option.value }"
                        @click="selectRatio(option.value)"
                      >
                        {{ option.label }}
                      </button>
                    </div>
                  </div>
                  <div v-if="mode === 'image'" class="studio-size-section">
                    <div class="studio-size-label">分辨率</div>
                    <div class="studio-choice-grid is-resolution">
                      <button
                        v-for="option in resolutionOptions"
                        :key="option.value"
                        type="button"
                        class="studio-choice-button"
                        :class="{ 'is-active': selectedResolution === option.value }"
                        @click="selectResolution(option.value)"
                      >
                        {{ option.label }}
                      </button>
                    </div>
                    <p class="studio-size-current">{{ selectedSizeDetailLabel }}</p>
                  </div>
                  <p v-else class="studio-size-current">视频模式按渠道模型提交，质量参数由上游决定。</p>
                </div>
              </div>
              <button
                v-if="mode === 'image' && canEditImage && references.length"
                type="button"
                class="chat-input-action"
                :disabled="isSending"
                @click="$emit('clear-references')"
              >
                <span class="icon"><Icon icon="lucide:x" class="h-3.5 w-3.5" /></span>
                <span class="text">清空参考</span>
              </button>
            </template>
          </div>

          <div class="chat-input-submit-row">
            <div v-if="mode === 'image' && canEditImage && references.length" class="chat-input-status">
              <span class="min-w-0 truncate">{{ references.length }} 张参考图</span>
              <span class="chat-input-count">{{ imageForm.n }} 张输出</span>
            </div>
          <button
            v-if="isStreaming"
            type="button"
            class="chat-input-send chat-input-send-danger"
            aria-label="停止输出"
            @click.stop="$emit('stop')"
          >
            <Icon icon="lucide:square" class="h-4 w-4" />
            <span class="chat-input-send-label">停止</span>
          </button>
          <button
            v-else
            type="submit"
            class="chat-input-send"
            :class="text.trim() && !isSending ? 'chat-input-send-ready' : 'chat-input-send-idle'"
            :disabled="isSending || !text.trim()"
            :aria-label="submitAriaLabel"
            @click.stop
          >
            <Icon :icon="isSending ? 'lucide:loader-circle' : 'lucide:send-horizontal'" class="h-4 w-4" :class="{ 'animate-spin': isSending }" />
            <span class="chat-input-send-label">{{ isEditing ? '保存' : '发送' }}</span>
          </button>
          </div>
        </div>
      </div>

      <div v-if="isDragging && canEditImage && mode === 'image'" class="studio-drop-overlay">
        <Icon icon="lucide:image-plus" class="h-5 w-5" />
        松开以上传参考图
      </div>
    </form>

    <p v-if="error" class="studio-composer-error">{{ error }}</p>
  </footer>
</template>

<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import GroupedSelectMenu from '@/components/ui/GroupedSelectMenu.vue'
import {
  DEFAULT_IMAGE_SIZE,
  IMAGE_COUNT_OPTIONS,
  IMAGE_QUALITY_OPTIONS,
  formatImageSizeLabel,
  resolveImageSizePresets,
  type ImageSizeResolution,
} from '@/api/imageTasks'
import { useChannels } from '@/composables/useChannels'
import { groupImageModelsByChannel, groupVideoModelsByChannel } from '@/config/channels'
import { isFireflyImageModel } from '@/config/modelCatalog'
import type { StudioComposeMode, StudioImageForm, StudioReference } from './types'

const props = defineProps<{
  mode: StudioComposeMode
  text: string
  chatModel: string
  chatReasoningEffort: string
  imageForm: StudioImageForm
  videoModel: string
  chatModelOptions: string[]
  imageModelOptions: string[]
  videoModelOptions: string[]
  imageUpscaleEnabled: boolean
  references: StudioReference[]
  isSending: boolean
  isStreaming: boolean
  isEditing: boolean
  error: string
}>()

const emit = defineEmits<{
  'update:mode': [mode: StudioComposeMode]
  'update:text': [text: string]
  'update:chatModel': [model: string]
  'update:chatReasoningEffort': [effort: string]
  'update:imageModel': [model: string]
  'update:videoModel': [model: string]
  'update:imageSize': [size: string]
  'update:imageQuality': [quality: string]
  'update:imageCount': [count: number]
  submit: []
  stop: []
  'cancel-edit': []
  'add-files': [files: File[]]
  'remove-reference': [index: number]
  'clear-references': []
  'preview-reference': [reference: StudioReference]
  'open-prompts': []
}>()

const { canChat, canImage, canEdit, canVideo, loadChannels } = useChannels()
/** 图生图入口：启用渠道能力并集含 edit */
const canEditImage = computed(() => canEdit.value)
/** 视频模式：启用渠道能力并集含 video */
const canVideoMode = computed(() => canVideo.value)

const composerShellRef = ref<HTMLElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const settingsButtonRef = ref<HTMLButtonElement | null>(null)
const isDragging = ref(false)
const settingsOpen = ref(false)
let textareaResizeFrame = 0
let composerResizeObserver: ResizeObserver | null = null

/**
 * 能力驱动模式列表：Studio 能力面 = 启用渠道 capabilities 并集。
 * - chat → 对话 / 搜索（搜索依附 chat）
 * - image → 画图
 * - video → 视频
 * 缺席=不出现（与渠道空状态原则一致）
 */
const modeOptions = computed(() => {
  const options: Array<{ label: string; value: StudioComposeMode }> = []
  if (canImage.value) options.push({ label: '画图', value: 'image' })
  if (canVideoMode.value) options.push({ label: '视频', value: 'video' })
  if (canChat.value) {
    options.push({ label: '对话', value: 'chat' })
    options.push({ label: '搜索', value: 'search' })
  }
  // 极端：所有能力都关时仍给一个对话入口，避免空工具栏
  if (!options.length) options.push({ label: '对话', value: 'chat' })
  return options
})

const submitAriaLabel = computed(() => {
  if (props.mode === 'image') return '提交图片任务'
  if (props.mode === 'video') return '提交视频任务'
  return '发送消息'
})

const textValue = computed({
  get: () => props.text,
  set: (value: string) => emit('update:text', value),
})

const modeValue = computed({
  get: () => props.mode,
  set: (value: string | number) => emit('update:mode', normalizeModeValue(value)),
})

const chatModelValue = computed({
  get: () => props.chatModel,
  set: (value: string | string[]) => emit('update:chatModel', String(Array.isArray(value) ? value[0] : value || 'auto')),
})

const chatReasoningEffortValue = computed({
  get: () => props.chatReasoningEffort || 'default',
  set: (value: string | string[]) => {
    const next = String(Array.isArray(value) ? value[0] : value || 'default')
    emit('update:chatReasoningEffort', next === 'default' ? '' : next)
  },
})

function normalizeModeValue(value: string | number): StudioComposeMode {
  if (value === 'chat' || value === 'search' || value === 'image' || value === 'video') return value
  return 'image'
}

function modeIcon(mode: StudioComposeMode) {
  if (mode === 'image') return 'lucide:image'
  if (mode === 'video') return 'lucide:clapperboard'
  if (mode === 'search') return 'lucide:search'
  return 'lucide:message-circle'
}

/** 当前 mode 不在能力并集内时，落到第一个可用模式 */
function ensureModeAllowed() {
  const allowed = new Set(modeOptions.value.map((item) => item.value))
  if (allowed.has(props.mode)) return
  const fallback = modeOptions.value[0]?.value || 'chat'
  if (fallback !== props.mode) emit('update:mode', fallback)
}

const imageModelValue = computed({
  get: () => props.imageForm.model,
  set: (value: string | string[]) => emit('update:imageModel', String(Array.isArray(value) ? value[0] : value || '')),
})

const videoModelValue = computed({
  get: () => props.videoModel,
  set: (value: string | string[]) => emit('update:videoModel', String(Array.isArray(value) ? value[0] : value || '')),
})

const chatModelSelectOptions = computed(() => props.chatModelOptions.map((model) => ({
  label: model === 'auto' ? '自动模型' : model,
  value: model,
})))

const chatReasoningEffortOptions = [
  { label: '默认思考', value: 'default' },
  { label: '低', value: 'low' },
  { label: '中', value: 'medium' },
  { label: '高', value: 'high' },
  { label: '超高', value: 'extended' },
]

const imageModelSelectOptions = computed(() => props.imageModelOptions.map((model) => ({
  label: model,
  value: model,
})))

const videoModelSelectOptions = computed(() => props.videoModelOptions.map((model) => ({
  label: model,
  value: model,
})))

/**
 * 图像模型分组：按启用渠道数据驱动（渠道名=组名）。
 * 仍用 isFireflyImageModel 决定旁路图像归属，避免 sora2/veo/kling 视频模型进 Firefly 图像组。
 * 渠道禁用 → 整组消失（listEnabledChannels）。
 */
const imageModelSelectGroups = computed(() => {
  const groups = groupImageModelsByChannel(props.imageModelOptions, {
    // 只有图像族进 Firefly 组；视频/未知 firefly 前缀回落到默认渠道（与旧手写逻辑一致）
    isBypassImageModel: isFireflyImageModel,
  })
  if (!groups.length) {
    return [{ options: imageModelSelectOptions.value }]
  }
  return groups.map((group) => ({
    label: group.label,
    options: group.options,
  }))
})

/** 视频模型分组：只进具备 video 能力的启用渠道 */
const videoModelSelectGroups = computed(() => {
  const groups = groupVideoModelsByChannel(props.videoModelOptions)
  if (!groups.length) {
    return [{ options: videoModelSelectOptions.value }]
  }
  return groups.map((group) => ({
    label: group.label,
    options: group.options,
  }))
})

const sizePresets = computed(() => resolveImageSizePresets(props.imageForm.model, props.imageUpscaleEnabled))
const selectedPreset = computed(() => sizePresets.value.find((preset) => preset.value === props.imageForm.size))
const selectedRatio = computed(() => selectedPreset.value?.ratio || 'auto')
const selectedResolution = computed(() => selectedPreset.value?.resolution || 'auto')
const ratioOptions = computed(() => {
  const seen = new Set<string>()
  return sizePresets.value
    .filter((preset) => {
      if (seen.has(preset.ratio)) return false
      seen.add(preset.ratio)
      return true
    })
    .map((preset) => ({ label: preset.ratio === 'auto' ? '自动' : preset.ratio, value: preset.ratio }))
})
const resolutionOptions = computed(() => {
  const order: ImageSizeResolution[] = ['auto', '1K', '2K', '4K']
  const values = new Set(sizePresets.value.map((preset) => preset.resolution))
  return order.filter((value) => values.has(value)).map((value) => ({ label: value === 'auto' ? '自动' : value, value }))
})
const selectedSizeDetailLabel = computed(() => formatImageSizeLabel(props.imageForm.size))
const mediaSummaryLabel = computed(() => {
  if (props.mode === 'video') {
    return props.videoModel || '视频模型'
  }
  const count = props.imageForm.n > 1 ? ` · ${props.imageForm.n} 张` : ''
  return `${formatImageSizeLabel(props.imageForm.size)}${count}`
})
const imagePlaceholder = computed(() => {
  if (canEditImage.value && props.references.length) return '描述你想如何修改参考图'
  if (canEditImage.value) return '输入你想生成的画面，也可以粘贴或拖入参考图'
  return '输入你想生成的画面'
})
const placeholderText = computed(() => {
  if (props.mode === 'image') return imagePlaceholder.value
  if (props.mode === 'video') return '描述你想生成的视频画面，Enter 提交'
  if (props.mode === 'search') return '输入搜索问题，Enter 搜索，Shift+Enter 换行'
  return '输入消息，Enter 发送，Shift+Enter 换行'
})

function toggleSettings() {
  settingsOpen.value = !settingsOpen.value
}

function handleOpenPrompts() {
  settingsOpen.value = false
  emit('open-prompts')
}

function resizeTextarea() {
  if (typeof window === 'undefined') return
  if (textareaResizeFrame) window.cancelAnimationFrame(textareaResizeFrame)
  textareaResizeFrame = window.requestAnimationFrame(() => {
    textareaResizeFrame = 0
    const element = textareaRef.value
    if (!element) return
    element.style.height = 'auto'
    const maxHeight = Number.parseFloat(window.getComputedStyle(element).maxHeight) || 192
    const nextHeight = Math.min(element.scrollHeight, maxHeight)
    element.style.height = `${nextHeight}px`
    element.style.overflowY = element.scrollHeight > maxHeight + 1 ? 'auto' : 'hidden'
  })
}

function scheduleTextareaResize() {
  void nextTick(resizeTextarea)
}

function syncComposerHeight() {
  const shell = composerShellRef.value
  const parent = shell?.parentElement
  if (!shell || !parent) return
  parent.style.setProperty('--studio-composer-height', `${Math.ceil(shell.offsetHeight)}px`)
}

function selectRatio(ratio: string) {
  const auto = sizePresets.value.find((preset) => preset.value === DEFAULT_IMAGE_SIZE)
  if (ratio === 'auto') {
    emit('update:imageSize', auto?.value || DEFAULT_IMAGE_SIZE)
    return
  }
  const exact = selectedResolution.value !== 'auto'
    ? sizePresets.value.find((preset) => preset.ratio === ratio && preset.resolution === selectedResolution.value)
    : undefined
  const next = exact || sizePresets.value.find((preset) => preset.ratio === ratio) || auto
  emit('update:imageSize', next?.value || DEFAULT_IMAGE_SIZE)
}

function selectResolution(resolution: ImageSizeResolution) {
  const auto = sizePresets.value.find((preset) => preset.value === DEFAULT_IMAGE_SIZE)
  if (resolution === 'auto') {
    emit('update:imageSize', auto?.value || DEFAULT_IMAGE_SIZE)
    return
  }
  const exact = selectedRatio.value !== 'auto'
    ? sizePresets.value.find((preset) => preset.ratio === selectedRatio.value && preset.resolution === resolution)
    : undefined
  const next = exact || sizePresets.value.find((preset) => preset.resolution === resolution) || auto
  emit('update:imageSize', next?.value || DEFAULT_IMAGE_SIZE)
}

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  emit('add-files', Array.from(input.files || []))
  input.value = ''
}

function handlePaste(event: ClipboardEvent) {
  if (props.mode !== 'image' || !canEditImage.value) return
  const files = Array.from(event.clipboardData?.files || []).filter(isImageFile)
  if (!files.length) return
  event.preventDefault()
  emit('add-files', files)
}

function handleDrop(event: DragEvent) {
  isDragging.value = false
  if (props.mode !== 'image' || !canEditImage.value) return
  emit('add-files', Array.from(event.dataTransfer?.files || []))
}

function handleDragLeave(event: DragEvent) {
  const current = event.currentTarget as HTMLElement
  if (event.relatedTarget instanceof Node && current.contains(event.relatedTarget)) return
  isDragging.value = false
}

function isImageFile(file: File) {
  return file.type.startsWith('image/') || /\.(avif|bmp|gif|heic|heif|ico|jpe?g|png|svg|tiff?|webp)$/i.test(file.name)
}

function handleOutsideClick(event: MouseEvent) {
  if (!settingsOpen.value) return
  const target = event.target as Node
  if (settingsButtonRef.value?.contains(target)) return
  settingsOpen.value = false
}

if (typeof window !== 'undefined') {
  window.addEventListener('click', handleOutsideClick)
}

onMounted(() => {
  void loadChannels()
  ensureModeAllowed()
  scheduleTextareaResize()
  syncComposerHeight()
  if (typeof ResizeObserver !== 'undefined' && composerShellRef.value) {
    composerResizeObserver = new ResizeObserver(syncComposerHeight)
    composerResizeObserver.observe(composerShellRef.value)
  }
})

watch(
  () => [props.text, props.mode, props.references.length, props.isEditing],
  scheduleTextareaResize,
  { flush: 'post' },
)

watch(
  modeOptions,
  () => ensureModeAllowed(),
  { flush: 'post' },
)

watch(
  () => [props.mode, canEditImage.value] as const,
  ([mode, editEnabled]) => {
    // 无 edit 能力或离开画图模式时清掉参考图，避免脏状态提交
    if ((mode !== 'image' || !editEnabled) && props.references.length) {
      emit('clear-references')
    }
  },
)

onBeforeUnmount(() => {
  if (typeof window === 'undefined') return
  if (textareaResizeFrame) window.cancelAnimationFrame(textareaResizeFrame)
  composerResizeObserver?.disconnect()
  composerResizeObserver = null
  composerShellRef.value?.parentElement?.style.removeProperty('--studio-composer-height')
  window.removeEventListener('click', handleOutsideClick)
})
</script>

<style scoped src="./styles/studio-composer-panel.css"></style>
<style scoped src="./styles/studio-composer-actions.css"></style>
<style scoped src="./styles/studio-composer-input.css"></style>
<style scoped src="./styles/studio-composer-attach.css"></style>
<style scoped src="./styles/studio-composer-send.css"></style>
<style scoped src="./styles/studio-composer-size.css"></style>
<style scoped src="./styles/studio-composer-overlay.css"></style>
<style scoped src="./styles/studio-composer-responsive.css"></style>

