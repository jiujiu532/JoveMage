import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'
import { getNumberPreference, preferenceKeys, setNumberPreference } from '@/lib/preferences'

type PreferenceKey = (typeof preferenceKeys)[keyof typeof preferenceKeys]

export type UsePagedListMode = 'page' | 'offset'

export type UsePagedListOptions = {
  /** 默认每页条数 */
  defaultPageSize: number
  /** 可选每页条数；若提供则作为 preference 的 allowed 白名单 */
  pageSizeOptions?: readonly number[]
  /** localStorage 偏好键（get/setNumberPreference）；不传则不持久化 */
  preferenceKey?: PreferenceKey
  /**
   * page：请求用 page / page_size（Accounts / Gallery）
   * offset：请求用 limit / offset（Logs）
   * 两种模式都暴露 page + offset，mode 仅作语义标记
   */
  mode?: UsePagedListMode
  /** 无 pageSizeOptions 时的下限（传给 getNumberPreference） */
  minPageSize?: number
  /** 无 pageSizeOptions 时的上限（传给 getNumberPreference） */
  maxPageSize?: number
}

export type UsePagedListReturn = {
  page: Ref<number>
  pageSize: Ref<number>
  /** 由 totalCount / pageSize 计算，至少为 1 */
  pageCount: ComputedRef<number>
  /** (page - 1) * pageSize，供 offset 模式 API */
  offset: ComputedRef<number>
  /** 列表总条数；调用方在加载后写入 */
  totalCount: Ref<number>
  pageSizeOptions: number[]
  mode: UsePagedListMode
  /** 将 page 重置为 1（筛选变更时用） */
  resetToFirst: () => void
}

/**
 * 列表分页状态：page / pageSize / pageCount / offset + 可选偏好持久化。
 * 不负责发请求；调用方 watch page/pageSize 后自行加载。
 */
export function usePagedList(options: UsePagedListOptions): UsePagedListReturn {
  const {
    defaultPageSize,
    pageSizeOptions,
    preferenceKey,
    mode = 'page',
    minPageSize,
    maxPageSize,
  } = options

  const resolvedOptions = pageSizeOptions?.length
    ? [...pageSizeOptions]
    : [20, 50, 100]

  const page = ref(1)
  const totalCount = ref(0)
  const pageSize = ref(
    preferenceKey
      ? getNumberPreference(preferenceKey, defaultPageSize, {
          allowed: pageSizeOptions,
          min: minPageSize,
          max: maxPageSize,
        })
      : defaultPageSize,
  )

  const pageCount = computed(() =>
    Math.max(1, Math.ceil(totalCount.value / Math.max(1, pageSize.value))),
  )

  const offset = computed(() =>
    Math.max(0, (Math.max(1, page.value) - 1) * Math.max(1, pageSize.value)),
  )

  function resetToFirst() {
    page.value = 1
  }

  watch(pageSize, (value) => {
    if (preferenceKey) setNumberPreference(preferenceKey, value)
    if (page.value !== 1) page.value = 1
  })

  watch(pageCount, (count) => {
    if (page.value > count) page.value = count
    if (page.value < 1) page.value = 1
  })

  return {
    page,
    pageSize,
    pageCount,
    offset,
    totalCount,
    pageSizeOptions: resolvedOptions,
    mode,
    resetToFirst,
  }
}
