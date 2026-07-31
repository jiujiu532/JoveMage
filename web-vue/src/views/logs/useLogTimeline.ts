import { computed, type MaybeRefOrGetter, ref, toValue, watch } from 'vue'
import type { SystemLogRow } from '@/api/logs'
import { isSystemLogFailed } from '@/api/logs'

export type DetailTone = 'success' | 'danger' | 'warning' | 'info' | 'muted'
export type DetailTimelineCategory = 'entry' | 'prepare' | 'network' | 'upstream' | 'resolve' | 'download' | 'retry' | 'response'

export type DetailTimelineStepConfig = {
  key: string
  label: string
  group: string
  hint?: string
}

export type DetailTimelineStep = DetailTimelineStepConfig & {
  valueMs: number
  value: string
  tone: DetailTone
  category: DetailTimelineCategory
  statusLabel: string
  barStyle: Record<string, string>
  time: string
  note: string
}

export type DetailTimelineSegment = {
  key: string
  label: string
  valueMs: number
  value: string
  percent: string
  tone: DetailTone
  category: DetailTimelineCategory
  compact: boolean
  barStyle: Record<string, string>
  title: string
}

export type DetailTimelineLegendItem = {
  key: DetailTimelineCategory | DetailTone
  label: string
  category: DetailTimelineCategory | 'state'
  tone: DetailTone
}

export type DetailTimelineGroup = {
  name: string
  steps: DetailTimelineStep[]
}

export type LogTimelineData = {
  segments: DetailTimelineSegment[]
  groups: DetailTimelineGroup[]
  legendItems: DetailTimelineLegendItem[]
  bottleneckStep: DetailTimelineStep | null
  stepCount: number
  segmentTotal: number
  hasTimeline: boolean
  autoExpandDetails: boolean
}

export const detailTimelineSteps: DetailTimelineStepConfig[] = [
  { key: 'handler_queue_ms', label: '等待入口', group: '入口与账号', hint: 'run_in_threadpool' },
  { key: 'stream_first_queue_ms', label: '读取首包', group: '入口与账号', hint: '首个响应事件' },
  { key: 'account_wait_ms', label: '等待账号', group: '入口与账号', hint: '账号池筛选' },
  { key: 'egress_wait_ms', label: '等待出口', group: '入口与账号', hint: '代理出口准备' },
  { key: 'egress_acquire_ms', label: '出口租约', group: '入口与账号', hint: '代理节点并发' },
  { key: 'upload_ms', label: '上传输入图', group: '上游准备', hint: '参考图上传' },
  { key: 'bootstrap_ms', label: '预热页面', group: '上游准备', hint: 'ChatGPT 页面' },
  { key: 'requirements_ms', label: '获取请求令牌', group: '上游准备', hint: 'requirements / token' },
  { key: 'prepare_conversation_ms', label: '准备会话', group: '上游准备', hint: '图片会话上下文' },
  { key: 'generation_start_ms', label: '启动生成', group: '上游准备', hint: '提交上游请求' },
  { key: 'http_dns_ms', label: 'HTTP DNS', group: 'HTTP 连接', hint: '域名解析' },
  { key: 'http_tcp_ms', label: 'HTTP TCP', group: 'HTTP 连接', hint: '代理 / TCP 建连' },
  { key: 'http_tls_ms', label: 'HTTP TLS', group: 'HTTP 连接', hint: 'TLS 握手' },
  { key: 'http_wait_ms', label: 'HTTP 等待', group: 'HTTP 连接', hint: '请求发出到首包' },
  { key: 'http_ttfb_ms', label: 'HTTP 首包', group: 'HTTP 连接', hint: '请求开始到首包' },
  { key: 'sse_first_event_ms', label: 'SSE 首事件', group: '生成与结果', hint: '首个 data 事件' },
  { key: 'sse_max_gap_ms', label: 'SSE 最大空窗', group: '生成与结果', hint: '两次事件最大间隔' },
  { key: 'sse_last_gap_ms', label: 'SSE 收尾空窗', group: '生成与结果', hint: '最后事件到关闭' },
  { key: 'conversation_stream_ms', label: '上游生成', group: '生成与结果', hint: 'ChatGPT 会话流' },
  { key: 'stream_error_ms', label: '上游断流', group: '生成与结果', hint: 'HTTP2 / SSE' },
  { key: 'resolve_ms', label: '解析/轮询', group: '生成与结果', hint: 'conversation / file' },
  { key: 'download_ms', label: '下载图片', group: '生成与结果', hint: '图片文件下载' },
  { key: 'retry_wait_ms', label: '重试等待', group: '生成与结果', hint: '轮询 / 退避' },
  { key: 'response_ms', label: '响应整理', group: '生成与结果', hint: 'Codex 响应' },
  { key: 'stream_ms', label: '单图内部', group: '生成与结果', hint: '单图链路' },
  { key: 'total_ms', label: '单图总耗时', group: '生成与结果', hint: '完整链路' },
]

export const detailTimelineGroupOrder = ['入口与账号', '上游准备', 'HTTP 连接', '生成与结果']

export const detailTimelineAggregateKeys = new Set([
  'http_dns_ms',
  'http_tcp_ms',
  'http_tls_ms',
  'http_wait_ms',
  'http_ttfb_ms',
  'sse_first_event_ms',
  'sse_max_gap_ms',
  'sse_last_gap_ms',
  'stream_ms',
  'total_ms',
])

export const defaultTimelineWarningThresholdMs = 60_000

export const timelineWarningThresholdMs: Record<string, number> = {
  handler_queue_ms: 1_000,
  stream_first_queue_ms: 1_000,
  account_wait_ms: 10_000,
  egress_wait_ms: 10_000,
  egress_acquire_ms: 10_000,
  upload_ms: 60_000,
  bootstrap_ms: 60_000,
  requirements_ms: 60_000,
  prepare_conversation_ms: 60_000,
  generation_start_ms: 60_000,
  http_dns_ms: 1_000,
  http_tcp_ms: 3_000,
  http_tls_ms: 5_000,
  http_wait_ms: 30_000,
  http_ttfb_ms: 30_000,
  sse_first_event_ms: 30_000,
  sse_max_gap_ms: 60_000,
  sse_last_gap_ms: 30_000,
  download_ms: 60_000,
  retry_wait_ms: 60_000,
  response_ms: 30_000,
}

export const detailTimelineCategoryLabels: Record<DetailTimelineCategory, string> = {
  entry: '入口与账号',
  prepare: '上游准备',
  network: 'HTTP 连接',
  upstream: '上游生成',
  resolve: '解析/轮询',
  download: '图片下载',
  retry: '重试等待',
  response: '响应整理',
}

export const detailTimelineCategoryOrder: DetailTimelineCategory[] = [
  'entry',
  'prepare',
  'network',
  'upstream',
  'resolve',
  'download',
  'retry',
  'response',
]

function formatInlineValue(value: unknown): string {
  if (value === undefined || value === null || value === '') return ''
  if (Array.isArray(value)) return value.map(formatInlineValue).filter(Boolean).join(' · ')
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).filter(([, item]) => item !== undefined && item !== null && item !== '')
    if (!entries.length) return ''
    const primitive = entries.every(([, item]) => !item || ['string', 'number', 'boolean'].includes(typeof item))
    if (primitive && entries.length <= 8) {
      return entries.map(([key, item]) => `${key}: ${formatInlineValue(item)}`).join(' · ')
    }
    try {
      return JSON.stringify(value, null, 2)
    } catch {
      return String(value)
    }
  }
  return String(value).trim()
}

export function formatTimelineMs(value: unknown): string {
  const ms = Number(value || 0)
  if (!Number.isFinite(ms) || ms <= 0) return '-'
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}m`
  if (ms >= 10_000) return `${(ms / 1000).toFixed(1)}s`
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`
  return `${Math.round(ms)}ms`
}

function detailRecord(item: SystemLogRow): Record<string, any> {
  const detail = item.raw.detail
  return detail && typeof detail === 'object' ? detail : {}
}

function monitorRecord(item: SystemLogRow): Record<string, any> {
  const monitor = detailRecord(item).monitor
  return monitor && typeof monitor === 'object' ? monitor : {}
}

function metricFromRecord(record: unknown, key: string): number {
  if (!record || typeof record !== 'object') return 0
  const raw = (record as Record<string, unknown>)[key]
  const parsed = Number(raw || 0)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0
}

export function metricValueFromLog(item: SystemLogRow, key: string): number {
  const detail = detailRecord(item)
  const monitor = monitorRecord(item)
  const values = [
    metricFromRecord(detail.perf, key),
    metricFromRecord(detail.metrics, key),
    metricFromRecord(monitor.metrics, key),
  ]
  const images = monitor.images
  if (images && typeof images === 'object') {
    Object.values(images as Record<string, any>).forEach((image) => {
      if (image && typeof image === 'object') values.push(metricFromRecord(image.metrics, key))
    })
  }
  return Math.max(...values, 0)
}

export function timelineStepCategory(key: string, group: string): DetailTimelineCategory {
  if (group === '入口与账号') return 'entry'
  if (group === '上游准备') return 'prepare'
  if (group === 'HTTP 连接') return 'network'
  if (key === 'sse_first_event_ms' || key === 'sse_max_gap_ms' || key === 'sse_last_gap_ms') return 'upstream'
  if (key === 'conversation_stream_ms') return 'upstream'
  if (key === 'resolve_ms') return 'resolve'
  if (key === 'download_ms') return 'download'
  if (key === 'retry_wait_ms') return 'retry'
  return 'response'
}

export function timelineStepTone(key: string, valueMs: number, _maxMs: number): DetailTone {
  if (key === 'stream_error_ms') return 'danger'
  const threshold = timelineWarningThresholdMs[key] ?? defaultTimelineWarningThresholdMs
  if (valueMs >= threshold) return 'warning'
  return 'info'
}

export function timelineStatusLabel(tone: DetailTone): string {
  if (tone === 'danger') return '异常'
  if (tone === 'warning') return '慢'
  if (tone === 'success') return '完成'
  if (tone === 'info') return '记录'
  return '记录'
}

function eventTimeForMetric(item: SystemLogRow, metricKey: string): string {
  const events = monitorRecord(item).events
  if (!Array.isArray(events)) return ''
  const matched = events.find((event) => event && typeof event === 'object' && Number((event as Record<string, unknown>)[metricKey] || 0) > 0)
  return formatInlineValue((matched as Record<string, unknown> | undefined)?.time)
}

function requestShapeImageSummary(item: SystemLogRow): string {
  const shape = detailRecord(item).request_shape
  if (!shape || typeof shape !== 'object') return ''
  const record = shape as Record<string, unknown>
  const pairs: Array<[string, string]> = [
    ['input_image_parts', '输入图'],
    ['image_url_parts', '图链'],
    ['image_parts', '图片块'],
    ['data_url_images', 'base64'],
    ['remote_image_urls', '远程图'],
    ['literal_image_placeholders', '占位图'],
  ]
  const parts = pairs
    .map(([key, label]) => [label, Number(record[key] || 0)] as const)
    .filter(([, count]) => Number.isFinite(count) && count > 0)
    .map(([label, count]) => `${label} ${count}`)
  return parts.join(' · ')
}

export function timelineStepNote(item: SystemLogRow, step: DetailTimelineStepConfig): string {
  const parts = [step.hint || '']
  if (step.key === 'upload_ms') parts.push(requestShapeImageSummary(item))
  if (step.key === 'resolve_ms' && item.imageUrls.length) parts.push(`结果图 ${item.imageUrls.length}`)
  if (step.key === 'download_ms' && item.imageUrls.length) parts.push(`下载 ${item.imageUrls.length} 张`)
  return parts.filter(Boolean).join(' · ')
}

export function buildTimelineSegments(item: SystemLogRow): DetailTimelineSegment[] {
  const rawSegments = detailTimelineSteps
    .filter((step) => !detailTimelineAggregateKeys.has(step.key))
    .map((step) => ({
      ...step,
      valueMs: metricValueFromLog(item, step.key),
    }))
    .filter((step) => step.valueMs > 0)
  const totalMs = rawSegments.reduce((total, step) => total + step.valueMs, 0)
  if (totalMs <= 0) return []
  const maxMs = Math.max(...rawSegments.map((step) => step.valueMs), 0)
  return rawSegments.map((step) => {
    const percent = (step.valueMs / totalMs) * 100
    const tone = timelineStepTone(step.key, step.valueMs, maxMs)
    const category = timelineStepCategory(step.key, step.group)
    const value = formatTimelineMs(step.valueMs)
    return {
      key: step.key,
      label: step.label,
      valueMs: step.valueMs,
      value,
      percent: `${percent.toFixed(percent >= 10 ? 0 : 1)}%`,
      tone,
      category,
      compact: percent < 12,
      barStyle: { flexGrow: String(Math.max(step.valueMs, 1)) },
      title: `${step.label} ${value} · ${percent.toFixed(1)}%`,
    }
  })
}

export function buildTimelineGroups(item: SystemLogRow): DetailTimelineGroup[] {
  const maxMs = Math.max(...detailTimelineSteps.map((step) => metricValueFromLog(item, step.key)), 0)
  if (maxMs <= 0) return []
  const groups = new Map<string, DetailTimelineStep[]>()
  detailTimelineSteps.forEach((step) => {
    const valueMs = metricValueFromLog(item, step.key)
    if (valueMs <= 0) return
    const width = Math.max(3, Math.round((valueMs / maxMs) * 100))
    const tone = timelineStepTone(step.key, valueMs, maxMs)
    const category = timelineStepCategory(step.key, step.group)
    const groupSteps = groups.get(step.group) || []
    groupSteps.push({
      ...step,
      valueMs,
      value: formatTimelineMs(valueMs),
      tone,
      category,
      statusLabel: timelineStatusLabel(tone),
      barStyle: { width: `${width}%` },
      time: eventTimeForMetric(item, step.key),
      note: timelineStepNote(item, step),
    })
    groups.set(step.group, groupSteps)
  })
  return detailTimelineGroupOrder
    .map((name) => ({ name, steps: groups.get(name) || [] }))
    .filter((group) => group.steps.length > 0)
}

export function buildTimelineLegendItems(segments: DetailTimelineSegment[]): DetailTimelineLegendItem[] {
  if (!segments.length) return []
  const categories = new Set(segments.map((segment) => segment.category))
  const items: DetailTimelineLegendItem[] = detailTimelineCategoryOrder
    .filter((category) => categories.has(category))
    .map((category) => ({
      key: category,
      label: detailTimelineCategoryLabels[category],
      category,
      tone: 'info',
    }))
  if (segments.some((segment) => segment.tone === 'warning')) {
    items.push({ key: 'warning', label: '超过阈值', category: 'state', tone: 'warning' })
  }
  if (segments.some((segment) => segment.tone === 'danger')) {
    items.push({ key: 'danger', label: '异常中断', category: 'state', tone: 'danger' })
  }
  return items
}

export function pickBottleneckStep(groups: DetailTimelineGroup[]): DetailTimelineStep | null {
  const steps = groups.flatMap((group) => group.steps)
  return steps.reduce<DetailTimelineStep | null>((current, step) => {
    if (!current || step.valueMs > current.valueMs) return step
    return current
  }, null)
}

export function buildLogTimeline(item: SystemLogRow | null | undefined): LogTimelineData {
  if (!item) {
    return {
      segments: [],
      groups: [],
      legendItems: [],
      bottleneckStep: null,
      stepCount: 0,
      segmentTotal: 0,
      hasTimeline: false,
      autoExpandDetails: false,
    }
  }

  const segments = buildTimelineSegments(item)
  const groups = buildTimelineGroups(item)
  const bottleneckStep = pickBottleneckStep(groups)
  const stepCount = groups.reduce((total, group) => total + group.steps.length, 0)
  const segmentTotal = segments.reduce((total, segment) => total + segment.valueMs, 0)
  const autoExpandDetails = Boolean(
    isSystemLogFailed(item)
      || Number(item.durationMs || 0) >= 180_000
      || metricValueFromLog(item, 'stream_error_ms') > 0
      || bottleneckStep?.tone === 'danger',
  )

  return {
    segments,
    groups,
    legendItems: buildTimelineLegendItems(segments),
    bottleneckStep,
    stepCount,
    segmentTotal,
    hasTimeline: segments.length > 0 || groups.length > 0,
    autoExpandDetails,
  }
}

/** 接收日志行，返回 timeline 数据；详情展开状态由组件自管时可只取数据侧 */
export function useLogTimeline(log: MaybeRefOrGetter<SystemLogRow | null | undefined>) {
  const detailsExpanded = ref(false)

  const timeline = computed(() => buildLogTimeline(toValue(log)))

  const segments = computed(() => timeline.value.segments)
  const groups = computed(() => timeline.value.groups)
  const legendItems = computed(() => timeline.value.legendItems)
  const bottleneckStep = computed(() => timeline.value.bottleneckStep)
  const stepCount = computed(() => timeline.value.stepCount)
  const segmentTotal = computed(() => timeline.value.segmentTotal)
  const hasTimeline = computed(() => timeline.value.hasTimeline)
  const autoExpandDetails = computed(() => timeline.value.autoExpandDetails)
  const detailsVisible = computed(() => detailsExpanded.value)

  function toggleDetails() {
    detailsExpanded.value = !detailsExpanded.value
  }

  function setDetailsExpanded(value: boolean) {
    detailsExpanded.value = value
  }

  watch(
    () => {
      const item = toValue(log)
      return item?.id || ''
    },
    () => {
      detailsExpanded.value = autoExpandDetails.value
    },
    { immediate: true },
  )

  return {
    timeline,
    segments,
    groups,
    legendItems,
    bottleneckStep,
    stepCount,
    segmentTotal,
    hasTimeline,
    autoExpandDetails,
    detailsExpanded,
    detailsVisible,
    toggleDetails,
    setDetailsExpanded,
    formatTimelineMs,
  }
}
