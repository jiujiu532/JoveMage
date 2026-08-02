<template>
  <FormSection collapsible icon="mdi:cloud-sync-outline" title="R2 备份管理" subtitle="定时备份到 Cloudflare R2，可加密与轮转。">
    <div class="settings-block-stack">
      <section class="settings-block">
        <header class="settings-block__header">
          <div class="settings-block__headtext">
            <p class="settings-block__title">开关</p>
            <p class="settings-block__desc">定时任务与加密是否生效。</p>
          </div>
        </header>
        <div class="settings-check-grid">
          <div class="settings-check-item">
            <div class="settings-check-control">
              <Checkbox v-model="backup.enabled">启用定时备份</Checkbox>
            </div>
          </div>
          <div class="settings-check-item">
            <div class="settings-check-control">
              <Checkbox v-model="backup.encrypt">启用备份加密</Checkbox>
            </div>
          </div>
        </div>
      </section>

      <section class="settings-block">
        <header class="settings-block__header">
          <span class="settings-block__icon" aria-hidden="true"><Icon icon="mdi:cloud-outline" /></span>
          <div class="settings-block__headtext">
            <p class="settings-block__title">R2 连接</p>
            <p class="settings-block__desc">账号、桶与访问密钥。</p>
          </div>
        </header>
        <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
          <FormField label="Cloudflare Account ID">
            <Input v-model.trim="backup.account_id" block />
          </FormField>
          <FormField label="Bucket 名称">
            <Input v-model.trim="backup.bucket" block />
          </FormField>
          <FormField label="Access Key ID">
            <Input v-model.trim="backup.access_key_id" block />
          </FormField>
          <FormField label="Secret Access Key">
            <Input v-model="backup.secret_access_key" type="password" block />
          </FormField>
          <FormField label="备份前缀">
            <Input v-model.trim="backup.prefix" block placeholder="backups" />
          </FormField>
          <FormField label="保留份数">
            <Input
              :model-value="backupRotationKeepField.input.value"
              type="number"
              block
              @update:model-value="backupRotationKeepField.update"
            />
          </FormField>
          <FormField label="备份间隔（分钟）">
            <Input
              :model-value="backupIntervalMinutesField.input.value"
              type="number"
              block
              @update:model-value="backupIntervalMinutesField.update"
            />
          </FormField>
          <FormField label="加密口令">
            <Input v-model="backup.passphrase" type="password" block placeholder="留空" />
          </FormField>
        </div>
      </section>

      <section class="settings-block">
        <header class="settings-block__header">
          <span class="settings-block__icon" aria-hidden="true"><Icon icon="mdi:checkbox-multiple-marked-outline" /></span>
          <div class="settings-block__headtext">
            <p class="settings-block__title">备份内容</p>
            <p class="settings-block__desc">勾选要打进备份包的数据。</p>
          </div>
        </header>
        <div class="settings-check-grid">
          <div
            v-for="item in backupIncludeOptions"
            :key="item.value"
            class="settings-check-item"
          >
            <div class="settings-check-control">
              <Checkbox v-model="backup.include[item.value]">{{ item.label }}</Checkbox>
            </div>
          </div>
        </div>
      </section>

      <section class="settings-block">
        <header class="settings-block__header">
          <span class="settings-block__icon" aria-hidden="true"><Icon icon="mdi:play-circle-outline" /></span>
          <div class="settings-block__headtext">
            <p class="settings-block__title">操作与状态</p>
            <p class="settings-block__desc">测试连接、立即备份与最近结果。</p>
          </div>
        </header>

        <div class="flex flex-wrap items-center gap-2">
          <Button size="xs" variant="outline" :disabled="backupBusy === 'test'" @click="testBackupConnection">
            {{ backupBusy === 'test' ? '测试中...' : '测试连接' }}
          </Button>
          <Button size="xs" variant="outline" :disabled="backupBusy === 'run' || backupState?.running" @click="runBackupNow">
            {{ backupBusy === 'run' || backupState?.running ? '备份中...' : '立即备份' }}
          </Button>
          <Button size="xs" variant="outline" :disabled="backupLoading" @click="loadBackups">
            {{ backupLoading ? '加载中...' : '刷新历史' }}
          </Button>
        </div>

        <div v-if="backupTestResult" class="settings-result-box">
          <p :class="backupTestResult.ok ? 'settings-tone-ok' : 'settings-tone-bad'">
            {{ backupTestResult.ok ? '备份连接可用' : '备份连接不可用' }}
            <span v-if="backupTestResult.status"> · HTTP {{ backupTestResult.status }}</span>
          </p>
          <p v-if="backupTestResult.error" class="mt-1 break-all settings-tone-bad">{{ backupTestResult.error }}</p>
        </div>

        <div class="settings-result-box">
          <div class="settings-meta-grid">
            <span>最近状态</span>
            <span class="text-right text-foreground">{{ backupStatusText }}</span>
            <span>最近开始</span>
            <span class="text-right text-foreground">{{ formatDateTime(backupState?.last_started_at) }}</span>
            <span>最近完成</span>
            <span class="text-right text-foreground">{{ formatDateTime(backupState?.last_finished_at) }}</span>
            <span>最近对象</span>
            <span class="break-all text-right font-mono text-foreground">{{ backupState?.last_object_key || '-' }}</span>
            <span>最近错误</span>
            <span class="break-all text-right settings-tone-bad">{{ backupState?.last_error || '-' }}</span>
          </div>
        </div>

        <div v-if="backupItems.length > 0" class="mt-3 space-y-2">
          <div
            v-for="item in backupItems.slice(0, 5)"
            :key="item.key"
            class="settings-list-row"
          >
            <div class="min-w-0">
              <p class="truncate font-medium text-foreground">{{ item.name || item.key }}</p>
              <p class="mt-1 text-muted-foreground">{{ formatBytes(item.size_bytes ?? item.size ?? 0) }} · {{ item.last_modified || '-' }}</p>
            </div>
            <Button size="xs" variant="outline" root-class="text-rose-600" :disabled="backupBusy === item.key" @click="deleteBackupItem(item)">
              删除
            </Button>
          </div>
        </div>
      </section>
    </div>
  </FormSection>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Icon } from '@iconify/vue'
import { Button, Checkbox, FormField, Input } from 'nanocat-ui'
import {
  settingsApi,
  type BackupItem,
  type BackupState,
  type BackupTestResult,
} from '@/api/settings'
import FormSection from '@/components/ai/FormSection.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useToast } from '@/composables/useToast'
import type { Settings } from '@/types/api'

type BackupSettings = NonNullable<Settings['backup']>

type NumberFieldBinding = {
  input: ReturnType<typeof ref<string>>
  update: (value: string) => void
}

const props = defineProps<{
  backup: BackupSettings
  requireSavedSettings: (actionLabel: string) => boolean
}>()

const toast = useToast()
const confirmDialog = useConfirmDialog()

const backupBusy = ref('')
const backupLoading = ref(false)
const backupState = ref<BackupState | null>(null)
const backupItems = ref<BackupItem[]>([])
const backupTestResult = ref<BackupTestResult | null>(null)

const backupIncludeOptions = [
  { value: 'config', label: '系统配置' },
  { value: 'register', label: '注册配置' },
  { value: 'cpa', label: 'CPA 配置' },
  { value: 'sub2api', label: 'Sub2API 配置' },
  { value: 'logs', label: '调度与调用日志' },
  { value: 'dashboard_metrics', label: '概览统计' },
  { value: 'image_tasks', label: '图片任务记录' },
  { value: 'accounts_snapshot', label: '账号快照' },
  { value: 'auth_keys_snapshot', label: '用户密钥快照' },
  { value: 'images', label: '图片文件目录' },
] as const

const backupStatusText = computed(() => {
  const state = backupState.value
  if (!state) return '未加载'
  if (state.running) return '备份中'
  if (state.last_status === 'success') return '最近成功'
  if (state.last_status === 'error') return '最近失败'
  return state.last_status || '未执行'
})

const numberValue = (value: unknown, fallback: number, min: number, max?: number): number => {
  const parsed = Number(value)
  const finite = Number.isFinite(parsed) ? parsed : fallback
  const bounded = Math.max(min, finite)
  return typeof max === 'number' ? Math.min(max, bounded) : bounded
}

const intValue = (value: unknown, fallback: number, min: number, max?: number): number => (
  Math.round(numberValue(value, fallback, min, max))
)

const createNumberField = (
  getter: () => number,
  setter: (value: number) => void,
  options: { integer?: boolean; min?: number; max?: number; fallback?: number } = {},
): NumberFieldBinding => {
  const input = ref('')

  watch(getter, (value) => {
    const next = String(value)
    if (input.value !== next) {
      input.value = next
    }
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

const backupIntervalMinutesField = createNumberField(
  () => props.backup.interval_minutes ?? 1440,
  (value) => { props.backup.interval_minutes = value },
  { integer: true, min: 1, fallback: 1440 },
)
const backupRotationKeepField = createNumberField(
  () => props.backup.rotation_keep ?? 10,
  (value) => { props.backup.rotation_keep = value },
  { integer: true, min: 0, fallback: 10 },
)

function formatBytes(value: unknown) {
  const bytes = Number(value) || 0
  if (bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let size = bytes
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex += 1
  }
  return `${size.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`
}

function formatDateTime(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw) return '-'
  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) return raw
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(parsed)
}

async function loadBackups() {
  backupLoading.value = true
  try {
    const response = await settingsApi.listBackups()
    backupItems.value = Array.isArray(response.items) ? response.items : []
    backupState.value = response.state || null
  } catch (error: any) {
    backupItems.value = []
    backupState.value = null
    toast.error(error.message || '加载备份历史失败')
  } finally {
    backupLoading.value = false
  }
}

async function testBackupConnection() {
  if (!props.requireSavedSettings('测试备份连接')) return
  const confirmed = await confirmDialog.ask({
    title: '确认测试备份连接',
    message: '即将使用已保存的备份配置发起 R2/备份存储连接测试，可能访问外部存储服务。是否继续？',
    confirmText: '开始测试',
    cancelText: '取消',
  })
  if (!confirmed) return

  backupBusy.value = 'test'
  backupTestResult.value = null
  try {
    const response = await settingsApi.testBackup()
    backupTestResult.value = response.result
    if (response.result.ok) toast.success('备份连接测试通过')
    else toast.warning(response.result.error || '备份连接测试失败')
  } catch (error: any) {
    backupTestResult.value = { ok: false, error: error.message || '备份连接测试失败' }
    toast.error(error.message || '备份连接测试失败')
  } finally {
    backupBusy.value = ''
  }
}

async function runBackupNow() {
  if (!props.requireSavedSettings('执行立即备份')) return
  const confirmed = await confirmDialog.ask({
    title: '确认立即备份',
    message: '即将把当前配置和运行数据写入备份存储，可能产生外部上传流量。是否继续？',
    confirmText: '开始备份',
    cancelText: '取消',
  })
  if (!confirmed) return

  backupBusy.value = 'run'
  try {
    const response = await settingsApi.runBackup()
    toast.success(`备份已完成：${response.result.key}`)
    await loadBackups()
  } catch (error: any) {
    toast.error(error.message || '执行备份失败')
  } finally {
    backupBusy.value = ''
  }
}

async function deleteBackupItem(item: BackupItem) {
  const confirmed = await confirmDialog.ask({
    title: '删除备份',
    message: `确定删除备份 ${item.name || item.key}？`,
    confirmText: '删除',
    cancelText: '取消',
  })
  if (!confirmed) return

  backupBusy.value = item.key
  try {
    await settingsApi.deleteBackup(item.key)
    toast.success('备份已删除')
    await loadBackups()
  } catch (error: any) {
    toast.error(error.message || '删除备份失败')
  } finally {
    backupBusy.value = ''
  }
}

onMounted(() => {
  void loadBackups()
})
</script>
