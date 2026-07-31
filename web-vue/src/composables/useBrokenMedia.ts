import { ref, type Ref } from 'vue'

export type UseBrokenMediaReturn = {
  brokenSet: Ref<Set<string>>
  isBroken: (key: string) => boolean
  markBroken: (event: Event, key: string) => void
  reset: () => void
}

/**
 * 媒体预览加载失败标记：@error 时淡出元素并记入 Set，供 isBroken 判断 fallback。
 */
export function useBrokenMedia(): UseBrokenMediaReturn {
  const brokenSet = ref<Set<string>>(new Set())

  function isBroken(key: string): boolean {
    return brokenSet.value.has(key)
  }

  function markBroken(event: Event, key: string) {
    const img = event.target as HTMLImageElement
    img.style.opacity = '0'
    brokenSet.value = new Set([...brokenSet.value, key])
  }

  function reset() {
    brokenSet.value = new Set()
  }

  return {
    brokenSet,
    isBroken,
    markBroken,
    reset,
  }
}
