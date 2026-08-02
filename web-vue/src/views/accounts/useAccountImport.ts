import { ref, type Ref } from 'vue'
import { accountsApi } from '@/api/accounts'
import type { AccountRefreshProgress } from '@/api/accounts'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useToast } from '@/composables/useToast'
import {
  IMPORT_BATCH_SIZE,
  normalizeErrorMessage,
  parseCPAJsonTokens,
  parseSessionJsonTokens,
  parseTokenLines,
  uniqueTokens,
  type BulkProgressKind,
  type SetErrorFn,
} from './accountPageShared'

export type AccountImportMode =
  | 'access_token'
  | 'session_json'
  | 'cpa_json'
  | 'remote_cpa'
  | 'sub2api'
  | 'firefly_cookie'

export type UseAccountImportOptions = {
  setError: SetErrorFn
  loadData: (options?: { silentErrorToast?: boolean }) => Promise<void>
  openBulkProgress: (title: string, total: number, kind: BulkProgressKind) => void
  bulkStopRequested: Ref<boolean>
  refreshProgress: Ref<AccountRefreshProgress | null>
  batchBusy: Ref<boolean>
  batchActionLabel: Ref<string>
}

/**
 * 多模式账号导入：ChatGPT token/session/CPA + Firefly Cookie，复用 bulk 进度 UI。
 */
export function useAccountImport(options: UseAccountImportOptions) {
  const {
    setError,
    loadData,
    openBulkProgress,
    bulkStopRequested,
    refreshProgress,
    batchBusy,
    batchActionLabel,
  } = options
  const toast = useToast()
  const confirmDialog = useConfirmDialog()

  const importBusy = ref(false)
  const showImportModal = ref(false)
  const importMode = ref<AccountImportMode>('access_token')
  const manualTokenText = ref('')
  const sessionJsonText = ref('')
  const fireflyCookieText = ref('')

  /** 侧栏分组：ChatGPT 与 Firefly 分列，避免混用导入格式 */
  const importModeSections: Array<{
    key: string
    title: string
    options: Array<{ label: string; value: AccountImportMode }>
  }> = [
    {
      key: 'chatgpt',
      title: 'ChatGPT',
      options: [
        { label: '导入 Access Token', value: 'access_token' },
        { label: '导入 Session JSON', value: 'session_json' },
        { label: '导入 CPA JSON 文件', value: 'cpa_json' },
        { label: '从远程 CPA 服务器导入', value: 'remote_cpa' },
        { label: '从 Sub2API 服务器导入', value: 'sub2api' },
      ],
    },
    {
      key: 'firefly',
      title: 'Firefly',
      options: [
        { label: '导入 Express Cookie', value: 'firefly_cookie' },
      ],
    },
  ]

  const importModeOptions = importModeSections.flatMap((section) => section.options)

  function setImportMode(mode: AccountImportMode) {
    importMode.value = mode
  }

  async function openImportModal(mode: AccountImportMode = 'access_token') {
    showImportModal.value = true
    setImportMode(mode)
  }

  function closeImportModal() {
    if (importBusy.value) return
    showImportModal.value = false
  }

  async function promptRemoveImportedAbnormalAccounts(importedTokens: string[], errorCount: number) {
    if (errorCount <= 0 || bulkStopRequested.value) return

    let preview: Awaited<ReturnType<typeof accountsApi.cleanupImportedAbnormalAccounts>>
    try {
      preview = await accountsApi.cleanupImportedAbnormalAccounts(importedTokens, false)
    } catch (error) {
      setError('检查本次异常账号失败，已先保留', error)
      return
    }

    if (!preview.abnormal) {
      toast.info('本次导入有刷新异常，但没有找到可清理的异常账号，可能未写入本地或状态已变化')
      return
    }

    const confirmed = await confirmDialog.ask({
      title: '移除本次异常账号？',
      message: `本次导入刷新返回 ${errorCount} 条异常。\n后端确认 ${preview.abnormal} 个本次导入账号当前状态为异常，是否直接删除？\n\n只会删除本次导入且状态为异常的账号，正常、限流和历史账号会保留。`,
      confirmText: `删除 ${preview.abnormal} 个`,
      cancelText: '先保留',
    })

    if (!confirmed) return

    try {
      const result = await accountsApi.cleanupImportedAbnormalAccounts(importedTokens, true)
      toast.success(`已移除 ${result.removed || 0} 个本次异常账号`)
    } catch (error) {
      setError('移除本次异常账号失败', error)
    } finally {
      await loadData({ silentErrorToast: true })
    }
  }

  async function importTokenBatch(tokens: string[], sourceType: string, title: string) {
    const normalizedTokens = uniqueTokens(tokens)
    if (!normalizedTokens.length) {
      toast.warning('没有可导入的 access token')
      return
    }

    const confirmed = await confirmDialog.ask({
      title,
      message: `即将导入 ${normalizedTokens.length} 个账号，已存在账号会刷新远端信息。是否继续？`,
      confirmText: '确认导入',
      cancelText: '取消',
    })
    if (!confirmed) return

    importBusy.value = true
    batchBusy.value = true
    batchActionLabel.value = title
    openBulkProgress(title, normalizedTokens.length, 'mutation')
    let addedCount = 0
    let skippedCount = 0
    let refreshedCount = 0
    let processed = 0
    const errors: string[] = []
    try {
      for (let index = 0; index < normalizedTokens.length; index += IMPORT_BATCH_SIZE) {
        if (bulkStopRequested.value) break
        const batch = normalizedTokens.slice(index, index + IMPORT_BATCH_SIZE)
        try {
          const result = await accountsApi.importAccounts(
            batch.map((accessToken) => ({
              access_token: accessToken,
              type: 'free',
              source_type: sourceType,
            })),
            sourceType,
            { refresh: true, returnItems: false },
          )
          addedCount += Number(result.added || 0)
          skippedCount += Number(result.skipped || 0)
          refreshedCount += Number(result.refreshed || 0)
          errors.push(...(Array.isArray(result.errors) ? result.errors.filter(Boolean) : []))
        } catch (error) {
          errors.push(`${batch[0]?.slice(0, 6) || '-'}... 等 ${batch.length} 个账号：${normalizeErrorMessage(error)}`)
        } finally {
          processed = Math.min(normalizedTokens.length, processed + batch.length)
          refreshProgress.value = {
            ...(refreshProgress.value || { total: normalizedTokens.length }),
            total: normalizedTokens.length,
            processed,
            done: processed >= normalizedTokens.length,
            total_quota: 0,
          }
        }
      }

      await loadData({ silentErrorToast: true })
      const stopped = bulkStopRequested.value && processed < normalizedTokens.length
      refreshProgress.value = {
        ...(refreshProgress.value || { total: normalizedTokens.length, processed }),
        total: normalizedTokens.length,
        processed,
        done: true,
        total_quota: 0,
      }
      if (stopped) {
        toast.warning(`${title}已停止：已处理 ${processed}/${normalizedTokens.length} 个`)
      } else if (errors.length > 0) {
        toast.warning(`${title}完成：新增 ${addedCount}，跳过 ${skippedCount}，刷新 ${refreshedCount}，失败 ${errors.length}`)
      } else {
        toast.success(`${title}完成：新增 ${addedCount}，跳过 ${skippedCount}，刷新 ${refreshedCount}`)
      }
      if (addedCount + skippedCount + refreshedCount > 0) {
        manualTokenText.value = ''
        sessionJsonText.value = ''
      }
      if (!stopped && errors.length > 0) {
        await promptRemoveImportedAbnormalAccounts(normalizedTokens, errors.length)
      }
    } catch (error) {
      refreshProgress.value = {
        ...(refreshProgress.value || { total: normalizedTokens.length, processed }),
        total: normalizedTokens.length,
        processed,
        done: true,
        error: normalizeErrorMessage(error),
        total_quota: 0,
      }
      setError(`${title}失败`, error)
    } finally {
      importBusy.value = false
      batchBusy.value = false
      batchActionLabel.value = ''
    }
  }

  /**
   * Firefly：一行一个 Express Cookie（或 cookie JSON 里的 cookie 字段）。
   * 后端用 cookie 走 IMS 换 access_token，不走 ChatGPT OAuth 刷新。
   */
  async function importFireflyCookieBatch(cookies: string[], title = '导入 Express Cookie') {
    const normalizedCookies = uniqueTokens(cookies)
    if (!normalizedCookies.length) {
      toast.warning('没有可导入的 Express Cookie')
      return
    }

    const confirmed = await confirmDialog.ask({
      title,
      message: `即将导入 ${normalizedCookies.length} 个 Firefly 账号。Cookie 会在服务端换取 access_token；已存在账号会按 token 去重跳过。是否继续？`,
      confirmText: '确认导入',
      cancelText: '取消',
    })
    if (!confirmed) return

    importBusy.value = true
    batchBusy.value = true
    batchActionLabel.value = title
    openBulkProgress(title, normalizedCookies.length, 'mutation')
    let addedCount = 0
    let skippedCount = 0
    let refreshedCount = 0
    let processed = 0
    const errors: string[] = []
    try {
      for (let index = 0; index < normalizedCookies.length; index += IMPORT_BATCH_SIZE) {
        if (bulkStopRequested.value) break
        const batch = normalizedCookies.slice(index, index + IMPORT_BATCH_SIZE)
        try {
          const result = await accountsApi.importAccounts(
            batch.map((cookie) => ({
              cookie,
              type: 'firefly',
              source_type: 'firefly',
            })),
            'firefly',
            // Firefly 创建时后端会跳过 ChatGPT refresh；cookie→token 已在 normalize 完成
            { refresh: false, returnItems: false },
          )
          addedCount += Number(result.added || 0)
          skippedCount += Number(result.skipped || 0)
          refreshedCount += Number(result.refreshed || 0)
          errors.push(...(Array.isArray(result.errors) ? result.errors.filter(Boolean) : []))
        } catch (error) {
          errors.push(`${batch[0]?.slice(0, 10) || '-'}... 等 ${batch.length} 个：${normalizeErrorMessage(error)}`)
        } finally {
          processed = Math.min(normalizedCookies.length, processed + batch.length)
          refreshProgress.value = {
            ...(refreshProgress.value || { total: normalizedCookies.length }),
            total: normalizedCookies.length,
            processed,
            done: processed >= normalizedCookies.length,
            total_quota: 0,
          }
        }
      }

      await loadData({ silentErrorToast: true })
      const stopped = bulkStopRequested.value && processed < normalizedCookies.length
      refreshProgress.value = {
        ...(refreshProgress.value || { total: normalizedCookies.length, processed }),
        total: normalizedCookies.length,
        processed,
        done: true,
        total_quota: 0,
      }
      if (stopped) {
        toast.warning(`${title}已停止：已处理 ${processed}/${normalizedCookies.length} 个`)
      } else if (errors.length > 0) {
        toast.warning(`${title}完成：新增 ${addedCount}，跳过 ${skippedCount}，失败 ${errors.length}`)
      } else {
        toast.success(`${title}完成：新增 ${addedCount}，跳过 ${skippedCount}`)
      }
      if (addedCount + skippedCount + refreshedCount > 0) {
        fireflyCookieText.value = ''
      }
    } catch (error) {
      refreshProgress.value = {
        ...(refreshProgress.value || { total: normalizedCookies.length, processed }),
        total: normalizedCookies.length,
        processed,
        done: true,
        error: normalizeErrorMessage(error),
        total_quota: 0,
      }
      setError(`${title}失败`, error)
    } finally {
      importBusy.value = false
      batchBusy.value = false
      batchActionLabel.value = ''
    }
  }

  async function importManualTokenText() {
    await importTokenBatch(parseTokenLines(manualTokenText.value), 'manual', '导入 Access Token')
  }

  async function importTokenTextFile(file: File | null | undefined) {
    if (!file) return
    const text = await file.text()
    manualTokenText.value = text
    await importManualTokenText()
  }

  async function importSessionJson() {
    await importTokenBatch(parseSessionJsonTokens(sessionJsonText.value), 'session_json', '导入 Session JSON')
  }

  async function importLocalCPAFiles(files: FileList | File[] | null | undefined) {
    const fileList = Array.from(files || [])
    if (!fileList.length) return
    importBusy.value = true
    try {
      const tokens: string[] = []
      for (const file of fileList) {
        const text = await file.text()
        tokens.push(...parseCPAJsonTokens(text, file.name))
      }
      importBusy.value = false
      await importTokenBatch(tokens, 'cpa_json', '导入 CPA JSON 文件')
    } catch (error) {
      setError('导入 CPA JSON 文件失败', error)
    } finally {
      importBusy.value = false
    }
  }

  async function importFireflyCookieText() {
    await importFireflyCookieBatch(parseTokenLines(fireflyCookieText.value), '导入 Express Cookie')
  }

  async function importFireflyCookieFile(file: File | null | undefined) {
    if (!file) return
    const text = await file.text()
    fireflyCookieText.value = text
    await importFireflyCookieText()
  }

  return {
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
  }
}
