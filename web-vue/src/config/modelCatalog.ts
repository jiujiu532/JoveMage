import type { Settings } from '@/types/api'

export const FALLBACK_CHAT_MODELS = [
  'auto',
  'gpt-5',
  'gpt-5-1',
  'gpt-5-2',
  'gpt-5-3',
  'gpt-5-3-mini',
  'gpt-5-5',
  'gpt-5-mini',
]

export const FALLBACK_IMAGE_MODELS = [
  'gpt-image-2',
]

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

/** Firefly 图像族标记（不含 firefly- 前缀），对齐 utils/helper.py */
const FIREFLY_IMAGE_FAMILY_MARKERS = ['nano-banana', 'gpt-image'] as const
/** Firefly 视频族标记（不含 firefly- 前缀），对齐 utils/helper.py */
const FIREFLY_VIDEO_FAMILY_MARKERS = ['sora2', 'veo31', 'kling'] as const

/** 取出 firefly-/firefly_ 后的 rest；非 Firefly 返回 null */
function fireflyModelRest(model: string): string | null {
  const value = String(model || '').trim().toLowerCase()
  if (value.startsWith('firefly-')) return value.slice('firefly-'.length)
  if (value.startsWith('firefly_')) return value.slice('firefly_'.length)
  return null
}

/** Firefly 图像模型：nano-banana / gpt-image 族 */
export function isFireflyImageModel(model: string): boolean {
  const rest = fireflyModelRest(model)
  if (rest === null || !rest) return false
  for (const marker of FIREFLY_IMAGE_FAMILY_MARKERS) {
    if (rest === marker || rest.startsWith(`${marker}-`) || rest.startsWith(`${marker}.`)) {
      return true
    }
  }
  return false
}

/** Firefly 视频模型：sora2 / veo31 / kling 族（与图像族互斥） */
export function isFireflyVideoModel(model: string): boolean {
  const rest = fireflyModelRest(model)
  if (rest === null || !rest) return false
  for (const marker of FIREFLY_IMAGE_FAMILY_MARKERS) {
    if (rest === marker || rest.startsWith(`${marker}-`) || rest.startsWith(`${marker}.`)) {
      return false
    }
  }
  for (const marker of FIREFLY_VIDEO_FAMILY_MARKERS) {
    if (rest === marker || rest.startsWith(marker)) return true
  }
  return false
}

/** 任意 Firefly 模型（图像或视频） */
export function isFireflyModelId(model: string): boolean {
  return isFireflyImageModel(model) || isFireflyVideoModel(model)
}

export function isImageModelId(model: string): boolean {
  const value = String(model || '').trim().toLowerCase()
  if (!value) return false
  // 视频模型不当图像；图像族命中；其余 firefly- 前缀（未知族）仍按图像渠道宽口径放行
  if (isFireflyVideoModel(value)) return false
  if (isFireflyImageModel(value)) return true
  if (value.startsWith('firefly-') || value.startsWith('firefly_')) return true
  return value.includes('image') || value.includes('dall-e') || value.includes('gpt-image')
}

export function resolveChatModels(settings: Settings | null | undefined): string[] {
  const fromCatalog = normalizeList(settings?.model_catalog?.chat_models)
  if (fromCatalog.length > 0) return fromCatalog
  return [...FALLBACK_CHAT_MODELS]
}

export function resolveImageModels(settings: Settings | null | undefined): string[] {
  const fromImageConfig = normalizeList(settings?.image_generation?.model_options)
  if (fromImageConfig.length > 0) return fromImageConfig
  const fromCatalog = normalizeList(settings?.model_catalog?.image_api_models)
  if (fromCatalog.length > 0) return fromCatalog
  return [...FALLBACK_IMAGE_MODELS]
}
