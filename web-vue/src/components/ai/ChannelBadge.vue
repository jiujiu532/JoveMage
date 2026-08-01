<template>
  <!-- 主体默认渠道无标（ChatGPT 即默认）；force 时仍可显示中性名 -->
  <span
    v-if="visible"
    class="channel-badge"
    :class="[
      `channel-badge--size-${size}`,
      shouldColor ? 'channel-badge--colored' : 'channel-badge--neutral',
      compact ? 'channel-badge--compact' : '',
    ]"
    :style="colorStyleVars"
    :title="titleText"
  >
    <span
      v-if="showDot && shouldColor"
      class="channel-badge__dot"
      aria-hidden="true"
    />
    <Icon
      v-if="showIcon && descriptor"
      :icon="descriptor.icon"
      class="channel-badge__icon"
      aria-hidden="true"
    />
    <span v-if="showName && displayName" class="channel-badge__name">{{ displayName }}</span>
  </span>
</template>

<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { computed } from 'vue'
import {
  getChannel,
  getChannelColorStyle,
  shouldBadgeChannel,
  type ChannelDescriptor,
} from '@/config/channels'

const props = withDefaults(defineProps<{
  /** 渠道 id，如 firefly / chatgpt */
  channel: string
  /** 显示名称（默认 true） */
  showName?: boolean
  /** 显示图标（默认 true） */
  showIcon?: boolean
  /** 显示色点（默认 true；仅旁路渠道） */
  showDot?: boolean
  size?: 'xs' | 'sm'
  /**
   * 主体默认渠道默认不渲染；设 true 时强制显示中性样式
   *（用于需要写明「ChatGPT」的场景，如 Tab 外的说明文案旁）
   */
  force?: boolean
  /** 更紧凑：仅色点+图标，无内边距 */
  compact?: boolean
  /** 覆盖展示名；默认取描述符 name，Firefly 可用短名 */
  label?: string
}>(), {
  showName: true,
  showIcon: true,
  showDot: true,
  size: 'sm',
  force: false,
  compact: false,
  label: '',
})

const descriptor = computed<ChannelDescriptor | undefined>(() => getChannel(props.channel))

const shouldColor = computed(() => shouldBadgeChannel(descriptor.value))

const visible = computed(() => {
  if (!descriptor.value) return false
  if (shouldColor.value) return true
  return props.force
})

const displayName = computed(() => {
  if (props.label) return props.label
  if (!descriptor.value) return ''
  // 列表/徽标用短名，避免 "Adobe Firefly" 过长
  if (descriptor.value.id === 'firefly') return 'Firefly'
  return descriptor.value.name
})

const titleText = computed(() => descriptor.value?.name || props.channel)

const colorStyleVars = computed(() => {
  if (!shouldColor.value || !descriptor.value) return undefined
  const style = getChannelColorStyle(descriptor.value)
  if (!style) return undefined
  return {
    '--channel-solid': style.solid,
    '--channel-soft-bg': style.softBg,
    '--channel-soft-fg': style.softFg,
    '--channel-border': style.border,
  } as Record<string, string>
})
</script>

<style scoped>
.channel-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  min-width: 0;
  max-width: 100%;
  border-radius: var(--radius);
  font-family: var(--font-display);
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  line-height: 1;
  white-space: nowrap;
  vertical-align: middle;
}

.channel-badge--size-xs {
  min-height: 1.25rem;
  padding: 0.1rem 0.4rem;
  font-size: 10px;
  gap: 0.22rem;
}

.channel-badge--size-sm {
  min-height: 1.5rem;
  padding: 0.2rem 0.5rem;
  font-size: 11px;
}

.channel-badge--compact {
  padding-left: 0;
  padding-right: 0;
  min-height: 0;
  background: transparent !important;
  border: none !important;
}

.channel-badge--neutral {
  border: 1px solid hsl(var(--border));
  background: hsl(var(--muted) / 0.45);
  color: hsl(var(--muted-foreground));
}

.channel-badge--colored {
  border: 1px solid var(--channel-border);
  background: var(--channel-soft-bg);
  color: var(--channel-soft-fg);
}

.channel-badge__dot {
  flex: 0 0 auto;
  width: 0.45rem;
  height: 0.45rem;
  border-radius: 999px;
  background: var(--channel-solid);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--channel-solid) 25%, transparent);
}

.channel-badge--size-xs .channel-badge__dot {
  width: 0.38rem;
  height: 0.38rem;
}

.channel-badge__icon {
  flex: 0 0 auto;
  width: 0.9rem;
  height: 0.9rem;
}

.channel-badge--size-xs .channel-badge__icon {
  width: 0.75rem;
  height: 0.75rem;
}

.channel-badge__name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

html[data-theme='dark'] .channel-badge--neutral {
  border-color: var(--bauhaus-line-soft, #3d3d3d);
  color: var(--bauhaus-grey, #a3a3a3);
}
</style>
