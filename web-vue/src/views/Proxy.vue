<template>
  <div class="space-y-6">
    <PagePanel class="space-y-5">
      <PanelHeader title="代理管理" align="start">
        <template #copy>
          <p class="mt-1 text-xs text-muted-foreground">
            出口优先级：账号个人代理 > 账号组代理/代理组 > 默认出口；默认出口可配置代理组、代理 URL 或直连。
          </p>
        </template>
        <template #actions>
          <Button size="sm" variant="outline" :disabled="loading" @click="loadData">
            {{ loading ? '刷新中...' : '刷新' }}
          </Button>
          <Button size="sm" variant="primary" :disabled="savingDefaultProxy || loading" @click="saveDefaultProxy">
            {{ savingDefaultProxy ? '保存中...' : '保存出口配置' }}
          </Button>
        </template>
      </PanelHeader>

      <div class="proxy-egress">
        <FormSection density="roomy" class="proxy-egress__form">
          <div class="proxy-egress__row">
            <label class="block text-xs">
              <span class="ui-field-label">默认出口模式</span>
              <GroupedSelectMenu
                :model-value="defaultProxyMode"
                :options="defaultProxyModeOptions"
                aria-label="默认出口模式"
                selected-indicator="none"
                block
                @update:model-value="setDefaultProxyMode"
              />
            </label>

            <label v-if="defaultProxyMode === 'group'" class="block text-xs">
              <span class="ui-field-label">默认出口代理组</span>
              <GroupedSelectMenu
                :model-value="selectedDefaultProxyGroupId"
                :options="defaultProxyGroupOptions"
                :disabled="loading"
                aria-label="默认出口代理组"
                selected-indicator="none"
                block
                @update:model-value="selectDefaultProxyGroup"
              />
            </label>

            <label v-else-if="defaultProxyMode === 'custom'" class="block text-xs">
              <span class="ui-field-label">自定义代理 URL</span>
              <Input
                :model-value="defaultCustomProxyInput"
                block
                root-class="font-mono"
                placeholder="http://127.0.0.1:7890 或 socks5://127.0.0.1:7890"
                @update:model-value="setDefaultCustomProxyInput"
              />
            </label>

            <div v-else class="proxy-egress__hint">未指定账号或账号组代理时直连。</div>
          </div>
          <ActionRow class="mt-3" gap="tight">
            <Button size="xs" variant="outline" :disabled="testingKey === DEFAULT_TEST_KEY || !canTestDefaultProxy" @click="testDefaultProxy">
              {{ testingKey === DEFAULT_TEST_KEY ? '测试中...' : '测试默认出口' }}
            </Button>
            <Button size="xs" variant="outline" :disabled="savingDefaultProxy || testingKey === DEFAULT_TEST_KEY" @click="setDefaultProxyDirect">
              设为直连
            </Button>
          </ActionRow>
          <p class="proxy-egress__current" :title="defaultProxyPreview">
            <span class="proxy-egress__current-label">当前默认出口</span>
            <span class="proxy-egress__current-value">{{ defaultProxyPreview }}</span>
          </p>

          <div class="proxy-egress__divider"></div>

          <div class="proxy-egress__row">
            <label class="block text-xs">
              <span class="ui-field-label">备用出口模式</span>
              <GroupedSelectMenu
                :model-value="fallbackProxyMode"
                :options="fallbackProxyModeOptions"
                aria-label="备用出口模式"
                selected-indicator="none"
                block
                @update:model-value="setFallbackProxyMode"
              />
            </label>

            <label v-if="fallbackProxyMode === 'group'" class="block text-xs">
              <span class="ui-field-label">备用出口代理组</span>
              <GroupedSelectMenu
                :model-value="selectedFallbackProxyGroupId"
                :options="defaultProxyGroupOptions"
                :disabled="loading"
                aria-label="备用出口代理组"
                selected-indicator="none"
                block
                @update:model-value="selectFallbackProxyGroup"
              />
            </label>

            <label v-else-if="fallbackProxyMode === 'custom'" class="block text-xs">
              <span class="ui-field-label">备用代理 URL</span>
              <Input
                :model-value="fallbackCustomProxyInput"
                block
                root-class="font-mono"
                placeholder="http://127.0.0.1:7890 或 socks5://127.0.0.1:7890"
                @update:model-value="setFallbackCustomProxyInput"
              />
            </label>

            <div v-else class="proxy-egress__hint">
              {{ fallbackProxyMode === 'direct' ? '早期连接失败时重试直连一次。' : '未启用备用出口。' }}
            </div>
          </div>
          <p class="proxy-egress__note">仅图片请求在早期 TLS / 连接超时且尚未收到上游事件时重试一次；生成中断和轮询超时不会切换。</p>
          <p class="proxy-egress__current" :title="fallbackProxyPreview">
            <span class="proxy-egress__current-label">当前备用出口</span>
            <span class="proxy-egress__current-value">{{ fallbackProxyPreview }}</span>
          </p>
        </FormSection>

        <FormSection density="roomy" surface="background" class="proxy-egress__test">
          <p class="proxy-egress__test-title">默认出口测试结果</p>
          <div v-if="defaultTestResult" class="proxy-egress__test-body">
            <div class="proxy-egress__test-status" :class="defaultTestResult.ok ? 'is-ok' : 'is-fail'">
              <span class="proxy-egress__test-dot" aria-hidden="true"></span>
              <span class="proxy-egress__test-word">{{ defaultTestResult.ok ? '可用' : '不可用' }}</span>
            </div>
            <dl class="proxy-egress__test-meta">
              <div class="proxy-egress__test-kv">
                <dt>HTTP</dt>
                <dd>{{ defaultTestResult.status || '-' }}</dd>
              </div>
              <div class="proxy-egress__test-kv">
                <dt>延迟</dt>
                <dd>{{ defaultTestResult.latency_ms || 0 }}ms</dd>
              </div>
            </dl>
            <p v-if="defaultTestResult.error" class="proxy-egress__test-error">{{ defaultTestResult.error }}</p>
          </div>
          <div v-else class="proxy-egress__test-empty">
            <span class="proxy-egress__test-empty-bar" aria-hidden="true"></span>
            <span>尚未测试</span>
          </div>
        </FormSection>
      </div>
    </PagePanel>

    <PagePanel class="space-y-4">
      <PanelHeader title="代理组 / 多出口">
        <template #copy>
          <p class="mt-1 text-xs text-muted-foreground">
            一个代理组就是一组多出口节点；图片请求会从未满的节点里随机选择一个，请求结束前固定该出口，出口满了会等待，不会自动绕到直连。
          </p>
        </template>
        <template #actions>
          <Input
            :model-value="groupKeyword"
            block
            root-class="min-w-[12rem] md:w-80"
            placeholder="搜索代理组 / 节点 / 地址"
            @update:model-value="groupKeyword = $event.trim()"
          />
          <Button size="sm" variant="primary" @click="openCreateGroupModal">新建代理组</Button>
        </template>
      </PanelHeader>
      <PageLoadingState
        v-if="loading && groups.length === 0"
        title="正在加载代理组"
        description="读取代理组、节点和健康状态。"
      />
      <StateBlock v-else-if="filteredGroups.length === 0">
        <EmptyState plain title="暂无代理组" description="新建代理组后，可绑定账号组、账号或默认出口使用。" />
      </StateBlock>
      <ul v-else class="proxy-groups">
        <li
          v-for="group in filteredGroups"
          :key="group.id"
          class="proxy-group"
          :class="[
            isGroupExpanded(group.id) ? 'proxy-group--open' : '',
            group.enabled ? '' : 'proxy-group--disabled',
          ]"
        >
          <button
            type="button"
            class="proxy-group__summary"
            :aria-expanded="isGroupExpanded(group.id)"
            @click="toggleGroupExpanded(group.id)"
          >
            <CollapseCaret :open="isGroupExpanded(group.id)" />

            <span class="proxy-group__main">
              <span class="proxy-group__name-row">
                <span class="proxy-group__name" :title="group.name || group.id">{{ group.name || group.id }}</span>
                <StateBadge :tone="group.enabled ? 'success' : 'muted'" size="sm">
                  {{ group.enabled ? '启用' : '停用' }}
                </StateBadge>
              </span>
              <span class="proxy-group__facts">
                <span class="proxy-group__fact">{{ group.nodes.length }} 节点</span>
                <span class="proxy-group__fact proxy-group__fact--strategy">{{ groupStrategyLabel(group.strategy) }}</span>
                <span class="proxy-group__id" :title="group.id">ID:{{ group.id }}</span>
              </span>
              <span v-if="group.notes" class="proxy-group__notes" :title="group.notes">{{ group.notes }}</span>
            </span>

            <span class="proxy-group__health" v-if="group.nodes.length">
              <template v-for="tone in (['ok', 'fail', 'idle'] as const)" :key="tone">
                <span
                  v-if="groupHealthSummary(group)[tone]"
                  class="proxy-group__health-pill"
                  :class="`proxy-group__health-pill--${tone}`"
                  :title="tone === 'ok' ? '可用' : tone === 'fail' ? '失败' : '未测'"
                >
                  <span class="proxy-group__health-dot" aria-hidden="true"></span>{{ groupHealthSummary(group)[tone] }}
                </span>
              </template>
            </span>

            <span class="proxy-group__actions" @click.stop>
              <Button size="xs" variant="outline" root-class="w-14 justify-center" @click="openEditGroupModal(group)">
                编辑
              </Button>
              <FloatingActionMenu
                label="更多"
                :items="proxyGroupActionItems(group)"
                align="right"
                size="sm"
                trigger-class="h-7 justify-center px-2 text-[11px]"
                :trigger-width="64"
                @select="handleProxyGroupAction(group, $event)"
              />
            </span>
          </button>

          <div v-show="isGroupExpanded(group.id)" class="proxy-group__detail">
            <div class="proxy-group__detail-col proxy-group__detail-col--nodes">
              <p class="proxy-group__detail-label">节点</p>
              <div class="proxy-group__nodes">
                <ProxyNodeSummaryCard
                  v-for="node in group.nodes"
                  :key="node.id"
                  :node="node"
                />
              </div>
            </div>

            <div class="proxy-group__detail-col">
              <p class="proxy-group__detail-label">引用</p>
              <button
                type="button"
                class="proxy-group-ref"
                :title="`点击复制 ${proxyGroupReference(group)}`"
                @click="copyProxyGroupReference(group)"
              >
                <span class="proxy-group-ref__text">{{ proxyGroupReference(group) }}</span>
                <span class="proxy-group-ref__hint">复制</span>
              </button>
            </div>

            <div class="proxy-group__detail-col">
              <p class="proxy-group__detail-label">健康</p>
              <ul class="proxy-group-health">
                <li
                  v-for="node in group.nodes"
                  :key="`${group.id}-${node.id}-health`"
                  class="proxy-group-health__item"
                  :class="nodeHealthTone(group, node)"
                  :title="node.last_error || node.last_checked_at || '尚未测试'"
                >
                  <span class="proxy-group-health__name">{{ node.name || node.id }}</span>
                  <span class="proxy-group-health__value">{{ nodeHealthValue(group, node) }}</span>
                </li>
              </ul>
            </div>
          </div>
        </li>
      </ul>
    </PagePanel>

    <ModalShell :open="showGroupModal" max-width="56rem" :z-index="120">
      <ModalHeader
        :title="editingGroupId ? '编辑代理组' : '新建代理组'"
        :close-disabled="savingGroupId === FORM_TEST_KEY"
        :bordered="false"
        compact
        @close="closeGroupModal"
      />

      <ModalBody class="space-y-4">
        <FormSection title="基础信息" surface="plain">
              <div class="grid grid-cols-1 gap-2.5 md:grid-cols-[minmax(0,1fr)_16rem]">
                <label class="text-xs">
                  <span class="ui-field-label">代理组名称</span>
                  <Input
                    :model-value="groupForm.name"
                    block
                    placeholder="香港代理池"
                    @update:model-value="groupForm.name = $event.trim()"
                  />
                </label>
                <label class="text-xs">
                  <span class="ui-field-label">代理组 ID</span>
                  <Input
                    :model-value="groupForm.id"
                    block
                    root-class="font-mono"
                    :disabled="Boolean(editingGroupId)"
                    @update:model-value="groupForm.id = normalizeGroupId($event)"
                  />
                </label>
              </div>
              <div class="grid grid-cols-1 gap-2.5 md:grid-cols-[minmax(0,1fr)_auto]">
                <label class="text-xs">
                  <span class="ui-field-label">备注</span>
                  <Input
                    :model-value="groupForm.notes"
                    block
                    placeholder="可选"
                    @update:model-value="groupForm.notes = $event.trim()"
                  />
                </label>
                <div class="flex items-end">
                  <Checkbox v-model="groupForm.enabled">启用代理组</Checkbox>
                </div>
              </div>
        </FormSection>

              <div class="space-y-3">
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <p class="text-xs font-medium text-foreground">代理节点</p>
                  <Button size="xs" variant="outline" @click="addGroupNode">添加节点</Button>
                </div>
                <div class="space-y-3">
                  <FormSection
                    v-for="(node, index) in groupForm.nodes"
                    :key="`${node.id}-${index}`"
                    surface="muted"
                  >
                    <div class="grid grid-cols-1 gap-2 md:grid-cols-[10rem_minmax(0,1fr)_8rem_auto]">
                      <label class="text-xs">
                        <span class="ui-field-label">名称</span>
                        <Input
                          :model-value="node.name"
                          block
                          @update:model-value="node.name = $event.trim()"
                        />
                      </label>
                      <label class="text-xs">
                        <span class="ui-field-label">代理 URL</span>
                        <Input
                          :model-value="node.url"
                          block
                          root-class="font-mono"
                          placeholder="http://user:password@host:port"
                          @update:model-value="node.url = $event.trim()"
                        />
                      </label>
                      <label class="text-xs">
                        <span class="ui-field-label">图片并发</span>
                        <Input
                          :model-value="String(node.image_concurrency_limit ?? 0)"
                          block
                          type="number"
                          min="0"
                          step="1"
                          placeholder="默认 30，0 不限"
                          title="限制该节点同时处理的图片请求数；超出后等待同组节点空位，不会改走直连。0 表示不限制。"
                          @update:model-value="node.image_concurrency_limit = normalizeImageConcurrencyLimit($event)"
                        />
                      </label>
                      <div class="flex items-end gap-2">
                        <Checkbox v-model="node.enabled">启用</Checkbox>
                      </div>
                    </div>
                    <div class="mt-2 flex flex-wrap items-center justify-between gap-2">
                      <label class="min-w-[12rem] flex-1 text-xs">
                        <span class="ui-field-label">备注</span>
                        <Input
                          :model-value="node.notes || ''"
                          block
                          placeholder="可选"
                          @update:model-value="node.notes = $event.trim()"
                        />
                      </label>
                      <div class="flex items-end gap-2 pt-5">
                        <Button
                          size="xs"
                          variant="outline"
                          :disabled="!editingGroupId || !node.url || testingKey === `group:${editingGroupId}:${node.id}`"
                          @click="testProxyGroupNode({ id: editingGroupId, name: groupForm.name }, node)"
                        >
                          {{ testingKey === `group:${editingGroupId}:${node.id}` ? '检测中...' : '检测' }}
                        </Button>
                        <Button size="xs" variant="outline" root-class="text-rose-600" @click="removeGroupNode(index)">
                          删除
                        </Button>
                      </div>
                    </div>
                  </FormSection>
                </div>
              </div>
      </ModalBody>

      <ModalFooter :bordered="false">
        <Button size="xs" variant="outline" root-class="min-w-14 justify-center" :disabled="savingGroupId === FORM_TEST_KEY" @click="closeGroupModal">
          取消
        </Button>
        <Button size="xs" variant="primary" root-class="min-w-14 justify-center" :disabled="savingGroupId === FORM_TEST_KEY" @click="saveProxyGroup">
          {{ savingGroupId === FORM_TEST_KEY ? '保存中...' : editingGroupId ? '更新' : '保存' }}
        </Button>
      </ModalFooter>
    </ModalShell>

  </div>
</template>

<script setup lang="ts">
import { computed, onActivated, onMounted, reactive, ref } from 'vue'
import { Button, Checkbox, EmptyState, Input } from 'nanocat-ui'
import type { ActionMenuItem } from 'nanocat-ui'
import { prepareSettingsForEdit, settingsApi } from '@/api/settings'
import { parseProxyReference, proxyApi, serializeProxyReference, type ProxyGroup, type ProxyNode, type ProxyTestResult } from '@/api/proxy'
import ActionRow from '@/components/ai/ActionRow.vue'
import CollapseCaret from '@/components/ai/CollapseCaret.vue'
import FloatingActionMenu from '@/components/ai/FloatingActionMenu.vue'
import FormSection from '@/components/ai/FormSection.vue'
import ModalBody from '@/components/ai/ModalBody.vue'
import ModalFooter from '@/components/ai/ModalFooter.vue'
import ModalHeader from '@/components/ai/ModalHeader.vue'
import ModalShell from '@/components/ai/ModalShell.vue'
import PageLoadingState from '@/components/ai/PageLoadingState.vue'
import PagePanel from '@/components/ai/PagePanel.vue'
import PanelHeader from '@/components/ai/PanelHeader.vue'
import ProxyNodeSummaryCard from '@/components/ai/ProxyNodeSummaryCard.vue'
import StateBadge from '@/components/ai/StateBadge.vue'
import StateBlock from '@/components/ai/StateBlock.vue'
import { actionMenuGroups } from '@/components/ai/menuItems'
import GroupedSelectMenu from '@/components/ui/GroupedSelectMenu.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useSettingsStore } from '@/stores/settings'
import { useToast } from '@/composables/useToast'
import type { Settings } from '@/types/api'

type DefaultProxyMode = 'direct' | 'group' | 'custom'
type FallbackProxyMode = 'off' | DefaultProxyMode

type ProxyGroupForm = {
  id: string
  name: string
  enabled: boolean
  notes: string
  nodes: ProxyNode[]
}

const DEFAULT_TEST_KEY = '__default__'
const FORM_TEST_KEY = '__form__'
const DEFAULT_PROXY_NODE_IMAGE_CONCURRENCY = 30

const settingsStore = useSettingsStore()
const toast = useToast()
const confirmDialog = useConfirmDialog()

const loading = ref(false)
const savingDefaultProxy = ref(false)
const savingGroupId = ref('')
const deletingGroupId = ref('')
const testingKey = ref('')
const groupKeyword = ref('')
const showGroupModal = ref(false)
const editingGroupId = ref('')
const expandedGroupIds = ref<Set<string>>(new Set())
const defaultProxyMode = ref<DefaultProxyMode>('direct')
const selectedDefaultProxyGroupId = ref('')
const defaultCustomProxyInput = ref('')
const fallbackProxyMode = ref<FallbackProxyMode>('off')
const selectedFallbackProxyGroupId = ref('')
const fallbackCustomProxyInput = ref('')
const currentSettings = ref<Settings | null>(null)
const defaultTestResult = ref<ProxyTestResult | null>(null)
const groups = ref<ProxyGroup[]>([])
const testResults = reactive<Record<string, ProxyTestResult>>({})
const groupForm = reactive<ProxyGroupForm>(createDefaultGroupForm())
let hasActivatedOnce = false

const defaultProxyModeOptions = [
  { label: '直连', value: 'direct' },
  { label: '代理组', value: 'group' },
  { label: '自定义代理', value: 'custom' },
] as const

const fallbackProxyModeOptions = [
  { label: '关闭', value: 'off' },
  { label: '直连', value: 'direct' },
  { label: '代理组', value: 'group' },
  { label: '自定义代理', value: 'custom' },
] as const

const filteredGroups = computed(() => {
  const query = groupKeyword.value.trim().toLowerCase()
  const rows = [...groups.value].sort((left, right) => (
    (left.name || left.id).localeCompare(right.name || right.id, 'zh-Hans-CN')
  ))
  if (!query) return rows
  return rows.filter((item) => [
    item.id,
    item.name,
    item.notes,
    ...item.nodes.flatMap((node) => [node.id, node.name, node.url, node.notes]),
  ].some((value) => String(value || '').toLowerCase().includes(query)))
})

const defaultProxyGroupOptions = computed(() => {
  const rows = groups.value.map((group) => ({
    label: `${group.enabled === false ? '停用 · ' : ''}${group.name || group.id}${Array.isArray(group.nodes) ? ` · ${group.nodes.length} 个节点` : ''}`,
    value: group.id,
  }))
  const selectedId = selectedDefaultProxyGroupId.value
  if (selectedId && !rows.some((item) => item.value === selectedId)) {
    rows.unshift({ label: `未知代理组 · ${selectedId}`, value: selectedId })
  }
  return [
    { label: '选择代理组', value: '' },
    ...rows,
  ]
})

const defaultProxyPreview = computed(() => {
  if (defaultProxyMode.value === 'direct') return '直连'
  if (defaultProxyMode.value === 'group') {
    const group = groups.value.find((item) => item.id === selectedDefaultProxyGroupId.value)
    return selectedDefaultProxyGroupId.value ? `代理组：${group?.name || selectedDefaultProxyGroupId.value}` : '代理组：未选择'
  }
  return defaultCustomProxyInput.value || '自定义代理：未填写'
})

const fallbackProxyPreview = computed(() => {
  if (fallbackProxyMode.value === 'off') return '关闭'
  if (fallbackProxyMode.value === 'direct') return '直连'
  if (fallbackProxyMode.value === 'group') {
    const group = groups.value.find((item) => item.id === selectedFallbackProxyGroupId.value)
    return selectedFallbackProxyGroupId.value ? `代理组：${group?.name || selectedFallbackProxyGroupId.value}` : '代理组：未选择'
  }
  return fallbackCustomProxyInput.value || '自定义代理：未填写'
})

const canTestDefaultProxy = computed(() => {
  if (defaultProxyMode.value === 'group') return Boolean(selectedDefaultProxyGroupId.value)
  if (defaultProxyMode.value === 'custom') return Boolean(defaultCustomProxyInput.value.trim())
  return false
})

const isDefaultProxyDirty = computed(() => {
  const settings = currentSettings.value
  if (!settings) return false
  return (
    normalizeDefaultProxyForCompare(defaultProxyValue()) !== normalizeDefaultProxyForCompare(defaultProxyFromSettings(settings))
    || normalizeDefaultProxyForCompare(fallbackProxyValue()) !== normalizeDefaultProxyForCompare(fallbackProxyFromSettings(settings))
  )
})

function createDefaultNode(index = 0): ProxyNode {
  return {
    id: createGeneratedId('node'),
    name: `出口 ${index + 1}`,
    url: '',
    enabled: true,
    image_concurrency_limit: DEFAULT_PROXY_NODE_IMAGE_CONCURRENCY,
    notes: '',
  }
}

function createDefaultGroupForm(): ProxyGroupForm {
  return {
    id: '',
    name: '',
    enabled: true,
    notes: '',
    nodes: [createDefaultNode(0)],
  }
}

function normalizeReferenceId(value: string) {
  return value
    .trim()
    .replace(/[^A-Za-z0-9._-]+/g, '-')
    .replace(/^[-._]+|[-._]+$/g, '')
    .slice(0, 64)
}

function normalizeGroupId(value: string) {
  return normalizeReferenceId(value)
}

function proxyGroupReference(group: Pick<ProxyGroup, 'id'>) {
  return serializeProxyReference('group', group.id)
}

async function copyText(value: string, message = '已复制') {
  const text = String(value || '').trim()
  if (!text) return
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const input = document.createElement('textarea')
      input.value = text
      input.setAttribute('readonly', 'readonly')
      input.style.position = 'fixed'
      input.style.opacity = '0'
      document.body.appendChild(input)
      input.select()
      document.execCommand('copy')
      document.body.removeChild(input)
    }
    toast.success(message)
  } catch {
    toast.error('复制失败')
  }
}

function copyProxyGroupReference(group: Pick<ProxyGroup, 'id'>) {
  void copyText(proxyGroupReference(group), '代理组引用已复制')
}

function createGeneratedId(prefix: string) {
  let suffix = ''
  try {
    suffix = globalThis.crypto?.randomUUID?.().replace(/-/g, '').slice(0, 10) || ''
  } catch {
    suffix = ''
  }
  if (!suffix) {
    suffix = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`.slice(0, 10)
  }
  return `${prefix}-${suffix}`
}

function normalizeImageConcurrencyLimit(value: unknown) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 0
  return Math.max(0, Math.min(10000, Math.floor(parsed)))
}

function normalizeGroupNode(item: ProxyNode, index: number): ProxyNode {
  const id = normalizeGroupId(item.id || '') || createGeneratedId('node')
  return {
    id,
    name: String(item.name || `出口 ${index + 1}`).trim(),
    url: String(item.url || '').trim(),
    enabled: item.enabled !== false,
    image_concurrency_limit: normalizeImageConcurrencyLimit(item.image_concurrency_limit ?? DEFAULT_PROXY_NODE_IMAGE_CONCURRENCY),
    last_latency_ms: Number(item.last_latency_ms || 0),
    fail_count: Number(item.fail_count || 0),
    last_error: String(item.last_error || '').trim(),
    last_checked_at: String(item.last_checked_at || '').trim(),
    last_error_at: String(item.last_error_at || '').trim(),
    cooldown_until: String(item.cooldown_until || '').trim(),
    notes: String(item.notes || '').trim(),
  }
}

function normalizeGroup(item: ProxyGroup): ProxyGroup {
  const id = normalizeGroupId(item.id || item.name || '')
  return {
    id,
    name: String(item.name || item.id || '').trim(),
    strategy: item.strategy || 'request_random',
    rotation_interval_minutes: 0,
    enabled: item.enabled !== false,
    notes: String(item.notes || '').trim(),
    nodes: Array.isArray(item.nodes)
      ? item.nodes.map(normalizeGroupNode).filter((node) => node.id)
      : [],
  }
}

function updateGroups(items: ProxyGroup[]) {
  groups.value = Array.isArray(items) ? items.map(normalizeGroup).filter((item) => item.id) : []
}

function proxyActionError(action: string, error: unknown) {
  const message = error instanceof Error ? error.message : String(error || '').trim()
  return message ? `${action}：${message}` : action
}

function defaultProxyFromSettings(settings: Settings) {
  return String(settings.basic?.proxy || settings.proxy || '').trim()
}

function fallbackProxyFromSettings(settings: Settings) {
  return String(settings.fallback_proxy || '').trim()
}

function defaultProxyValue() {
  if (defaultProxyMode.value === 'direct') return serializeProxyReference('direct')
  if (defaultProxyMode.value === 'group') return serializeProxyReference('group', selectedDefaultProxyGroupId.value)
  return serializeProxyReference('custom', defaultCustomProxyInput.value)
}

function fallbackProxyValue() {
  if (fallbackProxyMode.value === 'off') return ''
  if (fallbackProxyMode.value === 'direct') return serializeProxyReference('direct')
  if (fallbackProxyMode.value === 'group') return serializeProxyReference('group', selectedFallbackProxyGroupId.value)
  return serializeProxyReference('custom', fallbackCustomProxyInput.value)
}

function normalizeDefaultProxyForCompare(value: unknown) {
  const reference = parseProxyReference(value)
  if (reference.mode === 'global' || reference.mode === 'direct') return 'direct'
  if (reference.mode === 'group') return serializeProxyReference('group', reference.value)
  if (reference.mode === 'profile') return String(value || '').trim()
  return reference.value.trim()
}

function syncDefaultProxyControlsFromValue(value: unknown) {
  const reference = parseProxyReference(value)
  selectedDefaultProxyGroupId.value = ''
  defaultCustomProxyInput.value = ''
  defaultTestResult.value = null
  if (reference.mode === 'group') {
    defaultProxyMode.value = 'group'
    selectedDefaultProxyGroupId.value = reference.value
    return
  }
  if (reference.mode === 'custom' || reference.mode === 'profile') {
    defaultProxyMode.value = 'custom'
    defaultCustomProxyInput.value = reference.mode === 'profile' ? String(value || '').trim() : reference.value
    return
  }
  defaultProxyMode.value = 'direct'
}

function syncFallbackProxyControlsFromValue(value: unknown) {
  const reference = parseProxyReference(value)
  selectedFallbackProxyGroupId.value = ''
  fallbackCustomProxyInput.value = ''
  if (reference.mode === 'group') {
    fallbackProxyMode.value = 'group'
    selectedFallbackProxyGroupId.value = reference.value
    return
  }
  if (reference.mode === 'direct') {
    fallbackProxyMode.value = 'direct'
    return
  }
  if (reference.mode === 'custom' || reference.mode === 'profile') {
    fallbackProxyMode.value = 'custom'
    fallbackCustomProxyInput.value = reference.mode === 'profile' ? String(value || '').trim() : reference.value
    return
  }
  fallbackProxyMode.value = 'off'
}

function setDefaultProxyMode(mode: string | string[]) {
  const value = Array.isArray(mode) ? mode[0] : mode
  defaultProxyMode.value = ['direct', 'group', 'custom'].includes(value)
    ? value as DefaultProxyMode
    : 'direct'
  defaultTestResult.value = null
}

function setFallbackProxyMode(mode: string | string[]) {
  const value = Array.isArray(mode) ? mode[0] : mode
  fallbackProxyMode.value = ['off', 'direct', 'group', 'custom'].includes(value)
    ? value as FallbackProxyMode
    : 'off'
}

function selectDefaultProxyGroup(groupId: string | string[]) {
  const value = Array.isArray(groupId) ? groupId[0] : groupId
  selectedDefaultProxyGroupId.value = String(value || '').trim()
  defaultProxyMode.value = 'group'
  defaultTestResult.value = null
}

function selectFallbackProxyGroup(groupId: string | string[]) {
  const value = Array.isArray(groupId) ? groupId[0] : groupId
  selectedFallbackProxyGroupId.value = String(value || '').trim()
  fallbackProxyMode.value = 'group'
}

function setDefaultCustomProxyInput(value: string) {
  defaultCustomProxyInput.value = String(value || '').trim()
  defaultProxyMode.value = 'custom'
  defaultTestResult.value = null
}

function setFallbackCustomProxyInput(value: string) {
  fallbackCustomProxyInput.value = String(value || '').trim()
  fallbackProxyMode.value = 'custom'
}

async function loadData() {
  loading.value = true
  try {
    const [settings, groupResponse] = await Promise.all([
      settingsApi.get(),
      proxyApi.listGroups(),
    ])
    currentSettings.value = prepareSettingsForEdit(settings)
    settingsStore.$patch({ settings })
    updateGroups(groupResponse.groups || [])
    syncDefaultProxyControlsFromValue(defaultProxyFromSettings(settings))
    syncFallbackProxyControlsFromValue(fallbackProxyFromSettings(settings))
  } catch (error: any) {
    toast.error(error.message || '加载代理配置失败')
  } finally {
    loading.value = false
  }
}

async function saveDefaultProxy() {
  if (!currentSettings.value) {
    toast.warning('配置尚未加载完成')
    return
  }
  if (defaultProxyMode.value === 'group' && !selectedDefaultProxyGroupId.value) {
    toast.warning('请选择默认出口代理组')
    return
  }
  if (defaultProxyMode.value === 'custom' && !defaultCustomProxyInput.value.trim()) {
    toast.warning('请填写自定义代理 URL')
    return
  }
  if (fallbackProxyMode.value === 'group' && !selectedFallbackProxyGroupId.value) {
    toast.warning('请选择备用出口代理组')
    return
  }
  if (fallbackProxyMode.value === 'custom' && !fallbackCustomProxyInput.value.trim()) {
    toast.warning('请填写备用代理 URL')
    return
  }
  const confirmed = await confirmDialog.ask({
    title: '确认保存出口配置',
    message: '即将保存默认出口和备用出口配置。备用出口只在图片请求早期连接失败时重试一次，是否继续？',
    confirmText: '保存',
    cancelText: '取消',
  })
  if (!confirmed) return

  savingDefaultProxy.value = true
  try {
    const next = prepareSettingsForEdit(currentSettings.value)
    next.proxy = defaultProxyValue()
    next.fallback_proxy = fallbackProxyValue()
    const response = await settingsStore.updateSettingsPatch({
      proxy: next.proxy,
      fallback_proxy: next.fallback_proxy,
    })
    currentSettings.value = prepareSettingsForEdit(response.config || next)
    syncDefaultProxyControlsFromValue(defaultProxyFromSettings(currentSettings.value))
    syncFallbackProxyControlsFromValue(fallbackProxyFromSettings(currentSettings.value))
    toast.success('出口配置已保存')
  } catch (error: any) {
    toast.error(proxyActionError('保存出口配置失败', error))
  } finally {
    savingDefaultProxy.value = false
  }
}

function setDefaultProxyDirect() {
  defaultProxyMode.value = 'direct'
  selectedDefaultProxyGroupId.value = ''
  defaultCustomProxyInput.value = ''
  defaultTestResult.value = null
}

async function testDefaultProxy() {
  if (defaultProxyMode.value === 'direct') {
    toast.info('直连模式无需测试出口')
    return
  }
  if (defaultProxyMode.value === 'group' && !selectedDefaultProxyGroupId.value) {
    toast.warning('请选择默认出口代理组')
    return
  }
  if (defaultProxyMode.value === 'custom' && !defaultCustomProxyInput.value.trim()) {
    toast.warning('请先填写自定义代理 URL')
    return
  }
  const confirmed = await confirmDialog.ask({
    title: '确认测试默认出口',
    message: '即将使用当前默认出口发起外部网络测试请求。请确认当前允许测试该出口连接。',
    confirmText: '开始测试',
    cancelText: '取消',
  })
  if (!confirmed) return

  testingKey.value = DEFAULT_TEST_KEY
  try {
    if (defaultProxyMode.value === 'group') {
      const response = await proxyApi.testGroup({ id: selectedDefaultProxyGroupId.value })
      if (response.groups) updateGroups(response.groups)
      const results = response.results || []
      const failed = results.filter((item) => !item.result.ok)
      const firstResult = results[0]?.result
      const maxLatency = results.reduce((max, item) => Math.max(max, Number(item.result.latency_ms || 0)), 0)
      defaultTestResult.value = {
        ok: results.length > 0 && failed.length === 0,
        status: firstResult?.status || 0,
        latency_ms: maxLatency,
        error: failed.length ? `代理组检测完成，失败 ${failed.length} 个节点` : null,
      }
      if (defaultTestResult.value.ok) toast.success(`默认出口代理组可用，共 ${results.length} 个节点`)
      else toast.warning(defaultTestResult.value.error || '默认出口代理组测试失败')
      return
    }
    const response = await proxyApi.test(defaultCustomProxyInput.value.trim())
    defaultTestResult.value = response.result
    if (response.result.ok) toast.success(`默认出口可用，耗时 ${response.result.latency_ms}ms`)
    else toast.warning(response.result.error || '默认出口测试失败')
  } catch (error: any) {
    defaultTestResult.value = {
      ok: false,
      status: 0,
      latency_ms: 0,
      error: error.message || '默认出口测试失败',
    }
    toast.error(error.message || '默认出口测试失败')
  } finally {
    testingKey.value = ''
  }
}

function resetGroupForm() {
  editingGroupId.value = ''
  Object.assign(groupForm, createDefaultGroupForm())
}

function openCreateGroupModal() {
  resetGroupForm()
  showGroupModal.value = true
}

function openEditGroupModal(group: ProxyGroup) {
  editingGroupId.value = group.id
  Object.assign(groupForm, {
    id: group.id,
    name: group.name || group.id,
    enabled: group.enabled !== false,
    notes: group.notes || '',
    nodes: group.nodes.length ? group.nodes.map((node, index) => normalizeGroupNode(node, index)) : [createDefaultNode(0)],
  })
  showGroupModal.value = true
}

function closeGroupModal() {
  if (savingGroupId.value === FORM_TEST_KEY) return
  showGroupModal.value = false
  resetGroupForm()
}

function addGroupNode() {
  groupForm.nodes.push(createDefaultNode(groupForm.nodes.length))
}

function removeGroupNode(index: number) {
  if (groupForm.nodes.length <= 1) {
    groupForm.nodes = [createDefaultNode(0)]
    return
  }
  groupForm.nodes.splice(index, 1)
}

async function saveProxyGroup() {
  const groupName = groupForm.name.trim()
  if (!groupName) {
    toast.warning('请填写代理组名称')
    return
  }
  const id = normalizeGroupId(editingGroupId.value || groupForm.id) || createGeneratedId('pg')
  const nodes = groupForm.nodes
    .map((node, index) => normalizeGroupNode(node, index))
    .filter((node) => node.url)
  if (!nodes.length) {
    toast.warning('请至少填写一个代理节点地址')
    return
  }

  savingGroupId.value = FORM_TEST_KEY
  try {
    const wasEditing = Boolean(editingGroupId.value)
    const response = await proxyApi.saveGroup({
      id,
      name: groupName,
      strategy: 'request_random',
      enabled: groupForm.enabled,
      notes: groupForm.notes.trim(),
      nodes,
      create_only: !editingGroupId.value,
    })
    updateGroups(response.groups || [])
    savingGroupId.value = ''
    closeGroupModal()
    toast.success(wasEditing ? '代理组已更新' : '代理组已创建')
  } catch (error: any) {
    toast.error(proxyActionError('保存代理组失败', error))
  } finally {
    savingGroupId.value = ''
  }
}

async function toggleProxyGroup(group: ProxyGroup) {
  const nextEnabled = !group.enabled
  const confirmed = await confirmDialog.ask({
    title: nextEnabled ? '确认启用代理组' : '确认停用代理组',
    message: `即将${nextEnabled ? '启用' : '停用'}代理组 ${group.name || group.id}。绑定到该组的账号组会受到影响，是否继续？`,
    confirmText: nextEnabled ? '启用' : '停用',
    cancelText: '取消',
  })
  if (!confirmed) return

  savingGroupId.value = group.id
  try {
    const response = await proxyApi.saveGroup({
      ...group,
      enabled: nextEnabled,
    })
    updateGroups(response.groups || [])
    toast.success(`代理组 ${group.name || group.id} 已${group.enabled ? '停用' : '启用'}`)
  } catch (error: any) {
    toast.error(proxyActionError('切换代理组失败', error))
  } finally {
    savingGroupId.value = ''
  }
}

async function deleteProxyGroup(group: ProxyGroup) {
  const confirmed = await confirmDialog.ask({
    title: '删除代理组',
    message: `确认删除代理组 ${group.name || group.id}？账号组里已有的绑定不会自动清空。`,
    confirmText: '确认删除',
    cancelText: '取消',
  })
  if (!confirmed) return

  deletingGroupId.value = group.id
  try {
    const response = await proxyApi.deleteGroup(group.id)
    updateGroups(response.groups || [])
    toast.success('代理组已删除')
  } catch (error: any) {
    toast.error(proxyActionError('删除代理组失败', error))
  } finally {
    deletingGroupId.value = ''
  }
}

function proxyGroupActionItems(group: ProxyGroup): ActionMenuItem[] {
  const allKey = `group:${group.id}:all`
  return actionMenuGroups(
    [
      {
        key: 'test-all',
        label: testingKey.value === allKey ? '检测中...' : '检测全部节点',
        disabled: testingKey.value === allKey || group.nodes.length === 0,
      },
    ],
    [
      {
        key: 'toggle-enabled',
        label: savingGroupId.value === group.id
          ? '处理中...'
          : group.enabled ? '停用代理组' : '启用代理组',
        disabled: savingGroupId.value === group.id,
      },
    ],
    [
      {
        key: 'delete',
        label: deletingGroupId.value === group.id ? '删除中...' : '删除代理组',
        danger: true,
        disabled: deletingGroupId.value === group.id,
      },
    ],
  )
}

function handleProxyGroupAction(group: ProxyGroup, action: string) {
  if (action === 'test-all') void testProxyGroupAll(group)
  if (action === 'toggle-enabled') void toggleProxyGroup(group)
  if (action === 'delete') void deleteProxyGroup(group)
}

async function testProxyGroupNode(group: Pick<ProxyGroup, 'id' | 'name'>, node: ProxyNode) {
  const confirmed = await confirmDialog.ask({
    title: '确认测试代理节点',
    message: `即将使用代理组 ${group.name || group.id} 的节点 ${node.name || node.id} 发起外部网络测试请求。请确认当前允许测试该代理连接。`,
    confirmText: '开始测试',
    cancelText: '取消',
  })
  if (!confirmed) return

  const key = `group:${group.id}:${node.id}`
  testingKey.value = key
  try {
    const response = await proxyApi.testGroup({ id: group.id, node_id: node.id })
    if (response.groups) updateGroups(response.groups)
    const result = response.result || response.results?.[0]?.result
    if (result) testResults[key] = result
    if (result?.ok) toast.success(`节点检测通过，耗时 ${result.latency_ms}ms`)
    else toast.warning(result?.error || '节点检测失败')
  } catch (error: any) {
    testResults[key] = {
      ok: false,
      status: 0,
      latency_ms: 0,
      error: error.message || '节点检测失败',
    }
    toast.error(error.message || '节点检测失败')
  } finally {
    testingKey.value = ''
  }
}

async function testProxyGroupAll(group: ProxyGroup) {
  const confirmed = await confirmDialog.ask({
    title: '确认测试代理组',
    message: `即将测试代理组 ${group.name || group.id} 内的 ${group.nodes.length} 个节点。每个节点都会发起外部网络测试请求，是否继续？`,
    confirmText: '开始测试',
    cancelText: '取消',
  })
  if (!confirmed) return

  const key = `group:${group.id}:all`
  testingKey.value = key
  try {
    const response = await proxyApi.testGroup({ id: group.id })
    if (response.groups) updateGroups(response.groups)
    const results = response.results || []
    for (const item of results) {
      if (item.node_id && item.result) {
        testResults[`group:${group.id}:${item.node_id}`] = item.result
      }
    }
    const failed = results.filter((item) => !item.result.ok)
    if (failed.length) toast.warning(`代理组检测完成，失败 ${failed.length} 个节点`)
    else toast.success(`代理组检测通过，共 ${results.length} 个节点`)
  } catch (error: any) {
    toast.error(error.message || '代理组检测失败')
  } finally {
    testingKey.value = ''
  }
}

function groupStrategyLabel(strategy: ProxyGroup['strategy']) {
  if (strategy === 'round_robin') return '轮询'
  if (strategy === 'time_window') return '时间窗'
  return '随机'
}

function isGroupExpanded(id: string) {
  return expandedGroupIds.value.has(id)
}

function toggleGroupExpanded(id: string) {
  const next = new Set(expandedGroupIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedGroupIds.value = next
}

/** 概要行用的健康统计：可用 / 失败 / 未测 */
function groupHealthSummary(group: ProxyGroup) {
  let ok = 0
  let fail = 0
  let idle = 0
  for (const node of group.nodes) {
    const tone = nodeHealthTone(group, node)
    if (tone === 'is-ok') ok += 1
    else if (tone === 'is-fail') fail += 1
    else idle += 1
  }
  return { ok, fail, idle }
}

function nodeHealthValue(group: ProxyGroup, node: ProxyNode) {
  if (testingKey.value === `group:${group.id}:all` || testingKey.value === `group:${group.id}:${node.id}`) return '检测中...'
  const result = testResults[`group:${group.id}:${node.id}`]
  if (result?.ok) return `HTTP ${result.status || '-'} ${result.latency_ms || 0}ms`
  if (result && !result.ok) return result.error || '检测失败'
  if (node.last_error) return node.last_error
  if (node.last_checked_at) return `${node.last_latency_ms || 0}ms`
  return '尚未测试'
}

function nodeHealthTone(group: ProxyGroup, node: ProxyNode) {
  if (testingKey.value === `group:${group.id}:all` || testingKey.value === `group:${group.id}:${node.id}`) return 'is-testing'
  const result = testResults[`group:${group.id}:${node.id}`]
  if (result) return result.ok ? 'is-ok' : 'is-fail'
  if (node.last_error) return 'is-fail'
  if (node.last_checked_at) return 'is-ok'
  return 'is-idle'
}

onMounted(() => {
  void loadData()
})

onActivated(() => {
  if (!hasActivatedOnce) {
    hasActivatedOnce = true
    return
  }
  if (showGroupModal.value || savingDefaultProxy.value || savingGroupId.value || testingKey.value || isDefaultProxyDirty.value) return
  void loadData()
})
</script>

<style scoped>
/* ============ 出口配置区（上） ============ */
.proxy-egress {
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(0, 1fr) 300px;
}
@media (max-width: 960px) {
  .proxy-egress {
    grid-template-columns: 1fr;
  }
}

.proxy-egress__row {
  display: grid;
  gap: 10px;
  grid-template-columns: minmax(0, 220px) minmax(0, 1fr);
  align-items: end;
}
@media (max-width: 720px) {
  .proxy-egress__row {
    grid-template-columns: 1fr;
    align-items: stretch;
  }
}

.proxy-egress__hint {
  display: flex;
  min-height: 2.5rem;
  align-items: center;
  border: 1.5px dashed color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 30%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--bauhaus-card, #fff) 55%, transparent);
  padding: 0 12px;
  color: hsl(var(--muted-foreground));
  font-size: 12px;
}

.proxy-egress__current {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-top: 12px;
  font-size: 12px;
  min-width: 0;
}
.proxy-egress__current-label {
  flex: 0 0 auto;
  color: hsl(var(--muted-foreground));
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.proxy-egress__current-value {
  min-width: 0;
  overflow: hidden;
  color: var(--bauhaus-blue, #2d5da1);
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.proxy-egress__divider {
  margin: 16px 0;
  border-top: 2px solid color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 14%, transparent);
}

.proxy-egress__note {
  margin-top: 8px;
  color: hsl(var(--muted-foreground));
  font-size: 11px;
  line-height: 1.5;
}

/* 测试结果卡 */
.proxy-egress__test-title {
  color: hsl(var(--muted-foreground));
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.proxy-egress__test-body {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.proxy-egress__test-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 1.5px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  padding: 6px 12px;
  box-shadow: var(--shadow-hard-sm, 2px 2px 0 0 var(--bauhaus-ink, #2d2d2d));
  align-self: flex-start;
}
.proxy-egress__test-status.is-ok {
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 10%, var(--bauhaus-card, #fff));
}
.proxy-egress__test-status.is-fail {
  background: color-mix(in srgb, var(--bauhaus-red, #ff4d4d) 10%, var(--bauhaus-card, #fff));
}
.proxy-egress__test-dot {
  width: 9px;
  height: 9px;
  border: 1.5px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: 50%;
  background: var(--bauhaus-blue, #2d5da1);
}
.proxy-egress__test-status.is-fail .proxy-egress__test-dot {
  background: var(--bauhaus-red, #ff4d4d);
}
.proxy-egress__test-word {
  font-size: 13px;
  font-weight: 700;
}
.proxy-egress__test-status.is-ok .proxy-egress__test-word {
  color: var(--bauhaus-blue, #2d5da1);
}
.proxy-egress__test-status.is-fail .proxy-egress__test-word {
  color: var(--bauhaus-red, #ff4d4d);
}
.proxy-egress__test-meta {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin: 0;
}
.proxy-egress__test-kv {
  display: flex;
  flex-direction: column;
  gap: 2px;
  border: 1px solid color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 18%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--bauhaus-card, #fff) 70%, transparent);
  padding: 8px 10px;
}
.proxy-egress__test-kv dt {
  color: hsl(var(--muted-foreground));
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.proxy-egress__test-kv dd {
  margin: 0;
  color: var(--bauhaus-ink, #2d2d2d);
  font-size: 15px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.proxy-egress__test-error {
  overflow-wrap: anywhere;
  border-left: 3px solid var(--bauhaus-red, #ff4d4d);
  padding-left: 8px;
  color: var(--bauhaus-red, #ff4d4d);
  font-size: 11px;
  line-height: 1.5;
}
.proxy-egress__test-empty {
  margin-top: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: hsl(var(--muted-foreground));
  font-size: 12px;
}
.proxy-egress__test-empty-bar {
  width: 14px;
  height: 3px;
  background: color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 30%, transparent);
}

/* ============ 代理组折叠列表（下） ============ */
.proxy-groups {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.proxy-group {
  overflow: hidden;
  border: 1.5px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  background: hsl(var(--card));
  box-shadow: var(--shadow-hard-sm, 2px 2px 0 0 var(--bauhaus-ink, #2d2d2d));
}
.proxy-group--disabled {
  background: color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 4%, hsl(var(--card)));
}

/* 概要行（整行可点） */
.proxy-group__summary {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 14px;
  width: 100%;
  padding: 12px 14px;
  background: transparent;
  border: 0;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease;
}
.proxy-group__summary:hover {
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 4%, transparent);
}
.proxy-group__summary:focus-visible {
  outline: 2px solid var(--bauhaus-blue, #2d5da1);
  outline-offset: -2px;
}

.proxy-group__main {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 5px;
}
.proxy-group__name-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.proxy-group__name {
  overflow: hidden;
  color: var(--bauhaus-ink, #2d2d2d);
  font-size: 14px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.proxy-group--disabled .proxy-group__name {
  color: hsl(var(--muted-foreground));
}
.proxy-group__facts {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  min-width: 0;
}
.proxy-group__fact {
  border: 1px solid color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 30%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 7%, transparent);
  padding: 1px 7px;
  color: var(--bauhaus-blue, #2d5da1);
  font-size: 10px;
  font-weight: 600;
  line-height: 1.6;
}
.proxy-group__fact--strategy {
  background: color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 6%, transparent);
  color: hsl(var(--muted-foreground));
}
.proxy-group__id {
  overflow: hidden;
  color: hsl(var(--muted-foreground));
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 10.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.proxy-group__notes {
  overflow: hidden;
  color: hsl(var(--muted-foreground));
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 概要行右侧健康胶囊 */
.proxy-group__health {
  display: flex;
  flex: 0 0 auto;
  gap: 6px;
}
.proxy-group__health-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1.5px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.proxy-group__health-dot {
  width: 7px;
  height: 7px;
  border: 1.5px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: 50%;
}
.proxy-group__health-pill--ok { color: var(--bauhaus-blue, #2d5da1); }
.proxy-group__health-pill--ok .proxy-group__health-dot { background: var(--bauhaus-blue, #2d5da1); }
.proxy-group__health-pill--fail { color: var(--bauhaus-red, #ff4d4d); }
.proxy-group__health-pill--fail .proxy-group__health-dot { background: var(--bauhaus-red, #ff4d4d); }
.proxy-group__health-pill--idle { color: hsl(var(--muted-foreground)); }
.proxy-group__health-pill--idle .proxy-group__health-dot {
  background: color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 30%, transparent);
}

.proxy-group__actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 8px;
}

/* 展开详情 */
.proxy-group__detail {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) minmax(0, 1fr);
  gap: 18px;
  border-top: 1.5px solid color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 16%, transparent);
  background: color-mix(in srgb, var(--bauhaus-paper-2, #f5f0e6) 55%, transparent);
  padding: 14px 16px 16px;
}
@media (max-width: 900px) {
  .proxy-group__detail {
    grid-template-columns: 1fr;
  }
}
.proxy-group__detail-label {
  margin: 0 0 8px;
  color: hsl(var(--muted-foreground));
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}
.proxy-group__nodes {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

@media (max-width: 720px) {
  .proxy-group__summary {
    grid-template-columns: auto minmax(0, 1fr);
    row-gap: 8px;
  }
  .proxy-group__health,
  .proxy-group__actions {
    grid-column: 2;
  }
}

/* 引用按钮 */
.proxy-group-ref {
  display: inline-flex;
  max-width: 100%;
  align-items: center;
  gap: 6px;
  border: 1.5px solid color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 28%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--bauhaus-card, #fff) 70%, transparent);
  padding: 4px 8px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  color: hsl(var(--muted-foreground));
  cursor: pointer;
  transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;
}
.proxy-group-ref:hover {
  border-color: var(--bauhaus-blue, #2d5da1);
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 7%, transparent);
  color: var(--bauhaus-blue, #2d5da1);
}
.proxy-group-ref__text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.proxy-group-ref__hint {
  flex: 0 0 auto;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  opacity: 0;
  transition: opacity 0.15s ease;
}
.proxy-group-ref:hover .proxy-group-ref__hint {
  opacity: 1;
}

/* 健康列 */
.proxy-group-health {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.proxy-group-health__item {
  display: flex;
  align-items: baseline;
  gap: 7px;
  min-width: 0;
  font-size: 11px;
  line-height: 1.4;
}
.proxy-group-health__item::before {
  content: '';
  flex: 0 0 auto;
  align-self: center;
  width: 7px;
  height: 7px;
  border: 1.5px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: 50%;
  background: color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 25%, transparent);
}
.proxy-group-health__item.is-ok::before { background: var(--bauhaus-blue, #2d5da1); }
.proxy-group-health__item.is-fail::before { background: var(--bauhaus-red, #ff4d4d); }
.proxy-group-health__item.is-testing::before { background: var(--bauhaus-postit, #f4e7c4); }
.proxy-group-health__name {
  flex: 0 0 auto;
  color: var(--bauhaus-ink, #2d2d2d);
  font-weight: 600;
}
.proxy-group-health__value {
  min-width: 0;
  overflow: hidden;
  font-variant-numeric: tabular-nums;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.proxy-group-health__item.is-ok .proxy-group-health__value { color: var(--bauhaus-blue, #2d5da1); }
.proxy-group-health__item.is-fail .proxy-group-health__value { color: var(--bauhaus-red, #ff4d4d); }
.proxy-group-health__item.is-testing .proxy-group-health__value { color: hsl(var(--muted-foreground)); }
.proxy-group-health__item.is-idle .proxy-group-health__value { color: hsl(var(--muted-foreground)); }
</style>

