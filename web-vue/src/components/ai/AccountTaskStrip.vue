<template>
  <div
    class="account-task-strips"
    :class="{ 'account-task-strips--empty': !hasAnyTask }"
    aria-label="账号批量任务进度"
  >
    <div
      v-for="slot in slots"
      :key="slot.tier"
      class="account-task-strip"
      :class="[
        slot.tier === 'light' ? 'account-task-strip--light' : 'account-task-strip--heavy',
        slot.task ? `account-task-strip--${slot.task.uiStatus}` : 'account-task-strip--empty',
        slot.task?.fading ? 'account-task-strip--fading' : '',
      ]"
      :role="slot.task ? 'button' : undefined"
      :tabindex="slot.task ? 0 : undefined"
      @click="slot.task && emit('expand', slot.tier)"
      @keydown.enter.prevent="slot.task && emit('expand', slot.tier)"
      @keydown.space.prevent="slot.task && emit('expand', slot.tier)"
    >
      <span class="account-task-strip__badge" :title="slot.tier === 'light' ? '轻量任务' : '重量任务'">
        {{ tierBadgeLabel(slot.tier) }}
      </span>
      <span class="account-task-strip__body">
        <template v-if="slot.task">
          <span class="account-task-strip__title">{{ stripTitle(slot.task) }}</span>
          <span class="account-task-strip__meta">
            <span class="tabular-nums">{{ slot.task.progress }}/{{ slot.task.total || '?' }}</span>
            <span v-if="slot.task.uiStatus === 'stopping'" class="account-task-strip__stop-hint">
              · 停止中{{ slot.task.batchRemaining > 0 ? ` 本批剩 ${slot.task.batchRemaining}` : '' }}
            </span>
            <span v-else-if="slot.task.uiStatus === 'completed'"> · 已完成</span>
            <span v-else-if="slot.task.uiStatus === 'stopped'"> · 已停止</span>
            <span v-else-if="slot.task.uiStatus === 'failed'" class="account-task-strip__failed"> · 失败</span>
          </span>
        </template>
        <template v-else>
          <span class="account-task-strip__empty-text">无任务</span>
        </template>
      </span>
      <span v-if="slot.task" class="account-task-strip__actions" @click.stop>
        <Button
          v-if="slot.task.uiStatus === 'running' || slot.task.uiStatus === 'stopping'"
          size="xs"
          variant="outline"
          root-class="min-w-8 justify-center"
          :disabled="slot.task.uiStatus === 'stopping' || slot.task.cancelRequested"
          :title="slot.task.uiStatus === 'stopping' ? '停止中…' : '停止'"
          @click="emit('stop', slot.tier)"
        >
          {{ slot.task.uiStatus === 'stopping' || slot.task.cancelRequested ? '…' : '停' }}
        </Button>
        <Button
          v-else-if="slot.task.uiStatus === 'failed'"
          size="xs"
          variant="outline"
          root-class="min-w-8 justify-center"
          title="关闭"
          @click="emit('dismiss', slot.tier)"
        >
          ×
        </Button>
        <Button
          size="xs"
          variant="outline"
          root-class="min-w-8 justify-center"
          title="展开进度"
          @click="emit('expand', slot.tier)"
        >
          ▣
        </Button>
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Button } from 'nanocat-ui'
import type { AccountTaskTier } from '@/api/accounts'
import { taskTypeLabel, tierBadgeLabel } from '@/views/accounts/accountTaskLabels'
import type { TrackedAccountTask } from '@/views/accounts/useAccountTaskProgress'

type StripSlot = TrackedAccountTask | { tier: AccountTaskTier; isEmpty: true }

const props = defineProps<{
  tasks: StripSlot[]
}>()

const emit = defineEmits<{
  expand: [tier: AccountTaskTier]
  stop: [tier: AccountTaskTier]
  dismiss: [tier: AccountTaskTier]
}>()

function stripTitle(task: TrackedAccountTask) {
  // 优先用短动作名，避免顶栏过长
  const short = taskTypeLabel(task.type)
  if (task.title && task.title.length <= 16) return task.title
  return short
}

function isEmptySlot(slot: StripSlot): slot is { tier: AccountTaskTier; isEmpty: true } {
  return 'isEmpty' in slot && slot.isEmpty === true
}

// 常驻两条：重量 + 轻量；无任务时显示「无任务」占位
const slots = computed(() => {
  const heavy = props.tasks.find((task) => task.tier === 'heavy') || null
  const light = props.tasks.find((task) => task.tier === 'light') || null
  return [
    { tier: 'heavy' as AccountTaskTier, task: heavy && !isEmptySlot(heavy) ? heavy : null },
    { tier: 'light' as AccountTaskTier, task: light && !isEmptySlot(light) ? light : null },
  ]
})

const hasAnyTask = computed(() => slots.value.some((slot) => Boolean(slot.task)))
</script>

<style scoped>
.account-task-strips {
  display: flex;
  min-width: 0;
  flex: 0 0 auto;
  flex-direction: column;
  gap: 4px;
  justify-content: center;
  margin-right: 8px;
}

/* 双空态：一行两个小胶囊，不撑高工具行 */
.account-task-strips--empty {
  flex-direction: row;
  gap: 6px;
  align-items: center;
}

.account-task-strip {
  display: flex;
  min-width: 0;
  max-width: 24rem;
  align-items: center;
  gap: 6px;
  border: 1px solid hsl(var(--border));
  border-radius: var(--radius);
  background: hsl(var(--card));
  padding: 3px 6px 3px 4px;
  cursor: pointer;
  transition: opacity 0.45s ease, border-color 0.15s ease, background 0.15s ease;
}

.account-task-strip--empty {
  cursor: default;
  border-style: dashed;
  background: hsl(var(--muted) / 0.25);
  opacity: 0.7;
  width: auto;
  min-width: 4.5rem;
  justify-content: center;
  padding: 2px 6px;
}

.account-task-strip:hover {
  border-color: hsl(var(--foreground) / 0.28);
}

.account-task-strip--heavy {
  border-color: hsl(var(--foreground) / 0.22);
  background: hsl(var(--muted) / 0.55);
}

.account-task-strip--light {
  opacity: 0.92;
  border-color: hsl(var(--border));
  background: hsl(var(--card) / 0.85);
}

.account-task-strip--failed {
  border-color: hsl(var(--tone-error-border) / 0.55);
  background: hsl(var(--tone-error-bg));
}

.account-task-strip--empty {
  cursor: default;
  border-style: dashed;
  background: hsl(var(--muted) / 0.25);
  opacity: 0.7;
  max-width: 10rem;
  justify-content: flex-start;
}

.account-task-strip--empty:hover {
  border-color: hsl(var(--border));
}

.account-task-strip__empty-text {
  color: hsl(var(--muted-foreground));
  font-size: 12px;
  font-weight: 500;
}

.account-task-strip--fading {
  opacity: 0.55;
}

.account-task-strip__badge {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  min-width: 1.25rem;
  height: 1.25rem;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
}

.account-task-strip--heavy .account-task-strip__badge {
  background: hsl(var(--foreground) / 0.12);
  color: hsl(var(--foreground));
}

.account-task-strip--light .account-task-strip__badge {
  background: hsl(var(--muted));
  color: hsl(var(--muted-foreground));
}

.account-task-strip__body {
  display: flex;
  min-width: 0;
  flex: 1 1 auto;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 8px;
  font-size: 12px;
  line-height: 1.25;
}

.account-task-strip__title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  color: hsl(var(--foreground));
}

.account-task-strip__meta {
  color: hsl(var(--muted-foreground));
  font-size: 11px;
}

.account-task-strip__failed {
  color: hsl(var(--tone-error-foreground));
  font-weight: 600;
}

.account-task-strip__actions {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 4px;
}

@media (max-width: 767px) {
  .account-task-strips {
    width: 100%;
    margin-right: 0;
    margin-bottom: 4px;
  }

  .account-task-strip {
    max-width: none;
  }
}
</style>
