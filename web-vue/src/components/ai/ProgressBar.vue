<template>
  <div
    class="progress-bar"
    role="progressbar"
    :aria-label="ariaLabel"
    :aria-valuenow="normalizedValue"
    aria-valuemin="0"
    aria-valuemax="100"
  >
    <div class="progress-bar__fill" :style="{ width: `${normalizedValue}%` }"></div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  value: number | string
  ariaLabel?: string
}>(), {
  ariaLabel: 'Progress',
})

const normalizedValue = computed(() => {
  const value = Number(props.value)
  if (!Number.isFinite(value)) return 0
  return Math.min(100, Math.max(0, value))
})
</script>

<style scoped>
.progress-bar {
  height: 0.5rem;
  overflow: hidden;
  border: 1px solid var(--bauhaus-ink);
  border-radius: var(--radius);
  background: hsl(var(--muted));
}

.progress-bar__fill {
  height: 100%;
  background: var(--bauhaus-blue);
  transition: width 180ms ease;
}
</style>
