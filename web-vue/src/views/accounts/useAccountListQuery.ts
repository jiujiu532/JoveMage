import { computed, ref } from 'vue'
import { accountsApi } from '@/api/accounts'
import type { Account, AccountListParams } from '@/api/accounts'
import { usePagedList } from '@/composables/usePagedList'
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
  const sourceFilter = ref<'all' | 'chatgpt' | 'firefly'>('all')
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

  const sourceFilterOptions = [
    { label: '全部渠道', value: 'all' },
    { label: 'ChatGPT', value: 'chatgpt' },
    { label: 'Firefly', value: 'firefly' },
  ] as const

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

  return {
    loading,
    keyword,
    statusFilter,
    groupFilter,
    sourceFilter,
    statusFilterOptions,
    sourceFilterOptions,
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
  }
}
