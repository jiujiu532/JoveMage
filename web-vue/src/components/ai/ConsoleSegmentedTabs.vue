<template>
  <div class="console-segmented-tabs" :class="`console-segmented-tabs--${fit}`">
    <SegmentedTabs
      :model-value="modelValue"
      :options="options"
      :aria-label="ariaLabel"
      @update:model-value="(value) => emit('update:modelValue', value)"
    />
  </div>
</template>

<script setup lang="ts">
import { SegmentedTabs } from 'nanocat-ui'
import type { SegmentedOption, SegmentedValue } from 'nanocat-ui'

withDefaults(defineProps<{
  modelValue: SegmentedValue
  options: SegmentedOption[]
  ariaLabel?: string
  fit?: 'stretch' | 'content'
}>(), {
  fit: 'stretch',
})

const emit = defineEmits<{
  'update:modelValue': [value: SegmentedValue]
}>()
</script>

<style scoped>
.console-segmented-tabs {
  display: block;
  width: 100%;
  min-width: 0;
  max-width: 100%;
}

.console-segmented-tabs--content {
  width: auto;
  max-width: 100%;
}

/*
 * 包豪斯分段：外框 ink 硬边 + 内容自适应；
 * 激活态 = 纯蓝块 + 白字（覆盖全局 postit 黄，账号 Tab 不再「便签黄」突兀）
 */
.console-segmented-tabs :deep(.ui-segmented) {
  display: inline-flex;
  width: auto;
  max-width: 100%;
  flex-wrap: wrap;
  gap: 0;
  padding: 0 !important;
  border: 2px solid var(--bauhaus-ink, #2d2d2d) !important;
  border-radius: var(--radius) !important;
  background: hsl(var(--card)) !important;
  overflow: hidden;
  box-shadow: 2px 2px 0 0 var(--bauhaus-ink, #2d2d2d);
}

html[data-theme='dark'] .console-segmented-tabs :deep(.ui-segmented) {
  border-color: hsl(var(--border)) !important;
  box-shadow: none;
}

.console-segmented-tabs--stretch :deep(.ui-segmented) {
  display: flex;
  width: 100%;
}

.console-segmented-tabs :deep(.ui-segmented-btn) {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.45rem;
  min-height: 2.25rem;
  border-radius: 0 !important;
  border: none !important;
  border-right: 1px solid hsl(var(--border)) !important;
  padding: 0 0.9rem !important;
  font-family: var(--font-display) !important;
  font-size: 11px !important;
  line-height: 1 !important;
  font-weight: 600 !important;
  letter-spacing: 0.1em !important;
  text-transform: uppercase !important;
  white-space: nowrap;
  background: transparent !important;
  color: var(--bauhaus-grey, #9e9e9e) !important;
  box-shadow: none !important;
  transition: background 120ms ease, color 120ms ease;
}

.console-segmented-tabs :deep(.ui-segmented-btn:last-child) {
  border-right: none !important;
}

.console-segmented-tabs--stretch :deep(.ui-segmented-btn) {
  flex: 1 1 0;
}

.console-segmented-tabs--content :deep(.ui-segmented-btn) {
  flex: 0 0 auto;
}

.console-segmented-tabs :deep(.ui-segmented-btn:hover:not(.ui-segmented-btn-active)) {
  background: hsl(var(--muted)) !important;
  color: hsl(var(--foreground)) !important;
}

.console-segmented-tabs :deep(.ui-segmented-btn-active) {
  background: var(--bauhaus-blue, #2d5da1) !important;
  color: #ffffff !important;
  font-weight: 700 !important;
  box-shadow: none !important;
  border-color: transparent !important;
  z-index: 1;
}

.console-segmented-tabs :deep(.ui-segmented-count) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.35rem;
  height: 1.2rem;
  padding: 0 0.35rem;
  border-radius: 999px !important;
  font-family: var(--font-display) !important;
  font-size: 10px !important;
  font-weight: 700 !important;
  letter-spacing: 0 !important;
  text-transform: none !important;
  font-variant-numeric: tabular-nums;
  background: hsl(var(--muted)) !important;
  color: hsl(var(--muted-foreground)) !important;
  line-height: 1;
}

.console-segmented-tabs :deep(.ui-segmented-btn-active .ui-segmented-count) {
  background: rgba(255, 255, 255, 0.22) !important;
  color: #ffffff !important;
}

/* 窄屏：横向滑动，避免被 PagePanel overflow 裁切 */
@media (max-width: 1023px) {
  .console-segmented-tabs {
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;
    overscroll-behavior-x: contain;
    scrollbar-width: thin;
    padding-bottom: 2px;
  }

  .console-segmented-tabs :deep(.ui-segmented) {
    display: inline-flex;
    flex-wrap: nowrap;
    width: max-content;
    min-width: 0;
    max-width: none;
    border-width: 1.5px !important;
    overflow: visible;
    box-shadow: none;
  }

  .console-segmented-tabs :deep(.ui-segmented-btn) {
    min-height: 2.15rem;
    flex: 0 0 auto;
    padding: 0 0.75rem !important;
    font-size: 10px !important;
    letter-spacing: 0.06em !important;
  }

  .console-segmented-tabs--stretch :deep(.ui-segmented-btn) {
    flex: 0 0 auto;
  }
}
</style>
