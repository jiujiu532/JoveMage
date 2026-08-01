<template>
  <article
    class="channel-card"
    :class="[
      shouldColor ? 'channel-card--colored' : 'channel-card--neutral',
      isEmpty ? 'channel-card--empty' : '',
    ]"
    :style="colorStyleVars"
  >
    <header class="channel-card__header">
      <div class="channel-card__identity">
        <span
          v-if="shouldColor"
          class="channel-card__dot"
          aria-hidden="true"
        />
        <span class="channel-card__icon-box" aria-hidden="true">
          <Icon
            v-if="descriptor.icon"
            :icon="descriptor.icon"
            class="channel-card__icon"
          />
        </span>
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

    <!-- 空态：保留卡片占位，引导去账号管理 -->
    <div v-if="isEmpty" class="channel-card__empty">
      <p class="channel-card__empty-title">暂无账号</p>
      <p class="channel-card__empty-desc">
        此渠道尚未接入号池，添加后才会参与调度与统计。
      </p>
      <RouterLink class="channel-card__empty-link" to="/accounts">
        去账号管理添加
      </RouterLink>
    </div>

    <template v-else>
      <div class="channel-card__metrics">
        <div class="channel-card__metric">
          <span class="channel-card__metric-label">账号</span>
          <strong class="channel-card__metric-value">{{ accountCount }}</strong>
        </div>
        <div class="channel-card__metric">
          <span class="channel-card__metric-label">正常</span>
          <strong class="channel-card__metric-value">{{ healthyCount }}</strong>
        </div>
        <div class="channel-card__metric">
          <span class="channel-card__metric-label">{{ meterIsCredits ? 'Credits' : '健康度' }}</span>
          <strong class="channel-card__metric-value">
            {{ meterIsCredits ? creditsTotal : `${healthPercent}%` }}
          </strong>
        </div>
      </div>

      <div class="channel-card__meters">
        <div class="channel-card__meter">
          <div class="channel-card__meter-head">
            <span>健康度</span>
            <span class="channel-card__meter-num">{{ healthyCount }}/{{ accountCount }}</span>
          </div>
          <div
            class="channel-card__bar"
            role="progressbar"
            :aria-label="`${titleText} 健康度`"
            :aria-valuenow="healthPercent"
            aria-valuemin="0"
            aria-valuemax="100"
          >
            <div class="channel-card__bar-fill channel-card__bar-fill--health" :style="{ width: `${healthPercent}%` }" />
          </div>
        </div>

        <div v-if="meterIsCredits" class="channel-card__meter">
          <div class="channel-card__meter-head">
            <span>Credits 剩余</span>
            <span class="channel-card__meter-num">{{ creditsTotal }}</span>
          </div>
          <div
            class="channel-card__bar"
            role="progressbar"
            :aria-label="`${titleText} credits 剩余`"
            :aria-valuenow="creditsBarPercent"
            aria-valuemin="0"
            aria-valuemax="100"
          >
            <div class="channel-card__bar-fill channel-card__bar-fill--credits" :style="{ width: `${creditsBarPercent}%` }" />
          </div>
        </div>

        <div v-else class="channel-card__meter">
          <div class="channel-card__meter-head">
            <span>号池占用</span>
            <span class="channel-card__meter-num">{{ accountCount }} 号</span>
          </div>
          <div
            class="channel-card__bar"
            role="progressbar"
            :aria-label="`${titleText} 号池规模`"
            :aria-valuenow="poolBarPercent"
            aria-valuemin="0"
            aria-valuemax="100"
          >
            <div class="channel-card__bar-fill channel-card__bar-fill--pool" :style="{ width: `${poolBarPercent}%` }" />
          </div>
        </div>
      </div>

      <p v-if="secondaryLine" class="channel-card__secondary">
        {{ secondaryLine }}
      </p>
    </template>
  </article>
</template>

<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import ChannelBadge from './ChannelBadge.vue'
import {
  channelShortName,
  getChannelColorStyle,
  shouldBadgeChannel,
  type ChannelDescriptor,
} from '@/config/channels'

const props = withDefaults(defineProps<{
  descriptor: ChannelDescriptor
  /** 覆盖副标题；默认「并行上游 · 号池摘要」 */
  subtitle?: string
  /** 额外次行文案（如「5 异常 · 2 待刷新」） */
  secondary?: string
}>(), {
  subtitle: '',
  secondary: '',
})

const shouldColor = computed(() => shouldBadgeChannel(props.descriptor))
const titleText = computed(() => {
  const short = channelShortName(props.descriptor)
  return `${short} 池`
})
const subtitleText = computed(() => props.subtitle || '并行上游 · 号池摘要')
const accountCount = computed(() => Math.max(0, Number(props.descriptor.account_count ?? 0) || 0))
const healthyCount = computed(() => Math.max(0, Number(props.descriptor.healthy_count ?? 0) || 0))
const creditsTotal = computed(() => Math.max(0, Number(props.descriptor.credits_total ?? 0) || 0))
const meterIsCredits = computed(() => props.descriptor.meter_kind === 'credits')
const secondaryLine = computed(() => String(props.secondary || '').trim())
const isEmpty = computed(() => accountCount.value <= 0)

const healthPercent = computed(() => {
  if (accountCount.value <= 0) return 0
  return Math.min(100, Math.round((healthyCount.value / accountCount.value) * 100))
})

/** credits 无总额上限时用对数压缩条，仅作视觉饱满度，不代表真实占比 */
const creditsBarPercent = computed(() => {
  const total = creditsTotal.value
  if (total <= 0) return 0
  // 0 → 0%，1 → ~18%，10 → ~40%，100 → ~62%，1000 → ~78%，10000+ → 92%
  const ratio = Math.log10(total + 1) / Math.log10(10001)
  return Math.max(8, Math.min(92, Math.round(ratio * 100)))
})

/** 非 credits 渠道第二根条：号池规模示意（相对 1/10/50/200） */
const poolBarPercent = computed(() => {
  const n = accountCount.value
  if (n <= 0) return 0
  if (n >= 200) return 100
  if (n >= 50) return 70 + Math.round(((n - 50) / 150) * 25)
  if (n >= 10) return 40 + Math.round(((n - 10) / 40) * 30)
  return Math.max(12, Math.round((n / 10) * 40))
})

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
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  width: 100%;
  min-height: 11.5rem;
  border: 2px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  background: hsl(var(--card));
  box-shadow: var(--shadow-card, 3px 3px 0 0 var(--bauhaus-ink));
  padding: 0.95rem 1rem 1rem;
  overflow: hidden;
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
}

.channel-card__identity {
  display: flex;
  align-items: center;
  gap: 0.6rem;
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

.channel-card__icon-box {
  display: inline-flex;
  flex: 0 0 auto;
  width: 2.25rem;
  height: 2.25rem;
  align-items: center;
  justify-content: center;
  border: 2px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  background: hsl(var(--tone-info-bg));
  color: var(--bauhaus-blue, #2d5da1);
  box-shadow: 2px 2px 0 0 var(--bauhaus-ink);
}

.channel-card--colored .channel-card__icon-box {
  background: var(--channel-soft-bg);
  color: var(--channel-soft-fg);
  border-color: var(--channel-border, var(--bauhaus-ink));
  box-shadow: none;
}

html[data-theme='dark'] .channel-card__icon-box {
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.45);
  border-color: hsl(var(--border));
}

.channel-card__icon {
  width: 1.05rem;
  height: 1.05rem;
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

.channel-card__metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.5rem;
  width: 100%;
}

.channel-card__metric {
  min-width: 0;
  padding: 0.55rem 0.6rem 0.5rem;
  border: 1px solid hsl(var(--border));
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--bauhaus-paper-2, #f5f0e6) 72%, transparent);
}

html[data-theme='dark'] .channel-card__metric {
  background: hsl(var(--muted) / 0.35);
}

.channel-card__metric-label {
  display: block;
  font-family: var(--font-display);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--bauhaus-grey, #9e9e9e);
  line-height: 1.2;
}

.channel-card__metric-value {
  display: block;
  margin-top: 0.35rem;
  font-family: var(--font-display);
  font-size: 1.2rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1;
  color: hsl(var(--foreground));
  font-variant-numeric: tabular-nums;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.channel-card__meters {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.55rem;
  width: 100%;
}

@media (min-width: 480px) {
  .channel-card__meters {
    grid-template-columns: 1fr 1fr;
  }
}

.channel-card__meter {
  min-width: 0;
}

.channel-card__meter-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.3rem;
  font-size: 11px;
  font-weight: 600;
  color: hsl(var(--muted-foreground));
}

.channel-card__meter-num {
  font-variant-numeric: tabular-nums;
  color: hsl(var(--foreground));
}

.channel-card__bar {
  height: 0.5rem;
  overflow: hidden;
  border: 1px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  background: hsl(var(--muted));
}

html[data-theme='dark'] .channel-card__bar {
  border-color: hsl(var(--border));
}

.channel-card__bar-fill {
  height: 100%;
  transition: width 180ms ease;
}

.channel-card__bar-fill--health {
  background: hsl(var(--tone-success-strong, 152 60% 36%));
}

.channel-card__bar-fill--credits {
  background: var(--channel-solid, var(--bauhaus-red, #ff4d4d));
}

.channel-card__bar-fill--pool {
  background: var(--bauhaus-blue, #2d5da1);
}

.channel-card__secondary {
  font-size: 12px;
  color: hsl(var(--muted-foreground));
  line-height: 1.35;
}

.channel-card--colored .channel-card__secondary {
  color: color-mix(in srgb, var(--channel-soft-fg, hsl(var(--muted-foreground))) 78%, hsl(var(--muted-foreground)));
}

.channel-card__empty {
  display: flex;
  flex: 1;
  flex-direction: column;
  justify-content: center;
  gap: 0.35rem;
  min-height: 5.5rem;
  padding: 0.85rem 0.9rem;
  border: 1px dashed hsl(var(--border));
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--bauhaus-paper-2, #f5f0e6) 65%, transparent);
}

html[data-theme='dark'] .channel-card__empty {
  background: hsl(var(--muted) / 0.28);
}

.channel-card__empty-title {
  font-family: var(--font-display);
  font-size: 0.95rem;
  font-weight: 700;
  color: hsl(var(--foreground));
}

.channel-card__empty-desc {
  font-size: 12px;
  line-height: 1.45;
  color: hsl(var(--muted-foreground));
}

.channel-card__empty-link {
  margin-top: 0.35rem;
  align-self: flex-start;
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--bauhaus-blue, #2d5da1);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.channel-card--colored .channel-card__empty-link {
  color: var(--channel-soft-fg, var(--bauhaus-blue, #2d5da1));
}

.channel-card__empty-link:hover {
  opacity: 0.85;
}

@media (max-width: 639px) {
  .channel-card {
    min-height: 0;
    padding: 0.85rem;
    gap: 0.7rem;
  }

  .channel-card__header {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.55rem;
  }

  .channel-card__metrics {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.4rem;
  }

  .channel-card__metric {
    padding: 0.45rem 0.45rem 0.4rem;
  }

  .channel-card__metric-value {
    font-size: 1.05rem;
  }
}
</style>
