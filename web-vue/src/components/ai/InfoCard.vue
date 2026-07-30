<template>
  <component
    :is="tag"
    class="info-card"
    :class="[
      `info-card--tone-${tone}`,
      `info-card--density-${density}`,
    ]"
  >
    <div v-if="title || description || $slots.actions" class="info-card__header">
      <div class="min-w-0">
        <p v-if="title" class="info-card__title">{{ title }}</p>
        <p v-if="description" class="info-card__description">{{ description }}</p>
      </div>
      <div v-if="$slots.actions" class="info-card__actions">
        <slot name="actions" />
      </div>
    </div>
    <div v-if="$slots.default" class="info-card__body">
      <slot />
    </div>
  </component>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  tag?: 'article' | 'div' | 'section'
  title?: string
  description?: string
  tone?: 'card' | 'muted'
  density?: 'compact' | 'normal' | 'roomy'
}>(), {
  tag: 'section',
  title: '',
  description: '',
  tone: 'card',
  density: 'normal',
})
</script>

<style scoped>
.info-card {
  position: relative;
  border: 2px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  box-shadow: var(--shadow-card, 3px 3px 0 0 var(--bauhaus-ink));
  overflow: hidden;
  transition:
    transform 0.16s ease,
    border-color 0.16s ease,
    box-shadow 0.16s ease;
}

html[data-theme='dark'] .info-card {
  border-color: hsl(var(--border));
  box-shadow: var(--shadow-card-soft, 0 4px 14px rgba(0, 0, 0, 0.45));
}

@media (prefers-reduced-motion: reduce) {
  .info-card {
    transition: none;
  }
}

.info-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 5px;
  background: var(--bauhaus-blue, #2d5da1);
}

.info-card--tone-card {
  background: hsl(var(--card));
}

.info-card--tone-muted {
  background: hsl(var(--muted) / 0.45);
}

.info-card--density-compact {
  padding: 12px 12px 12px 16px;
}

.info-card--density-normal {
  padding: 16px 16px 16px 20px;
}

.info-card--density-roomy {
  padding: 20px 20px 20px 24px;
}

.info-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.info-card__title {
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.3;
  color: hsl(var(--foreground));
}

.info-card__description {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.55;
  color: var(--bauhaus-grey, #9e9e9e);
}

.info-card__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.info-card__header + .info-card__body {
  margin-top: 12px;
}

@media (max-width: 640px) {
  .info-card {
    border-width: 1.5px;
    box-shadow: 2px 2px 0 0 var(--bauhaus-ink, #2d2d2d);
  }

  html[data-theme='dark'] .info-card {
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
  }

  .info-card::before {
    width: 3px;
  }

  .info-card--density-compact {
    padding: 10px 10px 10px 14px;
  }

  .info-card--density-normal {
    padding: 12px 12px 12px 16px;
  }

  .info-card--density-roomy {
    padding: 14px 14px 14px 18px;
  }

  .info-card__header {
    gap: 8px;
  }

  .info-card__title {
    font-size: 13px;
    letter-spacing: -0.01em;
  }

  .info-card__description {
    margin-top: 4px;
    font-size: 11px;
  }

  .info-card__header + .info-card__body {
    margin-top: 10px;
  }
}
</style>
