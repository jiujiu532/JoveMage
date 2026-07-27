export type ReleaseInfo = {
  version: string
  date: string
  items: { type: string; content: string }[]
}

type GithubRelease = {
  tag_name?: string
  name?: string
  published_at?: string
  body?: string | null
  draft?: boolean
  prerelease?: boolean
}

/** 本地兜底（无网络 / 尚未发版时展示） */
export const FALLBACK_RELEASES: ReleaseInfo[] = [
  {
    version: '0.1.0',
    date: '2026-07-27',
    items: [
      { type: '变更', content: '项目正式更名为 JoveMage，仓库迁移至 jiujiu532/JoveMage' },
      { type: '变更', content: '版本号重置为 0.1.0' },
      { type: '变更', content: 'Docker 镜像改为 ghcr.io/jiujiu532/jovemage' },
      { type: '变更', content: '控制台品牌、favicon 与奶油纸面主题统一' },
      { type: '兼容', content: '环境变量 CHATGPT2API_* 仍可继续使用' },
    ],
  },
]

/** Keepachangelog 风格本地文件（可选，仓库默认不上传） */
export function parseChangelog(content: string): ReleaseInfo[] {
  return content
    .split(/^## /m)
    .slice(1)
    .map((block) => {
      const [title = '', ...lines] = block.trim().split('\n')
      const [, version = title.trim(), date = ''] = title.match(/^(.+?)(?:\s+-\s+(.+))?$/) || []
      return {
        version: version.trim(),
        date: date.trim(),
        items: lines
          .map((line) => line.trim().match(/^\+\s+\[(.+?)]\s+(.+)$/))
          .filter((match): match is RegExpMatchArray => Boolean(match))
          .map((match) => ({ type: match[1], content: match[2] })),
      }
    })
    .filter((release) => release.items.length)
}

/** 将 GitHub Releases 正文解析为条目列表 */
export function parseReleaseBody(body: string): { type: string; content: string }[] {
  const items: { type: string; content: string }[] = []
  for (const raw of body.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line) continue
    const typed = line.match(/^[-*+]\s*\[(.+?)]\s+(.+)$/)
    if (typed) {
      items.push({ type: typed[1].trim(), content: typed[2].trim() })
      continue
    }
    const bullet = line.match(/^[-*+]\s+(.+)$/)
    if (bullet) {
      items.push({ type: '更新', content: bullet[1].trim() })
      continue
    }
  }
  if (!items.length && body.trim()) {
    const summary = body.trim().split(/\r?\n/).find((l) => l.trim()) || body.trim()
    items.push({ type: '更新', content: summary.slice(0, 200) })
  }
  return items
}

export function parseGithubReleases(payload: unknown): ReleaseInfo[] {
  if (!Array.isArray(payload)) return []
  return (payload as GithubRelease[])
    .filter((release) => release && !release.draft)
    .map((release) => {
      const version = String(release.tag_name || release.name || '').trim()
      const date = String(release.published_at || '').slice(0, 10)
      const items = parseReleaseBody(String(release.body || ''))
      return { version, date, items }
    })
    .filter((release) => release.version && release.items.length)
}

export function normalizeVersionTag(value: string): string {
  const clean = value.trim()
  if (!clean) return ''
  return clean.startsWith('v') ? clean : `v${clean}`
}

function versionParts(value: string) {
  const match = value.trim().match(/^v?(\d+)\.(\d+)\.(\d+)/)
  return match ? match.slice(1).map(Number) : null
}

export function isNewerVersion(latestVersion: string, currentVersion: string): boolean {
  const latest = versionParts(latestVersion)
  const current = versionParts(currentVersion)
  if (!latest || !current) return false
  for (let index = 0; index < latest.length; index += 1) {
    if (latest[index] > current[index]) return true
    if (latest[index] < current[index]) return false
  }
  return false
}
