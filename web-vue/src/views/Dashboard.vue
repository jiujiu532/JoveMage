<template>
  <div class="space-y-5">
    <PageLoadingState
      v-if="!dashboardDataReady"
      title="正在加载概览"
      description="读取最新账号、调用趋势和模型统计。"
    />

    <template v-else>
    <section class="dashboard-metric-grid">
      <article
        v-for="stat in stats"
        :key="stat.key"
        class="dashboard-metric-card"
        :class="`dashboard-metric-card--${stat.tone}`"
      >
        <div class="dashboard-metric-card__body">
          <div class="dashboard-metric-card__text">
            <p class="dashboard-metric-card__label">{{ stat.label }}</p>
            <strong class="dashboard-metric-card__value">{{ stat.value }}</strong>
            <p v-if="stat.meta" class="dashboard-metric-card__meta">{{ stat.meta }}</p>
          </div>
          <span class="dashboard-metric-card__icon" aria-hidden="true">
            <Icon :icon="stat.icon" class="dashboard-metric-card__glyph" />
          </span>
        </div>
      </article>

      <!-- 图片额度：ChatGPT 张数与 Firefly Credits 分两行，避免两种计量混读 -->
      <article class="dashboard-metric-card dashboard-metric-card--blue dashboard-metric-card--quota">
        <div class="dashboard-metric-card__body">
          <div class="dashboard-metric-card__text">
            <p class="dashboard-metric-card__label">图片额度</p>
            <dl class="dashboard-quota-rows">
              <div class="dashboard-quota-row">
                <dt>ChatGPT</dt>
                <dd>
                  <strong>{{ imageQuota.chatgptValue }}</strong>
                  <span>张</span>
                </dd>
              </div>
              <div class="dashboard-quota-row">
                <dt>Firefly</dt>
                <dd>
                  <strong>{{ imageQuota.fireflyValue }}</strong>
                  <span>Credits</span>
                </dd>
              </div>
            </dl>
            <p v-if="imageQuota.note" class="dashboard-metric-card__meta">{{ imageQuota.note }}</p>
          </div>
          <span class="dashboard-metric-card__icon" aria-hidden="true">
            <Icon icon="lucide:coins" class="dashboard-metric-card__glyph" />
          </span>
        </div>
      </article>
    </section>

    <!-- 渠道并列卡：注册表内渠道始终显示（0 账号走空态）；≥2 张时中屏起双列 -->
    <section
      v-if="channelCards.length"
      class="channel-cards-grid grid grid-cols-1 gap-3"
      :class="channelCards.length >= 2 ? 'md:grid-cols-2' : ''"
    >
      <ChannelCard
        v-for="channel in channelCards"
        :key="channel.id"
        :descriptor="channel"
      />
    </section>

    <section class="grid grid-cols-1 gap-4">
      <ChartCard title="模型请求分布">
        <template #actions>
          <TimeRangeTabs v-model="timeRangeHourlyRequests" aria-label="模型请求分布时间范围" />
        </template>
        <div ref="hourlyRequestsChartRef" class="h-72 w-full px-2"></div>
      </ChartCard>
    </section>

    <section class="grid grid-cols-1 gap-4">
      <ChartCard title="调用趋势">
        <template #actions>
          <TimeRangeTabs v-model="timeRangeTrend" aria-label="调用趋势时间范围" />
        </template>
        <div ref="trendChartRef" class="h-56 w-full"></div>
      </ChartCard>
    </section>

    <section class="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <ChartCard title="成功率趋势">
        <template #actions>
          <TimeRangeTabs v-model="timeRangeSuccessRate" aria-label="成功率趋势时间范围" />
        </template>
        <div ref="successRateChartRef" class="h-56 w-full"></div>
      </ChartCard>

      <ChartCard title="平均响应时间">
        <template #actions>
          <TimeRangeTabs v-model="timeRangeResponseTime" aria-label="平均响应时间范围" />
        </template>
        <div ref="responseTimeChartRef" class="h-56 w-full"></div>
      </ChartCard>
    </section>

    <section class="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <ChartCard title="模型调用占比">
        <template #actions>
          <TimeRangeTabs v-model="timeRangeModel" aria-label="模型调用占比时间范围" />
        </template>
        <div ref="modelChartRef" class="h-56 w-full"></div>
      </ChartCard>

      <ChartCard title="模型使用排行">
        <template #actions>
          <TimeRangeTabs v-model="timeRangeModelRank" aria-label="模型使用排行时间范围" />
        </template>
        <div ref="modelRankChartRef" class="h-56 w-full"></div>
      </ChartCard>
    </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { ChartCard } from 'nanocat-ui'
import ChannelCard from '@/components/ai/ChannelCard.vue'
import PageLoadingState from '@/components/ai/PageLoadingState.vue'
import TimeRangeTabs from '@/components/ai/TimeRangeTabs.vue'
import { useDashboardPage } from './dashboard/useDashboardPage'

defineOptions({ name: 'Dashboard' })

const {
  stats,
  imageQuota,
  channelCards,
  dashboardDataReady,
  timeRangeHourlyRequests,
  timeRangeTrend,
  timeRangeSuccessRate,
  timeRangeModel,
  timeRangeModelRank,
  timeRangeResponseTime,
  hourlyRequestsChartRef,
  trendChartRef,
  successRateChartRef,
  responseTimeChartRef,
  modelChartRef,
  modelRankChartRef,
} = useDashboardPage()
</script>

<style scoped>
.dashboard-metric-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem;
}

@media (min-width: 768px) {
  .dashboard-metric-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (min-width: 1280px) {
  .dashboard-metric-grid {
    grid-template-columns: repeat(6, minmax(0, 1fr));
  }
}

.dashboard-metric-card {
  position: relative;
  min-width: 0;
  min-height: 6.25rem;
  padding: 0.9rem 0.9rem 0.8rem;
  border: 2px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  background: hsl(var(--card));
  box-shadow: var(--shadow-card, 3px 3px 0 0 var(--bauhaus-ink));
  overflow: hidden;
}

html[data-theme='dark'] .dashboard-metric-card {
  border-color: hsl(var(--border));
  box-shadow: var(--shadow-card-soft, 0 4px 14px rgba(0, 0, 0, 0.45));
}

.dashboard-metric-card::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: 5px;
  background: var(--bauhaus-blue, #2d5da1);
}

.dashboard-metric-card--green::before {
  background: hsl(var(--tone-success-strong, 142 55% 38%));
}

.dashboard-metric-card--yellow::before {
  background: var(--bauhaus-yellow, #f5d76e);
}

.dashboard-metric-card--red::before {
  background: var(--bauhaus-red, #ff4d4d);
}

.dashboard-metric-card--ink::before {
  background: var(--bauhaus-ink, #2d2d2d);
}

.dashboard-metric-card__body {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.55rem;
}

.dashboard-metric-card__text {
  min-width: 0;
  flex: 1 1 auto;
}

.dashboard-metric-card__label {
  margin: 0;
  overflow: hidden;
  color: var(--bauhaus-grey, #9e9e9e);
  font-family: var(--font-display);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dashboard-metric-card__value {
  display: block;
  margin-top: 0.55rem;
  overflow: hidden;
  color: hsl(var(--foreground));
  font-family: var(--font-display);
  font-size: 1.65rem;
  font-weight: 700;
  letter-spacing: -0.04em;
  line-height: 1.05;
  font-variant-numeric: tabular-nums;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dashboard-metric-card__meta {
  margin: 0.4rem 0 0;
  overflow: hidden;
  color: hsl(var(--muted-foreground));
  font-size: 0.68rem;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dashboard-metric-card__icon {
  display: inline-flex;
  width: 2.25rem;
  height: 2.25rem;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border: 2px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  box-shadow: 2px 2px 0 0 var(--bauhaus-ink, #2d2d2d);
  background: hsl(var(--tone-info-bg));
  color: var(--bauhaus-blue, #2d5da1);
}

html[data-theme='dark'] .dashboard-metric-card__icon {
  border-color: var(--bauhaus-ink, #f2f2f2);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.45);
}

.dashboard-metric-card--green .dashboard-metric-card__icon {
  background: hsl(var(--tone-success-bg));
  color: hsl(var(--tone-success-strong));
}

.dashboard-metric-card--yellow .dashboard-metric-card__icon {
  background: var(--bauhaus-postit, #fff9c4);
  color: var(--bauhaus-ink, #2d2d2d);
}

.dashboard-metric-card--red .dashboard-metric-card__icon {
  background: hsl(var(--tone-error-bg));
  color: hsl(var(--tone-error-strong));
}

.dashboard-metric-card--ink .dashboard-metric-card__icon {
  background: var(--bauhaus-paper-2, #f5f0e6);
  color: var(--bauhaus-grey, #6b6b6b);
}

.dashboard-metric-card__glyph {
  width: 1rem;
  height: 1rem;
}

/* 额度卡：数值区换成双行对照，不占大号单数字 */
.dashboard-metric-card--quota {
  min-height: 6.25rem;
}

.dashboard-quota-rows {
  display: grid;
  gap: 0.32rem;
  margin: 0.55rem 0 0;
}

.dashboard-quota-row {
  display: flex;
  min-width: 0;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.4rem;
}

.dashboard-quota-row dt {
  margin: 0;
  color: hsl(var(--muted-foreground));
  font-size: 0.72rem;
  font-weight: 600;
  white-space: nowrap;
}

.dashboard-quota-row dd {
  display: inline-flex;
  min-width: 0;
  align-items: baseline;
  justify-content: flex-end;
  gap: 0.22rem;
  margin: 0;
  color: hsl(var(--foreground));
  font-variant-numeric: tabular-nums;
}

.dashboard-quota-row strong {
  font-family: var(--font-display);
  font-size: 1rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1.1;
}

.dashboard-quota-row span {
  color: hsl(var(--muted-foreground));
  font-size: 0.66rem;
  font-weight: 500;
  white-space: nowrap;
}

@media (max-width: 640px) {
  .dashboard-metric-card__value {
    font-size: 1.4rem;
  }
}
</style>
