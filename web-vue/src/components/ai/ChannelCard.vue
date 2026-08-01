<template>
  <article
    class="channel-card"
    :class="shouldColor ? 'channel-card--colored' : 'channel-card--neutral'"
    :style="colorStyleVars"
  >
    <header class="channel-card__header">
      <div class="channel-card__identity">
        <span
          v-if="shouldColor"
          class="channel-card__dot"
          aria-hidden="true"
        />
        <Icon
          v-if="descriptor.icon"
          :icon="descriptor.icon"
          class="channel-card__icon"
          aria-hidden="true"
        />
        <div class="min-w-0">
          <p class="channel-card__title">{{ titleText }}</p>
          <p class="channel-card__subtitle">{{ subtitleText }}</p>
        </div>
      </div>
      <ChannelBadge
        v-if="shouldColor"
        :channel="descriptor.id"
        size="xs"
        :show-dot="false"
      />
    </header>

    <div class="channel-card__stats">
      <p class="channel-card__primary">
        <span class="channel-card__primary-num">{{ accountCount }}</span>
        <span class="channel-card__primary-unit">号</span>
        <span class="channel-card__primary-sep" aria-hidden="true">·</span>
        <span class="channel-card__primary-num">{{ healthyCount }}</span>
        <span class="channel-card__primary-unit">正常</span>
      </p>
      <p v-if="secondaryLine" class="channel-card__secondary">
        {{ secondaryLine }}
      </p>
      <p v-else-if="meterIsCredits" class="channel-card__secondary">
        credits 剩 {{ creditsTotal }}
      </p>
    </div>
  </article>
</template>

<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { computed } from 'vue'
import ChannelBadge from './ChannelBadge.vue'
import {
  channelShortName,
  getChannelColorStyle,
  shouldBadgeChannel,
  type ChannelDescriptor,
} from '@/config/channels'

const props = withDefaults(defineProps<{
  descriptor: ChannelDescriptor
  /** 覆盖副标题；默认「账号池」 */
  subtitle?: string
  /** 额外次行文案（如「5 异常 · 2 待刷新」）；不传则 credits 渠道自动显示汇总 */
  secondary?: string
}>(), {
  subtitle: '',
  secondary: '',
})

const shouldColor = computed(() => shouldBadgeChannel(props.descriptor))
const titleText = computed(() => {
  const short = channelShortName(props.descriptor)
  return props.descriptor.is_default ? `${short} 池` : `${short} 池`
})
const subtitleText = computed(() => props.subtitle || '并行上游 · 号池摘要')
const accountCount = computed(() => Number(props.descriptor.account_count ?? 0))
const healthyCount = computed(() => Number(props.descriptor.healthy_count ?? 0))
const creditsTotal = computed(() => Number(props.descriptor.credits_total ?? 0))
const meterIsCredits = computed(() => props.descriptor.meter_kind === 'credits')
const secondaryLine = computed(() => String(props.secondary || '').trim())

const colorStyleVars = computed(() => {
  if (!shouldColor.value) return undefined
  const style = getChannelColorStyle(props.descriptor)
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
.channel-card {
  position: relative;
  border: 2px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  background: hsl(var(--card));
  box-shadow: var(--shadow-card, 3px 3px 0 0 var(--bauhaus-ink));
  padding: 0.9rem 1rem 0.95rem;
  overflow: hidden;
  min-height: 7.25rem;
}

html[data-theme='dark'] .channel-card {
  border-color: hsl(var(--border));
  box-shadow: var(--shadow-card-soft, 0 4px 14px rgba(0, 0, 0, 0.45));
}

.channel-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 5px;
  background: var(--bauhaus-blue, #2d5da1);
}

.channel-card--colored::before {
  background: var(--channel-solid, var(--bauhaus-red, #ff4d4d));
}

.channel-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.85rem;
}

.channel-card__identity {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  min-width: 0;
}

.channel-card__dot {
  flex: 0 0 auto;
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 999px;
  background: var(--channel-solid, var(--bauhaus-red, #ff4d4d));
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--channel-solid, var(--bauhaus-red, #ff4d4d)) 25%, transparent);
}

.channel-card__icon {
  flex: 0 0 auto;
  width: 1.1rem;
  height: 1.1rem;
  color: var(--channel-soft-fg, hsl(var(--muted-foreground)));
}

.channel-card--neutral .channel-card__icon {
  color: var(--bauhaus-blue, #2d5da1);
}

.channel-card__title {
  font-family: var(--font-display);
  font-size: 0.95rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: hsl(var(--foreground));
  line-height: 1.2;
}

.channel-card__subtitle {
  margin-top: 0.15rem;
  font-size: 11px;
  color: hsl(var(--muted-foreground));
  line-height: 1.3;
}

.channel-card__stats {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.channel-card__primary {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.25rem 0.35rem;
  font-family: var(--font-display);
  color: hsl(var(--foreground));
}

.channel-card__primary-num {
  font-size: 1.35rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.channel-card__primary-unit {
  font-size: 0.78rem;
  font-weight: 600;
  color: hsl(var(--muted-foreground));
  letter-spacing: 0.04em;
}

.channel-card__primary-sep {
  margin: 0 0.15rem;
  color: hsl(var(--muted-foreground));
  font-weight: 700;
}

.channel-card__secondary {
  font-size: 12px;
  color: hsl(var(--muted-foreground));
  line-height: 1.35;
}

.channel-card--colored .channel-card__secondary {
  color: color-mix(in srgb, var(--channel-soft-fg, hsl(var(--muted-foreground))) 78%, hsl(var(--muted-foreground)));
}

/* 窄屏：内部信息竖向堆叠，避免横排挤扁 */
@media (max-width: 639px) {
  .channel-card {
    min-height: 0;
    padding: 0.85rem 0.85rem 0.9rem;
  }

  .channel-card__header {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.55rem;
    margin-bottom: 0.7rem;
  }

  .channel-card__stats {
    gap: 0.3rem;
  }

  .channel-card__primary-num {
    font-size: 1.2rem;
  }
}
</style>
