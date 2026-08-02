<template>
  <div class="space-y-4">
    <FormSection collapsible icon="mdi:alert-circle-outline" title="图片错误提示" subtitle="先决定是否友好化，再按场景改文案。">
      <div class="settings-block-stack">
        <section class="settings-block">
          <header class="settings-block__header">
            <span class="settings-block__icon" aria-hidden="true"><Icon icon="mdi:toggle-switch-outline" /></span>
            <div class="settings-block__headtext">
              <p class="settings-block__title">开关</p>
              <p class="settings-block__desc">关闭时继续返回上游原始错误。</p>
            </div>
          </header>
          <div class="settings-check-grid settings-check-grid--single">
            <div class="settings-check-item">
              <div class="settings-check-control">
                <Checkbox v-model="settings.image_error_friendly_enabled">启用图片错误提示友好化</Checkbox>
                <HelpTip text="关闭时保持原始错误返回；开启后按下方文案转换上游断流、轮询超时、额度耗尽等图片错误。" />
              </div>
            </div>
          </div>
        </section>

        <section class="settings-block">
          <header class="settings-block__header">
            <span class="settings-block__icon" aria-hidden="true"><Icon icon="mdi:text-box-edit-outline" /></span>
            <div class="settings-block__headtext">
              <p class="settings-block__title">自定义错误文案</p>
              <p class="settings-block__desc">按错误类型覆盖默认提示。</p>
            </div>
          </header>
          <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
            <FormField
              v-for="item in imageErrorMessageFields"
              :key="item.key"
              :label="item.label"
            >
              <template v-if="item.help" #label-extra>
                <HelpTip :text="item.help" />
              </template>
              <textarea
                v-model="settings.image_error_messages[item.key]"
                rows="3"
                class="ui-textarea-sm"
                :placeholder="item.placeholder"
                :disabled="!settings.image_error_friendly_enabled"
              ></textarea>
            </FormField>
          </div>
        </section>
      </div>
    </FormSection>
  </div>
</template>

<script setup lang="ts">
import { Checkbox, FormField, HelpTip } from 'nanocat-ui'
import { Icon } from '@iconify/vue'
import FormSection from '@/components/ai/FormSection.vue'
import type { Settings } from '@/types/api'

type ImageErrorMessageKey = keyof Settings['image_error_messages']

defineProps<{
  settings: Settings
}>()

const imageErrorMessageFields: Array<{
  key: ImageErrorMessageKey
  label: string
  placeholder: string
  help?: string
}> = [
  {
    key: 'fallback',
    label: '兜底错误',
    placeholder: '图片生成请求失败，请稍后重试。',
  },
  {
    key: 'quota',
    label: '额度耗尽',
    placeholder: '图片账号额度已用完，请稍后再试或联系管理员。',
  },
  {
    key: 'no_account',
    label: '账号暂不可用',
    placeholder: '当前图片账号暂不可用，可能是账号池、并发或上游波动，请稍后重试。',
  },
  {
    key: 'local_busy',
    label: '本地繁忙 / 无可用账号',
    placeholder: '当前没有可用的图片账号或账号并发已满，请稍后重试。',
  },
  {
    key: 'unsupported_model',
    label: '模型不支持',
    placeholder: '当前模型不支持图片生成，请检查 model 参数。',
  },
  {
    key: 'poll_timeout',
    label: '轮询超时',
    placeholder: '图片任务暂未返回结果，可能仍在排队或上游处理较慢，请重试。',
  },
  {
    key: 'stream_interrupted',
    label: '上游断流',
    placeholder: '图片生成连接中断，可能是上游服务繁忙或网络波动，请重试。',
  },
  {
    key: 'connection_failed',
    label: '连接失败',
    placeholder: '连接上游图片服务失败，可能是网络或代理波动，请重试。',
  },
  {
    key: 'connection_timeout',
    label: '连接超时',
    placeholder: '连接上游图片服务超时，请稍后重试。',
  },
  {
    key: 'token_invalid',
    label: '账号状态异常',
    placeholder: '图片生成账号状态异常，请稍后重试。',
  },
  {
    key: 'text_reply',
    label: '返回文本但无图',
    placeholder: '上游返回了文本说明，未生成图片。请调整提示词或重试。',
    help: '可使用 {text} 指定上游文本插入位置；不写占位符时会自动追加到下一行。',
  },
]
</script>
