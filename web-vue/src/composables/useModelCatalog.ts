import { computed, ref } from 'vue'
import { modelsApi } from '@/api/models'
import type { ModelCatalogResponse, ModelListResponse } from '@/api/models'
import type { Settings } from '@/types/api'
import {
  ensureFireflyImageModels,
  isFireflyImageModel,
  isImageModelId,
  isVideoModelId,
  resolveChatModels,
  resolveImageModels,
  resolveVideoModels,
} from '@/config/modelCatalog'

type SettingsResolver = () => Settings | null | undefined

const sharedCatalog = ref<ModelCatalogResponse | null>(null)
const loadError = ref<Error | null>(null)
const isLoading = ref(false)

let hasLoaded = false
let inflight: Promise<ModelCatalogResponse | null> | null = null

function normalizeList(raw: unknown): string[] {
  if (!Array.isArray(raw)) return []
  const result: string[] = []
  for (const item of raw) {
    const value = String(item || '').trim()
    if (!value || result.includes(value)) continue
    result.push(value)
  }
  return result
}

function normalizeCatalog(payload: ModelCatalogResponse | null | undefined): ModelCatalogResponse | null {
  if (!payload) return null
  const chatModels = normalizeList(payload.chat_models)
  // 后端 image_models 可能混入视频族；前端拆开
  const rawImageModels = normalizeList(payload.image_models)
  const imageModels = rawImageModels.filter((model) => !isVideoModelId(model))
  const videoModels = normalizeList([
    ...normalizeList(payload.video_models),
    ...rawImageModels.filter((model) => isVideoModelId(model)),
    ...normalizeList(payload.all_models).filter((model) => isVideoModelId(model)),
  ])
  return {
    ...payload,
    chat_models: chatModels,
    image_models: imageModels,
    video_models: videoModels,
    all_models: normalizeList(payload.all_models).length
      ? normalizeList(payload.all_models)
      : normalizeList([...chatModels, ...imageModels, ...videoModels]),
    capabilities: {
      image_upscale: Boolean(payload.capabilities?.image_upscale),
    },
  }
}

function catalogFromOpenAIModels(response: ModelListResponse): ModelCatalogResponse | null {
  const ids = normalizeList((Array.isArray(response.data) ? response.data : []).map(item => item?.id))
  if (ids.length === 0) return null
  const videoModels = ids.filter((model) => isVideoModelId(model))
  const imageModels = ids.filter((model) => isImageModelId(model) && !isVideoModelId(model))
  const chatModels = ids.filter((model) => !isImageModelId(model) && !isVideoModelId(model))
  return {
    object: 'model_catalog',
    chat_models: chatModels,
    image_models: imageModels,
    video_models: videoModels,
    all_models: ids,
    capabilities: {
      image_upscale: false,
    },
    source: {
      chat: 'openai_models_endpoint',
      image: 'openai_models_endpoint',
      video: 'openai_models_endpoint',
    },
    openai_models_endpoint: '/v1/models',
  }
}

export function useModelCatalog(resolveSettings: SettingsResolver) {
  const chatModels = computed(() => {
    const fromCatalog = normalizeList(sharedCatalog.value?.chat_models)
    return fromCatalog.length > 0 ? fromCatalog : resolveChatModels(resolveSettings())
  })

  const imageModels = computed(() => {
    const settings = resolveSettings()
    const fromCatalog = normalizeList(sharedCatalog.value?.image_models).filter(
      (model) => !isVideoModelId(model),
    )
    // catalog 非空也不能短路：后端 /api/model-catalog 会返回 ChatGPT 图像，
    // 但不注入 Firefly 图像（视频有 runtime 注入、图像没有）。
    // 若列表尚无 Firefly 图像族，从 all_models / settings / fallback 补齐。
    if (fromCatalog.length > 0) {
      if (fromCatalog.some(isFireflyImageModel)) return fromCatalog
      const fromAll = normalizeList(sharedCatalog.value?.all_models).filter(
        (model) => isFireflyImageModel(model) && !isVideoModelId(model),
      )
      if (fromAll.length > 0) return normalizeList([...fromCatalog, ...fromAll])
      return ensureFireflyImageModels(fromCatalog, settings)
    }
    return resolveImageModels(settings)
  })

  const videoModels = computed(() => {
    const fromCatalog = normalizeList(sharedCatalog.value?.video_models)
    if (fromCatalog.length > 0) return fromCatalog
    // catalog 未拆 video_models 时，从 all_models 回落
    const fromAll = normalizeList(sharedCatalog.value?.all_models).filter((model) => isVideoModelId(model))
    if (fromAll.length > 0) return fromAll
    // 后端空列表表示视频未启用/无账号：不要硬塞 FALLBACK 误导用户
    if (sharedCatalog.value && Array.isArray(sharedCatalog.value.video_models)) {
      return []
    }
    return resolveVideoModels(resolveSettings())
  })

  async function loadModelCatalog(force = false) {
    if (!force && hasLoaded) return sharedCatalog.value
    if (inflight) return inflight

    isLoading.value = true
    inflight = (async () => {
      hasLoaded = true
      try {
        const catalog = normalizeCatalog(await modelsApi.catalog())
        sharedCatalog.value = catalog
        loadError.value = null
        return catalog
      } catch (catalogError) {
        try {
          const fallback = normalizeCatalog(catalogFromOpenAIModels(await modelsApi.list()))
          sharedCatalog.value = fallback
          loadError.value = null
          return fallback
        } catch (listError) {
          sharedCatalog.value = null
          loadError.value = listError instanceof Error ? listError : new Error('Failed to load model catalog')
          console.error('Failed to load model catalog:', catalogError, listError)
          return null
        }
      } finally {
        isLoading.value = false
        inflight = null
      }
    })()

    return inflight
  }

  return {
    catalog: sharedCatalog,
    chatModels,
    imageModels,
    videoModels,
    isLoading,
    loadError,
    loadModelCatalog,
  }
}
