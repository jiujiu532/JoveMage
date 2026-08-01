/**
 * 前端渠道描述符：类型 + 本地默认表。
 * 权威数据源最终是 GET /api/channels；本模块是消费它的类型与兜底默认值层。
 * 后端接口未就绪时，页面用 DEFAULT_CHANNELS 渲染；就绪后调用 setChannelsFromApi。
 */

export type ChannelCapability = 'chat' | 'image' | 'video' | 'edit'
export type ChannelCredentialType = 'token' | 'cookie'
export type ChannelMeterKind = 'quota' | 'credits'

/** 预设色板槽位（后端只给槽位名，前端映射样式；禁止渠道自定义色） */
export type ChannelColorSlot = 'ember' | 'sky' | 'lime' | 'violet' | 'rose'

export interface ChannelDescriptor {
  id: string
  name: string
  /** iconify 图标名，如 mdi:fire */
  icon: string
  /** 预设色板槽位；ChatGPT 为 null（默认即无标） */
  color: ChannelColorSlot | string | null
  is_default: boolean
  credential_type: ChannelCredentialType
  registerable: boolean
  capabilities: ChannelCapability[]
  enabled: boolean
  meter_kind: ChannelMeterKind
  /** 运行时字段：来自 /api/channels，本地表可无 */
  account_count?: number
  healthy_count?: number
  credits_total?: number
}

export type ChannelColorStyle = {
  /** CSS color for solid fills / icons */
  solid: string
  /** soft background */
  softBg: string
  /** foreground on soft bg */
  softFg: string
  /** border */
  border: string
}

/**
 * 渠道色板：槽位 → Bauhaus 友好色。
 * 旁路渠道按注册顺序轮转；ChatGPT 不入色板。
 */
export const CHANNEL_COLOR_PALETTE: Record<string, ChannelColorStyle> = {
  ember: {
    solid: 'var(--bauhaus-red, #ff4d4d)',
    softBg: 'color-mix(in srgb, var(--bauhaus-red, #ff4d4d) 14%, transparent)',
    softFg: 'var(--bauhaus-red, #ff4d4d)',
    border: 'color-mix(in srgb, var(--bauhaus-red, #ff4d4d) 40%, transparent)',
  },
  sky: {
    solid: 'var(--bauhaus-blue, #2d5da1)',
    softBg: 'color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 14%, transparent)',
    softFg: 'var(--bauhaus-blue, #2d5da1)',
    border: 'color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 40%, transparent)',
  },
  lime: {
    solid: '#5a8f2f',
    softBg: 'color-mix(in srgb, #5a8f2f 14%, transparent)',
    softFg: '#5a8f2f',
    border: 'color-mix(in srgb, #5a8f2f 40%, transparent)',
  },
  violet: {
    solid: '#7c5cbf',
    softBg: 'color-mix(in srgb, #7c5cbf 14%, transparent)',
    softFg: '#7c5cbf',
    border: 'color-mix(in srgb, #7c5cbf 40%, transparent)',
  },
  rose: {
    solid: '#c45c7a',
    softBg: 'color-mix(in srgb, #c45c7a 14%, transparent)',
    softFg: '#c45c7a',
    border: 'color-mix(in srgb, #c45c7a 40%, transparent)',
  },
}

const COLOR_SLOT_ORDER: ChannelColorSlot[] = ['ember', 'sky', 'lime', 'violet', 'rose']

/** 本地默认表（与后端 registry 对齐）；后端未就绪时的兜底 */
export const DEFAULT_CHANNELS: readonly ChannelDescriptor[] = Object.freeze([
  {
    id: 'chatgpt',
    name: 'ChatGPT',
    icon: 'mdi:chat-outline',
    color: null,
    is_default: true,
    credential_type: 'token',
    registerable: true,
    capabilities: ['chat', 'image'],
    enabled: true,
    meter_kind: 'quota',
  },
  {
    id: 'firefly',
    name: 'Adobe Firefly',
    icon: 'mdi:fire',
    color: 'ember',
    is_default: false,
    credential_type: 'cookie',
    registerable: false,
    capabilities: ['image', 'edit', 'video'],
    enabled: true,
    meter_kind: 'credits',
  },
] as const satisfies readonly ChannelDescriptor[])

/** 运行时注册表；初始=本地默认，可被 setChannelsFromApi 替换 */
let channelRegistry: ChannelDescriptor[] = DEFAULT_CHANNELS.map((item) => ({ ...item }))

function cleanId(value: unknown): string {
  return String(value || '').trim().toLowerCase()
}

function normalizeDescriptor(raw: Partial<ChannelDescriptor> & { id: string }): ChannelDescriptor {
  const id = cleanId(raw.id) || 'unknown'
  const fromDefault = DEFAULT_CHANNELS.find((item) => item.id === id)
  const capabilities = Array.isArray(raw.capabilities)
    ? raw.capabilities.map((item) => String(item || '').trim().toLowerCase()).filter(Boolean) as ChannelCapability[]
    : fromDefault?.capabilities || []

  return {
    id,
    name: String(raw.name || fromDefault?.name || id).trim() || id,
    icon: String(raw.icon || fromDefault?.icon || 'mdi:circle-outline').trim(),
    color: raw.color === undefined ? (fromDefault?.color ?? null) : raw.color,
    is_default: Boolean(raw.is_default ?? fromDefault?.is_default ?? false),
    credential_type: (raw.credential_type || fromDefault?.credential_type || 'token') as ChannelCredentialType,
    registerable: Boolean(raw.registerable ?? fromDefault?.registerable ?? false),
    capabilities: capabilities.length ? capabilities : (fromDefault?.capabilities || []),
    enabled: raw.enabled === undefined ? (fromDefault?.enabled ?? true) : Boolean(raw.enabled),
    meter_kind: (raw.meter_kind || fromDefault?.meter_kind || 'quota') as ChannelMeterKind,
    account_count: raw.account_count,
    healthy_count: raw.healthy_count,
    credits_total: raw.credits_total,
  }
}

/** 当前渠道表（副本，避免外部原地改坏注册表） */
export function listChannels(): ChannelDescriptor[] {
  return channelRegistry.map((item) => ({ ...item }))
}

/** 仅启用渠道 */
export function listEnabledChannels(): ChannelDescriptor[] {
  return listChannels().filter((item) => item.enabled)
}

/** 旁路渠道（非默认主体） */
export function listBypassChannels(): ChannelDescriptor[] {
  return listChannels().filter((item) => !item.is_default)
}

export function getChannel(id: string | null | undefined): ChannelDescriptor | undefined {
  const needle = cleanId(id)
  if (!needle) return undefined
  return channelRegistry.find((item) => item.id === needle)
}

export function getDefaultChannel(): ChannelDescriptor {
  return channelRegistry.find((item) => item.is_default) || channelRegistry[0] || { ...DEFAULT_CHANNELS[0] }
}

/**
 * 用后端 /api/channels 响应替换本地表。
 * 失败/空数组时保持本地默认，避免整页空。
 */
export function setChannelsFromApi(channels: unknown): ChannelDescriptor[] {
  if (!Array.isArray(channels) || channels.length === 0) {
    return listChannels()
  }
  const next: ChannelDescriptor[] = []
  const seen = new Set<string>()
  for (const raw of channels) {
    if (!raw || typeof raw !== 'object') continue
    const source = raw as Partial<ChannelDescriptor>
    const id = cleanId(source.id)
    if (!id || seen.has(id)) continue
    seen.add(id)
    next.push(normalizeDescriptor({ ...source, id }))
  }
  if (!next.length) return listChannels()
  // 保证至少有一个 default
  if (!next.some((item) => item.is_default)) {
    next[0] = { ...next[0], is_default: true, color: null }
  }
  channelRegistry = next
  return listChannels()
}

/** 恢复本地默认表（测试 / 回退） */
export function resetChannelsToDefault(): void {
  channelRegistry = DEFAULT_CHANNELS.map((item) => ({ ...item }))
}

/**
 * 账号 source_type → 渠道 id。
 * firefly → firefly；其余 ChatGPT 来源（web/oauth_login/codex/manual…）→ chatgpt。
 */
export function resolveAccountChannelId(sourceType: unknown): string {
  const value = cleanId(sourceType)
  if (!value || value === 'all') return getDefaultChannel().id
  if (getChannel(value)) return value
  // 兼容后端 chatgpt 筛选桶：非 firefly 一律归主体
  if (value === 'chatgpt') return 'chatgpt'
  return getDefaultChannel().id
}

export function isFireflyChannel(sourceType: unknown): boolean {
  return resolveAccountChannelId(sourceType) === 'firefly'
}

/**
 * 模型 id → 渠道 id（命名空间约定：旁路 `{channel}-*`，ChatGPT 无前缀）。
 * 保留 isFireflyImageModel 等细粒度判断给路由；此处只做分组归属。
 */
export function channelOfModel(model: string): string {
  const value = String(model || '').trim().toLowerCase()
  if (!value) return getDefaultChannel().id
  for (const channel of channelRegistry) {
    if (channel.is_default) continue
    if (value === channel.id || value.startsWith(`${channel.id}-`) || value.startsWith(`${channel.id}_`)) {
      return channel.id
    }
  }
  return getDefaultChannel().id
}

export function getChannelColorStyle(channel: ChannelDescriptor | string | null | undefined): ChannelColorStyle | null {
  const descriptor = typeof channel === 'string' || !channel ? getChannel(channel as string) : channel
  if (!descriptor || descriptor.is_default || !descriptor.color) return null
  const slot = String(descriptor.color)
  if (CHANNEL_COLOR_PALETTE[slot]) return CHANNEL_COLOR_PALETTE[slot]
  // 未知槽位：按 id 稳定轮转，避免花屏
  const bypass = listBypassChannels()
  const index = Math.max(0, bypass.findIndex((item) => item.id === descriptor.id))
  const fallback = COLOR_SLOT_ORDER[index % COLOR_SLOT_ORDER.length]
  return CHANNEL_COLOR_PALETTE[fallback]
}

/** 是否应在 UI 上「上色/打标」（主体默认渠道 = 否） */
export function shouldBadgeChannel(channel: ChannelDescriptor | string | null | undefined): boolean {
  const descriptor = typeof channel === 'string' || !channel ? getChannel(channel as string) : channel
  if (!descriptor) return false
  return !descriptor.is_default
}

/**
 * 账号页顶部 Tab 选项：全部 + 各渠道。
 * counts 可从本地统计或将来 /api/channels.account_count 注入。
 */
export function buildChannelTabOptions(counts?: Record<string, number>): Array<{ label: string; value: string; count?: number }> {
  const allCount = counts?.all
  const tabs: Array<{ label: string; value: string; count?: number }> = [
    {
      label: allCount == null ? '全部' : `全部 · ${allCount}`,
      value: 'all',
      count: allCount,
    },
  ]
  for (const channel of listChannels()) {
    // 渠道关掉则 Tab 不出现（空状态原则：不出现而非灰掉）
    if (!channel.enabled) continue
    const count = counts?.[channel.id]
    // Tab 展示短名：Adobe Firefly → Firefly
    const shortName = channel.id === 'firefly' ? 'Firefly' : channel.name
    tabs.push({
      label: count == null ? shortName : `${shortName} · ${count}`,
      value: channel.id,
      count,
    })
  }
  return tabs
}

/**
 * Studio 图像模型分组：按启用渠道 + image 能力切分。
 * 保留调用方用 isFireflyImageModel 过滤视频模型后再传入。
 */
export function groupImageModelsByChannel(
  models: string[],
  options?: {
    /** 返回 true 表示该模型归属旁路渠道图像（默认：channelOfModel !== default） */
    isBypassImageModel?: (model: string) => boolean
  },
): Array<{ channelId: string; label: string; options: Array<{ label: string; value: string }> }> {
  const isBypassImageModel = options?.isBypassImageModel
  const buckets = new Map<string, Array<{ label: string; value: string }>>()

  for (const model of models) {
    const value = String(model || '').trim()
    if (!value) continue
    let channelId = channelOfModel(value)
    // 调用方可收窄：例如 firefly 视频模型不应进图像组
    if (isBypassImageModel && channelId !== getDefaultChannel().id && !isBypassImageModel(value)) {
      channelId = getDefaultChannel().id
    }
    const list = buckets.get(channelId) || []
    list.push({ label: value, value })
    buckets.set(channelId, list)
  }

  const groups: Array<{ channelId: string; label: string; options: Array<{ label: string; value: string }> }> = []
  for (const channel of listEnabledChannels()) {
    if (!channel.capabilities.includes('image')) continue
    const optionsForChannel = buckets.get(channel.id)
    if (!optionsForChannel?.length) continue
    groups.push({
      channelId: channel.id,
      label: channel.name,
      options: optionsForChannel,
    })
  }
  return groups
}
