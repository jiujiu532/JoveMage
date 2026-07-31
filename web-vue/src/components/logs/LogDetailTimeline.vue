<template>
  <section v-if="hasTimeline" class="detail-timeline">
    <div class="detail-timeline__header">
      <div>
        <span class="detail-timeline__title">步骤耗时</span>
        <p>按执行顺序展示，条形长度表示相对耗时</p>
      </div>
      <div class="detail-timeline__meta">
        <MetaChip size="xs" tone="muted">{{ stepCount }} 步</MetaChip>
        <MetaChip v-if="segmentTotal" size="xs" tone="muted">
          分段合计 {{ formatTimelineMs(segmentTotal) }}
        </MetaChip>
        <MetaChip v-if="bottleneckStep" size="xs" tone="warning">
          瓶颈 {{ bottleneckStep.label }}
        </MetaChip>
      </div>
    </div>

    <div v-if="segments.length" class="detail-timeline-segments">
      <div class="detail-timeline-segments__track">
        <div
          v-for="segment in segments"
          :key="segment.key"
          class="detail-timeline-segments__segment"
          :class="[
            `detail-timeline-segments__segment--${segment.category}`,
            `detail-timeline-segments__segment--${segment.tone}`,
            { 'detail-timeline-segments__segment--compact': segment.compact },
          ]"
          :style="segment.barStyle"
          :title="segment.title"
        >
          <span>{{ segment.label }}</span>
          <strong>{{ segment.value }}</strong>
        </div>
      </div>
      <div v-if="legendItems.length" class="detail-timeline-segments__legend">
        <span
          v-for="item in legendItems"
          :key="`${item.key}-legend`"
          class="detail-timeline-segments__legend-item"
          :class="[`detail-timeline-segments__legend-item--${item.category}`, `detail-timeline-segments__legend-item--${item.tone}`]"
        >
          <i />
          {{ item.label }}
        </span>
      </div>
    </div>

    <div v-else class="detail-timeline__empty">
      这条日志没有步骤耗时埋点；新的图片请求会显示分段耗时。
    </div>

    <div v-if="groups.length" class="detail-timeline__details">
      <button type="button" class="detail-timeline__toggle" @click.stop="toggleDetails">
        <span>步骤明细</span>
        <strong>{{ detailsVisible ? '收起' : '展开' }}</strong>
      </button>
      <div v-show="detailsVisible" class="detail-timeline__groups">
        <div v-for="group in groups" :key="group.name" class="detail-timeline__group">
          <div class="detail-timeline__group-title">{{ group.name }}</div>
          <div class="detail-timeline__steps">
            <div
              v-for="step in group.steps"
              :key="step.key"
              class="detail-timeline__step"
              :class="[`detail-timeline__step--${step.category}`, `detail-timeline__step--${step.tone}`]"
            >
              <div class="detail-timeline__step-main">
                <div class="detail-timeline__step-head">
                  <div class="detail-timeline__step-label">
                    <span>{{ step.label }}</span>
                    <StateBadge :tone="step.tone" size="xs" shape="rounded">
                      {{ step.statusLabel }}
                    </StateBadge>
                  </div>
                  <span v-if="step.time" class="detail-timeline__step-time">{{ step.time }}</span>
                </div>
                <div class="detail-timeline__bar">
                  <span :style="step.barStyle" />
                </div>
                <p v-if="step.note" class="detail-timeline__step-note">{{ step.note }}</p>
              </div>
              <strong class="detail-timeline__step-value">{{ step.value }}</strong>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { toRef } from 'vue'
import MetaChip from '@/components/ai/MetaChip.vue'
import StateBadge from '@/components/ai/StateBadge.vue'
import type { SystemLogRow } from '@/api/logs'
import {
  formatTimelineMs,
  useLogTimeline,
} from '@/views/logs/useLogTimeline'

const props = defineProps<{
  log: SystemLogRow
}>()

const {
  segments,
  groups,
  legendItems,
  bottleneckStep,
  stepCount,
  segmentTotal,
  hasTimeline,
  detailsVisible,
  toggleDetails,
} = useLogTimeline(toRef(props, 'log'))
</script>

<style scoped>
.detail-timeline {
  display: flex;
  flex-direction: column;
  gap: 14px;
  border: 1px solid hsl(var(--border));
  border-radius: var(--radius);
  background: hsl(var(--card));
  padding: 14px;
}

.detail-timeline__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.detail-timeline__title {
  font-size: 13px;
  font-weight: 650;
  color: hsl(var(--foreground));
}

.detail-timeline__header p {
  margin-top: 3px;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

.detail-timeline__meta {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.detail-timeline-segments {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.detail-timeline-segments__track {
  display: flex;
  height: 28px;
  min-height: 28px;
  gap: 2px;
  overflow: hidden;
  border-radius: var(--radius);
  background: hsl(var(--muted) / 0.72);
  padding: 3px;
}

.detail-timeline-segments__segment {
  position: relative;
  display: flex;
  min-width: 6px;
  align-items: center;
  justify-content: center;
  gap: 6px;
  overflow: hidden;
  border-radius: var(--radius);
  background: hsl(var(--muted-foreground) / 0.45);
  color: rgb(255 255 255 / 0.96);
  padding: 0 8px;
  white-space: nowrap;
}

.detail-timeline-segments__segment + .detail-timeline-segments__segment {
  border-left: 0;
}

.detail-timeline-segments__segment span,
.detail-timeline-segments__segment strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.detail-timeline-segments__segment span {
  font-size: 12px;
  font-weight: 600;
}

.detail-timeline-segments__segment strong {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 12px;
  font-weight: 750;
}

.detail-timeline-segments__segment--muted,
.detail-timeline-segments__segment--info {
  background: color-mix(in srgb, var(--bauhaus-ink) 46%, transparent);
}

.detail-timeline-segments__segment--compact {
  padding: 0;
}

.detail-timeline-segments__segment--compact span,
.detail-timeline-segments__segment--compact strong {
  display: none;
}

/* 阶段色：成功蓝 / 失败红 / 限流黄；其余 info·ink 阶梯可辨 */
.detail-timeline-segments__segment--entry {
  background: color-mix(in srgb, hsl(var(--tone-info-strong)) 78%, transparent);
}

.detail-timeline-segments__segment--prepare {
  background: color-mix(in srgb, hsl(var(--tone-info-strong)) 68%, transparent);
}

.detail-timeline-segments__segment--network {
  background: color-mix(in srgb, var(--bauhaus-blue) 72%, transparent);
}

.detail-timeline-segments__segment--upstream {
  background: color-mix(in srgb, var(--bauhaus-ink) 58%, transparent);
}

.detail-timeline-segments__segment--resolve {
  background: color-mix(in srgb, var(--bauhaus-postit) 88%, var(--bauhaus-yellow));
  color: var(--bauhaus-ink);
}

.detail-timeline-segments__segment--download {
  /* 成功语义 → pen 蓝 */
  background: color-mix(in srgb, var(--bauhaus-blue) 82%, transparent);
}

.detail-timeline-segments__segment--retry {
  background: color-mix(in srgb, var(--bauhaus-yellow) 70%, var(--bauhaus-postit));
  color: var(--bauhaus-ink);
}

.detail-timeline-segments__segment--response {
  background: color-mix(in srgb, var(--bauhaus-ink) 42%, transparent);
}

.detail-timeline-segments__segment--warning {
  /* 限流 / 警告 → postit 黄 */
  background: color-mix(in srgb, var(--bauhaus-yellow) 86%, var(--bauhaus-postit));
  color: var(--bauhaus-ink);
}

.detail-timeline-segments__segment--danger {
  background: color-mix(in srgb, var(--bauhaus-red) 88%, transparent);
  color: rgb(255 255 255 / 0.96);
}

.detail-timeline-segments__legend {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
}

.detail-timeline-segments__legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: hsl(var(--muted-foreground));
}

.detail-timeline-segments__legend-item i {
  height: 8px;
  width: 8px;
  flex: 0 0 auto;
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--bauhaus-ink) 48%, transparent);
}

.detail-timeline-segments__legend-item--entry i {
  background: hsl(var(--tone-info-strong));
}

.detail-timeline-segments__legend-item--prepare i {
  background: color-mix(in srgb, hsl(var(--tone-info-strong)) 78%, var(--bauhaus-ink));
}

.detail-timeline-segments__legend-item--network i {
  background: var(--bauhaus-blue);
}

.detail-timeline-segments__legend-item--upstream i {
  background: color-mix(in srgb, var(--bauhaus-ink) 72%, var(--bauhaus-blue));
}

.detail-timeline-segments__legend-item--resolve i {
  background: var(--bauhaus-postit);
  box-shadow: inset 0 0 0 1px var(--bauhaus-line-soft);
}

.detail-timeline-segments__legend-item--download i {
  background: var(--bauhaus-blue);
}

.detail-timeline-segments__legend-item--retry i {
  background: var(--bauhaus-yellow);
  box-shadow: inset 0 0 0 1px var(--bauhaus-line-soft);
}

.detail-timeline-segments__legend-item--response i {
  background: color-mix(in srgb, var(--bauhaus-ink) 55%, transparent);
}

.detail-timeline-segments__legend-item--state i {
  background: color-mix(in srgb, var(--bauhaus-ink) 55%, transparent);
}

.detail-timeline-segments__legend-item--warning i {
  background: var(--bauhaus-yellow);
  box-shadow: inset 0 0 0 1px var(--bauhaus-line-soft);
}

.detail-timeline-segments__legend-item--danger i {
  background: var(--bauhaus-red);
}

.detail-timeline__empty {
  border: 1px dashed hsl(var(--border));
  border-radius: var(--radius);
  background: hsl(var(--muted) / 0.25);
  padding: 14px;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

.detail-timeline__groups {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.detail-timeline__details {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.detail-timeline__toggle {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  border: 1px solid hsl(var(--border));
  border-radius: var(--radius);
  background: hsl(var(--muted) / 0.22);
  padding: 8px 10px;
  text-align: left;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

.detail-timeline__toggle:hover {
  background: hsl(var(--muted) / 0.34);
  color: hsl(var(--foreground));
}

.detail-timeline__toggle span {
  font-weight: 600;
  color: hsl(var(--foreground));
}

.detail-timeline__toggle strong {
  font-weight: 600;
}

.detail-timeline__group {
  display: grid;
  grid-template-columns: 5.5rem minmax(0, 1fr);
  gap: 12px;
}

.detail-timeline__group-title {
  padding-top: 5px;
  font-size: 12px;
  font-weight: 600;
  color: hsl(var(--muted-foreground));
}

.detail-timeline__steps {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 9px;
}

.detail-timeline__step {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 4.5rem;
  align-items: start;
  gap: 12px;
}

.detail-timeline__step-main {
  min-width: 0;
}

.detail-timeline__step-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.detail-timeline__step-label {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: hsl(var(--foreground));
}

.detail-timeline__step-time {
  flex: 0 0 auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 11px;
  color: hsl(var(--muted-foreground));
}

.detail-timeline__bar {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: hsl(var(--muted) / 0.48);
  margin-top: 7px;
}

.detail-timeline__bar span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: hsl(var(--muted-foreground) / 0.5);
}

.detail-timeline__step--entry .detail-timeline__bar span {
  background: rgb(96 165 250 / 0.78);
}

.detail-timeline__step--prepare .detail-timeline__bar span {
  background: rgb(20 184 166 / 0.76);
}

.detail-timeline__step--network .detail-timeline__bar span {
  background: rgb(14 165 233 / 0.7);
}

.detail-timeline__step--upstream .detail-timeline__bar span {
  background: rgb(99 102 241 / 0.76);
}

.detail-timeline__step--resolve .detail-timeline__bar span {
  background: rgb(245 158 11 / 0.62);
}

.detail-timeline__step--download .detail-timeline__bar span {
  background: rgb(34 197 94 / 0.68);
}

.detail-timeline__step--retry .detail-timeline__bar span {
  background: rgb(249 115 22 / 0.72);
}

.detail-timeline__step--response .detail-timeline__bar span {
  background: hsl(var(--muted-foreground) / 0.5);
}

.detail-timeline__step--warning .detail-timeline__bar span {
  background: rgb(245 158 11 / 0.84);
}

.detail-timeline__step--danger .detail-timeline__bar span {
  background: rgb(244 63 94 / 0.82);
}

.detail-timeline__step-note {
  margin-top: 6px;
  overflow-wrap: anywhere;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

.detail-timeline__step-value {
  padding-top: 1.6rem;
  text-align: right;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 13px;
  font-weight: 650;
  color: hsl(var(--foreground));
}

@media (max-width: 640px) {
  .detail-timeline__header {
    flex-direction: column;
  }

  .detail-timeline__group {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .detail-timeline__step {
    grid-template-columns: 1fr;
  }

  .detail-timeline-segments__track {
    height: 22px;
    min-height: 22px;
  }

  .detail-timeline__step-value {
    padding-top: 0;
    text-align: left;
  }
}
</style>
