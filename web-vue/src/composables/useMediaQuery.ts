import { onMounted, onUnmounted, ref, type Ref } from 'vue'

/**
 * 监听 CSS media query，返回响应式 matches。
 * setup 阶段即同步一次当前匹配（避免首帧 false 闪动），onUnmounted 解绑；SSR 守卫初始 false。
 */
export function useMediaQuery(query: string): Ref<boolean> {
  const supported = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
  const initial = supported ? window.matchMedia(query) : null
  const matches = ref(initial ? initial.matches : false)
  let mql: MediaQueryList | null = initial

  const sync = (list: MediaQueryList | MediaQueryListEvent) => {
    matches.value = list.matches
  }

  onMounted(() => {
    if (!supported) return
    if (!mql) mql = window.matchMedia(query)
    // 双保险：若挂载时与 setup 之间发生过变化，再同步一次
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
