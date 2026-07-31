import { computed, reactive, ref, type Ref } from 'vue'
import { accountsApi } from '@/api/accounts'
import { parseProxyReference, serializeProxyReference } from '@/api/proxy'
import type { ProxyGroup } from '@/api/proxy'
import type { AccountGroup } from '@/api/accounts'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useToast } from '@/composables/useToast'
import {
  createAccountGroupId,
  createDefaultAccountGroupForm,
  normalizeAccountGroupName,
  type AccountProxyMode,
  type SetErrorFn,
} from './accountPageShared'

export type UseAccountGroupsOptions = {
  setError: SetErrorFn
  loadData: (options?: { silentErrorToast?: boolean }) => Promise<void>
  groupFilter: Ref<string>
}

/**
 * 账号组：列表、代理配置、CRUD 与 modal 状态。
 */
export function useAccountGroups(options: UseAccountGroupsOptions) {
  const { setError, loadData, groupFilter } = options
  const toast = useToast()
  const confirmDialog = useConfirmDialog()

  const accountGroups = ref<AccountGroup[]>([])
  const proxyGroups = ref<ProxyGroup[]>([])
  const accountGroupsLoading = ref(false)
  const showAccountGroupsModal = ref(false)
  const accountGroupSaving = ref(false)
  const editingAccountGroupId = ref('')
  const selectedBindGroupId = ref('')
  const accountGroupProxyMode = ref<AccountProxyMode>('global')
  const selectedAccountGroupProxyGroupId = ref('')
  const accountGroupCustomProxyInput = ref('')
  const accountGroupForm = reactive(createDefaultAccountGroupForm())

  const groupFilterOptions = computed(() => [
    { label: '全部账号组', value: 'all' },
    { label: '未分组', value: '__ungrouped__' },
    ...accountGroups.value.map((group) => ({
      label: `${group.enabled === false ? '停用 · ' : ''}${group.name || group.id}`,
      value: group.id,
    })),
  ])

  const accountGroupOptions = computed(() => [
    { label: '不绑定账号组', value: '' },
    ...accountGroups.value.map((group) => ({
      label: `${group.enabled === false ? '停用 · ' : ''}${group.name || group.id}`,
      value: group.id,
    })),
  ])

  const accountGroupProxyOptions = computed(() => {
    const rows = proxyGroups.value.map((group) => ({
      label: `${group.enabled === false ? '停用 · ' : ''}${group.name || group.id}${Array.isArray(group.nodes) ? ` · ${group.nodes.length} 个节点` : ''}`,
      value: group.id,
    }))
    const selectedId = selectedAccountGroupProxyGroupId.value
    if (selectedId && !rows.some((item) => item.value === selectedId)) {
      rows.unshift({ label: `未知代理组 · ${selectedId}`, value: selectedId })
    }
    return [
      { label: '选择代理组', value: '' },
      ...rows,
    ]
  })

  const bindAccountGroupOptions = computed(() => [
    { label: '选择账号组', value: '' },
    ...accountGroupOptions.value.slice(1),
    { label: '取消分组', value: '__ungrouped__' },
  ])

  const accountGroupProxyPreview = computed(() => {
    const reference = parseProxyReference(accountGroupForm.proxy)
    if (reference.mode === 'global') return '使用默认代理'
    if (reference.mode === 'direct') return '强制直连'
    if (reference.mode === 'profile') {
      return `历史兼容引用：profile:${reference.value || '-'}`
    }
    if (reference.mode === 'group') {
      const group = proxyGroups.value.find((item) => item.id === reference.value)
      return `代理组：${group?.name || reference.value || '-'}`
    }
    return reference.value || '自定义代理'
  })

  function applyAccountGroupsPayload(response: { groups?: AccountGroup[]; proxy_groups?: ProxyGroup[] }) {
    accountGroups.value = Array.isArray(response.groups)
      ? response.groups.filter((group) => group.id)
      : []
    proxyGroups.value = Array.isArray(response.proxy_groups)
      ? response.proxy_groups.filter((group) => String(group?.id || '').trim())
      : []
    if (groupFilter.value !== 'all' && groupFilter.value !== '__ungrouped__' && !accountGroups.value.some((group) => group.id === groupFilter.value)) {
      groupFilter.value = 'all'
    }
    if (selectedBindGroupId.value && !accountGroups.value.some((group) => group.id === selectedBindGroupId.value)) {
      selectedBindGroupId.value = ''
    }
  }

  async function loadAccountGroups(loadOptions?: { silentErrorToast?: boolean }) {
    accountGroupsLoading.value = true
    try {
      const response = await accountsApi.listGroups()
      applyAccountGroupsPayload(response)
    } catch (error) {
      if (!loadOptions?.silentErrorToast) {
        setError('加载账号组失败', error)
      }
    } finally {
      accountGroupsLoading.value = false
    }
  }

  function syncAccountGroupProxyControlsFromValue(value: unknown, legacyProxyGroupId = '') {
    const fallback = legacyProxyGroupId ? serializeProxyReference('group', legacyProxyGroupId) : ''
    const raw = String(value || '').trim() || fallback
    const reference = parseProxyReference(raw)
    accountGroupCustomProxyInput.value = ''
    selectedAccountGroupProxyGroupId.value = ''
    accountGroupProxyMode.value = reference.mode === 'profile' ? 'custom' : reference.mode
    accountGroupForm.proxy = raw
    accountGroupForm.proxy_group_id = ''
    if (reference.mode === 'profile') {
      accountGroupCustomProxyInput.value = raw
      return
    }
    if (reference.mode === 'group') {
      selectedAccountGroupProxyGroupId.value = reference.value
      accountGroupForm.proxy_group_id = reference.value
      return
    }
    if (reference.mode === 'custom') {
      accountGroupCustomProxyInput.value = reference.value
    }
  }

  function setAccountGroupProxyMode(mode: string) {
    const nextMode = ['global', 'direct', 'group', 'custom'].includes(mode)
      ? mode as AccountProxyMode
      : 'global'
    accountGroupProxyMode.value = nextMode
    accountGroupForm.proxy_group_id = ''
    if (nextMode === 'global') {
      accountGroupForm.proxy = serializeProxyReference('global')
    } else if (nextMode === 'direct') {
      accountGroupForm.proxy = serializeProxyReference('direct')
    } else if (nextMode === 'group') {
      accountGroupForm.proxy_group_id = selectedAccountGroupProxyGroupId.value
      accountGroupForm.proxy = serializeProxyReference('group', selectedAccountGroupProxyGroupId.value)
    } else {
      accountGroupForm.proxy = serializeProxyReference('custom', accountGroupCustomProxyInput.value)
    }
  }

  function selectAccountGroupProxyGroup(groupId: string) {
    selectedAccountGroupProxyGroupId.value = groupId.trim()
    accountGroupProxyMode.value = 'group'
    accountGroupForm.proxy_group_id = selectedAccountGroupProxyGroupId.value
    accountGroupForm.proxy = serializeProxyReference('group', selectedAccountGroupProxyGroupId.value)
  }

  function setAccountGroupCustomProxyInput(value: string) {
    accountGroupCustomProxyInput.value = value.trim()
    accountGroupProxyMode.value = 'custom'
    accountGroupForm.proxy_group_id = ''
    accountGroupForm.proxy = serializeProxyReference('custom', accountGroupCustomProxyInput.value)
  }

  function resetAccountGroupForm() {
    Object.assign(accountGroupForm, createDefaultAccountGroupForm())
    editingAccountGroupId.value = ''
    syncAccountGroupProxyControlsFromValue(accountGroupForm.proxy)
  }

  function openAccountGroupsModal() {
    showAccountGroupsModal.value = true
    resetAccountGroupForm()
    void loadAccountGroups({ silentErrorToast: true })
  }

  function closeAccountGroupsModal() {
    if (accountGroupSaving.value) return
    showAccountGroupsModal.value = false
    resetAccountGroupForm()
  }

  function editAccountGroup(group: AccountGroup) {
    const proxy = group.proxy || (group.proxy_group_id ? serializeProxyReference('group', group.proxy_group_id) : '')
    editingAccountGroupId.value = group.id
    Object.assign(accountGroupForm, {
      id: group.id,
      name: group.name || group.id,
      proxy,
      proxy_group_id: group.proxy_group_id || '',
      enabled: group.enabled !== false,
      notes: group.notes || '',
    })
    syncAccountGroupProxyControlsFromValue(proxy, group.proxy_group_id || '')
  }

  async function saveAccountGroup() {
    if (accountGroupSaving.value) return
    const name = accountGroupForm.name.trim()
    const id = (accountGroupForm.id || editingAccountGroupId.value || createAccountGroupId(name)).trim()
    if (!name) {
      toast.warning('请填写账号组名称')
      return
    }
    const normalizedName = normalizeAccountGroupName(name)
    const duplicatedName = accountGroups.value.some((group) => (
      group.id !== id &&
      normalizeAccountGroupName(group.name || group.id) === normalizedName
    ))
    if (duplicatedName) {
      toast.warning('账号组名称已存在，请换一个名称')
      return
    }
    if (accountGroupProxyMode.value === 'group' && !selectedAccountGroupProxyGroupId.value.trim()) {
      toast.warning('请选择账号组默认代理组')
      return
    }
    if (accountGroupProxyMode.value === 'custom' && !accountGroupCustomProxyInput.value.trim()) {
      toast.warning('请填写账号组自定义代理地址')
      return
    }

    accountGroupSaving.value = true
    const wasEditing = Boolean(editingAccountGroupId.value)
    try {
      const response = await accountsApi.saveGroup({
        id,
        name,
        proxy: accountGroupForm.proxy.trim(),
        proxy_group_id: accountGroupForm.proxy_group_id.trim(),
        enabled: accountGroupForm.enabled,
        notes: accountGroupForm.notes.trim(),
        create_only: !editingAccountGroupId.value,
      })
      applyAccountGroupsPayload(response)
      selectedBindGroupId.value = response.group?.id || selectedBindGroupId.value
      resetAccountGroupForm()
      toast.success(wasEditing ? '账号组已更新' : '账号组已创建')
    } catch (error) {
      setError(wasEditing ? '更新账号组失败' : '创建账号组失败', error)
    } finally {
      accountGroupSaving.value = false
    }
  }

  async function deleteAccountGroup(group: AccountGroup) {
    if (accountGroupSaving.value) return
    const accountCount = Number(group.account_count || 0)
    const confirmed = await confirmDialog.ask({
      title: '删除账号组',
      message: `确认删除账号组「${group.name || group.id}」吗？${accountCount ? `当前 ${accountCount} 个账号会变为未分组。` : '不会删除任何账号。'}`,
      confirmText: '确认删除',
      cancelText: '取消',
    })
    if (!confirmed) return

    accountGroupSaving.value = true
    try {
      const response = await accountsApi.deleteGroup(group.id)
      applyAccountGroupsPayload(response)
      await loadData({ silentErrorToast: true })
      if (editingAccountGroupId.value === group.id) resetAccountGroupForm()
      toast.success('账号组已删除')
    } catch (error) {
      setError('删除账号组失败', error)
    } finally {
      accountGroupSaving.value = false
    }
  }

  return {
    accountGroups,
    proxyGroups,
    accountGroupsLoading,
    showAccountGroupsModal,
    accountGroupSaving,
    editingAccountGroupId,
    selectedBindGroupId,
    accountGroupProxyMode,
    selectedAccountGroupProxyGroupId,
    accountGroupCustomProxyInput,
    accountGroupForm,
    groupFilterOptions,
    accountGroupOptions,
    accountGroupProxyOptions,
    bindAccountGroupOptions,
    accountGroupProxyPreview,
    applyAccountGroupsPayload,
    loadAccountGroups,
    resetAccountGroupForm,
    openAccountGroupsModal,
    closeAccountGroupsModal,
    editAccountGroup,
    saveAccountGroup,
    deleteAccountGroup,
    setAccountGroupProxyMode,
    selectAccountGroupProxyGroup,
    setAccountGroupCustomProxyInput,
  }
}
