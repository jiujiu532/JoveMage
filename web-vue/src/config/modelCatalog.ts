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

export function isImageModelId(model: string): boolean {
  const value = String(model || '').trim().toLowerCase()
  if (!value) return false
  // Adobe Firefly 族（含 nano-banana 等不含 image 字样的 id）
  if (value.startsWith('firefly-') || value.startsWith('firefly_')) return true
  return value.includes('image') || value.includes('dall-e') || value.includes('gpt-image')
}

export function isFireflyModelId(model: string): boolean {
  const value = String(model || '').trim().toLowerCase()
  return value.startsWith('firefly-') || value.startsWith('firefly_')
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
