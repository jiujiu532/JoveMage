<template>
  <article
    class="logs-mobile-card"
    :class="{ 'is-selected': selected }"
  >
    <div class="logs-mobile-card__head">
      <Checkbox
        :model-value="selected"
        @update:model-value="onSelect"
      >
        <span class="sr-only">选择日志 {{ item.time || item.id }}</span>
      </Checkbox>
      <p class="logs-mobile-card__time cell-time">{{ item.time || '-' }}</p>
      <StateBadge :tone="statusTone" shape="rounded" :bordered="false">
        {{ statusLabel }}
      </StateBadge>
    </div>
    <div class="logs-mobile-card__meta">
      <MetaChip size="xs" tone="muted">{{ typeLabel }}</MetaChip>
      <ChannelBadge
        v-if="item.channel"
        :channel="item.channel"
        size="xs"
        force
        class="logs-mobile-card__channel"
      />
      <span class="cell-num text-xs text-muted-foreground">{{ durationLabel }}</span>
      <p class="cell-token min-w-0 flex-1 truncate text-xs" :title="tokenLabel">
        {{ tokenLabel || '-' }}
      </p>
    </div>
    <div class="logs-mobile-card__body">
      <LogImagePreviewCell
        v-if="item.imageUrls?.length"
        :image-urls="item.imageUrls"
        :first-image-broken="firstImageBroken"
        :alt="item.preview || '日志结果图片'"
        @preview-click="emit('view', item)"
        @image-error="onImageError"
      />
      <p
        class="logs-mobile-card__summary"
        :class="{ 'text-rose-600': failed }"
        :title="summary"
      >
        {{ summary || '-' }}
      </p>
    </div>
    <div class="logs-mobile-card__actions">
      <Button size="xs" variant="outline" @click="emit('view', item)">查看详情</Button>
      <Button size="xs" variant="ghost" root-class="text-rose-600 hover:text-rose-700" @click="emit('delete', item)">
        删除
      </Button>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Button, Checkbox } from 'nanocat-ui'
import ChannelBadge from '@/components/ai/ChannelBadge.vue'
import LogImagePreviewCell from '@/components/ai/LogImagePreviewCell.vue'
import MetaChip from '@/components/ai/MetaChip.vue'
import StateBadge from '@/components/ai/StateBadge.vue'
import {
  formatLogDuration,
  isSystemLogFailed,
  isSystemLogLimited,
  isSystemLogSuccess,
  type SystemLogRow,
} from '@/api/logs'

const props = defineProps<{
  item: SystemLogRow
  selected: boolean
  firstImageBroken?: boolean
}>()

const emit = defineEmits<{
  select: [id: string, checked: boolean | string]
  view: [item: SystemLogRow]
  delete: [item: SystemLogRow]
  'image-error': [event: Event, url: string]
}>()

const failed = computed(() => isSystemLogFailed(props.item))

const statusLabel = computed(() => {
  if (isSystemLogSuccess(props.item)) return '成功'
  if (isSystemLogFailed(props.item)) return '失败'
  if (isSystemLogLimited(props.item)) return '受限'
  return props.item.status || '记录'
})

const statusTone = computed<'success' | 'danger' | 'warning' | 'muted'>(() => {
  if (isSystemLogSuccess(props.item)) return 'success'
  if (isSystemLogFailed(props.item)) return 'danger'
  if (isSystemLogLimited(props.item)) return 'warning'
  return 'muted'
})

const typeLabel = computed(() => {
  if (props.item.type === 'call') return '调用日志'
  if (props.item.type === 'account') return '账号日志'
  return props.item.type || '日志'
})

const tokenLabel = computed(() => props.item.keyName || props.item.keyId || props.item.accountEmail)

const summary = computed(() => props.item.summary || props.item.error || props.item.reason || props.item.preview)

const durationLabel = computed(() => formatLogDuration(props.item.durationMs) || '-')

function onSelect(checked: boolean | string) {
  emit('select', props.item.id, checked)
}

function onImageError(event: Event, url: string) {
  emit('image-error', event, url)
}
</script>

<style scoped>
.logs-mobile-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border: 2px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  background: hsl(var(--card));
  box-shadow: 2px 2px 0 0 var(--bauhaus-ink, #2d2d2d);
  padding: 10px 12px;
}

.logs-mobile-card.is-selected {
  border-color: var(--bauhaus-blue, #2d5da1);
  box-shadow: 2px 2px 0 0 var(--bauhaus-blue, #2d5da1);
}

.logs-mobile-card__head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.logs-mobile-card__time {
  min-width: 0;
  flex: 1 1 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
  color: var(--bauhaus-ink, #2d2d2d);
}

.logs-mobile-card__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 8px;
}

.logs-mobile-card__body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.logs-mobile-card__summary {
  margin: 0;
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  font-size: 12px;
  line-height: 1.45;
  color: hsl(var(--foreground));
  overflow-wrap: anywhere;
}

.logs-mobile-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-top: 2px;
}

.logs-mobile-card :deep(.cell-num) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
}

.logs-mobile-card :deep(.cell-token) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  letter-spacing: -0.01em;
  color: hsl(var(--foreground));
}

html[data-theme='dark'] .logs-mobile-card {
  border-color: hsl(var(--border));
  box-shadow: 2px 2px 0 0 hsl(var(--border));
}

html[data-theme='dark'] .logs-mobile-card.is-selected {
  border-color: var(--bauhaus-blue, #2d5da1);
  box-shadow: 2px 2px 0 0 var(--bauhaus-blue, #2d5da1);
}

html[data-theme='dark'] .logs-mobile-card__time {
  color: hsl(var(--foreground));
}
</style>
