<template>
  <div class="max-w-3xl">
    <FormSection
      collapsible
      title="Adobe Firefly"
      subtitle="独立于 ChatGPT 的代理 / Cloudflare 配置，仅影响 firefly-* 生图 / 视频渠道。"
    >
      <div class="ff-stack">
        <!-- 渠道总开关：醒目大卡 -->
        <div class="ff-hero" :class="{ 'ff-hero--on': settings.firefly_enabled }">
          <div class="ff-hero__icon" aria-hidden="true">
            <Icon icon="mdi:fire" class="h-5 w-5" />
          </div>
          <div class="ff-hero__text">
            <p class="ff-hero__title">Firefly 渠道</p>
            <p class="ff-hero__desc">
              {{ settings.firefly_enabled ? '已启用：调度 Firefly 账号并对外放出 firefly 模型。' : '已停用：不调度 Firefly 账号，也不对外放出 firefly 模型。' }}
            </p>
          </div>
          <div class="ff-hero__control">
            <Checkbox
              :model-value="Boolean(settings.firefly_enabled)"
              @update:model-value="settings.firefly_enabled = Boolean($event)"
            >
              {{ settings.firefly_enabled ? '已启用' : '启用' }}
            </Checkbox>
          </div>
        </div>

        <!-- 图像生成 -->
        <section class="ff-card">
          <header class="ff-card__header">
            <span class="ff-card__icon" aria-hidden="true"><Icon icon="mdi:image-outline" class="h-4 w-4" /></span>
            <div class="ff-card__headtext">
              <p class="ff-card__title">图像生成</p>
              <p class="ff-card__desc">文生图 / 图生图（nano-banana / gpt-image）的等待节奏与默认模型。</p>
            </div>
            <span class="ff-card__tag">text2image · image2image</span>
          </header>
          <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
            <FormField label="生成超时">
              <template #label-extra>
                <HelpTip text="单位秒，单次 Firefly 文生图从提交到拿到结果的最长等待。" />
              </template>
              <Input
                :model-value="genTimeoutField.input.value"
                type="number"
                step="1"
                block
                placeholder="180"
                @update:model-value="genTimeoutField.update"
              />
            </FormField>

            <FormField label="轮询间隔">
              <template #label-extra>
                <HelpTip text="单位秒，轮询 Adobe 状态接口的间隔，默认 3 秒。" />
              </template>
              <Input
                :model-value="pollIntervalField.input.value"
                type="number"
                step="1"
                block
                placeholder="3"
                @update:model-value="pollIntervalField.update"
              />
            </FormField>

            <FormField label="最大重试次数">
              <template #label-extra>
                <HelpTip text="临时错误（429 / 451 / 5xx）时的最大换号重试次数。" />
              </template>
              <Input
                :model-value="retryMaxField.input.value"
                type="number"
                step="1"
                block
                placeholder="3"
                @update:model-value="retryMaxField.update"
              />
            </FormField>

            <FormField label="Cookie 刷新间隔（小时）">
              <template #label-extra>
                <HelpTip text="单位小时，Firefly 账号 Cookie 主动刷新间隔，默认 15 小时。" />
              </template>
              <Input
                :model-value="refreshIntervalField.input.value"
                type="number"
                step="1"
                block
                placeholder="15"
                @update:model-value="refreshIntervalField.update"
              />
            </FormField>

            <FormField label="默认模型" class="md:col-span-2">
              <template #label-extra>
                <HelpTip text="Firefly 渠道默认模型 id，例如 firefly-nano-banana-pro。" />
              </template>
              <Input
                v-model.trim="defaultModelProxy"
                block
                root-class="font-mono"
                placeholder="firefly-nano-banana-pro"
                list="firefly-default-model-suggestions"
              />
              <datalist id="firefly-default-model-suggestions">
                <option v-for="model in defaultModelSuggestions" :key="model" :value="model" />
              </datalist>
            </FormField>
          </div>
        </section>

        <!-- 视频生成 -->
        <section class="ff-card">
          <header class="ff-card__header">
            <span class="ff-card__icon" aria-hidden="true"><Icon icon="mdi:video-outline" class="h-4 w-4" /></span>
            <div class="ff-card__headtext">
              <p class="ff-card__title">视频生成</p>
              <p class="ff-card__desc">sora2 / veo31 / kling 的开关与等待节奏。</p>
            </div>
            <span class="ff-card__tag ff-card__tag--video">video</span>
          </header>
          <div class="ff-video-toggle" :class="{ 'ff-video-toggle--on': settings.firefly_video_enabled }">
            <Checkbox
              :model-value="Boolean(settings.firefly_video_enabled)"
              @update:model-value="settings.firefly_video_enabled = Boolean($event)"
            >
              启用 Firefly 视频生成
            </Checkbox>
          </div>
          <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
            <FormField label="视频超时">
              <template #label-extra>
                <HelpTip text="单位秒，单次 Firefly 视频从提交到拿到结果的最长等待，默认 600 秒。" />
              </template>
              <Input
                :model-value="videoTimeoutField.input.value"
                type="number"
                step="1"
                block
                placeholder="600"
                @update:model-value="videoTimeoutField.update"
              />
            </FormField>

            <FormField label="视频轮询间隔">
              <template #label-extra>
                <HelpTip text="单位秒，轮询 Adobe 视频任务状态的间隔，默认 3 秒。" />
              </template>
              <Input
                :model-value="videoPollIntervalField.input.value"
                type="number"
                step="1"
                block
                placeholder="3"
                @update:model-value="videoPollIntervalField.update"
              />
            </FormField>

            <FormField label="默认视频模型" class="md:col-span-2">
              <template #label-extra>
                <HelpTip text="Firefly 视频默认模型 id，例如 firefly-sora2-4s-16x9。" />
              </template>
              <Input
                v-model.trim="videoDefaultModelProxy"
                block
                root-class="font-mono"
                placeholder="firefly-sora2-4s-16x9"
                list="firefly-video-default-model-suggestions"
              />
              <datalist id="firefly-video-default-model-suggestions">
                <option v-for="model in videoDefaultModelSuggestions" :key="model" :value="model" />
              </datalist>
            </FormField>
          </div>
        </section>

        <SurfaceBox tone="muted" density="compact" class="text-xs leading-5 text-muted-foreground">
          账号请在「账号管理」中以 source_type = firefly 录入 Express Cookie。本页配置不参与 ChatGPT 的 CF / FlareSolverr 清障链路。
        </SurfaceBox>
      </div>
    </FormSection>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Icon } from '@iconify/vue'
import { Checkbox, FormField, HelpTip, Input } from 'nanocat-ui'
import FormSection from '@/components/ai/FormSection.vue'
import SurfaceBox from '@/components/ai/SurfaceBox.vue'
import type { Settings } from '@/types/api'

const props = defineProps<{
  settings: Settings
}>()

const defaultModelSuggestions = [
  'firefly-nano-banana-pro',
  'firefly-nano-banana',
  'firefly-nano-banana2',
  'firefly-gpt-image-2',
  'firefly-gpt-image-1.5',
]

const videoDefaultModelSuggestions = [
  'firefly-sora2-4s-16x9',
  'firefly-sora2-pro-8s-16x9',
  'firefly-veo31-8s-16x9-720p',
  'firefly-kling-o3-5s-16x9',
]

type NumberFieldBinding = {
  input: ReturnType<typeof ref<string>>
  update: (value: string) => void
}

function intValue(value: number, fallback: number, min = 0, max?: number) {
  let next = Number.isFinite(value) ? Math.trunc(value) : fallback
  if (next < min) next = min
  if (typeof max === 'number' && next > max) next = max
  return next
}

function numberValue(value: number, fallback: number, min = 0, max?: number) {
  let next = Number.isFinite(value) ? value : fallback
  if (next < min) next = min
  if (typeof max === 'number' && next > max) next = max
  return next
}

function createNumberField(
  getter: () => number,
  setter: (value: number) => void,
  options: { integer?: boolean; min?: number; max?: number; fallback?: number } = {},
): NumberFieldBinding {
  const input = ref('')

  watch(getter, (value) => {
    const next = String(value)
    if (input.value !== next) input.value = next
  }, { immediate: true })

  const update = (value: string) => {
    input.value = value
    const parsed = Number(value)
    if (value.trim() === '' || !Number.isFinite(parsed)) return
    const min = options.min ?? 0
    const fallback = options.fallback ?? getter()
    const next = options.integer
      ? intValue(parsed, fallback, min, options.max)
      : numberValue(parsed, fallback, min, options.max)
    setter(next)
  }

  return { input, update }
}

const genTimeoutField = createNumberField(
  () => Number(props.settings.firefly_gen_timeout_sec ?? 180),
  (value) => {
    props.settings.firefly_gen_timeout_sec = value
  },
  { integer: true, min: 1, fallback: 180 },
)

const pollIntervalField = createNumberField(
  () => Number(props.settings.firefly_poll_interval_sec ?? 3),
  (value) => {
    props.settings.firefly_poll_interval_sec = value
  },
  { integer: true, min: 1, fallback: 3 },
)

const retryMaxField = createNumberField(
  () => Number(props.settings.firefly_retry_max_attempts ?? 3),
  (value) => {
    props.settings.firefly_retry_max_attempts = value
  },
  { integer: true, min: 1, fallback: 3 },
)

const refreshIntervalField = createNumberField(
  () => Number(props.settings.firefly_refresh_interval_hours ?? 15),
  (value) => {
    props.settings.firefly_refresh_interval_hours = value
  },
  { integer: true, min: 1, fallback: 15 },
)

const defaultModelProxy = computed({
  get: () => String(props.settings.firefly_default_model || ''),
  set: (value: string) => {
    props.settings.firefly_default_model = value.trim()
  },
})

const videoTimeoutField = createNumberField(
  () => Number(props.settings.firefly_video_timeout_sec ?? 600),
  (value) => {
    props.settings.firefly_video_timeout_sec = value
  },
  { integer: true, min: 1, fallback: 600 },
)

const videoPollIntervalField = createNumberField(
  () => Number(props.settings.firefly_video_poll_interval_sec ?? 3),
  (value) => {
    props.settings.firefly_video_poll_interval_sec = value
  },
  { integer: true, min: 1, fallback: 3 },
)

const videoDefaultModelProxy = computed({
  get: () => String(props.settings.firefly_video_default_model || ''),
  set: (value: string) => {
    props.settings.firefly_video_default_model = value.trim()
  },
})
</script>

<style scoped>
.ff-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* 渠道总开关：醒目大卡 */
.ff-hero {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
  border: 2px solid var(--bauhaus-line-soft);
  border-radius: var(--radius);
  background: hsl(var(--card));
  transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}
.ff-hero--on {
  border-color: var(--bauhaus-ink);
  box-shadow: var(--shadow-hard-sm);
}
.ff-hero__icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border: 2px solid var(--bauhaus-ink);
  border-radius: var(--radius);
  background: hsl(var(--muted));
  color: hsl(var(--muted-foreground));
  transition: background 0.15s ease, color 0.15s ease;
}
.ff-hero--on .ff-hero__icon {
  background: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
}
.ff-hero__text {
  min-width: 0;
  flex: 1;
}
.ff-hero__title {
  font-size: 14px;
  font-weight: 700;
  color: hsl(var(--foreground));
}
.ff-hero__desc {
  margin-top: 2px;
  font-size: 12px;
  line-height: 1.5;
  color: hsl(var(--muted-foreground));
}
.ff-hero__control {
  flex-shrink: 0;
}

/* 分区卡片 */
.ff-card {
  padding: 14px 16px;
  border: 2px solid var(--bauhaus-ink);
  border-radius: var(--radius);
  background: hsl(var(--card));
  box-shadow: var(--shadow-hard-sm);
}
.ff-card__header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--bauhaus-line-soft);
}
.ff-card__icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border: 2px solid var(--bauhaus-ink);
  border-radius: var(--radius);
  background: hsl(var(--accent));
  color: hsl(var(--accent-foreground));
}
.ff-card__headtext {
  min-width: 0;
  flex: 1;
}
.ff-card__title {
  font-size: 13px;
  font-weight: 700;
  color: hsl(var(--foreground));
}
.ff-card__desc {
  margin-top: 1px;
  font-size: 12px;
  line-height: 1.45;
  color: hsl(var(--muted-foreground));
}
.ff-card__tag {
  flex-shrink: 0;
  padding: 2px 8px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.04em;
  border: 1px solid var(--bauhaus-line-soft);
  border-radius: 999px;
  background: hsl(var(--muted));
  color: hsl(var(--muted-foreground));
  font-family: var(--font-mono, monospace);
}
.ff-card__tag--video {
  background: hsl(var(--accent));
  color: hsl(var(--accent-foreground));
  border-color: var(--bauhaus-ink);
}

/* 视频开关行 */
.ff-video-toggle {
  margin-bottom: 12px;
  padding: 8px 12px;
  border: 1px solid var(--bauhaus-line-soft);
  border-radius: var(--radius);
  background: hsl(var(--muted) / 0.4);
  transition: background 0.15s ease, border-color 0.15s ease;
}
.ff-video-toggle--on {
  border-color: var(--bauhaus-ink);
  background: hsl(var(--accent) / 0.4);
}

html[data-theme='dark'] .ff-card,
html[data-theme='dark'] .ff-hero {
  background: var(--bauhaus-card);
}
html[data-theme='dark'] .ff-hero--on,
html[data-theme='dark'] .ff-card {
  box-shadow: var(--shadow-hard-soft);
}
</style>
