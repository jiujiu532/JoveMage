<template>
  <div
    v-if="content"
    class="detail-text-block"
    :class="`detail-text-block--tone-${tone}`"
    :style="{ '--detail-text-block-max-height': maxHeight }"
  >
    <div class="detail-text-block__header">
      <span class="detail-text-block__title">{{ title }}</span>
      <Button size="xs" variant="ghost" @click="$emit('copy', content)">
        复制
      </Button>
    </div>
    <pre class="detail-text-block__content scrollbar-slim">{{ content }}</pre>
  </div>
</template>

<script setup lang="ts">
import { Button } from 'nanocat-ui'

withDefaults(defineProps<{
  title: string
  content?: string
  tone?: 'default' | 'danger' | 'warning' | 'muted'
  maxHeight?: string
}>(), {
  content: '',
  tone: 'default',
  maxHeight: '16rem',
})

defineEmits<{
  (e: 'copy', value: string): void
}>()
</script>

<style scoped>
.detail-text-block {
  border: 1px solid var(--bauhaus-line-soft);
  border-radius: var(--radius);
  background: hsl(var(--card));
}

.detail-text-block--tone-danger {
  /* 覆盖全局 surface 合同的 line-soft 描边 */
  border-color: hsl(var(--tone-error-border)) !important;
  background: hsl(var(--tone-error-bg)) !important;
}

.detail-text-block--tone-warning {
  border-color: hsl(var(--tone-warning-border)) !important;
  background: hsl(var(--tone-warning-bg)) !important;
}

.detail-text-block--tone-muted {
  background: hsl(var(--muted) / 0.2);
}

.detail-text-block__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border-bottom: 1px solid var(--bauhaus-line-soft);
  padding: 8px 12px;
}

.detail-text-block__title {
  font-size: 12px;
  font-weight: 500;
  color: hsl(var(--foreground));
}

.detail-text-block__content {
  max-height: var(--detail-text-block-max-height, 16rem);
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: break-word;
  padding: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 11px;
  line-height: 1.55;
  color: hsl(var(--foreground));
}

.detail-text-block--tone-muted .detail-text-block__content {
  color: hsl(var(--muted-foreground));
}
</style>
