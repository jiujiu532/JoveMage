/**
 * 敏感信息展示脱敏。
 * 算法与原散点实现保持一致，禁止改打码规则。
 */

/** access_token 等长 token：≤12 全星，否则前 6 + ... + 后 4 */
export function maskToken(token: string): string {
  if (!token) return ''
  if (token.length <= 12) return '********'
  return `${token.slice(0, 6)}...${token.slice(-4)}`
}

/** 邮箱：本地名 ≤2 保留首字+*，否则前 2 + *** + 末字；域名原样 */
export function maskEmail(value: string): string {
  const email = value === undefined || value === null ? '' : String(value).trim()
  if (!email || !email.includes('@')) return email
  const [name, domain] = email.split('@')
  const masked = name.length <= 2 ? `${name.slice(0, 1)}*` : `${name.slice(0, 2)}***${name.slice(-1)}`
  return `${masked}@${domain}`
}

/** API Key 标签：匹配 sk- 后 ≥6 位，打成 前 5 + *** + 后 4 */
export function maskApiKey(value: string): string {
  const cleaned = value === undefined || value === null ? '' : String(value).trim()
  return cleaned.replace(/sk-[A-Za-z0-9_-]{6,}/g, (token) => `${token.slice(0, 5)}***${token.slice(-4)}`)
}

/** 代理 URL：仅隐藏 user:password@ 中的密码为 *** */
export function maskProxyUrl(value: unknown): string {
  const raw = String(value || '').trim()
  if (!raw) return ''
  return raw.replace(/:\/\/([^/@:]+):([^/@]+)@/, (_match, user) => `://${user}:***@`)
}
