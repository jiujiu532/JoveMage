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
  /* 与 style.css 页面主标题层级对齐；全局规则会再抬一级 */
  font-size: clamp(1.35rem, 1.2rem + 0.45vw, 1.625rem);
  font-weight: 700;
  letter-spacing: -0.045em;
  line-height: 1.15;
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
  .panel-header {
    gap: 8px;
    padding-bottom: 2px;
    margin-bottom: 2px;
    border-bottom-width: 1.5px;
  }

  .panel-header-title {
    font-size: clamp(1.15rem, 1.05rem + 0.6vw, 1.4rem);
    letter-spacing: -0.03em;
  }

  .panel-header-actions {
    width: 100%;
    gap: 6px;
  }

  .panel-header-actions :slotted(*) {
    flex: 1 1 auto;
  }
}
</style>
