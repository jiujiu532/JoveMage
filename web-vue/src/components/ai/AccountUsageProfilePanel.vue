<template>
  <div class="account-usage-profile space-y-3">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="min-w-0 flex flex-wrap items-center gap-2">
        <ChannelBadge
          v-if="channelId"
          :channel="channelId"
          size="xs"
          :force="true"
        />
        <span class="font-mono text-[11px] text-muted-foreground truncate" :title="accountId">
          {{ accountId }}
        </span>
      </div>
      <Button
        size="xs"
        variant="outline"
        root-class="min-w-16 justify-center"
        :disabled="loading"
        @click="reload"
      >
        {{ loading ? '刷新中…' : '刷新' }}
      </Button>
    </div>

    <PageLoadingState
      v-if="loading && !profile"
      title="加载行为档案"
      description="汇总今日调用、成功率与最近流水。"
    />

    <StateBlock
      v-else-if="error"
      compact
      dashed
      title="行为档案暂不可用"
      :description="error"
    >
      <div class="mt-3 flex justify-center">
        <Button size="xs" variant="outline" @click="reload">重试</Button>
      </div>
    </StateBlock>

    <template v-else>
      <MetricStrip
        density="compact"
        columns-class="grid grid-cols-2 gap-2 sm:grid-cols-4"
        :items="metricItems"
      />

      <FormSection title="最近流水" surface="plain">
        <StateBlock
          v-if="!recentRows.length"
          compact
          dashed
          title="暂无流水"
          description="该账号近期没有可展示的渠道调用记录。"
        />
        <div v-else class="account-usage-table-wrap">
          <table class="account-usage-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>动作</th>
                <th>模型</th>
                <th>结果</th>
                <th>trace</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in recentRows" :key="row.key || index">
                <td class="account-usage-table__time">{{ row.timeLabel }}</td>
                <td>
                  <div class="flex flex-wrap items-center gap-1.5">
                    <ChannelBadge
                      v-if="row.channelId"
                      :channel="row.channelId"
                      size="xs"
                      :show-name="false"
                    />
                    <span>{{ row.actionLabel }}</span>
                  </div>
                </td>
                <td class="font-mono text-[11px]">{{ row.modelLabel }}</td>
                <td>
                  <StateBadge :tone="row.resultTone" size="xs">
                    {{ row.resultLabel }}
                  </StateBadge>
                </td>
                <td>
                  <button
                    v-if="row.traceId"
                    type="button"
                    class="account-usage-trace"
                    :title="row.traceId"
                    @click="copyTrace(row.traceId)"
                  >
                    {{ shortTrace(row.traceId) }}
                  </button>
                  <span v-else class="text-muted-foreground">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </FormSection>

      <FormSection title="失败 / 跳过原因" surface="plain">
        <StateBlock
          v-if="!failureRows.length"
          compact
          dashed
          title="暂无统计"
          description="近期没有失败或被跳过的记录。"
        />
        <ul v-else class="account-usage-failures">
          <li
            v-for="item in failureRows"
            :key="item.reason"
            class="account-usage-failures__item"
          >
            <span class="account-usage-failures__reason" :title="item.reason">{{ item.reason }}</span>
            <span class="account-usage-failures__count">{{ item.count }}</span>
          </li>
        </ul>
      </FormSection>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Button } from 'nanocat-ui'
import ChannelBadge from '@/components/ai/ChannelBadge.vue'
import FormSection from '@/components/ai/FormSection.vue'
import MetricStrip from '@/components/ai/MetricStrip.vue'
import PageLoadingState from '@/components/ai/PageLoadingState.vue'
import StateBadge from '@/components/ai/StateBadge.vue'
import StateBlock from '@/components/ai/StateBlock.vue'
import {
  channelsApi,
  type AccountUsageProfile,
  type AccountUsageRecentItem,
} from '@/api/channels'
import { useClipboard } from '@/composables/useClipboard'
import { resolveAccountChannelId } from '@/config/channels'

const props = defineProps<{
  accountId: string
  /** 账号 source_type 或 channel id，用于顶栏 ChannelBadge */
  sourceType?: string
  /** 打开时自动拉取；父级切换 Tab 时传入 true 即可 */
  active?: boolean
}>()

const { copy } = useClipboard()

const loading = ref(false)
const error = ref('')
const profile = ref<AccountUsageProfile | null>(null)
let lastLoadedId = ''

const channelId = computed(() => {
  if (profile.value?.channel_id || profile.value?.channel) {
    return resolveAccountChannelId(profile.value.channel_id || profile.value.channel)
  }
  return resolveAccountChannelId(props.sourceType)
})

const metricItems = computed(() => {
  const data = profile.value
  const today = data?.today_calls ?? 0
  const rate = normalizeSuccessRate(data?.success_rate)
  const credits = data?.credits_used ?? 0
  const recentCount = Array.isArray(data?.recent) ? data!.recent.length : 0
  return [
    {
      key: 'today',
      label: '今日调用',
      value: today,
      icon: 'lucide:activity',
    },
    {
      key: 'rate',
      label: '成功率',
      value: formatPercent(rate),
      icon: 'lucide:percent',
    },
    {
      key: 'credits',
      label: 'Credits 消耗',
      value: credits,
      icon: 'lucide:coins',
    },
    {
      key: 'recent',
      label: '流水条数',
      value: recentCount,
      meta: '最近窗口',
      icon: 'lucide:list',
    },
  ]
})

type RecentRow = {
  key: string
  timeLabel: string
  actionLabel: string
  modelLabel: string
  resultLabel: string
  resultTone: 'success' | 'danger' | 'warning' | 'info' | 'muted'
  traceId: string
  channelId: string
}

const recentRows = computed<RecentRow[]>(() => {
  const list = Array.isArray(profile.value?.recent) ? profile.value!.recent : []
  return list.map((item, index) => normalizeRecentRow(item, index, channelId.value))
})

const failureRows = computed(() => {
  const map = profile.value?.failure_reasons || {}
  return Object.entries(map)
    .map(([reason, count]) => ({
      reason: String(reason || 'unknown'),
      count: Number(count) || 0,
    }))
    .filter((item) => item.count > 0)
    .sort((a, b) => b.count - a.count)
})

function normalizeSuccessRate(value: unknown): number {
  const num = Number(value)
  if (!Number.isFinite(num) || num < 0) return 0
  // 兼容 0-1 与 0-100
  if (num <= 1) return num
  return Math.min(1, num / 100)
}

function formatPercent(rate: number): string {
  return `${Math.round(rate * 1000) / 10}%`
}

function parseTime(value: unknown): Date | null {
  if (value == null || value === '') return null
  if (typeof value === 'number' && Number.isFinite(value)) {
    const ms = value < 1e12 ? value * 1000 : value
    const date = new Date(ms)
    return Number.isNaN(date.getTime()) ? null : date
  }
  const raw = String(value).trim()
  if (!raw) return null
  if (/^\d+$/.test(raw)) {
    const num = Number(raw)
    const ms = num < 1e12 ? num * 1000 : num
    const date = new Date(ms)
    return Number.isNaN(date.getTime()) ? null : date
  }
  const date = new Date(raw)
  return Number.isNaN(date.getTime()) ? null : date
}

function formatTimeLabel(value: unknown): string {
  const date = parseTime(value)
  if (!date) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

function normalizeRecentRow(item: AccountUsageRecentItem, index: number, fallbackChannel: string): RecentRow {
  const timeRaw = item.time ?? item.at ?? item.created_at
  const action = String(item.action || item.kind || item.type || 'call').trim() || 'call'
  const model = String(item.model || '').trim() || '—'
  const traceId = String(item.trace_id || item.traceId || '').trim()
  const channel = resolveAccountChannelId(item.channel_id || item.channel || fallbackChannel)

  let resultLabel = String(item.result || item.status || '').trim()
  let resultTone: RecentRow['resultTone'] = 'muted'
  if (item.success === true) {
    resultLabel = resultLabel || 'success'
    resultTone = 'success'
  } else if (item.success === false) {
    resultLabel = resultLabel || 'error'
    resultTone = 'danger'
  } else {
    const lower = resultLabel.toLowerCase()
    if (!resultLabel) {
      resultLabel = 'unknown'
      resultTone = 'muted'
    } else if (['success', 'ok', 'done', 'completed', 'succeeded'].includes(lower)) {
      resultTone = 'success'
    } else if (['error', 'failed', 'fail', 'failure'].includes(lower)) {
      resultTone = 'danger'
    } else if (['skip', 'skipped', 'cooldown', 'throttled', 'rate_limited'].includes(lower)) {
      resultTone = 'warning'
    } else {
      resultTone = 'info'
    }
  }

  return {
    key: traceId || `${action}-${index}-${timeRaw || ''}`,
    timeLabel: formatTimeLabel(timeRaw),
    actionLabel: action,
    modelLabel: model,
    resultLabel,
    resultTone,
    traceId,
    channelId: channel,
  }
}

function shortTrace(traceId: string): string {
  if (traceId.length <= 12) return traceId
  return `${traceId.slice(0, 6)}…${traceId.slice(-4)}`
}

async function copyTrace(traceId: string) {
  await copy(traceId, {
    success: 'trace_id 已复制',
    error: '复制 trace_id 失败',
  })
}

async function reload() {
  const id = String(props.accountId || '').trim()
  if (!id) {
    error.value = '缺少账号 ID'
    profile.value = null
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await channelsApi.getAccountProfile(id)
    profile.value = normalizeProfile(data, id)
    lastLoadedId = id
  } catch (err: unknown) {
    profile.value = null
    lastLoadedId = ''
    const status = (err as { response?: { status?: number } })?.response?.status
    if (status === 404) {
      error.value = '后端行为档案接口尚未就绪（404）。接口就绪后点刷新即可。'
    } else {
      error.value = err instanceof Error ? err.message : '加载行为档案失败'
    }
  } finally {
    loading.value = false
  }
}

function normalizeProfile(raw: AccountUsageProfile | null | undefined, accountId: string): AccountUsageProfile {
  const source = raw && typeof raw === 'object' ? raw : ({} as AccountUsageProfile)
  return {
    account_id: String(source.account_id || accountId),
    channel: source.channel,
    channel_id: source.channel_id,
    today_calls: Number(source.today_calls) || 0,
    success_rate: Number(source.success_rate) || 0,
    credits_used: Number(source.credits_used) || 0,
    recent: Array.isArray(source.recent) ? source.recent : [],
    failure_reasons: source.failure_reasons && typeof source.failure_reasons === 'object'
      ? source.failure_reasons
      : {},
  }
}

watch(
  () => [props.accountId, props.active] as const,
  ([id, active]) => {
    if (!active) return
    const nextId = String(id || '').trim()
    if (!nextId) return
    if (nextId === lastLoadedId && profile.value) return
    void reload()
  },
  { immediate: true },
)

defineExpose({ reload })
</script>

<style scoped>
.account-usage-table-wrap {
  overflow-x: auto;
  border: 1px solid hsl(var(--border));
  border-radius: var(--radius);
  background: hsl(var(--card));
}

.account-usage-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.account-usage-table th,
.account-usage-table td {
  padding: 0.55rem 0.65rem;
  text-align: left;
  border-bottom: 1px solid hsl(var(--border));
  vertical-align: middle;
}

.account-usage-table th {
  font-family: var(--font-display);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: hsl(var(--muted-foreground));
  background: hsl(var(--muted) / 0.35);
  white-space: nowrap;
}

.account-usage-table tbody tr:last-child td {
  border-bottom: none;
}

.account-usage-table__time {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  color: hsl(var(--muted-foreground));
}

.account-usage-trace {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  color: var(--bauhaus-blue, #2d5da1);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.account-usage-trace:hover {
  color: hsl(var(--foreground));
}

.account-usage-failures {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.account-usage-failures__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.5rem 0.65rem;
  border: 1px solid hsl(var(--border));
  border-radius: var(--radius);
  background: hsl(var(--muted) / 0.25);
}

.account-usage-failures__reason {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: hsl(var(--foreground));
}

.account-usage-failures__count {
  flex: 0 0 auto;
  font-family: var(--font-display);
  font-size: 0.95rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--bauhaus-red, #ff4d4d);
}
</style>
