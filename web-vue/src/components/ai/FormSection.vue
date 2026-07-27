<template>
  <section
    class="form-section"
    :class="[
      `form-section--density-${density}`,
      muted ? 'form-section--surface-muted' : `form-section--surface-${surface}`,
    ]"
  >
    <div v-if="title || subtitle || $slots.actions" class="form-section__header">
      <div class="min-w-0">
        <p v-if="title" class="form-section__title">{{ title }}</p>
        <p v-if="subtitle" class="form-section__subtitle">{{ subtitle }}</p>
      </div>
      <div v-if="$slots.actions" class="form-section__actions">
        <slot name="actions" />
      </div>
    </div>
    <slot />
  </section>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  title?: string
  subtitle?: string
  density?: 'compact' | 'normal' | 'roomy'
  surface?: 'card' | 'background' | 'muted' | 'plain'
  muted?: boolean
}>(), {
  title: '',
  subtitle: '',
  density: 'normal',
  surface: 'card',
  muted: false,
})
</script>

<style scoped>
.form-section {
  position: relative;
  border: 2px solid hsl(var(--border));
  border-radius: var(--radius);
  box-shadow: none;
  overflow: hidden;
}

.form-section--surface-card {
  background: hsl(var(--card));
}

.form-section--surface-background {
  background: hsl(var(--background));
}

.form-section--surface-muted {
  background: hsl(var(--muted) / 0.28);
}

.form-section--surface-plain {
  border-color: transparent;
  background: transparent;
}

.form-section--density-compact {
  padding: 10px 10px 10px 14px;
}

.form-section--density-normal {
  padding: 12px 12px 12px 16px;
}

.form-section--density-roomy {
  padding: 16px 16px 16px 20px;
}

.form-section--surface-plain.form-section--density-compact,
.form-section--surface-plain.form-section--density-normal,
.form-section--surface-plain.form-section--density-roomy {
  padding: 0;
}

.form-section__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.form-section__title {
  font-family: var(--font-display);
  font-size: 11px;
  font-weight: 700;
  line-height: 1.25;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--bauhaus-grey, #9e9e9e);
}

.form-section__subtitle {
  margin-top: 3px;
  font-size: 12px;
  line-height: 1.45;
  color: var(--bauhaus-grey, #9e9e9e);
}

.form-section__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

/* 非 plain 表面左侧色条 */
.form-section:not(.form-section--surface-plain)::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  background: var(--bauhaus-blue, #2d5da1);
}
</style>
