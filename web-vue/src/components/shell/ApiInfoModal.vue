<template>
  <ModalShell
    :open="open"
    max-width="32rem"
    :z-index="100"
    panel-class="p-6"
    close-on-backdrop
    @close="emit('close')"
  >
    <ModalHeader
      title="API 接口"
      subtitle="根据客户端选择对应接口"
      title-class="ui-subsection-title"
      :bordered="false"
      flush
      @close="emit('close')"
    />

    <div class="mt-4 space-y-3 text-sm">
      <div>
        <p class="text-xs text-muted-foreground">基础端点</p>
        <div class="mt-1 flex items-start gap-2">
          <ValueSurface
            tag="p"
            mono
            break-mode="all"
            root-class="min-w-0 flex-1"
          >
            {{ apiBaseUrl }}
          </ValueSurface>
          <Button
            size="sm"
            variant="outline"
            root-class="shrink-0 text-[11px] text-muted-foreground"
            @click="copyText(apiBaseUrl)"
          >
            复制
          </Button>
        </div>
      </div>
      <div>
        <p class="text-xs text-muted-foreground">SDK 接口</p>
        <div class="mt-1 flex items-start gap-2">
          <ValueSurface
            tag="p"
            mono
            break-mode="all"
            root-class="min-w-0 flex-1"
          >
            {{ apiSdkUrl }}
          </ValueSurface>
          <Button
            size="sm"
            variant="outline"
            root-class="shrink-0 text-[11px] text-muted-foreground"
            @click="copyText(apiSdkUrl)"
          >
            复制
          </Button>
        </div>
      </div>
      <div>
        <p class="text-xs text-muted-foreground">完整接口</p>
        <div class="mt-1 flex items-start gap-2">
          <ValueSurface
            tag="p"
            mono
            break-mode="all"
            root-class="min-w-0 flex-1"
          >
            {{ apiFullUrl }}
          </ValueSurface>
          <Button
            size="sm"
            variant="outline"
            root-class="shrink-0 text-[11px] text-muted-foreground"
            @click="copyText(apiFullUrl)"
          >
            复制
          </Button>
        </div>
      </div>
      <div>
        <p class="text-xs text-muted-foreground">支持模型</p>
        <div class="mt-1 space-y-3 rounded-sm border border-border bg-background px-3 py-2 text-xs text-muted-foreground">
          <div>
            <p class="mb-1 text-[11px] text-muted-foreground">聊天模型</p>
            <div class="flex flex-wrap gap-2 text-foreground">
              <MetaChip
                v-for="model in supportedChatModels"
                :key="`chat-${model}`"
                size="xs"
              >
                {{ model }}
              </MetaChip>
            </div>
          </div>
          <div>
            <p class="mb-1 text-[11px] text-muted-foreground">图片模型</p>
            <div class="flex flex-wrap gap-2 text-foreground">
              <MetaChip
                v-for="model in supportedImageModels"
                :key="`image-${model}`"
                size="xs"
              >
                {{ model }}
              </MetaChip>
            </div>
          </div>
        </div>
      </div>
      <div>
        <p class="text-xs text-muted-foreground">当前调用密钥</p>
        <div class="mt-1 flex items-start gap-2">
          <ValueSurface
            tag="p"
            mono
            break-mode="all"
            root-class="min-w-0 flex-1"
          >
            {{ apiKeyDisplay }}
          </ValueSurface>
          <Button
            size="sm"
            variant="outline"
            root-class="shrink-0 text-[11px] text-muted-foreground"
            :disabled="!currentAuthToken"
            @click="copyText(apiKeyDisplay)"
          >
            复制
          </Button>
        </div>
        <p class="mt-1 text-[11px] text-muted-foreground">
          请求头使用 Authorization: Bearer &lt;当前调用密钥&gt;。
        </p>
      </div>
    </div>

    <ModalFooter class="mt-6" :bordered="false" flush>
      <Button
        size="xs"
        variant="primary"
        root-class="min-w-14 justify-center"
        @click="emit('close')"
      >
        知道了
      </Button>
    </ModalFooter>
  </ModalShell>
</template>

<script setup lang="ts">
import { Button, ValueSurface } from 'nanocat-ui'
import MetaChip from '@/components/ai/MetaChip.vue'
import ModalFooter from '@/components/ai/ModalFooter.vue'
import ModalHeader from '@/components/ai/ModalHeader.vue'
import ModalShell from '@/components/ai/ModalShell.vue'
import { useClipboard } from '@/composables/useClipboard'

defineProps<{
  open: boolean
  apiBaseUrl: string
  apiSdkUrl: string
  apiFullUrl: string
  apiKeyDisplay: string
  currentAuthToken: string
  supportedChatModels: string[]
  supportedImageModels: string[]
}>()

const emit = defineEmits<{
  close: []
}>()

const { copy } = useClipboard()

async function copyText(value: string) {
  const text = String(value || '').trim()
  if (!text) return
  await copy(text, { error: '复制失败，请手动复制' })
}
</script>
