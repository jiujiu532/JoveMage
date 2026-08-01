import { computed, ref } from 'vue'
import { channelsApi } from '@/api/channels'
import {
  enabledHasCapability,
  listBypassChannels,
  listChannels,
  listEnabledBypassChannels,
  listEnabledChannels,
  setChannelsFromApi,
  unionEnabledCapabilities,
  useChannelRegistry,
  type ChannelCapability,
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

  /** Studio 能力面 = 启用渠道 capabilities 并集；依赖 registry 响应式 */
  const studioCapabilities = computed<ChannelCapability[]>(() => {
    void registry.value
    return unionEnabledCapabilities()
  })

  const canChat = computed(() => {
    void registry.value
    return enabledHasCapability('chat')
  })
  const canImage = computed(() => {
    void registry.value
    return enabledHasCapability('image')
  })
  /** 图生图 / 参考图入口 */
  const canEdit = computed(() => {
    void registry.value
    return enabledHasCapability('edit')
  })
  const canVideo = computed(() => {
    void registry.value
    return enabledHasCapability('video')
  })

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
    studioCapabilities,
    canChat,
    canImage,
    canEdit,
    canVideo,
    isLoading,
    loadError,
    hasLoadedOnce,
    loadChannels,
  }
}
