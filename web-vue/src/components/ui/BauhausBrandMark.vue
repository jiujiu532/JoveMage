<template>
  <svg
    :class="rootClass"
    :width="pixel"
    :height="pixel"
    viewBox="0 0 40 40"
    role="img"
    :aria-label="ariaLabel"
  >
    <title>{{ ariaLabel }}</title>
    <!-- 奶油纸底 -->
    <rect x="0" y="0" width="40" height="40" fill="var(--bauhaus-paper, #FDFBF7)" />
    <!-- 秩序：外框正方形 -->
    <rect
      x="2.5"
      y="2.5"
      width="35"
      height="35"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
    />
    <!-- 蓝：圆珠笔笔触 -->
    <rect x="6" y="20" width="14" height="14" fill="var(--bauhaus-blue, #2D5DA1)" />
    <!-- 红：修正色三角 -->
    <path d="M8 7 L21 7 L14.5 18 Z" fill="var(--bauhaus-red, #FF4D4D)" />
    <!-- 黄：便签圆 -->
    <circle cx="28" cy="14" r="7" fill="var(--bauhaus-yellow, #FFF9C4)" stroke="currentColor" stroke-width="1.5" />
    <!-- 墨锚点 -->
    <rect x="26" y="26" width="8" height="8" fill="currentColor" />
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    size?: number
    ariaLabel?: string
    rootClass?: string
  }>(),
  {
    size: 36,
    ariaLabel: 'JoveMage',
    rootClass: '',
  },
)

const pixel = computed(() => props.size)
</script>
