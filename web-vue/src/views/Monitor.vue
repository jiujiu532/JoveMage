<template>
  <div class="space-y-6">
    <PagePanel class="space-y-5">
      <PanelHeader title="实时监控" align="start">
        <template #copy>
          <p class="mt-1 text-xs text-muted-foreground">
            容器内存实时窗口，不做历史时间范围；用于观察等待入口、等待账号、等待出口、上游生成、上游断流和本地拒绝/繁忙。
          </p>
          <p class="mt-1 text-xs text-muted-foreground">
            入口排队高时可适当调大环境变量 CHATGPT2API_THREAD_TOKENS 提高本地并发；最近更新：{{ monitorData?.updated_at || '未获取' }}
          </p>
        </template>
        <template #actions>
          <StateBadge :tone="autoRefresh ? 'success' : 'muted'" shape="rounded">
            {{ autoRefresh ? '自动刷新' : '已暂停' }}
          </StateBadge>
          <label class="flex items-center gap-2 text-xs text-muted-foreground">
            <span class="whitespace-nowrap">间隔</span>
            <Input
              :model-value="String(refreshIntervalSeconds)"
              type="number"
              min="1"
              max="300"
              step="1"
              root-class="w-16"
              @update:model-value="setRefreshIntervalInput"
              @blur="applyRefreshInterval()"
              @change="applyRefreshInterval()"
              @keyup.enter="applyRefreshInterval()"
            />
            <span class="whitespace-nowrap">秒</span>
          </label>
          <Button size="sm" variant="outline" :disabled="isLoading" @click="loadMonitor(false)">
            {{ isLoading ? '刷新中...' : '立即刷新' }}
          </Button>
          <Button size="sm" variant="outline" @click="toggleAutoRefresh">
            {{ autoRefresh ? '暂停刷新' : '继续刷新' }}
          </Button>
        </template>
      </PanelHeader>

      <div class="grid gap-3 xl:grid-cols-2">
        <section
          v-for="group in diagnosticGroups"
          :key="group.key"
          class="monitor-metric-group"
        >
          <header class="monitor-metric-group__head">
            <h3 class="monitor-metric-group__title">{{ group.title }}</h3>
            <p class="monitor-metric-group__meta">{{ group.meta }}</p>
          </header>
          <div class="monitor-metric-group__grid">
            <div
              v-for="item in group.items"
              :key="`${group.key}-${item.key}`"
              class="monitor-metric-cell"
              :class="[
                item.primary ? 'monitor-metric-cell--primary' : 'monitor-metric-cell--quiet',
                `monitor-metric-cell--tone-${item.tone || 'ink'}`,
              ]"
            >
              <p class="monitor-metric-cell__label">{{ item.label }}</p>
              <p
                class="monitor-metric-cell__value"
                :class="item.value === '-' ? 'monitor-metric-cell__value--empty' : item.valueClass"
              >
                {{ item.value }}
              </p>
              <p v-if="item.meta" class="monitor-metric-cell__meta">{{ item.meta }}</p>
            </div>
          </div>
        </section>
      </div>

      <StateBlock
        v-if="loadError"
        compact
        dashed
        title="实时监控加载失败"
        :description="loadError"
      />
    </PagePanel>

    <PagePanel flush>
      <div class="p-4">
        <PanelHeader title="活跃请求" align="start">
          <template #copy>
            <p class="mt-1 text-xs text-muted-foreground">
              正在运行的图片请求，按进入时间排序。
            </p>
          </template>
          <template #actions>
            <MetaChip size="xs" tone="info">当前并发 {{ activeRows.length }} / {{ threadTokens }}</MetaChip>
            <MetaChip size="xs" tone="muted">入口排队 {{ entryQueueText }}</MetaChip>
          </template>
        </PanelHeader>
      </div>
      <div v-if="activeStageItems.length" class="flex flex-wrap gap-2 px-4 pb-3">
        <MetaChip
          v-for="item in activeStageItems"
          :key="item.label"
          size="xs"
          tone="muted"
        >
          {{ item.label }} {{ item.count }}
        </MetaChip>
      </div>
      <TableShell v-if="activeRows.length">
        <table class="monitor-table">
          <thead>
            <tr>
              <th>请求</th>
              <th>模型</th>
              <th>阶段</th>
              <th class="table-num">已耗时</th>
              <th class="table-num">关键耗时</th>
              <th>出口</th>
              <th>账号</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in activeRows" :key="row.call_id">
              <td>
                <p class="font-mono text-xs text-foreground">{{ shortCallId(row.call_id) }}</p>
                <p class="mt-1 text-[11px] text-muted-foreground">{{ row.endpoint || '-' }}</p>
              </td>
              <td>
                <MetaChip size="xs" tone="muted">{{ row.model || '-' }}</MetaChip>
              </td>
              <td>
                <StateBadge tone="info" shape="rounded" :bordered="false">
                  {{ row.stage_label || row.stage || '运行中' }}
                </StateBadge>
              </td>
              <td class="table-num">
                <span class="monitor-running-value">
                  <span class="monitor-running-dot" aria-hidden="true" />
                  {{ formatMs(row.elapsed_ms) }}
                </span>
              </td>
              <td class="table-num max-w-[22rem] truncate" :title="metricDigest(row)">{{ metricDigest(row) }}</td>
              <td>
                <MetaChip size="xs" tone="muted">{{ egressText(row) }}</MetaChip>
              </td>
              <td class="max-w-[12rem] truncate">{{ row.account_email || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </TableShell>
      <div v-else class="px-4 pb-4">
        <StateBlock compact dashed title="暂无活跃请求" description="开始压测或发起图片请求后，这里会实时出现运行中的调用。" />
      </div>
    </PagePanel>

    <div class="grid items-stretch gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(22rem,0.72fr)]">
      <PagePanel flush class="monitor-paired-panel">
        <div class="monitor-paired-header">
          <div class="monitor-paired-header__copy">
            <p class="ui-section-title">最近完成</p>
            <p class="monitor-paired-header__desc">
              最近完成的图片相关调用，窗口保存在进程内存中。
            </p>
          </div>
          <div class="monitor-paired-header__meta">
            <MetaChip size="xs" tone="muted">{{ completedWindowText }}</MetaChip>
          </div>
        </div>
        <div v-if="recentRows.length" class="monitor-paired-body">
          <TableShell class="monitor-paired-table">
            <table class="monitor-table">
              <thead>
                <tr>
                  <th>请求</th>
                  <th>状态</th>
                  <th>模型</th>
                  <th class="table-num">总耗时</th>
                  <th class="table-num">入口等待</th>
                  <th>账号 / 出口</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in recentRows" :key="`recent-${row.call_id}-${row.ended_at}`">
                  <td>
                    <p class="font-mono text-xs text-foreground">{{ shortCallId(row.call_id) }}</p>
                    <p class="mt-1 text-[11px] text-muted-foreground">{{ row.ended_at || row.updated_at || '-' }}</p>
                  </td>
                  <td>
                    <StateBadge :tone="statusTone(row.status)" shape="rounded" :bordered="false">
                      {{ statusLabel(row.status) }}
                    </StateBadge>
                  </td>
                  <td class="max-w-[12rem] truncate">{{ row.model || '-' }}</td>
                  <td class="table-num">{{ formatMs(row.duration_ms) }}</td>
                  <td class="table-num">{{ formatMs(metricValue(row, 'handler_queue_ms')) }}</td>
                  <td>{{ accountEgressDigest(row) }}</td>
                </tr>
              </tbody>
            </table>
          </TableShell>
        </div>
        <div v-else class="monitor-paired-body px-4 pb-4">
          <StateBlock compact dashed title="暂无完成记录" description="当前容器启动后还没有图片相关请求完成。" />
        </div>
      </PagePanel>

      <PagePanel flush class="monitor-paired-panel">
        <div class="monitor-paired-header">
          <div class="monitor-paired-header__copy">
            <p class="ui-section-title">慢请求</p>
            <p class="monitor-paired-header__desc">
              按等待入口、等待账号、等待出口、上游生成和上游断流综合排序。
            </p>
          </div>
          <div class="monitor-paired-header__meta">
            <MetaChip size="xs" tone="muted">慢 {{ slowRows.length }}</MetaChip>
          </div>
        </div>
        <div v-if="slowRows.length" class="monitor-paired-body space-y-2 px-4 pb-4">
          <div
            v-for="row in slowRows"
            :key="`slow-${row.call_id}-${row.ended_at}`"
            class="monitor-slow-card"
          >
            <span class="monitor-slow-card__stripe" :class="`monitor-slow-card__stripe--${statusTone(row.status)}`" aria-hidden="true" />
            <div class="monitor-slow-card__body">
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <p class="truncate text-sm font-medium text-foreground">
                    {{ row.model || '-' }}
                    <span class="font-mono text-xs text-muted-foreground">{{ shortCallId(row.call_id) }}</span>
                  </p>
                  <p class="mt-1 text-xs text-muted-foreground">{{ row.endpoint || '-' }}</p>
                </div>
                <StateBadge :tone="statusTone(row.status)" size="xs" shape="rounded" :bordered="false">
                  {{ formatMs(row.duration_ms) }}
                </StateBadge>
              </div>
              <div class="mt-3 grid grid-cols-2 gap-1.5 sm:grid-cols-3">
                <span
                  v-for="item in slowMetricItems(row)"
                  :key="`${row.call_id}-${item.key}`"
                  class="monitor-slow-card__chip"
                  :class="item.important ? 'monitor-slow-card__chip--hot' : 'monitor-slow-card__chip--normal'"
                >
                  {{ item.label }} {{ item.value }}
                </span>
              </div>
              <p v-if="slowRowReason(row)" class="mt-2 text-xs text-muted-foreground">
                {{ slowRowReason(row) }}
              </p>
              <p v-if="row.error" class="mt-2 line-clamp-2 text-xs text-muted-foreground">
                {{ row.error }}
              </p>
            </div>
          </div>
        </div>
        <div v-else class="monitor-paired-body px-4 pb-4">
          <StateBlock compact dashed title="暂无慢请求" description="窗口内没有可排序的完成请求。" />
        </div>
      </PagePanel>
    </div>

    <PagePanel flush>
      <div class="p-4">
        <PanelHeader title="阶段事件" align="start">
          <template #copy>
            <p class="mt-1 text-xs text-muted-foreground">
              最近阶段变化，辅助观察请求是否集中卡在同一环节。
            </p>
          </template>
        </PanelHeader>
      </div>
      <TableShell v-if="eventRows.length">
        <table class="monitor-table">
          <thead>
            <tr>
              <th class="table-num">时间</th>
              <th>请求</th>
              <th>模型</th>
              <th>阶段</th>
              <th class="table-num">耗时</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in eventRows" :key="`${row.call_id}-${row.event}-${index}`">
              <td class="table-num">{{ row.time || '-' }}</td>
              <td class="font-mono text-xs">{{ shortCallId(row.call_id) }}</td>
              <td class="max-w-[14rem] truncate">{{ row.model || '-' }}</td>
              <td>{{ row.label || row.event }}</td>
              <td class="table-num">{{ eventMetricText(row) }}</td>
            </tr>
          </tbody>
        </table>
      </TableShell>
      <div v-else class="px-4 pb-4">
        <StateBlock compact dashed title="暂无阶段事件" description="有图片请求进入后会开始记录。" />
      </div>
    </PagePanel>

  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Button, Input } from 'nanocat-ui'
import { monitorApi, type RealtimeMonitorEvent, type RealtimeMonitorRecord, type RealtimeMonitorResponse } from '@/api/monitor'
import MetaChip from '@/components/ai/MetaChip.vue'
import PagePanel from '@/components/ai/PagePanel.vue'
import PanelHeader from '@/components/ai/PanelHeader.vue'
import StateBadge from '@/components/ai/StateBadge.vue'
import StateBlock from '@/components/ai/StateBlock.vue'
import TableShell from '@/components/ai/TableShell.vue'

type BadgeTone = 'success' | 'danger' | 'warning' | 'info' | 'muted'

const monitorData = ref<RealtimeMonitorResponse | null>(null)
const isLoading = ref(false)
const loadError = ref('')
const autoRefresh = ref(true)
const REFRESH_INTERVAL_STORAGE_KEY = 'jovemage_monitor_refresh_interval_secs'
const DEFAULT_REFRESH_INTERVAL_SECONDS = 5
const MIN_REFRESH_INTERVAL_SECONDS = 1
const MAX_REFRESH_INTERVAL_SECONDS = 300
const refreshIntervalSeconds = ref(readStoredRefreshInterval())
let refreshTimer: number | undefined
let refreshRunId = 0

const summary = computed(() => monitorData.value?.summary)
const activeRows = computed(() => monitorData.value?.active || [])
const recentRows = computed(() => monitorData.value?.recent.slice(0, 20) || [])
const slowRows = computed(() => monitorData.value?.slow.slice(0, 8) || [])
const eventRows = computed(() => monitorData.value?.events.slice(0, 30) || [])
const threadTokens = computed(() => monitorData.value?.threadpool?.tokens || '-')
const completedWindowText = computed(() => {
  const windowInfo = monitorData.value?.window
  if (!windowInfo) return '窗口 0 / 0'
  return `窗口 ${windowInfo.completed} / ${windowInfo.completed_capacity}`
})
const activeStageItems = computed(() =>
  Object.entries(summary.value?.active_by_stage || {})
    .filter(([, count]) => Number(count) > 0)
    .slice(0, 8)
    .map(([label, count]) => ({ label, count: Number(count) })),
)

const entryQueueMetricKeys = ['handler_queue_ms', 'stream_first_queue_ms'] as const
const entryAccountMetricKeys = ['handler_queue_ms', 'stream_first_queue_ms', 'account_wait_ms', 'egress_wait_ms'] as const
const entryQueueP95 = computed(() => maxMetricFromMap(summary.value?.metric_p95 || {}, entryQueueMetricKeys))
const entryQueueText = computed(() => formatMs(entryQueueP95.value))

const diagnosticGroups = computed(() => {
  const data = summary.value
  const p95 = summary.value?.metric_p95 || {}
  const bottleneckValue = Number(data?.bottleneck?.value_ms || 0)
  const localBusy = summary.value?.slow_counts?.local_reject_or_busy ?? 0
  const entryAccountTotal = sumMetricFromMap(p95, entryAccountMetricKeys)
  const httpConnectTotal = sumMetricFromMap(p95, ['http_dns_ms', 'http_tcp_ms', 'http_tls_ms'])
  return [
    {
      key: 'overview',
      title: '实时概览',
      meta: '窗口、成功率、瓶颈',
      items: [
        { key: 'active', label: '当前并发', value: data?.active ?? 0, meta: `线程容量 ${threadTokens.value}`, valueClass: 'text-[var(--bauhaus-blue)]', primary: true, tone: 'blue' },
        { key: 'completed', label: '完成窗口', value: data?.completed ?? 0, meta: completedWindowText.value, valueClass: 'text-foreground', primary: true, tone: 'yellow' },
        { key: 'success', label: '成功率', value: `${data?.success_rate ?? 0}%`, meta: `成功 ${data?.success ?? 0}`, valueClass: 'text-[var(--bauhaus-blue)]', primary: true, tone: 'blue' },
        { key: 'failed', label: '失败数', value: data?.failed ?? 0, meta: '窗口内失败', valueClass: Number(data?.failed || 0) > 0 ? 'text-[var(--bauhaus-red)]' : 'text-foreground', primary: true, tone: 'red' },
        { key: 'average', label: '平均耗时', value: formatMs(data?.avg_duration_ms), meta: '窗口均值', valueClass: 'text-foreground', tone: 'ink' },
        { key: 'p95', label: 'P95 耗时', value: formatMs(data?.p95_duration_ms), meta: '慢请求参考', valueClass: 'text-foreground', tone: 'ink' },
        { key: 'bottleneck', label: '当前瓶颈', value: data?.bottleneck?.label || '-', meta: 'P95 最大阶段', valueClass: 'text-foreground', tone: 'ink' },
        { key: 'bottleneck_ms', label: '瓶颈耗时', value: formatMs(bottleneckValue), meta: '阶段 P95', valueClass: 'text-foreground', tone: 'ink' },
      ],
    },
    {
      key: 'account',
      title: '入口、账号与出口',
      meta: '本地线程、账号池、代理出口',
      items: [
        { key: 'handler_queue_ms', label: '入口排队', value: formatMs(p95.handler_queue_ms), meta: '等待后端线程', valueClass: 'text-foreground', tone: 'ink' },
        { key: 'stream_first_queue_ms', label: '首包排队', value: formatMs(p95.stream_first_queue_ms), meta: '等待流式首包', valueClass: 'text-foreground', tone: 'ink' },
        { key: 'account_wait_ms', label: '账号等待', value: formatMs(p95.account_wait_ms), meta: '账号池筛选', valueClass: 'text-[var(--bauhaus-blue)]', primary: true, tone: 'blue' },
        { key: 'egress_wait_ms', label: '出口等待', value: formatMs(p95.egress_wait_ms), meta: activeEgressMeta(), valueClass: 'text-[var(--bauhaus-blue)]', primary: true, tone: 'blue' },
        { key: 'egress_acquire_ms', label: '出口租约', value: formatMs(p95.egress_acquire_ms), meta: '代理节点并发', valueClass: 'text-foreground', tone: 'cyan' },
        { key: 'entry_account_total_ms', label: '入口账号合计', value: formatMs(entryAccountTotal), meta: '入口 + 首包 + 账号 + 出口', valueClass: 'text-foreground', tone: 'yellow' },
        { key: 'entry_p95', label: '入口排队 P95', value: entryQueueText.value, meta: `线程容量 ${threadTokens.value} · 慢 ${data?.slow_counts?.handler_queue ?? 0}`, valueClass: 'text-foreground', tone: 'ink' },
        { key: 'local_busy', label: '本地拒绝/繁忙', value: `${localBusy}`, meta: '无号 / 并发 / 策略', valueClass: localBusy > 0 ? 'text-[var(--bauhaus-red)]' : 'text-foreground', tone: 'red' },
      ],
    },
    {
      key: 'upstream_prepare',
      title: '上游准备与 HTTP',
      meta: '上传、令牌、建连、首包',
      items: [
        { key: 'upload_ms', label: '图片上传', value: formatMs(p95.upload_ms), meta: '参考图上传', valueClass: 'text-foreground', tone: 'violet' },
        { key: 'bootstrap_ms', label: '上游初始化', value: formatMs(p95.bootstrap_ms), meta: 'ChatGPT 会话', valueClass: 'text-foreground', tone: 'violet' },
        { key: 'requirements_ms', label: '令牌获取', value: formatMs(p95.requirements_ms), meta: 'requirements / token', valueClass: 'text-foreground', tone: 'violet' },
        { key: 'prepare_conversation_ms', label: '会话准备', value: formatMs(p95.prepare_conversation_ms), meta: '准备图片会话', valueClass: 'text-foreground', tone: 'violet' },
        { key: 'generation_start_ms', label: '启动生成', value: formatMs(p95.generation_start_ms), meta: '提交上游请求', valueClass: 'text-foreground', tone: 'violet' },
        { key: 'http_connect_ms', label: 'HTTP 建连', value: formatMs(httpConnectTotal), meta: 'DNS + TCP + TLS', valueClass: 'text-foreground', tone: 'cyan' },
        { key: 'http_wait_ms', label: 'HTTP 等待', value: formatMs(p95.http_wait_ms), meta: '发出请求到首包', valueClass: 'text-foreground', tone: 'cyan' },
        { key: 'http_ttfb_ms', label: 'HTTP 首包', value: formatMs(p95.http_ttfb_ms), meta: '请求开始到首包', valueClass: 'text-foreground', tone: 'cyan' },
      ],
    },
    {
      key: 'upstream_result',
      title: '生成与结果',
      meta: '流、轮询、下载',
      items: [
        { key: 'sse_first_event_ms', label: 'SSE 首事件', value: formatMs(p95.sse_first_event_ms), meta: '首个 data 事件', valueClass: 'text-foreground', tone: 'cyan' },
        { key: 'sse_max_gap_ms', label: 'SSE 最大空窗', value: formatMs(p95.sse_max_gap_ms), meta: '两次事件最大间隔', valueClass: 'text-foreground', tone: 'cyan' },
        { key: 'conversation_stream_ms', label: '上游生成', value: formatMs(p95.conversation_stream_ms), meta: '会话流响应', valueClass: 'text-[var(--bauhaus-blue)]', primary: true, tone: 'blue' },
        { key: 'stream_error_ms', label: '上游断流', value: formatMs(p95.stream_error_ms), meta: 'HTTP2 / SSE', valueClass: Number(p95.stream_error_ms || 0) > 0 ? 'text-[var(--bauhaus-red)]' : 'text-foreground', tone: 'red' },
        { key: 'resolve_ms', label: '图片解析', value: formatMs(p95.resolve_ms), meta: 'conversation / file', valueClass: 'text-foreground', tone: 'orange' },
        { key: 'download_ms', label: '图片下载', value: formatMs(p95.download_ms), meta: '下载并返回', valueClass: 'text-foreground', tone: 'orange' },
        { key: 'stream_ms', label: '单图内部', value: formatMs(p95.stream_ms), meta: '上游到结果', valueClass: 'text-foreground', tone: 'orange' },
        { key: 'total_ms', label: '单图总耗时', value: formatMs(p95.total_ms), meta: '完整链路', valueClass: 'text-foreground', primary: true, tone: 'yellow' },
      ],
    },
  ]
})

async function loadMonitor(silent = true, source: 'auto' | 'manual' = silent ? 'auto' : 'manual') {
  const autoRequest = source === 'auto'
  const runId = refreshRunId
  if (autoRequest && !autoRefresh.value) return
  if (isLoading.value && silent) return
  isLoading.value = true
  try {
    const data = await monitorApi.realtime()
    if (autoRequest && (!autoRefresh.value || runId !== refreshRunId)) return
    monitorData.value = data
    loadError.value = ''
  } catch (error: any) {
    if (autoRequest && (!autoRefresh.value || runId !== refreshRunId)) return
    loadError.value = error?.message || 'Request failed'
  } finally {
    isLoading.value = false
  }
}

function startPolling() {
  if (refreshTimer) {
    window.clearInterval(refreshTimer)
    refreshTimer = undefined
  }
  if (!autoRefresh.value) return
  refreshTimer = window.setInterval(() => {
    if (!autoRefresh.value) return
    void loadMonitor(true, 'auto')
  }, normalizedRefreshIntervalSeconds() * 1000)
}

function stopPolling() {
  if (refreshTimer) {
    window.clearInterval(refreshTimer)
    refreshTimer = undefined
  }
  refreshRunId += 1
}

function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value
  if (autoRefresh.value) {
    applyRefreshInterval(false)
    startPolling()
    void loadMonitor(true, 'auto')
  } else {
    stopPolling()
  }
}

function clampRefreshInterval(value: unknown) {
  const seconds = Math.round(Number(value || DEFAULT_REFRESH_INTERVAL_SECONDS))
  if (!Number.isFinite(seconds)) return DEFAULT_REFRESH_INTERVAL_SECONDS
  return Math.min(MAX_REFRESH_INTERVAL_SECONDS, Math.max(MIN_REFRESH_INTERVAL_SECONDS, seconds))
}

function readStoredRefreshInterval() {
  try {
    return clampRefreshInterval(window.localStorage.getItem(REFRESH_INTERVAL_STORAGE_KEY))
  } catch {
    return DEFAULT_REFRESH_INTERVAL_SECONDS
  }
}

function normalizedRefreshIntervalSeconds() {
  return clampRefreshInterval(refreshIntervalSeconds.value)
}

function setRefreshIntervalInput(value: unknown) {
  refreshIntervalSeconds.value = clampRefreshInterval(value)
}

function applyRefreshInterval(restart = true) {
  const nextValue = normalizedRefreshIntervalSeconds()
  refreshIntervalSeconds.value = nextValue
  try {
    window.localStorage.setItem(REFRESH_INTERVAL_STORAGE_KEY, String(nextValue))
  } catch {
    // ignore storage errors
  }
  if (restart && autoRefresh.value) {
    startPolling()
  }
}

function formatMs(value: unknown) {
  const ms = Number(value || 0)
  if (!Number.isFinite(ms) || ms <= 0) return '-'
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}m`
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.round(ms)}ms`
}

function shortCallId(value: unknown) {
  const text = String(value || '')
  return text ? text.slice(0, 8) : '-'
}

function maxMetricFromMap(map: Record<string, number> | undefined, keys: readonly string[]) {
  return keys.reduce((max, key) => Math.max(max, Number(map?.[key] || 0)), 0)
}

function sumMetricFromMap(map: Record<string, number> | undefined, keys: readonly string[]) {
  return keys.reduce((sum, key) => sum + Math.max(0, Number(map?.[key] || 0)), 0)
}

function metricValue(row: RealtimeMonitorRecord, key: string) {
  const perf = row.perf || {}
  const metrics = row.metrics || {}
  return Math.max(Number(perf[key] || 0), Number(metrics[key] || 0))
}

function proxySourceLabel(value: unknown) {
  const source = String(value || 'direct')
  if (source.includes('account_group')) return '账号组'
  if (source.includes('account')) return '账号'
  if (source.includes('default')) return '默认'
  if (source.includes('global')) return '默认'
  if (source.includes('runtime_resource')) return '资源代理'
  if (source.includes('runtime')) return 'Runtime'
  if (source.includes('explicit')) return '指定'
  if (source.includes('direct')) return '直连'
  return source
}

function egressLabelText(row: RealtimeMonitorRecord) {
  const groupId = String(row.proxy_group_id || '').trim()
  const nodeName = String(row.proxy_node_name || '').trim()
  const nodeId = String(row.proxy_node_id || '').trim()
  const nodeLabel = [groupId, nodeName || nodeId].filter(Boolean).join('/')
  if (nodeLabel) return nodeLabel
  const value = String(row.egress_label || '').trim()
  const source = String(row.proxy_source || '').trim()
  if (!value || value === 'direct') return ''
  if (value === source || value === `${source}_profile`) return ''
  if (value.startsWith('proxy:')) return ''
  return value
}

function egressText(row: RealtimeMonitorRecord) {
  const label = proxySourceLabel(row.proxy_source)
  const egressLabel = egressLabelText(row)
  if (egressLabel) return `${label} ${egressLabel}`
  const hash = String(row.proxy_hash || '')
  if (hash && hash !== 'direct') return `${label} ${hash}`
  return label
}

function accountEgressDigest(row: RealtimeMonitorRecord) {
  const accountWait = formatMs(metricValue(row, 'account_wait_ms'))
  const egressWait = formatMs(metricValue(row, 'egress_wait_ms'))
  return `账号 ${accountWait} / 出口 ${egressWait}`
}

function activeEgressMeta() {
  const items = Object.entries(summary.value?.active_by_egress || {})
  if (!items.length) return '代理组、默认出口、Runtime 或直连出口'
  return items
    .slice(0, 2)
    .map(([key, count]) => {
      const [source, ...rest] = key.split(':')
      const detail = rest.join(':')
      return `${proxySourceLabel(source)}${detail ? ` ${detail}` : ''} ${count}`
    })
    .join(' / ')
}

function metricDigest(row: RealtimeMonitorRecord) {
  const pairs = [
    ['等待入口', 'handler_queue_ms'],
    ['首包', 'stream_first_queue_ms'],
    ['等待账号', 'account_wait_ms'],
    ['等待出口', 'egress_wait_ms'],
    ['出口租约', 'egress_acquire_ms'],
    ['上传', 'upload_ms'],
    ['初始化', 'bootstrap_ms'],
    ['令牌', 'requirements_ms'],
    ['准备', 'prepare_conversation_ms'],
    ['启动', 'generation_start_ms'],
    ['HTTP首包', 'http_ttfb_ms'],
    ['HTTP等待', 'http_wait_ms'],
    ['SSE首事件', 'sse_first_event_ms'],
    ['SSE空窗', 'sse_max_gap_ms'],
    ['上游生成', 'conversation_stream_ms'],
    ['上游断流', 'stream_error_ms'],
    ['解析/轮询', 'resolve_ms'],
    ['下载', 'download_ms'],
    ['重试等待', 'retry_wait_ms'],
    ['单图链路', 'stream_ms'],
  ] as const
  const parts = pairs
    .map(([label, key]) => {
      const value = metricValue(row, key)
      return value > 0 ? { label, value, text: `${label} ${formatMs(value)}` } : null
    })
    .filter(Boolean)
    .sort((a, b) => (b?.value || 0) - (a?.value || 0))
    .map(item => item?.text || '')
  const stageElapsed = Number(row.stage_elapsed_ms || 0)
  if (String(row.status || '').toLowerCase() === 'running' && stageElapsed > 0) {
    parts.unshift(`当前阶段 ${formatMs(stageElapsed)}`)
  }
  return parts.slice(0, 4).join(' / ') || '-'
}

function rowDurationMs(row: RealtimeMonitorRecord) {
  const value = Math.max(Number(row.duration_ms || 0), Number(row.elapsed_ms || 0))
  return Number.isFinite(value) ? Math.max(0, value) : 0
}

function trackedDurationMs(row: RealtimeMonitorRecord) {
  const queue = metricValue(row, 'handler_queue_ms') + metricValue(row, 'stream_first_queue_ms')
  const linearStages = [
    'account_wait_ms',
    'egress_wait_ms',
    'upload_ms',
    'bootstrap_ms',
    'requirements_ms',
    'prepare_conversation_ms',
    'generation_start_ms',
    'conversation_stream_ms',
    'stream_error_ms',
    'resolve_ms',
    'download_ms',
    'retry_wait_ms',
    'response_ms',
  ].reduce((sum, key) => sum + metricValue(row, key), 0)
  const wrappedStage = Math.max(metricValue(row, 'total_ms'), metricValue(row, 'stream_ms'), linearStages)
  return queue + wrappedStage
}

function untrackedDurationMs(row: RealtimeMonitorRecord) {
  return Math.max(0, rowDurationMs(row) - trackedDurationMs(row))
}

function slowMetricItems(row: RealtimeMonitorRecord) {
  const pairs = [
    { key: 'handler_queue_ms', label: '等待入口' },
    { key: 'stream_first_queue_ms', label: '首包' },
    { key: 'account_wait_ms', label: '等待账号' },
    { key: 'egress_wait_ms', label: '等待出口' },
    { key: 'egress_acquire_ms', label: '出口租约' },
    { key: 'upload_ms', label: '上传' },
    { key: 'bootstrap_ms', label: '初始化' },
    { key: 'requirements_ms', label: '令牌' },
    { key: 'prepare_conversation_ms', label: '准备' },
    { key: 'generation_start_ms', label: '启动' },
    { key: 'http_dns_ms', label: 'HTTP DNS' },
    { key: 'http_tcp_ms', label: 'HTTP TCP' },
    { key: 'http_tls_ms', label: 'HTTP TLS' },
    { key: 'http_wait_ms', label: 'HTTP 等待' },
    { key: 'http_ttfb_ms', label: 'HTTP 首包' },
    { key: 'sse_first_event_ms', label: 'SSE 首事件' },
    { key: 'sse_max_gap_ms', label: 'SSE 最大空窗' },
    { key: 'sse_last_gap_ms', label: 'SSE 收尾空窗' },
    { key: 'conversation_stream_ms', label: '上游生成' },
    { key: 'stream_error_ms', label: '上游断流' },
    { key: 'resolve_ms', label: '解析/轮询' },
    { key: 'download_ms', label: '下载' },
    { key: 'retry_wait_ms', label: '重试等待' },
    { key: 'response_ms', label: '响应整理' },
    { key: 'stream_ms', label: '单图内部' },
    { key: 'total_ms', label: '单图总耗时' },
  ]
  const items = pairs
    .map((item) => {
      const raw = metricValue(row, item.key)
      return raw > 0
        ? { ...item, raw, value: formatMs(raw), important: raw >= 10_000 }
        : null
    })
    .filter(Boolean) as Array<{ key: string; label: string; raw: number; value: string; important: boolean }>
  const untracked = untrackedDurationMs(row)
  if (untracked >= 1000) {
    items.push({
      key: 'untracked_ms',
      label: '未标记',
      raw: untracked,
      value: formatMs(untracked),
      important: untracked >= 10_000,
    })
  }
  if (!items.length) {
    const total = rowDurationMs(row)
    if (total > 0) {
      items.push({ key: 'duration_ms', label: '总耗时', raw: total, value: formatMs(total), important: total >= 10_000 })
    }
  }
  return items
}

function slowRowReason(row: RealtimeMonitorRecord) {
  const candidates = slowMetricItems(row)
    .filter(item => !['stream_ms', 'total_ms', 'duration_ms'].includes(item.key))
    .sort((a, b) => b.raw - a.raw)
  const top = candidates[0]
  if (!top || top.raw < 1000) return ''
  if (top.key === 'untracked_ms') {
    return `仍有 ${top.value} 没有落到具体阶段，说明这段链路还缺埋点。`
  }
  if (top.key === 'resolve_ms') {
    return `主要卡在图片结果解析/轮询，通常对应等待 ChatGPT 图片任务完成或轮询超时。`
  }
  if (top.key === 'conversation_stream_ms') {
    return `主要卡在上游生成中，通常是 ChatGPT 生成阶段耗时。`
  }
  if (top.key === 'stream_error_ms') {
    return `主要卡在上游断流，通常是 HTTP2/SSE、代理或上游边缘节点中断。`
  }
  if (top.key === 'http_ttfb_ms' || top.key === 'http_wait_ms') {
    return `主要卡在 HTTP 首包，通常是代理出口、上游边缘节点或请求排队变慢。`
  }
  if (['http_dns_ms', 'http_tcp_ms', 'http_tls_ms'].includes(top.key)) {
    return `主要卡在 HTTP 建连阶段：${top.label} ${top.value}。`
  }
  if (top.key === 'sse_first_event_ms') {
    return `主要卡在 SSE 首事件，说明连接已建立但上游长时间没有返回首个事件。`
  }
  if (top.key === 'sse_max_gap_ms' || top.key === 'sse_last_gap_ms') {
    return `主要卡在 SSE 空窗，说明上游流中间长时间没有新事件。`
  }
  if (top.key === 'egress_wait_ms') {
    return `主要卡在等待出口，通常是代理组、默认出口、Runtime 出口或出站会话准备变慢。`
  }
  if (['upload_ms', 'bootstrap_ms', 'requirements_ms', 'prepare_conversation_ms', 'generation_start_ms'].includes(top.key)) {
    return `主要卡在上游准备阶段：${top.label} ${top.value}。`
  }
  if (top.key === 'account_wait_ms') {
    return `主要卡在等待账号，通常是可用账号不足或账号并发被占满。`
  }
  if (top.key === 'retry_wait_ms') {
    return `主要卡在重试等待，通常是轮询、TLS 或连接失败后的退避时间。`
  }
  if (top.key === 'handler_queue_ms' || top.key === 'stream_first_queue_ms') {
    return `主要卡在等待入口，通常是后端同步线程容量不足；可通过环境变量 CHATGPT2API_THREAD_TOKENS 调整。`
  }
  return `主要耗时：${top.label} ${top.value}。`
}

function statusLabel(status: unknown) {
  const value = String(status || '').toLowerCase()
  if (value === 'success') return '成功'
  if (value === 'failed' || value === 'error' || value === 'fail') return '失败'
  if (value === 'running') return '运行中'
  return value || '-'
}

function statusTone(status: unknown): BadgeTone {
  const value = String(status || '').toLowerCase()
  if (value === 'success') return 'success'
  if (value === 'failed' || value === 'error' || value === 'fail') return 'danger'
  if (value === 'running') return 'info'
  return 'muted'
}

function eventMetricText(row: RealtimeMonitorEvent) {
  const pairs = [
    ['等待入口', 'handler_queue_ms'],
    ['首包', 'stream_first_queue_ms'],
    ['等待账号', 'account_wait_ms'],
    ['等待出口', 'egress_wait_ms'],
    ['上传', 'upload_ms'],
    ['初始化', 'bootstrap_ms'],
    ['令牌', 'requirements_ms'],
    ['准备', 'prepare_conversation_ms'],
    ['启动', 'generation_start_ms'],
    ['HTTP首包', 'http_ttfb_ms'],
    ['HTTP等待', 'http_wait_ms'],
    ['SSE首事件', 'sse_first_event_ms'],
    ['SSE空窗', 'sse_max_gap_ms'],
    ['上游生成', 'conversation_stream_ms'],
    ['上游断流', 'stream_error_ms'],
    ['解析/轮询', 'resolve_ms'],
    ['下载', 'download_ms'],
    ['重试等待', 'retry_wait_ms'],
    ['响应整理', 'response_ms'],
    ['单图内部', 'stream_ms'],
    ['单图总耗时', 'total_ms'],
  ] as const
  const parts = pairs
    .map(([label, key]) => {
      const value = Number(row[key] || 0)
      return value > 0 ? `${label} ${formatMs(value)}` : ''
    })
    .filter(Boolean)
  return parts.slice(0, 3).join(' / ') || '-'
}

onMounted(() => {
  void loadMonitor(false)
  startPolling()
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<style scoped>
.monitor-table {
  width: 100%;
  min-width: 840px;
  border-collapse: separate;
  border-spacing: 0;
  text-align: left;
  font-size: 13px;
}

/* 表头/行 hover 走全局 style.css；本地统一紧凑 + 斑马纹 + 表头语义 */
.monitor-table th {
  padding: 7px 12px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: hsl(var(--muted-foreground));
  white-space: nowrap;
}

.monitor-table td {
  border-bottom: 1px solid hsl(var(--border) / 0.6);
  padding: 8px 12px;
  vertical-align: middle;
  color: hsl(var(--foreground));
}

/* 斑马纹：隔行浅色，便于横向扫读 */
.monitor-table tbody tr:nth-child(odd) {
  background: color-mix(in srgb, var(--bauhaus-paper-2, #f5f0e6) 55%, transparent);
}

.monitor-table tbody tr:hover {
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 7%, transparent);
}

html[data-theme='dark'] .monitor-table tbody tr:nth-child(odd) {
  background: color-mix(in srgb, var(--bauhaus-paper-2, #222) 40%, transparent);
}

html[data-theme='dark'] .monitor-table tbody tr:hover {
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 16%, transparent);
}

/* 配对区表格：滚动由外层面板承担，去掉内层再滚一层 */
.monitor-paired-table {
  --table-shell-max-height: none;
}

/* ===== 诊断区块 ===== */
.monitor-metric-group {
  display: flex;
  min-width: 0;
  flex-direction: column;
  border: 1px solid var(--bauhaus-line-soft, #c9c2b4);
  border-radius: var(--radius);
  background: var(--bauhaus-paper-2, #f5f0e6);
  box-shadow: 2px 2px 0 0 var(--bauhaus-ink, #2d2d2d);
  overflow: hidden;
}

.monitor-metric-group__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid var(--bauhaus-line-soft, #c9c2b4);
  padding: 9px 12px 8px;
}

.monitor-metric-group__title {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: hsl(var(--foreground));
}

.monitor-metric-group__meta {
  font-size: 11px;
  color: hsl(var(--muted-foreground));
  white-space: nowrap;
}

.monitor-metric-group__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(8.75rem, 1fr));
  gap: 6px;
  padding: 10px 12px 12px;
}

/* ===== 诊断单元格：顶部彩色条 + 硬阴影，模仿执行控制统计卡 ===== */
.monitor-metric-cell {
  position: relative;
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
  border: 2px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  background: hsl(var(--card));
  box-shadow: 2px 2px 0 0 var(--bauhaus-ink, #2d2d2d);
  overflow: hidden;
  padding: 10px 10px 8px;
}

/* 顶部彩条：细一点，弱化色彩占比，阅读更聚焦 */
.monitor-metric-cell::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: 3px;
  background: var(--bauhaus-ink, #2d2d2d);
}

.monitor-metric-cell--tone-blue::before {
  background: var(--bauhaus-blue, #2d5da1);
}

.monitor-metric-cell--tone-red::before {
  background: var(--bauhaus-red, #ff4d4d);
}

.monitor-metric-cell--tone-yellow::before {
  background: var(--bauhaus-yellow, #fff9c4);
}

/* 子阶段色：莫兰迪灰调，建连=青、准备=紫、收尾=橙（低饱和，不抢主色） */
.monitor-metric-cell--tone-cyan::before {
  background: #6f9aa0;
}

.monitor-metric-cell--tone-violet::before {
  background: #8d80a8;
}

.monitor-metric-cell--tone-orange::before {
  background: #bd9573;
}

/* quiet 档弱化：细边、无硬阴影、浅底 */
.monitor-metric-cell--quiet {
  border-width: 1px;
  border-color: var(--bauhaus-line-soft, #c9c2b4);
  background: color-mix(in srgb, var(--bauhaus-paper, #fdfbf7) 60%, transparent);
  box-shadow: none;
}

.monitor-metric-cell--quiet::before {
  height: 3px;
  opacity: 0.7;
}

.monitor-metric-cell--primary .monitor-metric-cell__value {
  font-size: 17px;
}

.monitor-metric-cell__label {
  overflow: hidden;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: hsl(var(--muted-foreground));
}

.monitor-metric-cell__value {
  font-size: 15px;
  font-weight: 700;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
}

.monitor-metric-cell__value--empty {
  color: hsl(var(--muted-foreground));
  font-weight: 500;
}

.monitor-metric-cell__meta {
  overflow: hidden;
  font-size: 10.5px;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: hsl(var(--muted-foreground));
}

/* 已耗时带脉冲点，提示仍在推进 */
.monitor-running-value {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.monitor-running-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--bauhaus-blue, #2d5da1);
  box-shadow: 0 0 0 0 rgba(45, 93, 161, 0.5);
  animation: monitor-pulse 1.4s ease-out infinite;
}

@keyframes monitor-pulse {
  0% { box-shadow: 0 0 0 0 rgba(45, 93, 161, 0.45); }
  70% { box-shadow: 0 0 0 6px rgba(45, 93, 161, 0); }
  100% { box-shadow: 0 0 0 0 rgba(45, 93, 161, 0); }
}

html[data-theme='dark'] .monitor-metric-group {
  border-color: var(--bauhaus-line-soft);
  background: var(--bauhaus-paper-2);
  box-shadow: var(--shadow-hard);
}

html[data-theme='dark'] .monitor-metric-group__head {
  border-bottom-color: var(--bauhaus-line-soft);
}

html[data-theme='dark'] .monitor-metric-cell {
  border-color: var(--bauhaus-line-soft);
  box-shadow: var(--shadow-hard-sm);
}

/* ===== 慢请求卡片：包豪斯锐边 + 顶部耗时状态条 ===== */
.monitor-slow-card {
  position: relative;
  border: 1px solid var(--bauhaus-line-soft, #c9c2b4);
  border-radius: var(--radius);
  background: hsl(var(--card));
  box-shadow: 2px 2px 0 0 var(--bauhaus-ink, #2d2d2d);
  overflow: hidden;
}

.monitor-slow-card__stripe {
  display: block;
  height: 4px;
}

.monitor-slow-card__stripe--success {
  background: var(--bauhaus-blue, #2d5da1);
}

.monitor-slow-card__stripe--danger {
  background: var(--bauhaus-red, #c0392b);
}

.monitor-slow-card__stripe--info {
  background: var(--bauhaus-yellow, #d9a512);
}

.monitor-slow-card__stripe--muted {
  background: var(--bauhaus-line-soft, #c9c2b4);
}

.monitor-slow-card__body {
  padding: 10px 12px;
}

.monitor-slow-card__chip {
  border-radius: var(--radius);
  padding: 4px 7px;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.monitor-slow-card__chip--hot {
  border: 1px solid color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 35%, transparent);
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 12%, transparent);
  color: var(--bauhaus-blue, #2d5da1);
  font-weight: 700;
}

.monitor-slow-card__chip--normal {
  border: 1px solid var(--bauhaus-line-soft, #c9c2b4);
  background: var(--bauhaus-paper-2, #f5f0e6);
  color: hsl(var(--muted-foreground));
}

html[data-theme='dark'] .monitor-slow-card {
  border-color: var(--bauhaus-line-soft, #3d3d3d);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.45);
}

html[data-theme='dark'] .monitor-slow-card__chip--normal {
  border-color: var(--bauhaus-line-soft, #3d3d3d);
  background: color-mix(in srgb, var(--bauhaus-paper-2, #222) 88%, transparent);
}

.monitor-paired-panel {
  display: flex;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  flex-direction: column;
}

.monitor-paired-header {
  display: flex;
  min-height: 92px;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px 14px;
}

.monitor-paired-header__copy {
  min-width: 0;
  flex: 1 1 auto;
}

.monitor-paired-header__desc {
  margin-top: 6px;
  max-width: 48rem;
  color: hsl(var(--muted-foreground));
  font-size: 12px;
  line-height: 1.55;
}

.monitor-paired-header__meta {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: flex-end;
  padding-top: 2px;
}

.monitor-paired-body {
  height: clamp(360px, calc(100vh - 350px), 560px);
  min-height: 0;
  overflow-y: auto;
}

@media (max-width: 768px) {
  .monitor-paired-header {
    min-height: auto;
    flex-direction: column;
    align-items: stretch;
  }

  .monitor-paired-header__meta {
    justify-content: flex-start;
    padding-top: 0;
  }

}

</style>
