<template>
  <div class="panel-header" :class="`panel-header--align-${align}`">
    <div class="panel-header-copy">
      <p v-if="title" class="panel-header-title">{{ title }}</p>
      <slot name="copy" />
    </div>
    <div v-if="$slots.actions" class="panel-header-actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  title?: string
  align?: 'center' | 'start'
}>(), {
  title: '',
  align: 'center',
})
</script>

<style scoped>
.panel-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 4px;
  border-bottom: 2px solid hsl(var(--border));
  margin-bottom: 4px;
}

.panel-header--align-start {
  align-items: flex-start;
}

.panel-header-copy {
  min-width: 0;
  flex: var(--panel-header-copy-flex, 1 1 36rem);
}

.panel-header-title {
  font-family: var(--font-display);
  font-size: 1.05rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1.25;
  color: hsl(var(--foreground));
}

.panel-header-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: var(--panel-header-action-gap, 8px);
}

@media (max-width: 640px) {
  .panel-header-actions {
    width: 100%;
  }

  .panel-header-actions :slotted(*) {
    flex: 1 1 auto;
  }
}
</style>
