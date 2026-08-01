<template>
  <span
    v-if="visible"
    class="channel-dot"
    :class="`channel-dot--size-${size}`"
    :style="colorStyleVars"
    :title="titleText"
    role="img"
    :aria-label="titleText"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  getChannel,
  getChannelColorStyle,
  shouldBadgeChannel,
} from '@/config/channels'

/**
 * 纯圆点最小变体：表格行内 / 画廊卡角标。
 * 主体默认渠道不渲染（ChatGPT 无标）。
 */
const props = withDefaults(defineProps<{
  channel: string
  size?: 'xs' | 'sm'
}>(), {
  size: 'sm',
})

const descriptor = computed(() => getChannel(props.channel))
const visible = computed(() => shouldBadgeChannel(descriptor.value))
const titleText = computed(() => descriptor.value?.name || props.channel)

const colorStyleVars = computed(() => {
  if (!descriptor.value) return undefined
  const style = getChannelColorStyle(descriptor.value)
  if (!style) return undefined
  return {
    '--channel-solid': style.solid,
  } as Record<string, string>
})
</script>

<style scoped>
.channel-dot {
  display: inline-block;
  flex: 0 0 auto;
  border-radius: 999px;
  background: var(--channel-solid, var(--bauhaus-red, #ff4d4d));
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--channel-solid, var(--bauhaus-red, #ff4d4d)) 30%, transparent);
  vertical-align: middle;
}

.channel-dot--size-xs {
  width: 0.4rem;
  height: 0.4rem;
}

.channel-dot--size-sm {
  width: 0.5rem;
  height: 0.5rem;
}
</style>
