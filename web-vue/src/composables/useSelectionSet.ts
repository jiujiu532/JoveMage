import { computed, ref, type ComputedRef, type Ref } from 'vue'

export type UseSelectionSetOptions<T extends string | number> = {
  /** 当前页/当前可见且可选的 id；用于 allVisibleSelected 与 toggleAllVisible */
  getVisibleIds?: () => T[]
}

export type UseSelectionSetReturn<T extends string | number> = {
  selected: Ref<T[]>
  selectedSet: ComputedRef<Set<T>>
  selectedCount: ComputedRef<number>
  allVisibleSelected: ComputedRef<boolean>
  isSelected: (id: T) => boolean
  toggle: (id: T, checked?: boolean) => void
  toggleAllVisible: (checked?: boolean) => void
  clear: () => void
  prune: (validIds: (() => T[]) | Set<T> | T[]) => void
}

function toIdSet<T extends string | number>(validIds: (() => T[]) | Set<T> | T[]): Set<T> {
  if (typeof validIds === 'function') return new Set(validIds())
  if (validIds instanceof Set) return validIds
  return new Set(validIds)
}

/**
 * 通用多选集合：内部 ref 数组 + computed Set，统一 toggle / 全选可见 / prune。
 */
export function useSelectionSet<T extends string | number>(
  opts?: UseSelectionSetOptions<T>,
): UseSelectionSetReturn<T> {
  const selected = ref<T[]>([]) as Ref<T[]>

  const selectedSet = computed(() => new Set(selected.value))

  const selectedCount = computed(() => selected.value.length)

  const allVisibleSelected = computed(() => {
    const visible = opts?.getVisibleIds?.() ?? []
    if (!visible.length) return false
    const set = selectedSet.value
    return visible.every((id) => set.has(id))
  })

  function isSelected(id: T): boolean {
    return selectedSet.value.has(id)
  }

  function toggle(id: T, checked?: boolean) {
    const next = new Set(selected.value)
    const shouldSelect = typeof checked === 'boolean' ? checked : !next.has(id)
    if (shouldSelect) next.add(id)
    else next.delete(id)
    selected.value = Array.from(next)
  }

  function toggleAllVisible(checked?: boolean) {
    const ids = opts?.getVisibleIds?.() ?? []
    const next = new Set(selected.value)
    const shouldSelect = typeof checked === 'boolean' ? checked : !allVisibleSelected.value
    for (const id of ids) {
      if (shouldSelect) next.add(id)
      else next.delete(id)
    }
    selected.value = Array.from(next)
  }

  function clear() {
    selected.value = []
  }

  function prune(validIds: (() => T[]) | Set<T> | T[]) {
    if (selected.value.length === 0) return
    const valid = toIdSet(validIds)
    selected.value = selected.value.filter((id) => valid.has(id))
  }

  return {
    selected,
    selectedSet,
    selectedCount,
    allVisibleSelected,
    isSelected,
    toggle,
    toggleAllVisible,
    clear,
    prune,
  }
}
