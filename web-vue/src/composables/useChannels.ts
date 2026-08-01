import { computed, ref } from 'vue'
import { channelsApi } from '@/api/channels'
import {
  listBypassChannels,
  listChannels,
  listEnabledBypassChannels,
  listEnabledChannels,
  setChannelsFromApi,
  useChannelRegistry,
  type ChannelDescriptor,
} from '@/config/channels'

/**
 * 渠道数据接入：拉 GET /api/channels → setChannelsFromApi。
 * 失败保持本地 DEFAULT_CHANNELS，页面不空。
 * 模块级状态：多处 useChannels() 共享同一加载结果。
 */

const isLoading = ref(false)
const loadError = ref('')
const hasLoadedOnce = ref(false)
let inflight: Promise<ChannelDescriptor[]> | null = null

export function useChannels() {
  const registry = useChannelRegistry()

  const channels = computed(() => registry.value)
  const enabledChannels = computed(() => listEnabledChannels())
  const bypassChannels = computed(() => listBypassChannels())
  const enabledBypassChannels = computed(() => listEnabledBypassChannels())

  async function loadChannels(force = false): Promise<ChannelDescriptor[]> {
    if (!force && hasLoadedOnce.value && !inflight) {
      return listChannels()
    }
    if (inflight) return inflight

    isLoading.value = true
    loadError.value = ''
    inflight = (async () => {
      try {
        const response = await channelsApi.list()
        const next = setChannelsFromApi(response?.channels)
        hasLoadedOnce.value = true
        return next
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : '加载渠道列表失败'
        loadError.value = message
        // 失败回落本地默认表，不抛给调用方打断壳层
        hasLoadedOnce.value = true
        return listChannels()
      } finally {
        isLoading.value = false
        inflight = null
      }
    })()

    return inflight
  }

  return {
    channels,
    enabledChannels,
    bypassChannels,
    enabledBypassChannels,
    isLoading,
    loadError,
    hasLoadedOnce,
    loadChannels,
  }
}
