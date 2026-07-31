<template>
  <article
    class="mobile-list-card"
    :class="{
      'is-selected': selected,
      'mobile-list-card--compact': compact,
    }"
  >
    <div v-if="$slots.head" class="mobile-list-card__head">
      <slot name="head" />
    </div>
    <div v-if="$slots.meta" class="mobile-list-card__meta">
      <slot name="meta" />
    </div>
    <div v-if="$slots.body" class="mobile-list-card__body">
      <slot name="body" />
    </div>
    <slot />
    <div v-if="$slots.actions" class="mobile-list-card__actions">
      <slot name="actions" />
    </div>
  </article>
</template>

<script setup lang="ts">
/**
 * 移动端列表卡片壳：head / meta / body / actions + 默认插槽。
 * 纯结构与 Bauhaus 描边样式，业务内容由调用方填入。
 */
withDefaults(defineProps<{
  /** 选中态（蓝描边），用于多选列表 */
  selected?: boolean
  /** 更紧凑的间距与内边距 */
  compact?: boolean
}>(), {
  selected: false,
  compact: false,
})
</script>

<style scoped>
.mobile-list-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border: 2px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  background: hsl(var(--card));
  box-shadow: 2px 2px 0 0 var(--bauhaus-ink, #2d2d2d);
  padding: 10px 12px;
}

.mobile-list-card--compact {
  gap: 4px;
  padding: 8px 10px;
}

.mobile-list-card.is-selected {
  border-color: var(--bauhaus-blue, #2d5da1);
  box-shadow: 2px 2px 0 0 var(--bauhaus-blue, #2d5da1);
}

.mobile-list-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.mobile-list-card__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 8px;
}

.mobile-list-card__body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.mobile-list-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-top: 2px;
}

/* 默认插槽里的行样式（父组件 class 需写 mobile-list-card__line） */
.mobile-list-card :deep(.mobile-list-card__line) {
  margin: 0;
  font-size: 12px;
  line-height: 1.4;
  color: hsl(var(--foreground));
  overflow-wrap: anywhere;
}

html[data-theme='dark'] .mobile-list-card {
  border-color: hsl(var(--border));
  box-shadow: 2px 2px 0 0 hsl(var(--border));
}

html[data-theme='dark'] .mobile-list-card.is-selected {
  border-color: var(--bauhaus-blue, #2d5da1);
  box-shadow: 2px 2px 0 0 var(--bauhaus-blue, #2d5da1);
}
</style>
