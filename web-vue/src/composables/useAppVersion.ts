import { computed, ref } from 'vue'
import { versionApi } from '@/api/version'
import { useToast } from '@/composables/useToast'
import {
  FALLBACK_RELEASES,
  isNewerVersion,
  normalizeVersionTag,
  parseGithubReleases,
  type ReleaseInfo,
} from '@/lib/release'
import localVersion from '../../../VERSION?raw'

const releasePageUrl = 'https://github.com/jiujiu532/JoveMage/releases'
const latestVersionUrl = 'https://raw.githubusercontent.com/jiujiu532/JoveMage/main/VERSION'
const latestReleasesApiUrl = 'https://api.github.com/repos/jiujiu532/JoveMage/releases?per_page=20'
const updateCheckingMessage = '正在检查云端版本...'

async function fetchRemoteText(url: string) {
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), 8000)
  try {
    const response = await fetch(url, { cache: 'no-store', signal: controller.signal })
    if (!response.ok) throw new Error(`云端返回 ${response.status}`)
    return response.text()
  } finally {
    window.clearTimeout(timeoutId)
  }
}

async function fetchRemoteJson(url: string) {
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), 8000)
  try {
    const response = await fetch(url, {
      cache: 'no-store',
      signal: controller.signal,
      headers: { Accept: 'application/vnd.github+json' },
    })
    if (!response.ok) throw new Error(`云端返回 ${response.status}`)
    return response.json()
  } finally {
    window.clearTimeout(timeoutId)
  }
}

/** 当前版本、检查更新、release notes 与更新提示 */
export function useAppVersion() {
  const toast = useToast()
  const isUpdateDialogOpen = ref(false)
  const isCheckingUpdate = ref(false)
  const currentVersionTag = ref(normalizeVersionTag(localVersion))
  const latestVersionTag = ref('')
  const releaseEntries = ref<ReleaseInfo[]>([])
  const updateCheckMessage = ref('')

  const currentVersionLabel = computed(() => normalizeVersionTag(currentVersionTag.value || ''))
  const latestVersionLabel = computed(() =>
    normalizeVersionTag(latestVersionTag.value || releaseEntries.value[0]?.version || currentVersionTag.value || ''),
  )
  const versionButtonText = computed(() => currentVersionLabel.value || '版本')

  async function loadLocalReleaseEntries() {
    if (releaseEntries.value.length) return
    releaseEntries.value = FALLBACK_RELEASES
  }

  async function loadCurrentVersion() {
    try {
      const result = await versionApi.current()
      currentVersionTag.value = String(result.tag || '').trim()
      if (!latestVersionTag.value) {
        latestVersionTag.value = normalizeVersionTag(releaseEntries.value[0]?.version || currentVersionTag.value)
      }
    } catch {
      currentVersionTag.value = ''
      if (!latestVersionTag.value) {
        latestVersionTag.value = normalizeVersionTag(releaseEntries.value[0]?.version || '')
      }
    }
  }

  async function checkForUpdates(showMessage = true) {
    if (isCheckingUpdate.value) return
    isCheckingUpdate.value = true
    updateCheckMessage.value = updateCheckingMessage
    try {
      const [version, releasesPayload] = await Promise.all([
        fetchRemoteText(latestVersionUrl),
        fetchRemoteJson(latestReleasesApiUrl),
      ])
      latestVersionTag.value = normalizeVersionTag(version)
      const remoteReleases = parseGithubReleases(releasesPayload)
      if (remoteReleases.length) {
        releaseEntries.value = remoteReleases
      } else if (!releaseEntries.value.length) {
        releaseEntries.value = FALLBACK_RELEASES
      }
      const message = isNewerVersion(latestVersionLabel.value, currentVersionLabel.value)
        ? `发现新版本：${latestVersionLabel.value}`
        : `当前已是最新版本：${currentVersionLabel.value || latestVersionLabel.value}`
      updateCheckMessage.value = message
      if (showMessage) {
        if (isNewerVersion(latestVersionLabel.value, currentVersionLabel.value)) toast.info(message)
        else toast.success(message)
      }
    } catch (error: any) {
      if (!releaseEntries.value.length) {
        releaseEntries.value = FALLBACK_RELEASES
      }
      updateCheckMessage.value = '云端版本检查失败，当前展示本地更新日志。'
      if (showMessage) {
        const detail = error?.name === 'AbortError' ? '云端版本检查超时' : error?.message
        toast.warning(detail || '云端版本检查失败')
      }
    } finally {
      isCheckingUpdate.value = false
    }
  }

  function openUpdateDialog() {
    isUpdateDialogOpen.value = true
    updateCheckMessage.value = updateCheckingMessage
    void loadLocalReleaseEntries()
    void checkForUpdates(false)
  }

  function openReleasePage() {
    window.open(releasePageUrl, '_blank', 'noopener,noreferrer')
  }

  return {
    isUpdateDialogOpen,
    isCheckingUpdate,
    currentVersionTag,
    latestVersionTag,
    releaseEntries,
    updateCheckMessage,
    currentVersionLabel,
    latestVersionLabel,
    versionButtonText,
    loadCurrentVersion,
    checkForUpdates,
    openUpdateDialog,
    openReleasePage,
  }
}
