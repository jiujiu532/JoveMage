<template>
  <div class="grid gap-4 xl:grid-cols-3">
    <div class="xl:col-span-2">
      <FormSection collapsible icon="mdi:cloud-upload-outline" title="图片存储" subtitle="WebDAV 远端存储与公开访问前缀。">
        <div class="settings-block-stack">
          <section class="settings-block">
            <header class="settings-block__header">
              <div class="settings-block__headtext">
                <p class="settings-block__title">开关与模式</p>
                <p class="settings-block__desc">是否启用远端存储，以及写入策略。</p>
              </div>
            </header>
            <div class="settings-check-grid settings-check-grid--single">
              <div class="settings-check-item">
                <div class="settings-check-control">
                  <Checkbox v-model="imageStorage.enabled">启用 WebDAV 图片存储</Checkbox>
                </div>
              </div>
            </div>
            <div class="mt-3">
              <FormField label="存储模式">
                <div class="w-full">
                  <GroupedSelectMenu
                    v-model="imageStorage.mode"
                    :options="imageStorageModeOptions"
                    selected-indicator="none"
                    aria-label="图片存储模式"
                    block
                  />
                </div>
              </FormField>
            </div>
          </section>

          <section class="settings-block">
            <header class="settings-block__header">
              <span class="settings-block__icon" aria-hidden="true"><Icon icon="mdi:server-network" /></span>
              <div class="settings-block__headtext">
                <p class="settings-block__title">连接信息</p>
                <p class="settings-block__desc">WebDAV 地址、账号与路径。</p>
              </div>
            </header>
            <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
              <FormField label="WebDAV URL" class="md:col-span-2">
                <Input v-model.trim="imageStorage.webdav_url" block placeholder="https://example.com/dav" />
              </FormField>
              <FormField label="用户名">
                <Input v-model.trim="imageStorage.webdav_username" block />
              </FormField>
              <FormField label="密码">
                <Input v-model="imageStorage.webdav_password" type="password" block />
              </FormField>
              <FormField label="根路径">
                <Input v-model.trim="imageStorage.webdav_root_path" block placeholder="jovemage/images" />
              </FormField>
              <FormField label="公开访问前缀">
                <Input v-model.trim="imageStorage.public_base_url" block placeholder="https://cdn.example.com/images" />
              </FormField>
            </div>
          </section>

          <section class="settings-block">
            <header class="settings-block__header">
              <span class="settings-block__icon" aria-hidden="true"><Icon icon="mdi:lan-check" /></span>
              <div class="settings-block__headtext">
                <p class="settings-block__title">连通性</p>
                <p class="settings-block__desc">测试连接或触发全量同步。</p>
              </div>
            </header>
            <div class="flex flex-wrap items-center gap-2">
              <Button size="xs" variant="outline" :disabled="imageStorageBusy === 'test'" @click="testImageStorageConnection">
                {{ imageStorageBusy === 'test' ? '测试中...' : '测试 WebDAV' }}
              </Button>
              <Button size="xs" variant="outline" :disabled="imageStorageBusy === 'sync'" @click="syncImageStorageFiles">
                {{ imageStorageBusy === 'sync' ? '同步中...' : '全量同步' }}
              </Button>
            </div>
            <div v-if="imageStorageTestResult" class="settings-result-box">
              <p :class="imageStorageTestResult.ok ? 'settings-tone-ok' : 'settings-tone-bad'">
                {{ imageStorageTestResult.ok ? 'WebDAV 可用' : 'WebDAV 不可用' }}
                <span v-if="imageStorageTestResult.status"> · HTTP {{ imageStorageTestResult.status }}</span>
              </p>
              <p v-if="imageStorageTestResult.error" class="mt-1 break-all settings-tone-bad">{{ imageStorageTestResult.error }}</p>
            </div>
          </section>
        </div>
      </FormSection>
    </div>

    <FormSection collapsible icon="mdi:shield-check-outline" title="AI 审核" subtitle="请求前的内容审核接入。">
      <div class="settings-block-stack">
        <section class="settings-block">
          <header class="settings-block__header">
            <div class="settings-block__headtext">
              <p class="settings-block__title">开关</p>
              <p class="settings-block__desc">关闭时跳过请求前内容审核。</p>
            </div>
          </header>
          <div class="settings-check-grid settings-check-grid--single">
            <div class="settings-check-item">
              <div class="settings-check-control">
                <Checkbox v-model="aiReview.enabled">启用 AI 审核</Checkbox>
              </div>
            </div>
          </div>
        </section>
        <section class="settings-block">
          <header class="settings-block__header">
            <span class="settings-block__icon" aria-hidden="true"><Icon icon="mdi:robot-outline" /></span>
            <div class="settings-block__headtext">
              <p class="settings-block__title">模型接入</p>
              <p class="settings-block__desc">兼容 OpenAI Chat Completions 的审核模型。</p>
            </div>
          </header>
          <div class="grid grid-cols-1 gap-3">
            <FormField label="Base URL">
              <Input v-model.trim="aiReview.base_url" block placeholder="https://api.openai.com" />
            </FormField>
            <FormField label="API Key">
              <Input v-model="aiReview.api_key" type="password" block placeholder="sk-..." />
            </FormField>
            <FormField label="Model">
              <Input v-model.trim="aiReview.model" block placeholder="gpt-5.4-mini" />
            </FormField>
            <FormField label="审核提示词">
              <textarea
                v-model="aiReview.prompt"
                rows="5"
                class="ui-textarea-sm"
                placeholder="判断用户请求是否允许。只回答 ALLOW 或 REJECT。"
              ></textarea>
            </FormField>
          </div>
        </section>
      </div>
    </FormSection>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Icon } from '@iconify/vue'
import { Button, Checkbox, FormField, Input } from 'nanocat-ui'
import FormSection from '@/components/ai/FormSection.vue'
import GroupedSelectMenu from '@/components/ui/GroupedSelectMenu.vue'
import { settingsApi, type ImageStorageTestResult } from '@/api/settings'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useToast } from '@/composables/useToast'
import type { Settings } from '@/types/api'

type ImageStorageSettings = NonNullable<Settings['image_storage']>
type AiReviewSettings = Settings['ai_review']

const props = defineProps<{
  imageStorage: ImageStorageSettings
  aiReview: AiReviewSettings
  requireSavedSettings: (actionLabel: string) => boolean
}>()

const toast = useToast()
const confirmDialog = useConfirmDialog()

const imageStorageBusy = ref('')
const imageStorageTestResult = ref<ImageStorageTestResult | null>(null)

const imageStorageModeOptions = [
  { label: '仅本地', value: 'local' },
  { label: '仅 WebDAV', value: 'webdav' },
  { label: '本地 + WebDAV', value: 'both' },
]

async function testImageStorageConnection() {
  if (!props.requireSavedSettings('测试 WebDAV')) return
  const confirmed = await confirmDialog.ask({
    title: '确认测试 WebDAV',
    message: '即将使用已保存的图片存储配置发起 WebDAV 连接测试，可能访问外部存储服务。是否继续？',
    confirmText: '开始测试',
    cancelText: '取消',
  })
  if (!confirmed) return

  imageStorageBusy.value = 'test'
  imageStorageTestResult.value = null
  try {
    const response = await settingsApi.testImageStorage()
    imageStorageTestResult.value = response.result
    if (response.result.ok) toast.success('WebDAV 测试通过')
    else toast.warning(response.result.error || 'WebDAV 测试失败')
  } catch (error: any) {
    imageStorageTestResult.value = { ok: false, error: error.message || 'WebDAV 测试失败' }
    toast.error(error.message || 'WebDAV 测试失败')
  } finally {
    imageStorageBusy.value = ''
  }
}

async function syncImageStorageFiles() {
  if (!props.requireSavedSettings('同步本地图片')) return
  const confirmed = await confirmDialog.ask({
    title: '确认同步图片存储',
    message: '即将扫描本地图片并同步到已配置的 WebDAV 存储，可能产生外部上传流量。是否继续？',
    confirmText: '开始同步',
    cancelText: '取消',
  })
  if (!confirmed) return

  imageStorageBusy.value = 'sync'
  try {
    const response = await settingsApi.syncImageStorage()
    toast.success(`同步完成：上传 ${response.result.uploaded}，跳过 ${response.result.skipped}，失败 ${response.result.failed}`)
  } catch (error: any) {
    toast.error(error.message || '同步图片失败')
  } finally {
    imageStorageBusy.value = ''
  }
}
</script>
