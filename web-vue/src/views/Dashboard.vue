<template>
  <div class="space-y-5">
    <PageLoadingState
      v-if="!dashboardDataReady"
      title="正在加载概览"
      description="读取最新账号、调用趋势和模型统计。"
    />

    <template v-else>
    <section class="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <StatCard
        v-for="stat in stats"
        :key="stat.label"
        :label="stat.label"
        :value="stat.value"
        :caption="stat.meta"
        :icon="stat.icon"
        :icon-bg="stat.iconBg"
        :icon-color="stat.iconColor"
      />
      <!-- 图片额度：ChatGPT 张数与 Firefly Credits 分两行，避免两种计量混读 -->
      <article class="dashboard-quota-card">
        <div class="dashboard-quota-card__head">
          <p class="dashboard-quota-card__label">图片额度</p>
          <span class="dashboard-quota-card__icon" aria-hidden="true">
            <Icon icon="lucide:coins" class="h-4 w-4" />
          </span>
        </div>
        <dl class="dashboard-quota-card__rows">
          <div class="dashboard-quota-card__row">
            <dt>ChatGPT</dt>
            <dd>
              <strong>{{ imageQuota.chatgptValue }}</strong>
              <span class="dashboard-quota-card__unit">张</span>
            </dd>
          </div>
          <div class="dashboard-quota-card__row">
            <dt>Firefly</dt>
            <dd>
              <strong>{{ imageQuota.fireflyValue }}</strong>
              <span class="dashboard-quota-card__unit">Credits</span>
            </dd>
          </div>
        </dl>
        <p v-if="imageQuota.note" class="dashboard-quota-card__note">{{ imageQuota.note }}</p>
      </article>
    </section>

    <!-- 渠道并列卡：启用渠道始终占位（含 0 账号空态）；未启用不出现；窄屏竖排 -->
    <section
      v-if="channelCards.length"
      class="channel-cards-grid grid grid-cols-1 gap-3 md:grid-cols-2"
      :class="channelCards.length >= 3 ? 'xl:grid-cols-3' : ''"
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
import { ChartCard, StatCard } from 'nanocat-ui'
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
.dashboard-quota-card {
  position: relative;
  min-width: 0;
  min-height: 100%;
  padding: 1rem;
  border: 2px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  background: hsl(var(--card));
  box-shadow: var(--shadow-card, 3px 3px 0 0 var(--bauhaus-ink));
  overflow: hidden;
}

html[data-theme='dark'] .dashboard-quota-card {
  border-color: hsl(var(--border));
  box-shadow: var(--shadow-card-soft, 0 4px 14px rgba(0, 0, 0, 0.45));
}

.dashboard-quota-card::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: 6px;
  background: var(--bauhaus-blue, #2d5da1);
}

.dashboard-quota-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
}

.dashboard-quota-card__label {
  margin: 0;
  color: var(--bauhaus-grey, #9e9e9e);
  font-family: var(--font-display);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.dashboard-quota-card__icon {
  display: inline-flex;
  width: 2.25rem;
  height: 2.25rem;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border-radius: 9999px;
  background: hsl(var(--tone-info-bg));
  color: var(--bauhaus-blue, #2d5da1);
}

.dashboard-quota-card__rows {
  display: grid;
  gap: 0.42rem;
  margin: 0.7rem 0 0;
}

.dashboard-quota-card__row {
  display: flex;
  min-width: 0;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
}

.dashboard-quota-card__row dt {
  margin: 0;
  color: hsl(var(--muted-foreground));
  font-size: 0.74rem;
  font-weight: 600;
  letter-spacing: 0.01em;
  white-space: nowrap;
}

.dashboard-quota-card__row dd {
  display: inline-flex;
  min-width: 0;
  align-items: baseline;
  justify-content: flex-end;
  gap: 0.28rem;
  margin: 0;
  color: hsl(var(--foreground));
  font-variant-numeric: tabular-nums;
}

.dashboard-quota-card__row strong {
  font-family: var(--font-display);
  font-size: 1.05rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1.1;
}

.dashboard-quota-card__unit {
  color: hsl(var(--muted-foreground));
  font-size: 0.68rem;
  font-weight: 500;
  white-space: nowrap;
}

.dashboard-quota-card__note {
  margin: 0.5rem 0 0;
  color: hsl(var(--muted-foreground));
  font-size: 0.68rem;
  line-height: 1.3;
}
</style>
