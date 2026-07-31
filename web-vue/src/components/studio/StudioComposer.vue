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
          <div v-if="mode === 'image' && references.length" class="attach-images">
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

            <template v-else-if="mode === 'image'">
              <button
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
                  <span class="text">{{ imageSummaryLabel }}</span>
                  <Icon icon="lucide:chevron-down" class="h-3.5 w-3.5" />
                </button>

                <div v-if="settingsOpen" class="studio-size-popover" @click.stop>
                  <div class="studio-size-section">
                    <div class="studio-size-label">模型</div>
                    <GroupedSelectMenu
                      v-model="imageModelValue"
                      :groups="imageModelSelectGroups"
                      :options="imageModelSelectOptions"
                      selected-indicator="none"
                      show-group-labels
                      block
                    />
                  </div>
                  <div class="studio-size-section">
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
                  <div class="studio-size-section">
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
                  <div class="studio-size-section">
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
                  <div class="studio-size-section">
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
                </div>
              </div>
              <button
                v-if="references.length"
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
            <div v-if="references.length" class="chat-input-status">
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
            :aria-label="mode === 'image' ? '提交图片任务' : '发送消息'"
            @click.stop
          >
            <Icon :icon="isSending ? 'lucide:loader-circle' : 'lucide:send-horizontal'" class="h-4 w-4" :class="{ 'animate-spin': isSending }" />
            <span class="chat-input-send-label">{{ isEditing ? '保存' : '发送' }}</span>
          </button>
          </div>
        </div>
      </div>

      <div v-if="isDragging" class="studio-drop-overlay">
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
import { isFireflyImageModel } from '@/config/modelCatalog'
import type { StudioComposeMode, StudioImageForm, StudioReference } from './types'

const props = defineProps<{
  mode: StudioComposeMode
  text: string
  chatModel: string
  chatReasoningEffort: string
  imageForm: StudioImageForm
  chatModelOptions: string[]
  imageModelOptions: string[]
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

const composerShellRef = ref<HTMLElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const settingsButtonRef = ref<HTMLButtonElement | null>(null)
const isDragging = ref(false)
const settingsOpen = ref(false)
let textareaResizeFrame = 0
let composerResizeObserver: ResizeObserver | null = null

const modeOptions: Array<{ label: string; value: StudioComposeMode }> = [
  { label: '画图', value: 'image' },
  { label: '对话', value: 'chat' },
  { label: '搜索', value: 'search' },
]

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
  if (value === 'chat' || value === 'search' || value === 'image') return value
  return 'image'
}

function modeIcon(mode: StudioComposeMode) {
  if (mode === 'image') return 'lucide:image'
  if (mode === 'search') return 'lucide:search'
  return 'lucide:message-circle'
}

const imageModelValue = computed({
  get: () => props.imageForm.model,
  set: (value: string | string[]) => emit('update:imageModel', String(Array.isArray(value) ? value[0] : value || '')),
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

const imageModelSelectGroups = computed(() => {
  const chatgpt: Array<{ label: string; value: string }> = []
  const firefly: Array<{ label: string; value: string }> = []
  for (const model of props.imageModelOptions) {
    const option = { label: model, value: model }
    // 图像路径只认 Firefly 图像族，避免 sora2/veo/kling 视频模型误入
    if (isFireflyImageModel(model)) firefly.push(option)
    else chatgpt.push(option)
  }
  const groups: Array<{ label?: string; options: Array<{ label: string; value: string }> }> = []
  if (chatgpt.length) groups.push({ label: 'ChatGPT', options: chatgpt })
  if (firefly.length) groups.push({ label: 'Adobe Firefly', options: firefly })
  if (!groups.length) {
    groups.push({ options: imageModelSelectOptions.value })
  }
  return groups
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
const imageSummaryLabel = computed(() => {
  const count = props.imageForm.n > 1 ? ` · ${props.imageForm.n} 张` : ''
  return `${formatImageSizeLabel(props.imageForm.size)}${count}`
})
const imagePlaceholder = computed(() => props.references.length ? '描述你想如何修改参考图' : '输入你想生成的画面，也可以粘贴或拖入参考图')
const placeholderText = computed(() => {
  if (props.mode === 'image') return imagePlaceholder.value
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
  if (props.mode !== 'image') return
  const files = Array.from(event.clipboardData?.files || []).filter(isImageFile)
  if (!files.length) return
  event.preventDefault()
  emit('add-files', files)
}

function handleDrop(event: DragEvent) {
  isDragging.value = false
  if (props.mode !== 'image') return
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

