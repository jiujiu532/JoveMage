import { onMounted, onUnmounted, ref, type Ref } from 'vue'

/**
 * 监听 CSS media query，返回响应式 matches。
 * 在 onMounted 绑定、onUnmounted 解绑，SSR 安全（初始 false）。
 */
export function useMediaQuery(query: string): Ref<boolean> {
  const matches = ref(false)
  let mql: MediaQueryList | null = null

  const sync = (list: MediaQueryList | MediaQueryListEvent) => {
    matches.value = list.matches
  }

  onMounted(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    mql = window.matchMedia(query)
    matches.value = mql.matches
    if (typeof mql.addEventListener === 'function') {
      mql.addEventListener('change', sync)
    } else {
      // Safari < 14
      mql.addListener(sync)
    }
  })

  onUnmounted(() => {
    if (!mql) return
    if (typeof mql.removeEventListener === 'function') {
      mql.removeEventListener('change', sync)
    } else {
      mql.removeListener(sync)
    }
    mql = null
  })

  return matches
}

/** 窄屏断点，与组件内 @media (max-width: 640px) 对齐 */
export function useIsNarrow(maxWidthPx = 640): Ref<boolean> {
  return useMediaQuery(`(max-width: ${maxWidthPx}px)`)
}

/** 无精细指针（触控为主） */
export function useIsCoarsePointer(): Ref<boolean> {
  return useMediaQuery('(hover: none), (pointer: coarse)')
}
