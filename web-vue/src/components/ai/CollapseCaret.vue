<template>
  <span class="collapse-caret" :class="{ 'collapse-caret--open': open }" aria-hidden="true">
    <svg viewBox="0 0 12 12" :width="size" :height="size" fill="none">
      <path
        d="M2.5 4.5 6 8l3.5-3.5"
        stroke="currentColor"
        stroke-width="1.8"
        stroke-linecap="square"
      />
    </svg>
  </span>
</template>

<script setup lang="ts">
/**
 * 全局折叠指示箭头（Bauhaus 方形描边）
 * 统一样式：方形硬边 + 内部 V 形，展开时翻转 180° 并填充主题蓝。
 * 用法：<CollapseCaret :open="!collapsed" />
 */
withDefaults(defineProps<{
  open?: boolean
  size?: number
}>(), {
  open: false,
  size: 12,
})
</script>

<style scoped>
.collapse-caret {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  flex: 0 0 auto;
  border: 1.5px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  color: var(--bauhaus-ink, #2d2d2d);
  transition: transform 0.18s ease, background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}
.collapse-caret--open {
  transform: rotate(180deg);
  background: var(--bauhaus-blue, #2d5da1);
  border-color: var(--bauhaus-blue, #2d5da1);
  color: var(--bauhaus-card, #fff);
}
</style>
