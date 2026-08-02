import type { AccountBackendStatus } from '@/api/accounts'

export type BulkAction = 'refresh' | 'relogin' | 'reset' | 'enable' | 'disable' | 'delete'
export type BulkProgressKind = 'refresh' | 'mutation' | 'inspect'
export type AccountGlobalAction = 'refresh' | 'inspect' | 'delete' | 'relogin'
export type AccountGlobalScope = 'selected' | 'filter' | 'channel' | 'all'
export type AccountProxyMode = 'global' | 'direct' | 'group' | 'custom'

export type AccountGroupForm = {
  id: string
  name: string
  proxy: string
  proxy_group_id: string
  enabled: boolean
  notes: string
}

export type AccountForm = {
  id: string
  access_token: string
  cookie: string
  type: string
  source_type: string
  group_id: string
  proxy: string
  quota: string
  status: AccountBackendStatus
}

export const ACCOUNT_PAGE_SIZE_OPTIONS = [20, 50, 100]
export const DEFAULT_PAGE_SIZE = 20
export const REFRESH_BATCH_SIZE = 20
export const IMPORT_BATCH_SIZE = 20

export const ACCOUNT_SOURCE_FILTER_OPTIONS = [
  { label: '全部渠道', value: 'all' },
  { label: 'ChatGPT', value: 'chatgpt' },
  { label: 'Firefly', value: 'firefly' },
] as const

export const ACCOUNT_SOURCE_TYPE_OPTIONS = [
  { label: 'ChatGPT · web', value: 'web' },
  { label: 'ChatGPT · oauth_login', value: 'oauth_login' },
  { label: 'ChatGPT · codex', value: 'codex' },
  { label: 'ChatGPT · manual', value: 'manual' },
  { label: 'Adobe Firefly', value: 'firefly' },
] as const

export function createDefaultForm(): AccountForm {
  return {
    id: '',
    access_token: '',
    cookie: '',
    type: 'free',
    source_type: 'web',
    group_id: '',
    proxy: '',
    quota: '',
    status: '正常',
  }
}

export function isFireflySourceType(value: unknown): boolean {
  return String(value || '').trim().toLowerCase() === 'firefly'
}

export function createDefaultAccountGroupForm(): AccountGroupForm {
  return {
    id: '',
    name: '',
    proxy: '',
    proxy_group_id: '',
    enabled: true,
    notes: '',
  }
}

export function stableGroupNameHash(value: string) {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(36)
}

export function createAccountGroupId(name: string) {
  const hash = stableGroupNameHash(name).slice(0, 6)
  const slug = name
    .trim()
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^a-z0-9._-]+/g, '-')
    .replace(/[-._]+/g, '-')
    .replace(/^-+|-+$/g, '')
  const base = slug ? `${slug}-${hash}` : `group-${hash}`
  return base.slice(0, 64).replace(/-+$/g, '') || `group-${hash}`
}

export function normalizeAccountGroupName(name: unknown) {
  return String(name || '').trim().replace(/\s+/g, ' ').toLowerCase()
}

export function normalizeErrorMessage(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error)
  const duplicateMatch = raw.match(
    /duplicate cookie principal:\s*same\s+(__Secure-[^\s]+)\s+as\s+account\s+([a-z0-9_-]+)/i
  )
  if (!duplicateMatch) return raw
  const [, principal, accountId] = duplicateMatch
  return `账号主身份重复：${principal}（已存在于账号 ${accountId}）`
}

export function normalizeQuota(value: unknown): number | undefined {
  const raw = String(value ?? '').trim()
  if (!raw) return undefined
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? Math.max(0, Math.trunc(parsed)) : undefined
}

export function createExportFilename(extension = 'json') {
  const now = new Date()
  const parts = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, '0'),
    String(now.getDate()).padStart(2, '0'),
    '-',
    String(now.getHours()).padStart(2, '0'),
    String(now.getMinutes()).padStart(2, '0'),
    String(now.getSeconds()).padStart(2, '0'),
  ]
  return `accounts-export-${parts.join('')}.${extension}`
}

export function uniqueTokens(tokens: string[]) {
  return Array.from(new Set(tokens.map((token) => token.trim()).filter(Boolean)))
}

export function parseTokenLines(text: string) {
  return uniqueTokens(
    text
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith('#')),
  )
}

export function parseSessionJsonTokens(rawText: string) {
  const text = rawText.trim()
  if (!text) throw new Error('请先粘贴 Session JSON')
  const parsed = JSON.parse(text)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Session JSON 格式不正确')
  }
  const source = parsed as Record<string, unknown>
  const token = String(source.accessToken || source.access_token || '').trim()
  if (!token) throw new Error('Session JSON 中没有找到 accessToken')
  return [token]
}

export function tokenFromCPAAccount(value: unknown): string {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return ''
  const source = value as Record<string, unknown>
  return String(source.access_token || source.accessToken || '').trim()
}

export function parseCPAJsonTokens(rawText: string, label: string) {
  const text = rawText.trim()
  if (!text) throw new Error(`${label} 是空文件`)
  const parsed = JSON.parse(text)
  const candidates: unknown[] = []

  if (Array.isArray(parsed)) {
    candidates.push(...parsed)
  } else if (parsed && typeof parsed === 'object') {
    if (tokenFromCPAAccount(parsed)) {
      candidates.push(parsed)
    } else {
      const source = parsed as Record<string, unknown>
      for (const key of ['accounts', 'items', 'data', 'results']) {
        const rows = source[key]
        if (Array.isArray(rows)) candidates.push(...rows)
      }
    }
  }

  const tokens = uniqueTokens(candidates.map(tokenFromCPAAccount).filter(Boolean))
  if (!tokens.length) throw new Error(`${label} 中没有找到 access_token`)
  return tokens
}

export type SetErrorFn = (prefix: string, error: unknown, notify?: boolean) => void
