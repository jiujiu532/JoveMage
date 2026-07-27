<template>
  <section class="metric-strip" :class="columnsClass">
    <article
      v-for="(item, index) in items"
      :key="item.key || item.label"
      class="metric-strip-card"
      :class="[
        density === 'compact' ? 'metric-strip-card--compact' : '',
        hasIcon(item) ? `metric-strip-card--icon-${iconPlacement}` : '',
        item.cardClass || '',
        `metric-strip-card--tone-${toneOf(index)}`,
      ]"
    >
      <div
        class="metric-strip-card-body"
        :class="hasIcon(item) && iconPlacement === 'right' ? 'metric-strip-card-body--right-icon' : ''"
      >
        <span
          v-if="hasIcon(item)"
          class="metric-strip-icon"
          :class="[item.iconBgClass || item.iconBg || '', item.iconClass || item.iconColor || '']"
        >
          <svg
            v-if="isSvgPathIcon(item)"
            aria-hidden="true"
            viewBox="0 0 24 24"
            class="metric-strip-svg"
            fill="currentColor"
          >
            <path :d="item.svgPath || item.icon" />
          </svg>
          <Icon
            v-else-if="item.icon"
            aria-hidden="true"
            :icon="item.icon"
            class="metric-strip-svg"
          />
        </span>

        <span class="metric-strip-text">
          <span class="metric-strip-label">{{ item.label }}</span>
          <strong
            class="metric-strip-value"
            :class="item.valueClass || item.class || ''"
            :style="item.valueStyle || undefined"
          >
            {{ item.value }}
          </strong>
          <span v-if="item.meta" class="metric-strip-meta">{{ item.meta }}</span>
        </span>
      </div>
    </article>
  </section>
</template>

<script setup lang="ts">
import { Icon } from '@iconify/vue'

type MetricStripItem = {
  key?: string
  label: string
  value: string | number
  meta?: string
  class?: string
  valueClass?: string
  valueStyle?: Record<string, string>
  cardClass?: string
  icon?: string
  iconType?: 'iconify' | 'svgPath'
  svgPath?: string
  iconClass?: string
  iconColor?: string
  iconBg?: string
  iconBgClass?: string
}

withDefaults(defineProps<{
  items: MetricStripItem[]
  columnsClass?: string
  density?: 'normal' | 'compact'
  iconPlacement?: 'left' | 'right'
}>(), {
  columnsClass: 'grid-cols-2 md:grid-cols-3 xl:grid-cols-4',
  density: 'normal',
  iconPlacement: 'left',
})

const TONES = ['blue', 'red', 'yellow', 'ink'] as const

function toneOf(index: number) {
  return TONES[index % TONES.length]
}

function hasIcon(item: MetricStripItem) {
  return Boolean(item.icon || item.svgPath)
}

function isSvgPathIcon(item: MetricStripItem) {
  if (item.iconType === 'svgPath' || item.svgPath) return true
  return Boolean(item.icon && !item.icon.includes(':'))
}
</script>

<style scoped>
.metric-strip {
  display: grid;
  gap: 12px;
}

.metric-strip-card {
  position: relative;
  min-width: 0;
  min-height: 88px;
  padding: 16px 16px 14px;
  border: 2px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  background: hsl(var(--card));
  box-shadow: none;
  overflow: hidden;
}

html[data-theme='dark'] .metric-strip-card {
  border-color: hsl(var(--border));
}

/* 顶边功能色条：轮换三原色 + 墨色 */
.metric-strip-card::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: 6px;
  background: var(--bauhaus-blue, #2d5da1);
}

.metric-strip-card--tone-red::before {
  background: var(--bauhaus-red, #ff4d4d);
}

.metric-strip-card--tone-yellow::before {
  background: var(--bauhaus-yellow, #fff9c4);
}

.metric-strip-card--tone-ink::before {
  background: var(--bauhaus-ink, #2d2d2d);
}

.metric-strip-card--compact {
  min-height: 68px;
  padding: 12px;
}

.metric-strip-card-body {
  display: flex;
  min-width: 0;
  height: 100%;
  align-items: center;
  gap: 12px;
}

.metric-strip-card-body--right-icon {
  display: block;
  height: auto;
  padding-right: 48px;
}

.metric-strip-icon {
  display: inline-flex;
  width: 36px;
  height: 36px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius);
  border: 1px solid hsl(var(--border));
  background: hsl(var(--secondary));
}

.metric-strip-card--compact .metric-strip-icon {
  width: 30px;
  height: 30px;
}

.metric-strip-card--icon-right .metric-strip-icon {
  position: absolute;
  top: 18px;
  right: 14px;
  width: 36px;
  height: 36px;
  border-radius: var(--radius);
}

.metric-strip-card--compact.metric-strip-card--icon-right .metric-strip-icon {
  top: 12px;
  right: 12px;
  width: 30px;
  height: 30px;
}

.metric-strip-card--compact .metric-strip-card-body--right-icon {
  padding-right: 40px;
}

.metric-strip-svg {
  width: 18px;
  height: 18px;
}

.metric-strip-card--compact .metric-strip-svg {
  width: 16px;
  height: 16px;
}

.metric-strip-text {
  display: block;
  min-width: 0;
  line-height: 1.15;
}

.metric-strip-label {
  display: block;
  overflow: hidden;
  color: var(--bauhaus-grey, #9e9e9e);
  font-family: var(--font-display);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.metric-strip-value {
  display: block;
  overflow: hidden;
  margin-top: 8px;
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.04em;
  color: hsl(var(--foreground));
  text-overflow: ellipsis;
  white-space: nowrap;
}

.metric-strip-card:not(.metric-strip-card--compact) .metric-strip-value {
  margin-top: 10px;
  font-size: 28px;
}

.metric-strip-meta {
  display: block;
  overflow: hidden;
  margin-top: 6px;
  color: var(--bauhaus-grey, #9e9e9e);
  font-size: 11px;
  letter-spacing: 0.02em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 640px) {
  .metric-strip-card {
    min-height: 72px;
  }

  .metric-strip-card:not(.metric-strip-card--compact) .metric-strip-value {
    font-size: 22px;
  }
}
</style>
