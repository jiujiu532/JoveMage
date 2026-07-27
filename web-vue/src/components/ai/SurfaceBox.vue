<template>
  <component
    :is="tag"
    class="surface-box"
    :class="[
      `surface-box--tone-${tone}`,
      `surface-box--density-${density}`,
      {
        'surface-box--dashed': dashed,
        'surface-box--scroll': scroll,
        'surface-box--mono': mono,
        'surface-box--wrap': wrap,
      },
    ]"
  >
    <slot />
  </component>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  tag?: 'div' | 'p' | 'label'
  tone?: 'card' | 'background' | 'muted' | 'danger'
  density?: 'compact' | 'normal'
  dashed?: boolean
  scroll?: boolean
  mono?: boolean
  wrap?: boolean
}>(), {
  tag: 'div',
  tone: 'card',
  density: 'normal',
  dashed: false,
  scroll: false,
  mono: false,
  wrap: false,
})
</script>

<style scoped>
.surface-box {
  border: 2px solid hsl(var(--border));
  border-radius: var(--radius);
  font-size: 12px;
  box-shadow: none;
}

.surface-box--tone-card {
  background: hsl(var(--card));
  color: hsl(var(--foreground));
}

.surface-box--tone-background {
  background: hsl(var(--background));
  color: hsl(var(--foreground));
}

.surface-box--tone-muted {
  background: hsl(var(--muted) / 0.35);
  color: var(--bauhaus-grey, #9e9e9e);
}

.surface-box--tone-danger {
  border-color: var(--bauhaus-red, #ff4d4d);
  background: color-mix(in srgb, var(--bauhaus-red, #ff4d4d) 12%, #ffffff);
  color: var(--bauhaus-red, #ff4d4d);
}

html[data-theme='dark'] .surface-box--tone-danger {
  background: color-mix(in srgb, var(--bauhaus-red, #ff4d4d) 16%, transparent);
}

.surface-box--density-compact {
  padding: 8px 12px;
}

.surface-box--density-normal {
  padding: 12px;
}

.surface-box--dashed {
  border-style: dashed;
}

.surface-box--scroll {
  max-height: 6rem;
  overflow-y: auto;
}

.surface-box--mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 11px;
}

.surface-box--wrap {
  word-break: break-all;
}
</style>
