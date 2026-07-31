import { ref, watch } from 'vue'
import {
  getJsonPreference,
  getStringPreference,
  preferenceKeys,
  setJsonPreference,
  setStringPreference,
} from '@/lib/preferences'
import { normalizeImageCount } from '@/api/imageTasks'
import type {
  StudioConversation,
  StudioConversationBadgeState,
  StudioMessage,
  StudioMessageStatus,
  StudioSearchImageGroup,
  StudioSearchSource,
} from '@/components/studio/types'
import type { DebugSearchImageGroup, DebugSearchSource } from '@/api/debug'

/**
 * Studio 会话/角标/当前会话 ID 的本地持久化。
 * 负责 load + 防抖 schedule/flush + timer 清理，不碰发送与消息列表滚动。
 */
export function useStudioPersistence() {
  const conversations = ref<StudioConversation[]>(loadConversations())
  const activeConversationId = ref(getStringPreference(preferenceKeys.studioActiveConversationId, ''))
  const conversationNotices = ref<Record<string, StudioConversationBadgeState>>(loadConversationNotices())

  let conversationsPersistTimer: number | null = null
  let conversationNoticesPersistTimer: number | null = null
  let activeConversationPersistTimer: number | null = null

  watch(conversations, schedulePersistConversations)
  watch(conversationNotices, schedulePersistConversationNotices)
  watch(activeConversationId, schedulePersistActiveConversationId)

  function persistConversations() {
    const payload = conversations.value.slice(0, 80).map((conversation) => ({
      ...conversation,
      messages: conversation.messages.slice(-160).map((message) => ({
        ...message,
        status: message.status === 'streaming' || message.status === 'sending' ? 'done' : message.status,
      })),
    }))
    setJsonPreference(preferenceKeys.studioConversations, payload)
  }

  function schedulePersistConversations() {
    if (conversationsPersistTimer !== null) return
    conversationsPersistTimer = window.setTimeout(() => {
      conversationsPersistTimer = null
      persistConversations()
    }, 300)
  }

  function flushPersistConversations() {
    if (conversationsPersistTimer !== null) {
      window.clearTimeout(conversationsPersistTimer)
      conversationsPersistTimer = null
    }
    persistConversations()
  }

  function persistConversationNotices() {
    const validIds = new Set(conversations.value.map((conversation) => conversation.id))
    const payload = Object.fromEntries(
      Object.entries(conversationNotices.value).filter(([id, state]) => validIds.has(id) && (state === 'done' || state === 'error')),
    )
    setJsonPreference(preferenceKeys.studioConversationBadges, payload)
  }

  function schedulePersistConversationNotices() {
    if (conversationNoticesPersistTimer !== null) return
    conversationNoticesPersistTimer = window.setTimeout(() => {
      conversationNoticesPersistTimer = null
      persistConversationNotices()
    }, 300)
  }

  function flushPersistConversationNotices() {
    if (conversationNoticesPersistTimer !== null) {
      window.clearTimeout(conversationNoticesPersistTimer)
      conversationNoticesPersistTimer = null
    }
    persistConversationNotices()
  }

  function schedulePersistActiveConversationId() {
    if (activeConversationPersistTimer !== null) {
      window.clearTimeout(activeConversationPersistTimer)
    }
    activeConversationPersistTimer = window.setTimeout(() => {
      activeConversationPersistTimer = null
      setStringPreference(preferenceKeys.studioActiveConversationId, activeConversationId.value)
    }, 200)
  }

  function flushPersistActiveConversationId() {
    if (activeConversationPersistTimer !== null) {
      window.clearTimeout(activeConversationPersistTimer)
      activeConversationPersistTimer = null
    }
    setStringPreference(preferenceKeys.studioActiveConversationId, activeConversationId.value)
  }

  function flushAllPersistence() {
    if (conversationsPersistTimer !== null) flushPersistConversations()
    if (conversationNoticesPersistTimer !== null) flushPersistConversationNotices()
    if (activeConversationPersistTimer !== null) flushPersistActiveConversationId()
  }

  function markConversationNotice(conversationId: string, state: StudioConversationBadgeState) {
    if (!conversationId) return
    const current = conversationNotices.value[conversationId]
    const nextState = current === 'error' && state === 'done' ? current : state
    conversationNotices.value = {
      ...conversationNotices.value,
      [conversationId]: nextState,
    }
    schedulePersistConversationNotices()
  }

  function clearConversationNotice(conversationId: string) {
    if (!conversationId || !conversationNotices.value[conversationId]) return
    const next = { ...conversationNotices.value }
    delete next[conversationId]
    conversationNotices.value = next
    schedulePersistConversationNotices()
  }

  return {
    conversations,
    activeConversationId,
    conversationNotices,
    schedulePersistConversations,
    flushPersistConversations,
    schedulePersistConversationNotices,
    flushPersistConversationNotices,
    schedulePersistActiveConversationId,
    flushPersistActiveConversationId,
    flushAllPersistence,
    markConversationNotice,
    clearConversationNotice,
  }
}

// --- load / normalize（反序列化路径；搜索相关导出给 Studio 发送链路复用） ---

export function createId(prefix: string) {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}-${crypto.randomUUID()}`
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function cleanText(value: unknown) {
  return String(value ?? '').trim()
}

function loadConversations(): StudioConversation[] {
  const items = getJsonPreference<unknown[]>(preferenceKeys.studioConversations, [])
  if (!Array.isArray(items)) return []
  return items.map(normalizeConversation).filter((item): item is StudioConversation => Boolean(item)).slice(0, 80)
}

function loadConversationNotices(): Record<string, StudioConversationBadgeState> {
  const raw = getJsonPreference<Record<string, unknown>>(preferenceKeys.studioConversationBadges, {})
  const notices: Record<string, StudioConversationBadgeState> = {}
  Object.entries(raw || {}).forEach(([id, state]) => {
    if (state === 'done' || state === 'error') notices[id] = state
  })
  return notices
}

function normalizeConversation(item: unknown): StudioConversation | null {
  if (!item || typeof item !== 'object') return null
  const raw = item as Partial<StudioConversation>
  const messages = Array.isArray(raw.messages)
    ? raw.messages.map(normalizeMessage).filter((message): message is StudioMessage => Boolean(message)).slice(-160)
    : []
  return {
    id: cleanText(raw.id) || createId('studio'),
    title: cleanText(raw.title) || '新对话',
    createdAt: cleanText(raw.createdAt) || new Date().toISOString(),
    updatedAt: cleanText(raw.updatedAt) || new Date().toISOString(),
    messages,
  }
}

function normalizeMessage(item: unknown): StudioMessage | null {
  if (!item || typeof item !== 'object') return null
  const raw = item as Partial<StudioMessage>
  const content = cleanText(raw.content)
  const taskId = cleanText(raw.taskId)
  if (!content && !taskId) return null
  const id = cleanText(raw.id) || createId('message')
  const mode = raw.mode === 'chat' || raw.mode === 'search' ? raw.mode : 'image'
  const normalizedContent = mode === 'search' ? cleanSearchAnswer(content) : content
  const migratedSearchResult = mode === 'search' ? splitLegacySearchResult(normalizedContent) : { content: normalizedContent, sources: undefined }
  const searchSources = normalizeSearchSources(raw.searchSources) || migratedSearchResult.sources
  const searchImageGroups = mode === 'search'
    ? normalizeSearchImageGroups(raw.searchImageGroups) || extractSearchImageGroupsFromText(content)
    : undefined
  return {
    id,
    role: raw.role === 'assistant' ? 'assistant' : 'user',
    mode,
    content: mode === 'search'
      ? linkSearchCitations(migratedSearchResult.content, id, searchSources?.length || 0)
      : migratedSearchResult.content,
    createdAt: cleanText(raw.createdAt) || new Date().toISOString(),
    status: normalizeMessageStatus(raw.status),
    model: cleanText(raw.model) || undefined,
    imageSize: cleanText(raw.imageSize) || undefined,
    imageCount: Number.isFinite(Number(raw.imageCount)) ? normalizeImageCount(raw.imageCount) : undefined,
    taskId: taskId || undefined,
    error: cleanText(raw.error) || undefined,
    attachments: Array.isArray(raw.attachments) ? raw.attachments.map(cleanText).filter(Boolean).slice(0, 8) : undefined,
    searchSources,
    searchImageGroups,
  }
}

export function normalizeSearchImageGroups(value: unknown): StudioSearchImageGroup[] | undefined {
  if (!Array.isArray(value)) return undefined
  const groups: StudioSearchImageGroup[] = []
  for (const item of value) {
    if (!item || typeof item !== 'object') continue
    const raw = item as DebugSearchImageGroup & { aspectRatio?: unknown; numPerQuery?: unknown; query?: unknown; queries?: unknown }
    const rawQueries = Array.isArray(raw.queries)
      ? raw.queries
      : Array.isArray(raw.query)
        ? raw.query
        : typeof raw.query === 'string'
          ? [raw.query]
          : []
    const queries = rawQueries.map((query) => cleanText(query)).filter(Boolean).slice(0, 6)
    if (!queries.length) continue
    const aspectRatio = cleanText(raw.aspect_ratio ?? raw.aspectRatio)
    const numPerQueryValue = Number(raw.num_per_query ?? raw.numPerQuery)
    const group: StudioSearchImageGroup = { queries }
    if (aspectRatio) group.aspectRatio = aspectRatio
    if (Number.isFinite(numPerQueryValue) && numPerQueryValue > 0) group.numPerQuery = numPerQueryValue
    groups.push(group)
    if (groups.length >= 4) break
  }
  return groups.length ? groups : undefined
}

export function extractSearchImageGroupsFromText(value: unknown): StudioSearchImageGroup[] | undefined {
  const text = cleanText(value)
  if (!text) return undefined
  const groups: unknown[] = []
  text.replace(/image_group([^]*)/g, (_match, payload: string) => {
    try {
      groups.push(JSON.parse(payload || '{}'))
    } catch {
      // ignore malformed upstream marker
    }
    return ''
  })
  return normalizeSearchImageGroups(groups)
}

export function normalizeSearchSources(value: unknown): StudioSearchSource[] | undefined {
  if (!Array.isArray(value)) return undefined
  const sources: StudioSearchSource[] = []
  for (const item of value) {
    if (!item || typeof item !== 'object') continue
    const raw = item as DebugSearchSource
    const title = cleanText(raw.title)
    const url = cleanText(raw.url)
    const snippet = cleanText(raw.snippet)
    if (!title && !url && !snippet) continue
    sources.push({ title, url, snippet })
  }
  return sources.length ? sources : undefined
}

function splitLegacySearchResult(content: string): { content: string; sources?: StudioSearchSource[] } {
  const match = content.match(/\n{2,}\*\*来源\*\*\n([\s\S]+)$/)
  if (!match || typeof match.index !== 'number') return { content }
  const sources = match[1]
    .split('\n')
    .map(parseLegacySearchSourceLine)
    .filter((source): source is StudioSearchSource => Boolean(source))
  if (!sources.length) return { content }
  return { content: content.slice(0, match.index).trim(), sources }
}

function parseLegacySearchSourceLine(line: string): StudioSearchSource | null {
  const raw = cleanText(line)
  if (!raw) return null
  const match = raw.match(/^\d+\.\s+(?:\[([^\]]+)\]\(([^)]+)\)|(.+?))(?:\s+—\s+(.+))?$/)
  if (!match) return null
  const title = cleanText((match[1] || match[3] || '').replace(/\\([\[\]])/g, '$1'))
  const url = cleanText(match[2]).replace(/%20/g, ' ').replace(/%29/g, ')')
  const snippet = cleanText(match[4])
  return title || url || snippet ? { title, url, snippet } : null
}

function normalizeMessageStatus(value: unknown): StudioMessageStatus | undefined {
  if (['sending', 'streaming', 'queued', 'running', 'done', 'error'].includes(String(value))) {
    return String(value) as StudioMessageStatus
  }
  return undefined
}

export function cleanSearchAnswer(value: unknown) {
  return cleanText(value)
    .replace(/cite([^]*)/g, (_match, citationId: string) => {
      const matched = String(citationId || '').match(/search(\d+)/)
      return matched ? `[${Number(matched[1]) + 1}]` : ''
    })
    .replace(/image_group([^]*)/g, '')
    .replace(/(?!cite|image_group)[a-zA-Z0-9_]+[^]*/g, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

export function linkSearchCitations(content: string, ownerId: string, sourceCount: number) {
  const encodedOwnerId = encodeURIComponent(ownerId)
  return content.replace(/\[(\d{1,2})\](?!\()/g, (matched, rawIndex: string) => {
    const index = Number(rawIndex)
    if (!Number.isInteger(index) || index < 1) return matched
    if (!sourceCount || index > sourceCount) return ''
    return `[${index}](studio-citation:${encodedOwnerId}:${index})`
  }).replace(/\s+([，。！？；：,.!?;:])/g, '$1')
}
