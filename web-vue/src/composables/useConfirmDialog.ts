import { ref } from 'vue'

type ConfirmOptions = {
  title?: string
  message: string
  confirmText?: string
  cancelText?: string
}

// Global singleton state: all callers share the same dialog instance.
const open = ref(false)
const title = ref('确认操作')
const message = ref('')
const confirmText = ref('确定')
const cancelText = ref('取消')
let resolver: ((value: boolean) => void) | null = null
/** 串行化并发 ask，避免后一次覆盖前一次 resolver 导致 Promise 挂起 */
let askQueue: Promise<unknown> = Promise.resolve()

export function useConfirmDialog() {
  const ask = (options: ConfirmOptions) => {
    const run = () =>
      new Promise<boolean>((resolve) => {
        title.value = options.title || '确认操作'
        message.value = options.message
        confirmText.value = options.confirmText || '确定'
        cancelText.value = options.cancelText || '取消'
        open.value = true
        resolver = resolve
      })

    const result = askQueue.then(run, run)
    // 无论确认/取消，都推进队列
    askQueue = result.then(
      () => undefined,
      () => undefined,
    )
    return result
  }

  const confirm = () => {
    open.value = false
    const resolve = resolver
    resolver = null
    resolve?.(true)
  }

  const cancel = () => {
    open.value = false
    const resolve = resolver
    resolver = null
    resolve?.(false)
  }

  return {
    open,
    title,
    message,
    confirmText,
    cancelText,
    ask,
    confirm,
    cancel,
  }
}
