import { computed, onActivated, onMounted, reactive, ref, watch } from 'vue'
import { accountsApi, normalizeAccountBackendStatus } from '@/api/accounts'
import { proxyApi, parseProxyReference, serializeProxyReference } from '@/api/proxy'
import type { ProxyTestResult } from '@/api/proxy'
import type { Account } from '@/api/accounts'
import { useClipboard } from '@/composables/useClipboard'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useMediaQuery } from '@/composables/useMediaQuery'
import { useSelectionSet } from '@/composables/useSelectionSet'
import { useToast } from '@/composables/useToast'
import { MQ } from '@/lib/breakpoints'
import { saveBlob } from '@/lib/downloads'
import {
  getStringPreference,
  preferenceKeys,
  setStringPreference,
} from '@/lib/preferences'
import { accountCreditsText, statusCategory } from './viewUtils'
import {
  createDefaultForm,
  createExportFilename,
  isFireflySourceType,
  normalizeErrorMessage,
  normalizeQuota,
  uniqueTokens,
  type AccountProxyMode,
} from './accountPageShared'
import { useAccountListQuery } from './useAccountListQuery'
import { useAccountGroups } from './useAccountGroups'
import { useAccountBulkActions } from './useAccountBulkActions'
import { useAccountImport, type AccountImportMode } from './useAccountImport'

export type AccountsViewMode = 'cards' | 'compact' | 'single' | 'double'
export type { AccountImportMode }

/** 兼容旧偏好 list→compact；非法值回落到紧凑表 */
export function normalizeAccountsViewMode(value: string | null | undefined): AccountsViewMode {
  const raw = String(value || '').trim().toLowerCase()
  if (raw === 'list') return 'compact'
  if (raw === 'cards' || raw === 'compact' || raw === 'single' || raw === 'double') return raw
  return 'compact'
}

/**
 * 账号页编排层：聚合 list / groups / import / bulk / 单账号 CRUD，
 * 对外返回字段与切分前完全一致，Accounts.vue 无需改动。
 */
export function useAccountsPage() {
  const toast = useToast()
  const { copy } = useClipboard()
  const confirmDialog = useConfirmDialog()

  function setError(prefix: string, error: unknown, notify = true) {
    const message = normalizeErrorMessage(error)
    if (notify) toast.error(`${prefix}: ${message}`)
  }

  // ── 列表 / 筛选 / 分页 ──────────────────────────────────────────
  // pruneSelection 稍后注入（依赖 selection，而 selection 依赖 pagedAccounts）
  let pruneSelectionRef: ((ids: string[]) => void) | undefined
  const list = useAccountListQuery({
    setError,
    pruneSelection: (ids) => pruneSelectionRef?.(ids),
  })
  const {
    loading,
    keyword,
    statusFilter,
    groupFilter,
    sourceFilter,
    statusFilterOptions,
    sourceFilterOptions: sourceFilterOptionList,
    channelTabOptions,
    applyChannelCounts,
    setSourceFilter,
    accounts,
    accountListTotal,
    accountAllTotal,
    currentPage,
    pageSize,
    pageSizeOptions,
    pageCount,
    filteredAccounts,
    pagedAccounts,
    resetToFirst,
    scheduleListReload,
    loadData,
    enableListWatch,
  } = list

  // ── 账号组 ──────────────────────────────────────────────────────
  const groups = useAccountGroups({
    setError,
    loadData,
    groupFilter,
  })
  const {
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
  } = groups

  // ── 选择集 ──────────────────────────────────────────────────────
  // 可见可选：当前页非 demo 账号；对外仍暴露 selectedIds 等旧名
  const {
    selected: selectedIds,
    selectedCount,
    allVisibleSelected,
    isSelected,
    toggle: toggleSelect,
    toggleAllVisible: toggleSelectAllVisible,
    clear: clearSelection,
    prune: pruneSelection,
  } = useSelectionSet<string>({
    getVisibleIds: () => pagedAccounts.value
      .filter((item) => !item.is_demo)
      .map((item) => item.id),
  })
  pruneSelectionRef = pruneSelection

  // ── 批量操作 + 进度 ─────────────────────────────────────────────
  const bulk = useAccountBulkActions({
    setError,
    loadData,
    accounts,
    accountListTotal,
    accountAllTotal,
    selectedIds,
    clearSelection,
  })
  const {
    batchBusy,
    batchActionLabel,
    showRefreshProgress,
    refreshProgressTitle,
    refreshProgress,
    bulkStopRequested,
    refreshProgressPercent,
    refreshProgressMetricLabel,
    refreshProgressMetricValue,
    refreshProgressStatusText,
    canStopRefreshProgress,
    openBulkProgress,
    requestStopRefreshProgress,
    closeRefreshProgress,
    refreshAllAccounts,
    refreshSelectedAccounts,
    runBulkAction,
  } = bulk

  // ── 导入 ────────────────────────────────────────────────────────
  const accountImport = useAccountImport({
    setError,
    loadData,
    openBulkProgress,
    bulkStopRequested,
    refreshProgress,
    batchBusy,
    batchActionLabel,
  })
  const {
    importBusy,
    showImportModal,
    importMode,
    importModeOptions,
    importModeSections,
    manualTokenText,
    sessionJsonText,
    fireflyCookieText,
    setImportMode,
    openImportModal,
    closeImportModal,
    importManualTokenText,
    importTokenTextFile,
    importSessionJson,
    importLocalCPAFiles,
    importFireflyCookieText,
    importFireflyCookieFile,
  } = accountImport

  // ── 视图模式 / 单账号 CRUD / 导出 ───────────────────────────────
  const saving = ref(false)
  const showModal = ref(false)
  const editingId = ref<string | null>(null)
  const viewMode = ref<AccountsViewMode>('compact')
  /** ≤md 时 compact 表过宽，展示降级为 cards，不改写用户偏好 */
  const isTabletDown = useMediaQuery(MQ.tabletDown)
  const effectiveViewMode = computed<AccountsViewMode>(() => {
    if (isTabletDown.value && viewMode.value === 'compact') return 'cards'
    return viewMode.value
  })
  const refreshingAccountId = ref('')
  const resettingAccountId = ref('')
  const reloginAccountId = ref('')
  const exportBusy = ref(false)
  const proxyTesting = ref(false)
  const proxyMode = ref<AccountProxyMode>('global')
  const selectedProxyGroupId = ref('')
  const customProxyInput = ref('')
  const form = reactive(createDefaultForm())
  const isFireflyForm = computed(() => isFireflySourceType(form.source_type))
  /** 编辑态 Firefly credits 只读展示（不进提交表单） */
  const editingFireflyCreditsText = ref('')
  const accountStatusOptions = [
    { label: '正常', value: '正常' },
    { label: '限流', value: '限流' },
    { label: '异常', value: '异常' },
    { label: '禁用', value: '禁用' },
  ] as const
  const accountSourceTypeOptions = [
    { label: 'ChatGPT · web', value: 'web' },
    { label: 'ChatGPT · oauth_login', value: 'oauth_login' },
    { label: 'ChatGPT · codex', value: 'codex' },
    { label: 'ChatGPT · manual', value: 'manual' },
    { label: 'Adobe Firefly', value: 'firefly' },
  ] as const
  const sourceFilterOptions = sourceFilterOptionList

  let hasActivatedOnce = false

  const abnormalAccountIds = computed(() => (
    accounts.value
      .filter((item) => statusCategory(item) === 'abnormal')
      .map((item) => item.id)
  ))

  const abnormalAccountCount = computed(() => abnormalAccountIds.value.length)

  const accountProxyModeOptions = [
    { label: '使用默认代理', value: 'global' },
    { label: '强制直连', value: 'direct' },
    { label: '代理组（多节点）', value: 'group' },
    { label: '自定义代理', value: 'custom' },
  ] as const

  const proxyGroupOptions = computed(() => {
    const rows = proxyGroups.value.map((group) => ({
      label: `${group.enabled === false ? '停用 · ' : ''}${group.name || group.id}${Array.isArray(group.nodes) ? ` · ${group.nodes.length} 个节点` : ''}`,
      value: group.id,
    }))
    const selectedId = selectedProxyGroupId.value
    if (selectedId && !rows.some((item) => item.value === selectedId)) {
      rows.unshift({ label: `未知代理组 · ${selectedId}`, value: selectedId })
    }
    return [
      { label: '选择代理组', value: '' },
      ...rows,
    ]
  })

  const accountProxyPreview = computed(() => {
    const reference = parseProxyReference(form.proxy)
    if (reference.mode === 'global') return '使用默认代理'
    if (reference.mode === 'direct') return '强制直连'
    if (reference.mode === 'profile') {
      return `历史兼容引用：profile:${reference.value || '-'}`
    }
    if (reference.mode === 'group') {
      const group = proxyGroups.value.find((item) => item.id === reference.value)
      return `代理组：${group?.name || reference.value}`
    }
    return reference.value
  })

  async function copyAccountToken(item: Account) {
    const isFirefly = isFireflySourceType(item.source_type)
    const token = isFirefly
      ? String(item.cookie || item.access_token || '').trim()
      : String(item.access_token || item.cookie || '').trim()
    if (!token) {
      toast.warning(isFirefly ? '当前账号没有可复制的 Cookie / Token' : '当前账号没有可复制的 Token')
      return
    }

    await copy(token, {
      success: isFirefly ? '凭证已复制' : 'Token 已复制',
      error: isFirefly ? '复制凭证失败' : '复制 Token 失败',
    })
  }

  function resetForm() {
    editingId.value = null
    Object.assign(form, createDefaultForm())
    editingFireflyCreditsText.value = ''
    syncProxyControlsFromValue(form.proxy)
  }

  function syncProxyControlsFromValue(value: unknown) {
    const reference = parseProxyReference(value)
    customProxyInput.value = ''
    selectedProxyGroupId.value = ''
    proxyMode.value = reference.mode === 'profile' ? 'custom' : reference.mode
    if (reference.mode === 'profile') {
      customProxyInput.value = String(value || '').trim()
      return
    }
    if (reference.mode === 'group') {
      selectedProxyGroupId.value = reference.value
      return
    }
    if (reference.mode === 'custom') {
      customProxyInput.value = reference.value
    }
  }

  function setProxyMode(mode: string) {
    const nextMode = ['global', 'direct', 'group', 'custom'].includes(mode)
      ? mode as AccountProxyMode
      : 'global'
    proxyMode.value = nextMode
    if (nextMode === 'global') {
      form.proxy = serializeProxyReference('global')
    } else if (nextMode === 'direct') {
      form.proxy = serializeProxyReference('direct')
    } else if (nextMode === 'group') {
      form.proxy = serializeProxyReference('group', selectedProxyGroupId.value)
    } else {
      form.proxy = serializeProxyReference('custom', customProxyInput.value)
    }
  }

  function selectProxyGroup(groupId: string) {
    selectedProxyGroupId.value = groupId.trim()
    proxyMode.value = 'group'
    form.proxy = serializeProxyReference('group', selectedProxyGroupId.value)
  }

  function setCustomProxyInput(value: string) {
    customProxyInput.value = value.trim()
    proxyMode.value = 'custom'
    form.proxy = serializeProxyReference('custom', customProxyInput.value)
  }

  async function testAccountProxy() {
    if (proxyTesting.value) return

    const reference = parseProxyReference(form.proxy)
    if (reference.mode === 'direct') {
      toast.info('当前账号强制直连，不需要测试代理')
      return
    }

    if (proxyMode.value === 'group' && !selectedProxyGroupId.value) {
      toast.warning('请先选择代理组')
      return
    }

    if (proxyMode.value === 'custom' && !customProxyInput.value.trim()) {
      toast.warning('请先填写自定义代理地址')
      return
    }

    const confirmed = await confirmDialog.ask({
      title: '确认测试账号代理',
      message: '即将通过当前账号代理配置发起外部网络测试请求。请确认当前允许测试该代理连接。',
      confirmText: '开始测试',
      cancelText: '取消',
    })
    if (!confirmed) return

    proxyTesting.value = true
    try {
      const response: { result?: ProxyTestResult | null; results?: Array<{ result: ProxyTestResult }> } = proxyMode.value === 'group'
          ? await proxyApi.testGroup({ id: selectedProxyGroupId.value })
          : await proxyApi.test(proxyMode.value === 'custom' ? customProxyInput.value.trim() : '')
      const result = response.result || response.results?.[0]?.result
      if (!result) {
        toast.error('代理测试没有返回结果')
        return
      }
      if (result.ok) {
        toast.success(`代理可用：${result.latency_ms} ms，HTTP ${result.status}`)
      } else {
        toast.error(`代理不可用：${result.error || '未知错误'}`)
      }
    } catch (error) {
      setError('测试代理失败', error)
    } finally {
      proxyTesting.value = false
    }
  }

  function setViewMode(mode: AccountsViewMode | string) {
    const next = normalizeAccountsViewMode(mode)
    viewMode.value = next
    setStringPreference(preferenceKeys.accountsViewMode, next)
  }

  function openCreateModal(options?: { source_type?: string }) {
    resetForm()
    const sourceType = String(options?.source_type || '').trim()
    if (sourceType) {
      form.source_type = sourceType
      if (isFireflySourceType(sourceType)) {
        form.type = 'firefly'
      }
    }
    void loadAccountGroups({ silentErrorToast: true })
    showModal.value = true
  }

  function openEditModal(item: Account) {
    editingId.value = item.id
    form.id = item.id
    form.access_token = item.access_token || ''
    form.cookie = item.cookie || ''
    form.type = item.type || (isFireflySourceType(item.source_type) ? 'firefly' : 'free')
    form.source_type = item.source_type || 'web'
    form.group_id = item.group_id || ''
    form.proxy = item.proxy || ''
    form.quota = item.image_quota_unknown ? '' : String(item.quota ?? '')
    form.status = normalizeAccountBackendStatus(item.backend_status, item.enabled ? '正常' : '禁用')
    editingFireflyCreditsText.value = isFireflySourceType(item.source_type)
      ? accountCreditsText(item)
      : ''
    syncProxyControlsFromValue(form.proxy)
    void loadAccountGroups({ silentErrorToast: true })
    showModal.value = true
  }

  function closeModal() {
    showModal.value = false
    resetForm()
  }

  async function saveAccount() {
    const sourceType = form.source_type.trim() || 'web'
    const isFirefly = isFireflySourceType(sourceType)
    if (isFirefly) {
      if (!form.cookie.trim() && !form.access_token.trim()) {
        toast.warning('请填写 Adobe Express Cookie（或已有 Access Token）')
        return
      }
    } else if (!form.access_token.trim()) {
      toast.warning('Access token 不能为空')
      return
    }

    saving.value = true
    const accountIdForNotice = editingId.value || form.id || ''
    const isEditing = Boolean(editingId.value)

    try {
      const payloadId = editingId.value || form.id || undefined
      await accountsApi.upsert({
        id: payloadId,
        access_token: form.access_token.trim() || undefined,
        cookie: form.cookie.trim() || undefined,
        type: form.type.trim() || (isFirefly ? 'firefly' : undefined),
        source_type: sourceType,
        group_id: form.group_id.trim(),
        proxy: form.proxy.trim(),
        quota: normalizeQuota(form.quota),
        backend_status: form.status,
        enabled: form.status !== '禁用',
      })
      toast.success(isEditing ? `账号 ${accountIdForNotice} 已更新` : '账号已添加')
      closeModal()
      await loadData({ silentErrorToast: true })
    } catch (error) {
      setError('保存失败', error)
    } finally {
      saving.value = false
    }
  }

  async function toggleEnabled(item: Account) {
    const nextEnabled = !item.enabled
    const confirmed = await confirmDialog.ask({
      title: nextEnabled ? '确认启用账号' : '确认禁用账号',
      message: `即将${nextEnabled ? '启用' : '禁用'}账号 ${item.id}。这会影响该账号是否参与后续请求分配，是否继续？`,
      confirmText: nextEnabled ? '启用' : '禁用',
      cancelText: '取消',
    })
    if (!confirmed) return

    try {
      if (item.enabled) {
        await accountsApi.disable(item.id)
      } else {
        await accountsApi.enable(item.id)
      }
      toast.success(`账号 ${item.id} 已${item.enabled ? '禁用' : '启用'}`)
      await loadData({ silentErrorToast: true })
    } catch (error) {
      setError('切换状态失败', error)
    }
  }

  async function refreshToken(accountId: string) {
    const confirmed = await confirmDialog.ask({
      title: '确认刷新账号',
      message: `即将刷新账号 ${accountId} 的远端信息和额度，可能触发外部 ChatGPT 请求。是否继续？`,
      confirmText: '开始刷新',
      cancelText: '取消',
    })
    if (!confirmed) return

    refreshingAccountId.value = accountId
    toast.info(`正在刷新账号 ${accountId} 的远端信息...`)
    try {
      await accountsApi.refreshToken(accountId)
      toast.success(`账号 ${accountId} 刷新成功`)
      await loadData({ silentErrorToast: true })
    } catch (error) {
      toast.error(`账号 ${accountId} 刷新失败：${normalizeErrorMessage(error)}`)
      await loadData({ silentErrorToast: true })
    } finally {
      refreshingAccountId.value = ''
    }
  }

  async function reloginAccount(accountId: string) {
    if (reloginAccountId.value) return
    const account = accounts.value.find(item => item.id === accountId)
    if (!account) return
    const confirmed = await confirmDialog.ask({
      title: '重新登录账号',
      message: `确认重新登录 ${account.email || account.name || account.id} 吗？`,
      confirmText: '重新登录',
      cancelText: '取消',
    })
    if (!confirmed) return
    reloginAccountId.value = accountId
    try {
      const response = await accountsApi.reloginAccount(accountId)
      if (response.ok === false) {
        throw new Error(response.error || '重新登录失败')
      }
      toast.success('账号已重新登录')
      await loadData({ silentErrorToast: true })
    } catch (error) {
      setError('重新登录失败', error)
    } finally {
      reloginAccountId.value = ''
    }
  }

  async function resetAccountState(accountId: string) {
    const confirmed = await confirmDialog.ask({
      title: '重置账号状态',
      message: `是否重置账号 ${accountId} 的配额和冷却？此操作会清空本地计数并移除冷却状态。`,
      confirmText: '确认重置',
      cancelText: '取消',
    })
    if (!confirmed) return

    resettingAccountId.value = accountId
    try {
      await accountsApi.resetAccountState(accountId)
      toast.success(`账号 ${accountId} 已重置`)
      await loadData({ silentErrorToast: true })
    } catch (error) {
      toast.error(`账号 ${accountId} 重置失败：${normalizeErrorMessage(error)}`)
      await loadData({ silentErrorToast: true })
    } finally {
      resettingAccountId.value = ''
    }
  }

  async function removeAccount(accountId: string) {
    const confirmed = await confirmDialog.ask({
      title: '删除账号',
      message: `确认删除账号 ${accountId} 吗？此操作不可恢复。`,
      confirmText: '确认删除',
      cancelText: '取消',
    })
    if (!confirmed) return

    try {
      await accountsApi.delete(accountId)
      toast.success(`账号 ${accountId} 已删除`)
      await loadData({ silentErrorToast: true })
    } catch (error) {
      setError('删除失败', error)
    }
  }

  async function bindSelectedAccountsToGroup() {
    const targetIds = selectedIds.value.filter(Boolean)
    if (!targetIds.length) {
      toast.warning('请先选择账号')
      return
    }
    const nextGroupId = selectedBindGroupId.value === '__ungrouped__' ? '' : selectedBindGroupId.value.trim()
    if (selectedBindGroupId.value !== '__ungrouped__' && !nextGroupId) {
      toast.warning('请先选择要绑定的账号组')
      return
    }
    const groupName = nextGroupId
      ? accountGroups.value.find((group) => group.id === nextGroupId)?.name || nextGroupId
      : '未分组'
    const confirmed = await confirmDialog.ask({
      title: '批量绑定账号组',
      message: `确认把选中的 ${targetIds.length} 个账号绑定到 ${groupName} 吗？`,
      confirmText: '确认绑定',
      cancelText: '取消',
    })
    if (!confirmed) return

    openBulkProgress('批量绑定账号组', targetIds.length, 'mutation')
    batchBusy.value = true
    batchActionLabel.value = '批量绑定账号组'
    try {
      const result = await accountsApi.bindGroup(targetIds, nextGroupId)
      refreshProgress.value = {
        ...(refreshProgress.value || { total: targetIds.length }),
        total: targetIds.length,
        processed: targetIds.length,
        done: true,
        total_quota: 0,
      }
      toast.success(`已绑定 ${result.updated || 0} 个账号`)
      applyAccountGroupsPayload({ groups: result.groups, proxy_groups: proxyGroups.value })
      clearSelection()
      await loadData({ silentErrorToast: true })
    } catch (error) {
      refreshProgress.value = {
        ...(refreshProgress.value || { total: targetIds.length, processed: 0 }),
        total: targetIds.length,
        done: true,
        error: normalizeErrorMessage(error),
        total_quota: 0,
      }
      setError('批量绑定账号组失败', error)
    } finally {
      batchBusy.value = false
      batchActionLabel.value = ''
    }
  }

  async function exportAccounts(scope: 'selected' | 'all' | 'auto' = 'auto') {
    const targetIds = new Set(scope === 'all' ? [] : selectedIds.value)
    if (scope === 'all' || (scope === 'auto' && targetIds.size === 0)) {
      const totalHint = accountAllTotal.value || accountListTotal.value || accounts.value.length
      if (!totalHint) {
        toast.warning('暂无可导出的账号')
        return
      }
      const confirmed = await confirmDialog.ask({
        title: '导出全部账号认证',
        message: `即将导出全部 ${totalHint} 个账号。导出文件可能包含 refresh_token、id_token 或 access token，请只在可信环境保存。是否继续？`,
        confirmText: '确认导出',
        cancelText: '取消',
      })
      if (!confirmed) return

      exportBusy.value = true
      try {
        const blob = await accountsApi.exportAccounts([], 'json')
        saveBlob(blob, createExportFilename('json'))
        toast.success('已导出全部账号认证')
      } catch (error) {
        setError('导出失败', error)
      } finally {
        exportBusy.value = false
      }
      return
    }
    if (scope === 'selected' && targetIds.size === 0) {
      toast.warning('请先选择要导出的账号')
      return
    }

    const targetAccounts = (targetIds.size
      ? accounts.value.filter((item) => targetIds.has(item.id))
      : accounts.value
    )

    if (!targetAccounts.length) {
      toast.warning('暂无可导出的账号')
      return
    }

    const exportScopeLabel = targetIds.size === 0 ? '全部' : '选中'
    const confirmed = await confirmDialog.ask({
      title: '导出账号认证',
      message: `即将导出${exportScopeLabel} ${targetAccounts.length} 个账号。导出文件可能包含 refresh_token、id_token 或 access token，请只在可信环境保存。是否继续？`,
      confirmText: '确认导出',
      cancelText: '取消',
    })
    if (!confirmed) return

    exportBusy.value = true
    try {
      const blob = await accountsApi.exportAccounts(targetAccounts.map((item) => item.id), 'json')
      saveBlob(blob, createExportFilename('json'))
      toast.success(`已导出 ${targetAccounts.length} 个完整认证账号`)
    } catch (error) {
      const status = (error as { status?: number }).status
      if (status !== 400) {
        setError('导出失败', error)
        return
      }

      const tokens = uniqueTokens(targetAccounts.map((item) => item.access_token || ''))
      if (!tokens.length) {
        setError('导出失败', error)
        return
      }

      saveBlob(new Blob([`${tokens.join('\n')}\n`], { type: 'text/plain;charset=utf-8' }), createExportFilename('txt'))
      toast.warning(`没有可导出的完整认证 JSON，已改为导出 ${tokens.length} 个 Access Token`)
    } finally {
      exportBusy.value = false
    }
  }

  // ── watchers / lifecycle ────────────────────────────────────────
  watch(
    [keyword, statusFilter, groupFilter, sourceFilter],
    () => {
      clearSelection()
      if (currentPage.value !== 1) {
        resetToFirst()
        return
      }
      scheduleListReload(200)
    },
  )

  watch(pageSize, () => {
    clearSelection()
    // pageSize 偏好与回第一页由 usePagedList 处理；已在第 1 页时需主动重载
    if (currentPage.value === 1) scheduleListReload()
  })

  watch(currentPage, () => {
    clearSelection()
    scheduleListReload()
  })

  onMounted(async () => {
    viewMode.value = normalizeAccountsViewMode(getStringPreference(preferenceKeys.accountsViewMode))
    await Promise.all([
      loadData({ silentErrorToast: true }),
      loadAccountGroups({ silentErrorToast: true }),
    ])
    enableListWatch()
  })

  onActivated(() => {
    if (!hasActivatedOnce) {
      hasActivatedOnce = true
      return
    }
    if (showModal.value || showImportModal.value || showAccountGroupsModal.value) return
    if (saving.value || batchBusy.value || importBusy.value || accountGroupsLoading.value || accountGroupSaving.value) return
    void loadData({ silentErrorToast: true })
    void loadAccountGroups({ silentErrorToast: true })
  })

  return {
    loading,
    saving,
    showModal,
    keyword,
    statusFilter,
    groupFilter,
    sourceFilter,
    statusFilterOptions,
    sourceFilterOptions,
    channelTabOptions,
    applyChannelCounts,
    setSourceFilter,
    groupFilterOptions,
    editingId,
    accounts,
    accountListTotal,
    accountAllTotal,
    selectedIds,
    selectedCount,
    abnormalAccountCount,
    allVisibleSelected,
    currentPage,
    pageSize,
    pageSizeOptions,
    pageCount,
    batchBusy,
    batchActionLabel,
    viewMode,
    effectiveViewMode,
    refreshingAccountId,
    resettingAccountId,
    reloginAccountId,
    importBusy,
    exportBusy,
    showImportModal,
    importMode,
    importModeOptions,
    importModeSections,
    manualTokenText,
    sessionJsonText,
    fireflyCookieText,
    accountGroups,
    proxyGroups,
    accountGroupsLoading,
    showAccountGroupsModal,
    accountGroupSaving,
    editingAccountGroupId,
    accountGroupForm,
    accountGroupOptions,
    accountGroupProxyOptions,
    bindAccountGroupOptions,
    selectedBindGroupId,
    proxyTesting,
    proxyMode,
    accountGroupProxyMode,
    accountProxyModeOptions,
    proxyGroupOptions,
    selectedProxyGroupId,
    customProxyInput,
    selectedAccountGroupProxyGroupId,
    accountGroupCustomProxyInput,
    accountProxyPreview,
    accountGroupProxyPreview,
    showRefreshProgress,
    refreshProgressTitle,
    refreshProgress,
    refreshProgressPercent,
    refreshProgressMetricLabel,
    refreshProgressMetricValue,
    refreshProgressStatusText,
    canStopRefreshProgress,
    bulkStopRequested,
    accountStatusOptions,
    accountSourceTypeOptions,
    isFireflyForm,
    editingFireflyCreditsText,
    form,
    filteredAccounts,
    pagedAccounts,
    setViewMode,
    isSelected,
    toggleSelect,
    clearSelection,
    toggleSelectAllVisible,
    setImportMode,
    openImportModal,
    closeImportModal,
    loadAccountGroups,
    openAccountGroupsModal,
    closeAccountGroupsModal,
    resetAccountGroupForm,
    editAccountGroup,
    saveAccountGroup,
    deleteAccountGroup,
    testAccountProxy,
    setProxyMode,
    selectProxyGroup,
    setCustomProxyInput,
    setAccountGroupProxyMode,
    selectAccountGroupProxyGroup,
    setAccountGroupCustomProxyInput,
    importManualTokenText,
    importTokenTextFile,
    importSessionJson,
    importLocalCPAFiles,
    importFireflyCookieText,
    importFireflyCookieFile,
    refreshAllAccounts,
    refreshSelectedAccounts,
    requestStopRefreshProgress,
    closeRefreshProgress,
    loadData,
    copyAccountToken,
    openCreateModal,
    openEditModal,
    closeModal,
    saveAccount,
    toggleEnabled,
    refreshToken,
    reloginAccount,
    resetAccountState,
    removeAccount,
    runBulkAction,
    bindSelectedAccountsToGroup,
    exportAccounts,
  }
}
