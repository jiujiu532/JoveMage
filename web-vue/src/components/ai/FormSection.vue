<template>
  <section
    class="form-section"
    :class="[
      `form-section--density-${density}`,
      muted ? 'form-section--surface-muted' : `form-section--surface-${surface}`,
      collapsible && collapsed ? 'form-section--collapsed' : '',
    ]"
  >
    <div
      v-if="title || subtitle || $slots.actions"
      class="form-section__header"
      :class="{ 'form-section__header--toggle': collapsible }"
      :role="collapsible ? 'button' : undefined"
      :tabindex="collapsible ? 0 : undefined"
      :aria-expanded="collapsible ? (!collapsed).toString() : undefined"
      @click="onHeaderClick"
      @keydown="onHeaderKeydown"
    >
      <div class="min-w-0">
        <p v-if="title" class="form-section__title">{{ title }}</p>
        <p v-if="subtitle" class="form-section__subtitle">{{ subtitle }}</p>
      </div>
      <div class="form-section__header-end">
        <div v-if="$slots.actions" class="form-section__actions" @click.stop>
          <slot name="actions" />
        </div>
        <CollapseCaret v-if="collapsible" :open="!collapsed" />
      </div>
    </div>
    <div v-show="!collapsible || !collapsed" class="form-section__body">
      <slot />
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import CollapseCaret from '@/components/ai/CollapseCaret.vue'

const props = withDefaults(defineProps<{
  title?: string
  subtitle?: string
  density?: 'compact' | 'normal' | 'roomy'
  surface?: 'card' | 'background' | 'muted' | 'plain'
  muted?: boolean
  collapsible?: boolean
  defaultOpen?: boolean
}>(), {
  title: '',
  subtitle: '',
  density: 'normal',
  surface: 'card',
  muted: false,
  collapsible: false,
  defaultOpen: true,
})

const collapsed = ref(props.collapsible ? !props.defaultOpen : false)

function toggle() {
  if (!props.collapsible) return
  collapsed.value = !collapsed.value
}

function onHeaderClick() {
  toggle()
}

function onHeaderKeydown(e: KeyboardEvent) {
  if (!props.collapsible) return
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    toggle()
  }
}
</script>

<style scoped>
.form-section {
  position: relative;
  border: 1px solid hsl(var(--border));
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
  padding: 12px 12px 12px 16px;
}

.form-section--density-normal {
  padding: 14px 14px 14px 18px;
}

.form-section--density-roomy {
  padding: 18px 18px 18px 22px;
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
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid hsl(var(--border) / 0.75);
}

.form-section__header--toggle {
  cursor: pointer;
  user-select: none;
  outline: none;
}

.form-section__header--toggle:hover .form-section__title {
  color: var(--bauhaus-blue, #2d5da1);
}

.form-section__header--toggle:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 45%, transparent);
  outline-offset: 2px;
}

.form-section--collapsed .form-section__header {
  margin-bottom: 0;
  padding-bottom: 0;
  border-bottom-color: transparent;
}

.form-section--surface-plain .form-section__header {
  border-bottom: none;
  padding-bottom: 0;
}

.form-section__title {
  font-family: var(--font-body);
  font-size: 0.9375rem;
  font-weight: 600;
  line-height: 1.35;
  letter-spacing: 0;
  text-transform: none;
  color: hsl(var(--foreground));
  transition: color 0.12s ease;
}

.form-section__subtitle {
  margin-top: 5px;
  max-width: 62ch;
  font-family: var(--font-body);
  font-size: 0.8125rem;
  font-weight: 400;
  line-height: 1.5;
  letter-spacing: 0;
  color: hsl(var(--muted-foreground));
}

.form-section__header-end {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 8px;
}

.form-section__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.form-section__body {
  min-width: 0;
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

html[data-theme='dark'] .form-section {
  border-color: hsl(var(--border));
  background: hsl(var(--card));
}

html[data-theme='dark'] .form-section__title {
  color: hsl(var(--foreground));
}

html[data-theme='dark'] .form-section__subtitle {
  color: hsl(var(--muted-foreground) / 0.88);
}

html[data-theme='dark'] .form-section__header--toggle:hover .form-section__title {
  color: hsl(var(--primary));
}

html[data-theme='dark'] .form-section__header--toggle:hover .form-section__chevron {
  border-color: hsl(var(--primary));
}

@media (max-width: 640px) {
  .form-section--density-compact {
    padding: 10px 10px 10px 14px;
  }

  .form-section--density-normal {
    padding: 12px 12px 12px 14px;
  }

  .form-section--density-roomy {
    padding: 14px 14px 14px 16px;
  }

  .form-section:not(.form-section--surface-plain)::before {
    width: 3px;
  }

  .form-section__header {
    gap: 8px;
    margin-bottom: 10px;
    padding-bottom: 8px;
    flex-wrap: wrap;
  }

  .form-section__title {
    font-size: 0.875rem;
    letter-spacing: 0;
  }

  .form-section__subtitle {
    margin-top: 4px;
    font-size: 0.75rem;
  }

  .form-section__actions {
    gap: 6px;
  }
}
</style>
