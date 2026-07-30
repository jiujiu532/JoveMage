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
  display: flex;
  width: 100%;
}

.console-segmented-tabs--content {
  width: max-content;
  max-width: 100%;
}

/* 包豪斯 Tab：分段色块墙，激活 = 纯蓝块 + 白字 */
.console-segmented-tabs :deep(.ui-segmented) {
  width: 100%;
  flex-wrap: wrap;
  gap: 0;
  padding: 0;
  border: 2px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  background: hsl(var(--card));
  overflow: hidden;
}

html[data-theme='dark'] .console-segmented-tabs :deep(.ui-segmented) {
  border-color: hsl(var(--border));
}

.console-segmented-tabs--content :deep(.ui-segmented) {
  width: auto;
}

.console-segmented-tabs :deep(.ui-segmented-btn) {
  min-height: 36px;
  border-radius: 0;
  border: none;
  border-right: 1px solid hsl(var(--border));
  padding: 0 14px;
  font-family: var(--font-display);
  font-size: 11px;
  line-height: 1;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  white-space: nowrap;
  background: transparent;
  color: var(--bauhaus-grey, #9e9e9e);
  box-shadow: none;
}

.console-segmented-tabs :deep(.ui-segmented-btn:last-child) {
  border-right: none;
}

.console-segmented-tabs--stretch :deep(.ui-segmented-btn) {
  flex: 1 1 0;
  justify-content: center;
}

.console-segmented-tabs--content :deep(.ui-segmented-btn) {
  flex: 0 0 auto;
}

.console-segmented-tabs :deep(.ui-segmented-btn:hover:not(.ui-segmented-btn-active)) {
  background: hsl(var(--muted));
  color: hsl(var(--foreground));
}

.console-segmented-tabs :deep(.ui-segmented-btn-active) {
  border-color: transparent;
  background: var(--bauhaus-blue, #2d5da1);
  color: #ffffff;
  box-shadow: none;
  font-weight: 700;
}

.console-segmented-tabs :deep(.ui-segmented-btn-active .ui-segmented-count) {
  background: rgba(255, 255, 255, 0.22);
  color: #ffffff;
}

@media (max-width: 640px) {
  .console-segmented-tabs :deep(.ui-segmented) {
    border-width: 1.5px;
  }

  .console-segmented-tabs :deep(.ui-segmented-btn) {
    min-height: 36px;
    padding: 0 10px;
    font-size: 10px;
    letter-spacing: 0.08em;
  }

  .console-segmented-tabs--content {
    width: 100%;
    max-width: 100%;
  }

  .console-segmented-tabs--content :deep(.ui-segmented) {
    width: 100%;
  }

  .console-segmented-tabs--content :deep(.ui-segmented-btn) {
    flex: 1 1 0;
    justify-content: center;
  }
}
</style>
