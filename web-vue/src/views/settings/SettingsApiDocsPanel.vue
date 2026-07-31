<template>
  <div class="space-y-4">
    <FormSection collapsible title="接口接入" subtitle="第三方应用按 OpenAI 兼容接口接入，使用同一套 Bearer 鉴权。">
      <div class="settings-kv-grid">
        <div class="settings-kv-item">
          <p class="settings-kv-label">服务地址</p>
          <p class="settings-kv-value">{{ serviceBaseUrl }}</p>
        </div>
        <div class="settings-kv-item">
          <p class="settings-kv-label">Base URL（OpenAI）</p>
          <p class="settings-kv-value">{{ openAIBaseUrl }}</p>
        </div>
        <div class="settings-kv-item">
          <p class="settings-kv-label">API Key</p>
          <p class="settings-kv-value">{{ currentApiKey }}</p>
        </div>
        <div class="settings-kv-item">
          <p class="settings-kv-label">请求头</p>
          <p class="settings-kv-value">Authorization: Bearer {{ currentApiKey }}</p>
        </div>
      </div>
    </FormSection>

    <FormSection collapsible title="常用接口" subtitle="点击展开查看说明与示例请求。">
      <div class="settings-doc-list">
        <details
          v-for="item in apiDocItems"
          :key="item.path"
          class="settings-doc-item"
        >
          <summary class="settings-doc-summary">
            <span class="min-w-0">
              <span class="block text-sm font-medium text-foreground">{{ item.title }}</span>
              <span class="mt-1 block truncate font-mono text-xs text-muted-foreground">{{ item.method }} {{ item.path }}</span>
            </span>
            <span class="settings-doc-hint">展开</span>
          </summary>
          <div class="settings-doc-body">
            <p class="text-xs leading-5 text-muted-foreground">{{ item.description }}</p>
            <pre class="settings-doc-code">{{ item.example }}</pre>
          </div>
        </details>
      </div>
    </FormSection>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import FormSection from '@/components/ai/FormSection.vue'
import { getAuthToken } from '@/api/client'

const serviceBaseUrl = computed(() => window.location.origin)
const openAIBaseUrl = computed(() => `${serviceBaseUrl.value.replace(/\/$/, '')}/v1`)
const currentApiKey = computed(() => getAuthToken() || '<当前密钥>')
const apiDocItems = computed(() => [
  {
    title: '模型列表',
    method: 'GET',
    path: '/v1/models',
    description: '返回 OpenAI 兼容模型列表。',
    example: `curl ${openAIBaseUrl.value}/models \\\n  -H "Authorization: Bearer ${currentApiKey.value}"`,
  },
  {
    title: '聊天补全',
    method: 'POST',
    path: '/v1/chat/completions',
    description: 'OpenAI 兼容聊天补全接口，图片兼容场景也会解析 n 等参数。',
    example: `curl ${openAIBaseUrl.value}/chat/completions \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer ${currentApiKey.value}" \\\n  -d '{"model":"gpt-5-mini","messages":[{"role":"user","content":"你好"}]}'`,
  },
  {
    title: 'Responses',
    method: 'POST',
    path: '/v1/responses',
    description: '兼容 Responses 输入结构，支持文本与工具调用场景。',
    example: `curl ${openAIBaseUrl.value}/responses \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer ${currentApiKey.value}" \\\n  -d '{"model":"gpt-5-mini","input":"生成一张未来城市图片"}'`,
  },
  {
    title: 'Messages',
    method: 'POST',
    path: '/v1/messages',
    description: 'Anthropic Messages 兼容入口，支持 Authorization Bearer 或 x-api-key 鉴权。',
    example: `curl ${openAIBaseUrl.value}/messages \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer ${currentApiKey.value}" \\\n  -d '{"model":"gpt-5-mini","max_tokens":1024,"messages":[{"role":"user","content":"你好"}]}'`,
  },
  {
    title: '联网搜索',
    method: 'POST',
    path: '/v1/search',
    description: '本地搜索兼容入口，返回 answer 与 sources。',
    example: `curl ${openAIBaseUrl.value}/search \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer ${currentApiKey.value}" \\\n  -d '{"prompt":"今天的 OpenAI 新闻"}'`,
  },
  {
    title: '图片生成',
    method: 'POST',
    path: '/v1/images/generations',
    description: '图片生成接口，支持 prompt、model、n、size、quality 等参数。',
    example: `curl ${openAIBaseUrl.value}/images/generations \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer ${currentApiKey.value}" \\\n  -d '{"model":"gpt-image-2","prompt":"一张极简产品海报","n":1}'`,
  },
  {
    title: '图片编辑',
    method: 'POST',
    path: '/v1/images/edits',
    description: '图片编辑接口，支持 multipart 上传参考图。',
    example: `curl ${openAIBaseUrl.value}/images/edits \\\n  -H "Authorization: Bearer ${currentApiKey.value}" \\\n  -F "model=gpt-image-2" \\\n  -F "prompt=改成赛博朋克夜景" \\\n  -F "image=@./input.png"`,
  },
  {
    title: '创建可编辑文件任务',
    method: 'POST',
    path: '/v1/editable-file-tasks',
    description: '统一创建 PPT/PSD 文件任务，kind 可填 ppt 或 psd。',
    example: `curl ${openAIBaseUrl.value}/editable-file-tasks \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer ${currentApiKey.value}" \\\n  -d '{"kind":"ppt","prompt":"做一份产品发布会 PPT"}'`,
  },
  {
    title: '查询可编辑文件任务',
    method: 'GET',
    path: '/v1/editable-file-tasks?ids={taskId1,taskId2}',
    description: '按任务 ID 查询 PPT/PSD 文件生成状态。',
    example: `curl "${openAIBaseUrl.value}/editable-file-tasks?ids=task_1,task_2" \\\n  -H "Authorization: Bearer ${currentApiKey.value}"`,
  },
  {
    title: 'PPT 生成任务',
    method: 'POST',
    path: '/v1/ppt/generations',
    description: '直接创建 PPT 生成任务，返回任务 ID 后再查询状态。',
    example: `curl ${openAIBaseUrl.value}/ppt/generations \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer ${currentApiKey.value}" \\\n  -d '{"prompt":"生成一份市场分析 PPT"}'`,
  },
  {
    title: 'PSD 生成任务',
    method: 'POST',
    path: '/v1/psd/generations',
    description: '直接创建 PSD 生成任务，返回任务 ID 后再查询状态。',
    example: `curl ${openAIBaseUrl.value}/psd/generations \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer ${currentApiKey.value}" \\\n  -d '{"prompt":"生成一张电商海报 PSD"}'`,
  },
  {
    title: '文件下载',
    method: 'GET',
    path: '/files/{file_path}',
    description: '下载 PPT/PSD 任务生成的公开文件。',
    example: `curl ${serviceBaseUrl.value}/files/{file_path}`,
  },
])
</script>
