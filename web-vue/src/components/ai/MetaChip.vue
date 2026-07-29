<template>
  <NanocatMetaChip
    :tone="resolvedTone"
    :variant="variant"
    :size="resolvedSize"
    :chip-class="resolvedChipClass"
  >
    <slot />
  </NanocatMetaChip>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { MetaChip as NanocatMetaChip } from 'nanocat-ui'

const props = withDefaults(defineProps<{
  tone?: 'default' | 'muted' | 'success' | 'warning' | 'danger' | 'info'
  variant?: 'soft' | 'outline' | 'solid'
  size?: 'xs' | 'sm' | 'md'
  strong?: boolean
  chipClass?: string
}>(), {
  tone: 'default',
  variant: 'soft',
  size: 'sm',
  strong: false,
  chipClass: '',
})

const resolvedTone = computed(() => {
  if (props.tone === 'success') return 'success'
  if (props.tone === 'warning') return 'warning'
  if (props.tone === 'danger') return 'error'
  if (props.tone === 'info') return 'info'
  return 'neutral'
})

const resolvedSize = computed(() => props.size === 'md' ? 'md' : 'sm')

const resolvedChipClass = computed(() => {
  const classes = ['ai-meta-chip', `ai-meta-chip--${props.tone}`]
  if (props.size === 'xs') classes.push('min-h-5 px-2 py-0.5 text-[11px]')
  if (props.strong) classes.push('font-semibold')
  if (props.chipClass) classes.push(props.chipClass)
  return classes.join(' ')
})
</script>

<style>
/* 不改 nanocat 本体：用本地类压成 Bauhaus 锐边 + tone 令牌字色 */
.ai-meta-chip {
  border-radius: var(--radius) !important;
}

.ai-meta-chip--muted {
  color: hsl(var(--muted-foreground)) !important;
}

.ai-meta-chip--success {
  color: var(--bauhaus-blue, #2d5da1) !important;
}

.ai-meta-chip--warning {
  color: hsl(var(--tone-warning-foreground)) !important;
}

.ai-meta-chip--danger {
  color: hsl(var(--tone-error-foreground)) !important;
}

.ai-meta-chip--info {
  color: hsl(var(--tone-info-foreground)) !important;
}

html[data-theme='dark'] .ai-meta-chip--success {
  color: var(--bauhaus-blue, #3d8fd9) !important;
}

html[data-theme='dark'] .ai-meta-chip--warning {
  color: hsl(var(--tone-warning-foreground)) !important;
}

html[data-theme='dark'] .ai-meta-chip--danger {
  color: hsl(var(--tone-error-foreground)) !important;
}

html[data-theme='dark'] .ai-meta-chip--info {
  color: hsl(var(--tone-info-foreground)) !important;
}

html[data-theme='dark'] .ai-meta-chip--muted {
  color: var(--bauhaus-grey, #a3a3a3) !important;
}
</style>
