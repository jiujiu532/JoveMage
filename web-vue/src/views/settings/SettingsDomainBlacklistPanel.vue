<template>
  <div class="space-y-4">
    <FormSection collapsible title="自动拉黑规则" subtitle="内置规则始终生效；自定义规则随右上角保存设置写入。">
      <SurfaceBox density="compact">
        <p class="text-xs leading-5 text-muted-foreground">
          内置规则始终生效且只读；自定义规则随右上角「保存设置」写入配置。黑名单条目本身点操作即调 API 生效。
        </p>
      </SurfaceBox>

      <div class="space-y-2">
        <p class="text-xs font-medium text-foreground">内置规则</p>
        <div v-if="builtinRules.length" class="space-y-2">
          <div
            v-for="(rule, index) in builtinRules"
            :key="rule.id || `builtin_${index}`"
            class="settings-list-row"
          >
            <div class="min-w-0 space-y-0.5">
              <p class="font-medium text-foreground">{{ rule.label || rule.description || rule.id || '内置规则' }}</p>
              <p class="font-mono text-muted-foreground">{{ rule.match }}</p>
              <p v-if="rule.description && rule.label" class="text-muted-foreground">{{ rule.description }}</p>
            </div>
            <MetaChip size="xs" tone="muted" variant="outline">始终生效</MetaChip>
          </div>
        </div>
        <StateBlock v-else compact dashed>
          暂无内置规则（或接口尚未返回）。
        </StateBlock>
      </div>

      <div class="space-y-2">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <p class="text-xs font-medium text-foreground">自定义规则</p>
          <Button size="xs" variant="outline" @click="addCustomRule">添加规则</Button>
        </div>
        <div v-if="localRules.length" class="space-y-2">
          <div
            v-for="(rule, index) in localRules"
            :key="rule.id || `custom_${index}`"
            class="settings-list-row settings-list-row--rule"
          >
            <div class="min-w-0 space-y-1">
              <Input
                :model-value="rule.match"
                block
                root-class="font-mono"
                placeholder="错误文案子串，至少 8 字符，例如 cannot create your account"
                @update:model-value="updateCustomRule(index, { match: String($event || '') })"
              />
              <p
                v-if="rule.match.trim().length > 0 && rule.match.trim().length < 8"
                class="text-[11px] text-amber-600 dark:text-amber-400"
              >
                匹配串不足 8 字符，保存设置时会被后端丢弃
              </p>
            </div>
            <Checkbox
              :model-value="rule.enabled !== false"
              @update:model-value="updateCustomRule(index, { enabled: Boolean($event) })"
            >
              启用
            </Checkbox>
            <Button size="xs" variant="outline" @click="removeCustomRule(index)">删除</Button>
          </div>
        </div>
        <StateBlock v-else compact dashed>
          暂无自定义规则。修改后请点右上角「保存设置」。
        </StateBlock>
      </div>
    </FormSection>

    <FormSection collapsible title="黑名单列表" subtitle="按域名管理拉黑条目，操作即时生效。">
      <div class="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
        <Input
          v-model.trim="searchQuery"
          block
          root-class="sm:max-w-xs"
          placeholder="搜索域名 / 原因 / 邮箱"
        />
        <div class="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" :disabled="loading || busy !== ''" @click="loadList">
            {{ loading ? '刷新中...' : '刷新列表' }}
          </Button>
          <Button size="sm" variant="outline" :disabled="busy !== ''" @click="exportAll">
            {{ busy === 'export-all' ? '导出中...' : '导出全部' }}
          </Button>
          <Button size="sm" variant="outline" :disabled="busy !== ''" @click="triggerImport()">
            导入全部
          </Button>
          <input
            ref="importInputRef"
            type="file"
            accept="application/json,.json"
            class="hidden"
            @change="onImportFileChange"
          >
        </div>
      </div>

      <PageLoadingState
        v-if="loading && !entries.length"
        compact
        title="正在读取域名黑名单"
        description="按约定路径请求 /api/register/domain-blacklist。"
      />

      <StateBlock v-else-if="loadError" compact dashed>
        {{ loadError }}
      </StateBlock>

      <div v-else class="space-y-3">
        <article
          v-for="group in displayGroups"
          :key="group.key"
          class="overflow-hidden rounded-sm border border-border bg-card"
        >
          <button
            type="button"
            class="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left hover:bg-muted/30"
            @click="toggleGroup(group.key)"
          >
            <div class="min-w-0">
              <p class="text-sm font-medium text-foreground">{{ group.title }}</p>
              <p class="mt-0.5 text-[11px] text-muted-foreground">
                {{ group.legacy ? '遗留 / 已删除服务' : group.providerRef }}
              </p>
            </div>
            <div class="flex shrink-0 items-center gap-2">
              <MetaChip size="xs" tone="muted">{{ group.entries.length }} 条</MetaChip>
              <CollapseCaret :open="!collapsed[group.key]" />
            </div>
          </button>

          <div v-if="!collapsed[group.key]" class="space-y-3 border-t border-border px-3 py-3">
            <div v-if="!group.legacy" class="flex flex-col gap-2 lg:flex-row lg:items-end">
              <FormField label="添加域名" class="min-w-0 flex-1">
                <Input
                  v-model.trim="addDomainDraft[group.providerRef]"
                  block
                  root-class="font-mono"
                  placeholder="example.com"
                />
              </FormField>
              <FormField label="原因（可选）" class="min-w-0 flex-1">
                <Input
                  v-model.trim="addReasonDraft[group.providerRef]"
                  block
                  placeholder="可选"
                />
              </FormField>
              <div class="flex flex-wrap gap-2 pb-0.5">
                <Button
                  size="sm"
                  variant="primary"
                  :disabled="busy === `add:${group.providerRef}`"
                  @click="addDomain(group.providerRef)"
                >
                  {{ busy === `add:${group.providerRef}` ? '添加中...' : '添加' }}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  :disabled="busy !== ''"
                  @click="exportGroup(group.providerRef)"
                >
                  导出本组
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  :disabled="busy !== ''"
                  @click="triggerImport(group.providerRef)"
                >
                  导入本组
                </Button>
              </div>
            </div>

            <div v-if="group.entries.length" class="overflow-x-auto">
              <table class="min-w-full border-collapse text-left text-xs">
                <thead>
                  <tr class="border-b border-border text-muted-foreground">
                    <th class="px-2 py-1.5 font-medium">域名</th>
                    <th class="px-2 py-1.5 font-medium">来源</th>
                    <th class="px-2 py-1.5 font-medium">原因</th>
                    <th class="px-2 py-1.5 font-medium">命中</th>
                    <th class="px-2 py-1.5 font-medium">最近拉黑</th>
                    <th class="px-2 py-1.5 font-medium">样例邮箱</th>
                    <th class="px-2 py-1.5 font-medium"></th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="entry in group.entries"
                    :key="`${entry.provider_ref}:${entry.domain}`"
                    class="border-b border-border/70 last:border-b-0"
                  >
                    <td class="px-2 py-2 font-mono text-foreground">{{ entry.domain }}</td>
                    <td class="px-2 py-2 text-muted-foreground">{{ entry.source || '—' }}</td>
                    <td class="max-w-[12rem] truncate px-2 py-2 text-muted-foreground" :title="entry.reason || ''">
                      {{ entry.reason || '—' }}
                    </td>
                    <td class="px-2 py-2 tabular-nums text-muted-foreground">{{ entry.hit_count ?? 0 }}</td>
                    <td class="px-2 py-2 text-muted-foreground">{{ formatBannedAt(entry.last_banned_at) }}</td>
                    <td class="max-w-[12rem] truncate px-2 py-2 font-mono text-muted-foreground" :title="entry.sample_email || ''">
                      {{ entry.sample_email || '—' }}
                    </td>
                    <td class="px-2 py-2 text-right">
                      <Button
                        size="xs"
                        variant="outline"
                        :disabled="busy === `remove:${entry.provider_ref}:${entry.domain}`"
                        @click="removeEntry(entry)"
                      >
                        解除
                      </Button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <StateBlock v-else compact dashed>
              本组暂无匹配条目。
            </StateBlock>
          </div>
        </article>

        <StateBlock v-if="!displayGroups.length" compact dashed>
          暂无黑名单分组。请确认邮箱 Provider 已配置，或导入名单。
        </StateBlock>
      </div>
    </FormSection>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Button, Checkbox, FormField, Input } from 'nanocat-ui'
import CollapseCaret from '@/components/ai/CollapseCaret.vue'
import FormSection from '@/components/ai/FormSection.vue'
import {
  domainBlacklistProviderRef,
  registerApi,
  type DomainBlacklistBuiltinRule,
  type DomainBlacklistEntry,
  type DomainBlacklistImportMode,
  type DomainBlacklistProvider,
} from '@/api/register'
import MetaChip from '@/components/ai/MetaChip.vue'
import PageLoadingState from '@/components/ai/PageLoadingState.vue'
import StateBlock from '@/components/ai/StateBlock.vue'
import SurfaceBox from '@/components/ai/SurfaceBox.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useToast } from '@/composables/useToast'
import { saveBlob } from '@/lib/downloads'
import type { DomainBanRule } from '@/types/api'

const props = defineProps<{
  rules: DomainBanRule[]
}>()

const emit = defineEmits<{
  'update:rules': [value: DomainBanRule[]]
}>()

const toast = useToast()
const confirmDialog = useConfirmDialog()

const loading = ref(false)
const loadError = ref('')
const busy = ref('')
const searchQuery = ref('')
const entries = ref<DomainBlacklistEntry[]>([])
const providers = ref<DomainBlacklistProvider[]>([])
const builtinRules = ref<DomainBlacklistBuiltinRule[]>([])
const collapsed = reactive<Record<string, boolean>>({})
const addDomainDraft = reactive<Record<string, string>>({})
const addReasonDraft = reactive<Record<string, string>>({})
const importInputRef = ref<HTMLInputElement | null>(null)
const pendingImportProviderRef = ref<string | undefined>(undefined)
/** 并发 load 序号：只应用最后一次响应，避免 loading 短路跳过刷新 */
let loadSeq = 0
let pendingReload = false

const LEGACY_GROUP_KEY = '__legacy__'

const localRules = computed({
  get: () => (Array.isArray(props.rules) ? props.rules : []),
  set: (value: DomainBanRule[]) => emit('update:rules', value),
})

type DisplayGroup = {
  key: string
  providerRef: string
  title: string
  legacy: boolean
  entries: DomainBlacklistEntry[]
}

function normalizeEntry(raw: unknown): DomainBlacklistEntry | null {
  if (!raw || typeof raw !== 'object') return null
  const source = raw as Record<string, unknown>
  const provider_ref = String(source.provider_ref || '').trim()
  const domain = String(source.domain || '').trim()
  if (!provider_ref || !domain) return null
  return {
    ...source,
    provider_ref,
    domain,
    source: source.source != null ? String(source.source) : undefined,
    reason: source.reason != null ? String(source.reason) : undefined,
    hit_count: Number.isFinite(Number(source.hit_count)) ? Number(source.hit_count) : 0,
    last_banned_at: source.last_banned_at != null ? String(source.last_banned_at) : undefined,
    sample_email: source.sample_email != null ? String(source.sample_email) : undefined,
  }
}

function applyListResponse(data: {
  entries?: unknown
  providers?: unknown
  builtin_rules?: unknown
}) {
  const nextEntries = Array.isArray(data.entries)
    ? data.entries.map(normalizeEntry).filter((item): item is DomainBlacklistEntry => Boolean(item))
    : []
  const nextProviders = Array.isArray(data.providers)
    ? data.providers.filter((item): item is DomainBlacklistProvider => Boolean(item && typeof item === 'object'))
    : []
  const nextBuiltin = Array.isArray(data.builtin_rules)
    ? data.builtin_rules
      .filter((item): item is DomainBlacklistBuiltinRule => Boolean(item && typeof item === 'object'))
      .map((item) => {
        const match = String(item.match || '').trim()
        const label = item.label != null ? String(item.label).trim() : ''
        const description = item.description != null ? String(item.description).trim() : ''
        return {
          ...item,
          match,
          label: label || undefined,
          description: description || undefined,
        }
      })
      .filter((item) => item.match || item.label || item.id)
    : []

  entries.value = nextEntries
  providers.value = nextProviders
  builtinRules.value = nextBuiltin
}

function entryMatchesSearch(entry: DomainBlacklistEntry, query: string) {
  if (!query) return true
  const hay = [
    entry.domain,
    entry.source,
    entry.reason,
    entry.sample_email,
    entry.provider_ref,
  ]
    .map((part) => String(part || '').toLowerCase())
    .join(' ')
  return hay.includes(query)
}

const displayGroups = computed<DisplayGroup[]>(() => {
  const query = searchQuery.value.trim().toLowerCase()
  const visibleProviders = providers.value.filter((provider) => provider.excluded !== true)
  const providerRefSet = new Set(
    visibleProviders
      .map((provider) => domainBlacklistProviderRef(provider))
      .filter(Boolean),
  )

  const filtered = entries.value.filter((entry) => entryMatchesSearch(entry, query))
  const groups: DisplayGroup[] = []

  for (const provider of visibleProviders) {
    const providerRef = domainBlacklistProviderRef(provider)
    if (!providerRef) continue
    const title = String(provider.label || provider.name || provider.type || providerRef).trim() || providerRef
    const groupEntries = filtered
      .filter((entry) => entry.provider_ref === providerRef)
      .slice()
      .sort((a, b) => a.domain.localeCompare(b.domain))
    groups.push({
      key: providerRef,
      providerRef,
      title,
      legacy: false,
      entries: groupEntries,
    })
    if (collapsed[providerRef] === undefined) collapsed[providerRef] = false
  }

  const legacyEntries = filtered
    .filter((entry) => !providerRefSet.has(entry.provider_ref))
    .slice()
    .sort((a, b) => {
      const byProvider = a.provider_ref.localeCompare(b.provider_ref)
      return byProvider || a.domain.localeCompare(b.domain)
    })

  if (legacyEntries.length) {
    groups.push({
      key: LEGACY_GROUP_KEY,
      providerRef: LEGACY_GROUP_KEY,
      title: '遗留 / 已删除服务',
      legacy: true,
      entries: legacyEntries,
    })
    if (collapsed[LEGACY_GROUP_KEY] === undefined) collapsed[LEGACY_GROUP_KEY] = false
  }

  return groups
})

function formatBannedAt(value?: string) {
  const raw = String(value || '').trim()
  if (!raw) return '—'
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw
  return date.toLocaleString()
}

function toggleGroup(key: string) {
  collapsed[key] = !collapsed[key]
}

function cloneRules(rules: DomainBanRule[]): DomainBanRule[] {
  return rules.map((rule, index) => ({
    id: rule.id || `rule_${index + 1}`,
    match: String(rule.match || ''),
    enabled: rule.enabled !== false,
  }))
}

function addCustomRule() {
  const next = cloneRules(localRules.value)
  next.push({
    id: `rule_${Date.now()}`,
    match: '',
    enabled: true,
  })
  localRules.value = next
}

function updateCustomRule(index: number, patch: Partial<DomainBanRule>) {
  const next = cloneRules(localRules.value)
  if (!next[index]) return
  next[index] = {
    ...next[index],
    ...patch,
    match: patch.match != null ? String(patch.match) : next[index].match,
  }
  localRules.value = next
}

function removeCustomRule(index: number) {
  const next = cloneRules(localRules.value)
  next.splice(index, 1)
  localRules.value = next
}

async function loadList() {
  if (loading.value) {
    pendingReload = true
    return
  }
  loading.value = true
  loadError.value = ''
  const seq = ++loadSeq
  try {
    const data = await registerApi.getDomainBlacklist()
    if (seq !== loadSeq) return
    applyListResponse(data || {})
  } catch (error: any) {
    if (seq !== loadSeq) return
    loadError.value = error?.message || '域名黑名单加载失败'
    toast.error(loadError.value)
  } finally {
    if (seq === loadSeq) {
      loading.value = false
    }
    if (pendingReload) {
      pendingReload = false
      void loadList()
    }
  }
}

async function refreshAfterMutation() {
  await loadList()
}

async function addDomain(providerRef: string) {
  const domain = String(addDomainDraft[providerRef] || '').trim()
  if (!domain) {
    toast.warning('请填写域名')
    return
  }
  const reason = String(addReasonDraft[providerRef] || '').trim()
  busy.value = `add:${providerRef}`
  try {
    await registerApi.addDomainBlacklist({
      provider_ref: providerRef,
      domain,
      ...(reason ? { reason } : {}),
    })
    addDomainDraft[providerRef] = ''
    addReasonDraft[providerRef] = ''
    toast.success('域名已加入黑名单')
    await refreshAfterMutation()
  } catch (error: any) {
    toast.error(error?.message || '添加失败')
  } finally {
    busy.value = ''
  }
}

async function removeEntry(entry: DomainBlacklistEntry) {
  const confirmed = await confirmDialog.ask({
    title: '解除黑名单',
    message: `确认将 ${entry.domain} 从「${entry.provider_ref}」黑名单中解除？`,
    confirmText: '解除',
    cancelText: '取消',
  })
  if (!confirmed) return

  busy.value = `remove:${entry.provider_ref}:${entry.domain}`
  try {
    await registerApi.removeDomainBlacklist({
      provider_ref: entry.provider_ref,
      domain: entry.domain,
    })
    toast.success('已解除')
    await refreshAfterMutation()
  } catch (error: any) {
    toast.error(error?.message || '解除失败')
  } finally {
    busy.value = ''
  }
}

function downloadJson(payload: unknown, filename: string) {
  const text = `${JSON.stringify(payload, null, 2)}\n`
  saveBlob(new Blob([text], { type: 'application/json;charset=utf-8' }), filename)
}

async function exportAll() {
  busy.value = 'export-all'
  try {
    const data = await registerApi.exportDomainBlacklist()
    downloadJson(data, `domain-blacklist-all-${Date.now()}.json`)
    toast.success('已导出全部黑名单 JSON')
  } catch (error: any) {
    toast.error(error?.message || '导出失败')
  } finally {
    busy.value = ''
  }
}

async function exportGroup(providerRef: string) {
  busy.value = `export:${providerRef}`
  try {
    const data = await registerApi.exportDomainBlacklist(providerRef)
    const safe = providerRef.replace(/[^\w.-]+/g, '_')
    downloadJson(data, `domain-blacklist-${safe}-${Date.now()}.json`)
    toast.success('已导出本组 JSON')
  } catch (error: any) {
    toast.error(error?.message || '导出失败')
  } finally {
    busy.value = ''
  }
}

function triggerImport(providerRef?: string) {
  pendingImportProviderRef.value = providerRef
  const input = importInputRef.value
  if (!input) return
  input.value = ''
  input.click()
}

async function readJsonFile(file: File): Promise<unknown> {
  const text = await file.text()
  return JSON.parse(text)
}

async function onImportFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  const providerRef = pendingImportProviderRef.value
  pendingImportProviderRef.value = undefined
  if (!file) return

  let payload: unknown
  try {
    payload = await readJsonFile(file)
  } catch {
    toast.error('JSON 文件解析失败')
    input.value = ''
    return
  }

  // 第一步：合并 or 否（否再问是否替换）；第二步取消 = 中止导入
  const merge = await confirmDialog.ask({
    title: providerRef ? '导入本组黑名单' : '导入全部黑名单',
    message: '使用合并模式导入？选「否」可改用替换模式，或在下一步取消。',
    confirmText: '合并导入',
    cancelText: '否，其它方式',
  })

  let mode: DomainBlacklistImportMode | null = null
  if (merge) {
    mode = 'merge'
  } else {
    const replace = await confirmDialog.ask({
      title: '替换导入',
      message: providerRef
        ? `将以文件内容替换「${providerRef}」分组黑名单（该组原有条目会被清空后写入）。确定继续？选取消则中止导入。`
        : '将以文件内容替换全部黑名单（整表清空后写入文件内容）。确定继续？选取消则中止导入。',
      confirmText: '替换导入',
      cancelText: '取消导入',
    })
    if (!replace) {
      input.value = ''
      toast.info('已取消导入')
      return
    }
    mode = 'replace'
  }

  busy.value = providerRef ? `import:${providerRef}` : 'import-all'
  try {
    await registerApi.importDomainBlacklist({
      payload,
      mode,
      ...(providerRef ? { provider_ref: providerRef } : {}),
    })
    toast.success(mode === 'merge' ? '合并导入完成' : '替换导入完成')
    await refreshAfterMutation()
  } catch (error: any) {
    toast.error(error?.message || '导入失败')
  } finally {
    busy.value = ''
    input.value = ''
  }
}

onMounted(() => {
  void loadList()
})
</script>

<style scoped>
.settings-list-row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  border: 1px solid hsl(var(--border) / 0.9);
  border-radius: var(--radius);
  background: hsl(var(--background) / 0.4);
  padding: 10px 12px;
  font-size: 12px;
}

.settings-list-row--rule {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: center;
}

@media (min-width: 768px) {
  .settings-list-row--rule {
    grid-template-columns: minmax(0, 1fr) auto auto;
  }
}

html[data-theme='dark'] .settings-list-row {
  background: hsl(var(--background) / 0.55);
  border-color: hsl(var(--border));
}
</style>
