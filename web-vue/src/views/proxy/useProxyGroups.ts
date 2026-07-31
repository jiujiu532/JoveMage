import { computed, onActivated, onMounted, reactive, ref } from 'vue'
import type { ActionMenuItem } from 'nanocat-ui'
import { prepareSettingsForEdit, settingsApi } from '@/api/settings'
import {
  parseProxyReference,
  proxyApi,
  serializeProxyReference,
  type ProxyGroup,
  type ProxyNode,
  type ProxyTestResult,
} from '@/api/proxy'
import { actionMenuGroups } from '@/components/ai/menuItems'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useSettingsStore } from '@/stores/settings'
import { useClipboard } from '@/composables/useClipboard'
import { useToast } from '@/composables/useToast'
import type { Settings } from '@/types/api'

export type DefaultProxyMode = 'direct' | 'group' | 'custom'
export type FallbackProxyMode = 'off' | DefaultProxyMode

export type ProxyGroupForm = {
  id: string
  name: string
  enabled: boolean
  notes: string
  nodes: ProxyNode[]
}

export const DEFAULT_TEST_KEY = '__default__'
export const FORM_TEST_KEY = '__form__'
const DEFAULT_PROXY_NODE_IMAGE_CONCURRENCY = 30

export function useProxyGroups() {
  const settingsStore = useSettingsStore()
  const toast = useToast()
  const { copy } = useClipboard()
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
    await copy(text, { success: message })
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

  function setGroupKeyword(value: string) {
    groupKeyword.value = String(value || '').trim()
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

  return {
    DEFAULT_TEST_KEY,
    FORM_TEST_KEY,
    loading,
    savingDefaultProxy,
    savingGroupId,
    deletingGroupId,
    testingKey,
    groupKeyword,
    showGroupModal,
    editingGroupId,
    defaultProxyMode,
    selectedDefaultProxyGroupId,
    defaultCustomProxyInput,
    fallbackProxyMode,
    selectedFallbackProxyGroupId,
    fallbackCustomProxyInput,
    defaultTestResult,
    groups,
    testResults,
    groupForm,
    defaultProxyModeOptions,
    fallbackProxyModeOptions,
    filteredGroups,
    defaultProxyGroupOptions,
    defaultProxyPreview,
    fallbackProxyPreview,
    canTestDefaultProxy,
    isDefaultProxyDirty,
    normalizeGroupId,
    normalizeImageConcurrencyLimit,
    proxyGroupReference,
    copyProxyGroupReference,
    setDefaultProxyMode,
    setFallbackProxyMode,
    selectDefaultProxyGroup,
    selectFallbackProxyGroup,
    setDefaultCustomProxyInput,
    setFallbackCustomProxyInput,
    loadData,
    saveDefaultProxy,
    setDefaultProxyDirect,
    testDefaultProxy,
    openCreateGroupModal,
    openEditGroupModal,
    closeGroupModal,
    addGroupNode,
    removeGroupNode,
    saveProxyGroup,
    proxyGroupActionItems,
    handleProxyGroupAction,
    testProxyGroupNode,
    groupStrategyLabel,
    isGroupExpanded,
    toggleGroupExpanded,
    groupHealthSummary,
    nodeHealthValue,
    nodeHealthTone,
    setGroupKeyword,
  }
}
