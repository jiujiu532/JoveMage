import { computed, ref } from 'vue'
import { accountsApi } from '@/api/accounts'
import type { Account, AccountListParams } from '@/api/accounts'
import { usePagedList } from '@/composables/usePagedList'
import {
  buildChannelTabOptions,
  listChannels,
  resolveAccountChannelId,
} from '@/config/channels'
import { preferenceKeys } from '@/lib/preferences'
import { type AccountStatusFilter } from './viewUtils'
import {
  ACCOUNT_PAGE_SIZE_OPTIONS,
  DEFAULT_PAGE_SIZE,
  type SetErrorFn,
} from './accountPageShared'

export type UseAccountListQueryOptions = {
  setError: SetErrorFn
  /** loadData 后裁剪选中集；由编排层注入，避免与 selection 循环依赖 */
  pruneSelection?: (ids: string[]) => void
}

export type AccountChannelFilter = 'all' | string

/**
 * 账号列表：筛选、分页、加载与静默重载。
 * groupFilterOptions 依赖账号组，放在 useAccountGroups 侧避免循环依赖。
 */
export function useAccountListQuery(options: UseAccountListQueryOptions) {
  const { setError } = options

  const loading = ref(false)
  const keyword = ref('')
  const statusFilter = ref<AccountStatusFilter>('all')
  const groupFilter = ref('all')
  /** 渠道 Tab：all | chatgpt | firefly | 未来渠道 id；筛选参数仍走 source_type */
  const sourceFilter = ref<AccountChannelFilter>('all')
  /**
   * 渠道计数：优先用后端 /api/channels.account_count；
   * 未就绪时用最近一次列表结果的弱提示。
   */
  const channelCounts = ref<Record<string, number>>({})
  const {
    page: currentPage,
    pageSize,
    pageCount,
    totalCount: accountListTotal,
    pageSizeOptions,
    resetToFirst,
  } = usePagedList({
    defaultPageSize: DEFAULT_PAGE_SIZE,
    pageSizeOptions: ACCOUNT_PAGE_SIZE_OPTIONS,
    preferenceKey: preferenceKeys.accountsPageSize,
    mode: 'page',
  })
  const accounts = ref<Account[]>([])
  const accountAllTotal = ref(0)

  let listReloadTimer: number | undefined
  let listWatchReady = false

  const filteredAccounts = computed(() => accounts.value)
  const pagedAccounts = computed(() => accounts.value)

  const statusFilterOptions = [
    { label: '全部状态', value: 'all' },
    { label: '正常', value: 'normal' },
    { label: '受限', value: 'limited' },
    { label: '异常', value: 'abnormal' },
    { label: '禁用', value: 'disabled' },
  ] as const

  /**
   * 顶部渠道 Tab 选项：从 channels.ts 数据驱动。
   * 将来 setChannelsFromApi 后自动出现新渠道，无需改本文件。
   */
  const channelTabOptions = computed(() => {
    const counts: Record<string, number> = { ...channelCounts.value }
    if (sourceFilter.value === 'all') {
      counts.all = accountAllTotal.value || accountListTotal.value
    } else if (sourceFilter.value) {
      counts[sourceFilter.value] = accountListTotal.value
      if (counts.all == null) counts.all = accountAllTotal.value || accountListTotal.value
    }
    return buildChannelTabOptions(counts)
  })

  /** 兼容旧名：下拉筛选项（若别处仍引用） */
  const sourceFilterOptions = computed(() =>
    channelTabOptions.value.map((item) => ({ label: item.label, value: item.value })),
  )

  function accountListParams(): AccountListParams {
    return {
      page: currentPage.value,
      page_size: pageSize.value,
      keyword: keyword.value.trim(),
      status: statusFilter.value,
      group_id: groupFilter.value,
      // 渠道过滤交给后端，避免仅页内过滤导致 total/分页失真
      source_type: sourceFilter.value,
    }
  }

  function scheduleListReload(delay = 0) {
    if (!listWatchReady) return
    if (listReloadTimer !== undefined) {
      window.clearTimeout(listReloadTimer)
    }
    listReloadTimer = window.setTimeout(() => {
      listReloadTimer = undefined
      void loadData({ silentErrorToast: true })
    }, delay)
  }

  function estimateChannelCountsFromPage(rows: Account[], allTotal: number, listTotal: number, filter: string) {
    const next = { ...channelCounts.value }
    if (filter === 'all') {
      next.all = allTotal || listTotal
      const local: Record<string, number> = {}
      for (const row of rows) {
        const channelId = resolveAccountChannelId(row.source_type)
        local[channelId] = (local[channelId] || 0) + 1
      }
      for (const channel of listChannels()) {
        if (local[channel.id] != null) {
          next[channel.id] = Math.max(next[channel.id] || 0, local[channel.id])
        }
      }
    } else if (filter) {
      next[filter] = listTotal
      if (allTotal > 0) next.all = allTotal
    }
    channelCounts.value = next
  }

  /**
   * 注入后端渠道计数（将来 /api/channels 或 list.channel_counts）。
   * 主 agent 接好接口后调用即可。
   */
  function applyChannelCounts(counts: Record<string, number> | undefined | null) {
    if (!counts || typeof counts !== 'object') return
    channelCounts.value = { ...channelCounts.value, ...counts }
  }

  async function loadData(loadOptions?: { silentErrorToast?: boolean }) {
    loading.value = true
    try {
      const res = await accountsApi.list(accountListParams())
      const nextAccounts = (res.accounts || []).map((item) => ({
        ...item,
        lanes: Array.isArray(item.lanes) ? item.lanes : [],
        model_ids: {
          fast: item.model_ids?.fast || '',
          thinking: item.model_ids?.thinking || '',
          pro: item.model_ids?.pro || '',
        },
      }))
      accountListTotal.value = Number(res.total ?? nextAccounts.length ?? 0)
      accountAllTotal.value = Number(res.all_total ?? 0)
      accounts.value = nextAccounts
      estimateChannelCountsFromPage(
        nextAccounts,
        accountAllTotal.value,
        accountListTotal.value,
        sourceFilter.value,
      )
      options.pruneSelection?.(accounts.value.map((item) => item.id))
    } catch (error) {
      setError('加载失败', error, !loadOptions?.silentErrorToast)
    } finally {
      loading.value = false
    }
  }

  function enableListWatch() {
    listWatchReady = true
  }

  function setSourceFilter(value: AccountChannelFilter | string) {
    const next = String(value || 'all').trim() || 'all'
    if (sourceFilter.value === next) return
    sourceFilter.value = next
    resetToFirst()
  }

  return {
    loading,
    keyword,
    statusFilter,
    groupFilter,
    sourceFilter,
    channelCounts,
    statusFilterOptions,
    sourceFilterOptions,
    channelTabOptions,
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
    accountListParams,
    scheduleListReload,
    loadData,
    enableListWatch,
    applyChannelCounts,
    setSourceFilter,
  }
}
