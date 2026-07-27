<template>
  <span
    class="state-badge"
    :class="[
      `state-badge--tone-${tone}`,
      `state-badge--size-${size}`,
      `state-badge--shape-${shape}`,
      bordered ? 'state-badge--bordered' : 'state-badge--plain',
    ]"
  >
    <slot />
  </span>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  tone?: 'success' | 'danger' | 'warning' | 'info' | 'muted'
  size?: 'xs' | 'sm'
  shape?: 'pill' | 'rounded'
  bordered?: boolean
}>(), {
  tone: 'muted',
  size: 'sm',
  shape: 'rounded',
  bordered: true,
})
</script>

<style scoped>
.state-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  white-space: nowrap;
  font-family: var(--font-display);
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  line-height: 1;
  border-radius: var(--radius);
}

.state-badge--size-xs {
  min-height: 1.25rem;
  padding: 0.125rem 0.45rem;
  font-size: 10px;
}

.state-badge--size-sm {
  min-height: 1.5rem;
  min-width: 3rem;
  padding: 0.25rem 0.55rem;
  font-size: 11px;
}

/* 包豪斯：默认锐边；即便传 pill 也压成小圆角方块 */
.state-badge--shape-pill,
.state-badge--shape-rounded {
  border-radius: var(--radius);
}

.state-badge--bordered {
  border: 1px solid transparent;
}

.state-badge--plain {
  border: 1px solid transparent;
}

/* success → 蓝（秩序/可用）；warning → 黄；danger → 红；info → 蓝淡底 */
.state-badge--tone-success {
  background: var(--bauhaus-blue, #2d5da1);
  color: #ffffff;
}

.state-badge--bordered.state-badge--tone-success {
  border-color: var(--bauhaus-blue, #2d5da1);
}

.state-badge--tone-danger {
  background: var(--bauhaus-red, #ff4d4d);
  color: #ffffff;
}

.state-badge--bordered.state-badge--tone-danger {
  border-color: var(--bauhaus-red, #ff4d4d);
}

.state-badge--tone-warning {
  background: var(--bauhaus-yellow, #fff9c4);
  color: var(--bauhaus-ink, #2d2d2d);
}

.state-badge--bordered.state-badge--tone-warning {
  border-color: var(--bauhaus-yellow, #fff9c4);
}

.state-badge--tone-info {
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 14%, white);
  color: var(--bauhaus-blue, #2d5da1);
}

.state-badge--bordered.state-badge--tone-info {
  border-color: var(--bauhaus-blue, #2d5da1);
}

.state-badge--tone-muted {
  background: hsl(var(--muted));
  color: var(--bauhaus-grey, #9e9e9e);
}

.state-badge--bordered.state-badge--tone-muted {
  border-color: hsl(var(--border));
}

html[data-theme='dark'] .state-badge--tone-info {
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 22%, transparent);
}
</style>
