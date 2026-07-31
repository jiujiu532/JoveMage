<template>
  <div class="max-w-3xl">
    <FormSection
      collapsible
      title="Adobe Firefly"
      subtitle="独立于 ChatGPT 的代理 / Cloudflare 配置，仅影响 firefly-* 生图渠道。"
    >
      <div class="settings-block-stack">
        <section class="settings-block">
          <header class="settings-block__header">
            <p class="settings-block__title">开关</p>
            <p class="settings-block__desc">关闭后不会调度 Firefly 账号，也不会对外放出 firefly 模型（以后端为准）。</p>
          </header>
          <div class="settings-check-grid settings-check-grid--single">
            <div class="settings-check-item">
              <div class="settings-check-control">
                <Checkbox
                  :model-value="Boolean(settings.firefly_enabled)"
                  @update:model-value="settings.firefly_enabled = Boolean($event)"
                >
                  启用 Adobe Firefly 渠道
                </Checkbox>
              </div>
            </div>
          </div>
        </section>

        <section class="settings-block">
          <header class="settings-block__header">
            <p class="settings-block__title">生成超时与轮询</p>
            <p class="settings-block__desc">控制 Firefly generate-async 提交后的等待节奏。</p>
          </header>
          <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
            <FormField label="生成超时">
              <template #label-extra>
                <HelpTip text="单位秒，单次 Firefly 文生图从提交到拿到结果的最长等待。" />
              </template>
              <Input
                :model-value="genTimeoutField.input.value"
                type="number"
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
                block
                placeholder="3"
                @update:model-value="retryMaxField.update"
              />
            </FormField>

            <FormField label="默认模型">
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

        <SurfaceBox tone="muted" density="compact" class="text-xs leading-5 text-muted-foreground">
          账号请在「账号管理」中以 source_type = firefly 录入 Express Cookie。本页配置不参与 ChatGPT 的 CF / FlareSolverr 清障链路。
        </SurfaceBox>
      </div>
    </FormSection>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
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
  { min: 0.5, fallback: 3 },
)

const retryMaxField = createNumberField(
  () => Number(props.settings.firefly_retry_max_attempts ?? 3),
  (value) => {
    props.settings.firefly_retry_max_attempts = value
  },
  { integer: true, min: 1, fallback: 3 },
)

const defaultModelProxy = computed({
  get: () => String(props.settings.firefly_default_model || ''),
  set: (value: string) => {
    props.settings.firefly_default_model = value.trim()
  },
})
</script>
