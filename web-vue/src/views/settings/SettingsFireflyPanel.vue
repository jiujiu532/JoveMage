<template>
  <div class="ff-panel">
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

        <!-- 图像 / 视频：宽屏并排 -->
        <div class="ff-media-grid">
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
            <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
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

              <FormField label="默认模型" class="sm:col-span-2">
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
            <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
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

              <FormField label="默认视频模型" class="sm:col-span-2">
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
        </div>

        <!-- Credits 对账 -->
        <section class="ff-card">
          <header class="ff-card__header">
            <span class="ff-card__icon" aria-hidden="true"><Icon icon="mdi:scale-balance" class="h-4 w-4" /></span>
            <div class="ff-card__headtext">
              <p class="ff-card__title">Credits 对账</p>
              <p class="ff-card__desc">比对本地账本与 Adobe 远端余额，标出漂移账号。</p>
            </div>
            <button
              type="button"
              class="ff-reconcile-btn"
              :disabled="reconcileLoading"
              @click="runReconcile"
            >
              {{ reconcileLoading ? '对账中…' : '对账' }}
            </button>
          </header>

          <p v-if="reconcileError" class="ff-reconcile-error">{{ reconcileError }}</p>

          <template v-if="reconcileResult">
            <div class="ff-reconcile-metrics">
              <div class="ff-reconcile-metric">
                <span class="ff-reconcile-metric__label">一致</span>
                <span class="ff-reconcile-metric__value ff-reconcile-metric__value--ok">{{ reconcileResult.ok }}</span>
              </div>
              <div class="ff-reconcile-metric">
                <span class="ff-reconcile-metric__label">漂移</span>
                <span class="ff-reconcile-metric__value ff-reconcile-metric__value--drift">{{ reconcileResult.drift }}</span>
              </div>
              <div class="ff-reconcile-metric">
                <span class="ff-reconcile-metric__label">错误</span>
                <span class="ff-reconcile-metric__value ff-reconcile-metric__value--error">{{ reconcileResult.error }}</span>
              </div>
              <div class="ff-reconcile-metric">
                <span class="ff-reconcile-metric__label">合计</span>
                <span class="ff-reconcile-metric__value">{{ reconcileResult.total ?? reconcileResult.accounts.length }}</span>
              </div>
            </div>

            <div v-if="reconcileResult.accounts.length" class="ff-reconcile-table-wrap">
              <table class="ff-reconcile-table">
                <thead>
                  <tr>
                    <th>账号</th>
                    <th>本地</th>
                    <th>远端</th>
                    <th>漂移</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="row in reconcileResult.accounts"
                    :key="row.account_id"
                    :class="{
                      'ff-reconcile-row--drift': row.status === 'drift' || (row.drift != null && Number(row.drift) !== 0),
                      'ff-reconcile-row--error': row.status === 'error',
                    }"
                  >
                    <td class="ff-reconcile-id" :title="row.account_id">{{ shortId(row.account_id) }}</td>
                    <td>{{ formatCredit(row.local_credits) }}</td>
                    <td>{{ formatCredit(row.remote_credits) }}</td>
                    <td>{{ formatCredit(row.drift) }}</td>
                    <td>
                      <span class="ff-reconcile-status" :data-status="row.status">{{ statusLabel(row.status) }}</span>
                      <span v-if="row.error" class="ff-reconcile-row-error" :title="String(row.error)">{{ row.error }}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-else class="ff-reconcile-empty">暂无 Firefly 账号可对账。</p>
          </template>
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
import {
  channelsApi,
  type FireflyReconcileResponse,
} from '@/api/channels'
import type { Settings } from '@/types/api'

const props = defineProps<{
  settings: Settings
}>()

const reconcileLoading = ref(false)
const reconcileError = ref('')
const reconcileResult = ref<FireflyReconcileResponse | null>(null)

function formatCredit(value: unknown): string {
  if (value == null || value === '') return '—'
  const num = Number(value)
  if (!Number.isFinite(num)) return String(value)
  return Number.isInteger(num) ? String(num) : num.toFixed(2)
}

function shortId(id: string): string {
  const raw = String(id || '').trim()
  if (raw.length <= 18) return raw || '—'
  return `${raw.slice(0, 8)}…${raw.slice(-6)}`
}

function statusLabel(status: string): string {
  const value = String(status || '').toLowerCase()
  if (value === 'ok') return '一致'
  if (value === 'drift') return '漂移'
  if (value === 'error') return '错误'
  return value || '—'
}

async function runReconcile() {
  reconcileLoading.value = true
  reconcileError.value = ''
  try {
    const data = await channelsApi.reconcileFirefly()
    reconcileResult.value = {
      ok: Number(data?.ok) || 0,
      drift: Number(data?.drift) || 0,
      error: Number(data?.error) || 0,
      total: Number(data?.total) || 0,
      tolerance: data?.tolerance,
      channel: data?.channel,
      ts: data?.ts,
      accounts: Array.isArray(data?.accounts) ? data.accounts : [],
    }
  } catch (err: unknown) {
    reconcileResult.value = null
    reconcileError.value = err instanceof Error ? err.message : '对账失败'
  } finally {
    reconcileLoading.value = false
  }
}

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
.ff-panel {
  width: 100%;
  max-width: none;
}

.ff-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* 图像 / 视频：宽屏两列并排，窄屏纵向堆叠 */
.ff-media-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 14px;
}

@media (min-width: 1100px) {
  .ff-media-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    align-items: start;
  }
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

/* Credits 对账 */
.ff-reconcile-btn {
  flex-shrink: 0;
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  border: 2px solid var(--bauhaus-ink);
  border-radius: var(--radius);
  background: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
  box-shadow: var(--shadow-hard-sm);
  cursor: pointer;
  transition: opacity 0.15s ease, transform 0.1s ease;
}
.ff-reconcile-btn:hover:not(:disabled) {
  transform: translate(-1px, -1px);
}
.ff-reconcile-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  box-shadow: none;
}
.ff-reconcile-error {
  margin: 0 0 10px;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.45;
  color: var(--bauhaus-red, #ff4d4d);
  border: 1px solid color-mix(in srgb, var(--bauhaus-red, #ff4d4d) 40%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--bauhaus-red, #ff4d4d) 10%, transparent);
}
.ff-reconcile-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 12px;
}
.ff-reconcile-metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border: 1px solid var(--bauhaus-line-soft);
  border-radius: var(--radius);
  background: hsl(var(--muted) / 0.35);
}
.ff-reconcile-metric__label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: hsl(var(--muted-foreground));
}
.ff-reconcile-metric__value {
  font-family: var(--font-display, inherit);
  font-size: 1.15rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: hsl(var(--foreground));
}
.ff-reconcile-metric__value--ok {
  color: #5a8f2f;
}
.ff-reconcile-metric__value--drift {
  color: var(--bauhaus-red, #ff4d4d);
}
.ff-reconcile-metric__value--error {
  color: #c45c7a;
}
.ff-reconcile-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--bauhaus-line-soft);
  border-radius: var(--radius);
}
.ff-reconcile-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.ff-reconcile-table th,
.ff-reconcile-table td {
  padding: 0.5rem 0.65rem;
  text-align: left;
  border-bottom: 1px solid var(--bauhaus-line-soft);
  vertical-align: middle;
}
.ff-reconcile-table th {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: hsl(var(--muted-foreground));
  background: hsl(var(--muted) / 0.35);
  white-space: nowrap;
}
.ff-reconcile-table tbody tr:last-child td {
  border-bottom: none;
}
.ff-reconcile-row--drift {
  background: color-mix(in srgb, var(--bauhaus-red, #ff4d4d) 10%, transparent);
}
.ff-reconcile-row--error {
  background: color-mix(in srgb, #c45c7a 10%, transparent);
}
.ff-reconcile-id {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  max-width: 10rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ff-reconcile-status {
  display: inline-block;
  padding: 1px 7px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.04em;
  border-radius: 999px;
  border: 1px solid var(--bauhaus-line-soft);
  background: hsl(var(--muted));
  color: hsl(var(--muted-foreground));
}
.ff-reconcile-status[data-status='ok'] {
  border-color: color-mix(in srgb, #5a8f2f 40%, transparent);
  background: color-mix(in srgb, #5a8f2f 14%, transparent);
  color: #5a8f2f;
}
.ff-reconcile-status[data-status='drift'] {
  border-color: color-mix(in srgb, var(--bauhaus-red, #ff4d4d) 40%, transparent);
  background: color-mix(in srgb, var(--bauhaus-red, #ff4d4d) 14%, transparent);
  color: var(--bauhaus-red, #ff4d4d);
}
.ff-reconcile-status[data-status='error'] {
  border-color: color-mix(in srgb, #c45c7a 40%, transparent);
  background: color-mix(in srgb, #c45c7a 14%, transparent);
  color: #c45c7a;
}
.ff-reconcile-row-error {
  display: block;
  margin-top: 2px;
  max-width: 12rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 10px;
  color: hsl(var(--muted-foreground));
}
.ff-reconcile-empty {
  margin: 0;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

@media (max-width: 640px) {
  .ff-reconcile-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
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
