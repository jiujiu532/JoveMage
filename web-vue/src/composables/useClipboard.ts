import { useToast } from '@/composables/useToast'

export type ClipboardCopyOptions = {
  success?: string
  error?: string
  silent?: boolean
}

async function writeClipboardText(text: string): Promise<void> {
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }

  const input = document.createElement('textarea')
  input.value = text
  input.setAttribute('readonly', 'readonly')
  input.style.position = 'fixed'
  input.style.left = '-9999px'
  input.style.top = '0'
  document.body.appendChild(input)
  input.focus()
  input.select()
  input.setSelectionRange(0, input.value.length)
  const copied = document.execCommand('copy')
  document.body.removeChild(input)
  if (!copied) throw new Error('execCommand copy failed')
}

export function useClipboard() {
  const toast = useToast()

  async function copy(text: string, opts?: ClipboardCopyOptions): Promise<boolean> {
    const value = String(text ?? '')
    if (!value) return false

    try {
      await writeClipboardText(value)
      if (!opts?.silent) {
        toast.success(opts?.success ?? '已复制')
      }
      return true
    } catch (error) {
      console.error('Copy failed', error)
      if (!opts?.silent) {
        toast.error(opts?.error ?? '复制失败')
      }
      return false
    }
  }

  return { copy }
}
