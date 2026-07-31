<template>
  <section
    class="runtime-log-panel"
    :class="{ 'runtime-log-panel--fill': fill }"
    :style="panelStyle"
  >
    <div v-if="title || showToolbar || $slots.actions" class="runtime-log-panel__header">
      <div class="runtime-log-panel__heading">
        <span v-if="title" class="runtime-log-panel__title">{{ title }}</span>
        <span
          v-if="showToolbar && locked"
          class="runtime-log-panel__lock-hint"
          title="已锁定：新日志不会自动滚到底部"
        >已锁定</span>
      </div>
      <div class="runtime-log-panel__actions">
        <slot name="actions" />
        <template v-if="showToolbar">
          <Button
            size="xs"
            variant="outline"
            :disabled="isEmpty"
            title="滚动到最新日志并保持跟随"
            @click="scrollToBottom(true)"
          >
            滚动
          </Button>
          <Button
            size="xs"
            :variant="locked ? 'primary' : 'outline'"
            :title="locked ? '解锁：恢复自动跟随最新日志' : '锁定：日志照常更新，但停止自动滚动，可自行滑动查看历史'"
            @click="toggleLock"
          >
            {{ locked ? '解锁' : '锁定' }}
          </Button>
          <Button
            size="xs"
            variant="outline"
            :disabled="isEmpty"
            title="复制当前面板中的全部日志"
            @click="copyLogs"
          >
            复制
          </Button>
        </template>
      </div>
    </div>

    <div v-if="isEmpty" class="runtime-log-panel__empty">
      <EmptyState plain :title="emptyTitle" :description="emptyDescription" />
    </div>

    <div
      v-else
      ref="bodyEl"
      class="runtime-log-panel__body scrollbar-slim"
      @scroll.passive="onBodyScroll"
    >
      <pre v-if="rawText.trim()" class="runtime-log-panel__raw">{{ rawText }}</pre>
      <div v-else class="runtime-log-panel__lines">
        <div
          v-for="(line, index) in lines"
          :key="line.key || `${line.time || 'log'}-${index}`"
          class="runtime-log-panel__line"
          :class="[
            `runtime-log-panel__line--${line.level || 'info'}`,
            { 'runtime-log-panel__line--plain': !line.time },
          ]"
        >
          <span v-if="line.time" class="runtime-log-panel__time">{{ line.time }}</span>
          <span>{{ line.text || '-' }}</span>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Button, EmptyState } from 'nanocat-ui'
import { useClipboard } from '@/composables/useClipboard'
import { useToast } from '@/composables/useToast'

export type RuntimeLogPanelLine = {
  key?: string
  time?: string
  text: string
  level?: 'info' | 'success' | 'warning' | 'error' | string
}

const props = withDefaults(defineProps<{
  title?: string
  rawText?: string
  lines?: RuntimeLogPanelLine[]
  emptyTitle?: string
  emptyDescription?: string
  minHeight?: string
  maxHeight?: string
  fill?: boolean
  /** 是否显示滚动 / 锁定 / 复制工具栏，默认开启 */
  showToolbar?: boolean
  /** 初始是否锁定自动滚动 */
  defaultLocked?: boolean
}>(), {
  title: '',
  rawText: '',
  lines: () => [],
  emptyTitle: '暂无日志',
  emptyDescription: '',
  minHeight: '16rem',
  maxHeight: 'min(60vh, 42rem)',
  fill: false,
  showToolbar: true,
  defaultLocked: false,
})

const toast = useToast()
const { copy } = useClipboard()
const bodyEl = ref<HTMLElement | null>(null)
const locked = ref(Boolean(props.defaultLocked))
/** 程序滚动时忽略 scroll 事件，避免误触锁定 */
const ignoreScrollEvent = ref(false)
const NEAR_BOTTOM_PX = 48

const isEmpty = computed(() => !props.rawText.trim() && props.lines.length === 0)

const panelStyle = computed(() => ({
  '--runtime-log-min-height': props.minHeight,
  '--runtime-log-max-height': props.maxHeight,
}))

const contentFingerprint = computed(() => {
  if (props.rawText.trim()) {
    return `raw:${props.rawText.length}:${props.rawText.slice(-80)}`
  }
  const lines = props.lines
  if (!lines.length) return 'empty'
  const last = lines[lines.length - 1]
  return `lines:${lines.length}:${last?.key || ''}:${last?.text || ''}`
})

const exportText = computed(() => {
  if (props.rawText.trim()) return props.rawText
  return props.lines
    .map((line) => {
      const time = String(line.time || '').trim()
      const text = String(line.text || '').trimEnd()
      return time ? `${time}  ${text}` : text
    })
    .join('\n')
})

function isNearBottom(el: HTMLElement) {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX
}

function scrollToBottom(force = false) {
  const el = bodyEl.value
  if (!el) return
  if (!force && locked.value) return
  ignoreScrollEvent.value = true
  el.scrollTop = el.scrollHeight
  window.setTimeout(() => {
    ignoreScrollEvent.value = false
  }, 80)
  // 仅用户主动点「滚动」时才解除锁定并恢复跟随；自动更新不擅自解锁
  if (force && locked.value) {
    locked.value = false
  }
}

function toggleLock() {
  locked.value = !locked.value
  if (!locked.value) {
    // 手动解锁 → 回到最新并恢复自动跟随
    void nextTick(() => scrollToBottom(true))
  }
}

function onBodyScroll() {
  if (ignoreScrollEvent.value) return
  const el = bodyEl.value
  if (!el) return
  // 只在「当前处于自动跟随（未锁定）」时，用户上滑离开底部才转为锁定；
  // 已锁定状态下用户自由滑动查看历史，不再被这个监听改来改去
  if (!locked.value && !isNearBottom(el)) {
    locked.value = true
  }
}

async function copyLogs() {
  const text = exportText.value.trim()
  if (!text) {
    toast.error('暂无日志可复制')
    return
  }
  await copy(text, { success: '日志已复制' })
}

watch(
  contentFingerprint,
  async () => {
    if (isEmpty.value || locked.value) return
    await nextTick()
    scrollToBottom(false)
  },
  { flush: 'post' },
)
</script>

<style scoped>
.runtime-log-panel {
  display: flex;
  min-height: var(--runtime-log-min-height);
  max-height: var(--runtime-log-max-height);
  flex-direction: column;
  overflow: hidden;
  border: 1px solid hsl(var(--border));
  border-radius: var(--radius);
  background: hsl(var(--card));
}

.runtime-log-panel--fill {
  flex: 1;
  max-height: none;
}

.runtime-log-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid hsl(var(--border));
  padding: 8px 12px;
  background: hsl(var(--card));
}

.runtime-log-panel__heading {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.45rem;
}

.runtime-log-panel__title {
  font-size: 12px;
  font-weight: 500;
  color: hsl(var(--muted-foreground));
}

.runtime-log-panel__lock-hint {
  flex: 0 0 auto;
  border: 1px solid hsl(var(--border));
  border-radius: 999px;
  padding: 0.05rem 0.42rem;
  color: hsl(var(--muted-foreground));
  font-size: 10px;
  line-height: 1.4;
}

.runtime-log-panel__actions {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
}

.runtime-log-panel__empty {
  display: flex;
  min-height: var(--runtime-log-min-height);
  flex: 1;
  align-items: center;
  justify-content: center;
  padding: 16px;
}

.runtime-log-panel__body {
  min-height: 0;
  flex: 1;
  overflow: auto;
  background: #09090b;
  padding: 12px 16px;
  color: #fafafa;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 12px;
  line-height: 1.65;
}

.runtime-log-panel__raw {
  min-width: max-content;
  margin: 0;
  white-space: pre;
}

.runtime-log-panel__lines {
  display: grid;
  gap: 2px;
}

.runtime-log-panel__line {
  display: grid;
  grid-template-columns: 5.5rem minmax(0, 1fr);
  gap: 10px;
  white-space: pre-wrap;
  word-break: break-word;
}

.runtime-log-panel__line--plain {
  grid-template-columns: minmax(0, 1fr);
}

.runtime-log-panel__time {
  color: rgb(161 161 170);
}

.runtime-log-panel__line--error {
  color: #fecdd3;
}

.runtime-log-panel__line--success {
  color: #bbf7d0;
}

.runtime-log-panel__line--warning {
  color: #fde68a;
}

@media (max-width: 640px) {
  .runtime-log-panel__header {
    gap: 8px;
    padding: 6px 10px;
    flex-wrap: wrap;
  }

  .runtime-log-panel__title {
    font-size: 11px;
  }

  .runtime-log-panel__actions {
    gap: 4px;
  }

  .runtime-log-panel__body {
    padding: 10px 12px;
    font-size: 11px;
    line-height: 1.55;
  }

  .runtime-log-panel__line {
    grid-template-columns: 4.5rem minmax(0, 1fr);
    gap: 6px;
  }

  .runtime-log-panel__empty {
    padding: 12px;
  }
}
</style>
