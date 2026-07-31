<template>
  <ModalShell
    :open="open"
    max-width="42rem"
    :z-index="100"
    panel-class="p-6"
    close-on-backdrop
    @close="emit('close')"
  >
    <ModalHeader
      title="版本更新"
      subtitle="查看当前版本和更新日志"
      title-class="ui-subsection-title"
      :bordered="false"
      flush
      @close="emit('close')"
    />

    <div class="mt-4 grid gap-3 sm:grid-cols-2">
      <div class="rounded-sm border border-border bg-background px-4 py-3">
        <p class="text-xs text-muted-foreground">当前版本</p>
        <p class="mt-1 text-base font-semibold text-foreground">{{ currentVersionLabel }}</p>
      </div>
      <div class="rounded-sm border border-border bg-background px-4 py-3">
        <div class="flex items-center justify-between gap-3">
          <p class="text-xs text-muted-foreground">最新版本</p>
          <button
            type="button"
            class="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="isCheckingUpdate"
            @click="emit('check-updates')"
          >
            {{ isCheckingUpdate ? '检查中...' : '检查更新' }}
          </button>
        </div>
        <p class="mt-1 text-base font-semibold text-foreground">{{ latestVersionLabel }}</p>
      </div>
    </div>

    <div v-if="updateCheckMessage" class="mt-3 rounded-sm border border-border bg-muted/40 px-4 py-2 text-xs text-muted-foreground">
      {{ updateCheckMessage }}
    </div>

    <div class="mt-5 max-h-[56vh] space-y-5 overflow-y-auto pr-1">
      <div
        v-for="release in releaseEntries"
        :key="`${release.version}-${release.date}`"
        class="border-l border-border pl-4"
      >
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-sm font-semibold text-foreground">
            {{ release.version === 'Unreleased' ? '未发布' : release.version }}
          </span>
          <span v-if="release.date" class="text-xs text-muted-foreground">{{ release.date }}</span>
          <MetaChip
            v-if="normalizeVersionTag(release.version) === latestVersionLabel"
            size="xs"
            tone="success"
            strong
          >
            最新
          </MetaChip>
          <MetaChip
            v-if="normalizeVersionTag(release.version) === currentVersionLabel"
            size="xs"
            tone="muted"
          >
            当前
          </MetaChip>
        </div>
        <div class="mt-2 space-y-1.5">
          <div
            v-for="(item, index) in release.items"
            :key="`${release.version}-${index}`"
            class="flex items-start gap-2 text-sm leading-6 text-muted-foreground"
          >
            <MetaChip
              size="xs"
              :tone="releaseItemTone(item.type)"
              strong
              chip-class="mt-0.5 shrink-0"
            >
              {{ item.type }}
            </MetaChip>
            <span class="min-w-0 flex-1 text-foreground/85">{{ item.content }}</span>
          </div>
        </div>
      </div>
      <div v-if="!releaseEntries.length" class="rounded-sm border border-dashed border-border bg-muted/30 px-4 py-6 text-center text-sm text-muted-foreground">
        暂无更新日志。
      </div>
    </div>

    <ModalFooter class="mt-6" :bordered="false" flush>
      <Button
        size="xs"
        variant="outline"
        @click="emit('open-release-page')"
      >
        打开发布页
      </Button>
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
import { Button } from 'nanocat-ui'
import MetaChip from '@/components/ai/MetaChip.vue'
import ModalFooter from '@/components/ai/ModalFooter.vue'
import ModalHeader from '@/components/ai/ModalHeader.vue'
import ModalShell from '@/components/ai/ModalShell.vue'
import { normalizeVersionTag, type ReleaseInfo } from '@/lib/release'

defineProps<{
  open: boolean
  currentVersionLabel: string
  latestVersionLabel: string
  isCheckingUpdate: boolean
  updateCheckMessage: string
  releaseEntries: ReleaseInfo[]
}>()

const emit = defineEmits<{
  close: []
  'check-updates': []
  'open-release-page': []
}>()

function releaseItemTone(type: string): 'default' | 'muted' | 'success' | 'warning' | 'danger' | 'info' {
  const value = String(type || '').trim()
  if (['新增', '添加', 'Added'].includes(value)) return 'success'
  if (['优化', '改进', 'Changed', 'Improved'].includes(value)) return 'info'
  if (['修复', '修正', 'Fixed'].includes(value)) return 'warning'
  if (['移除', '删除', '废弃', 'Removed', 'Deprecated'].includes(value)) return 'danger'
  return 'muted'
}
</script>
