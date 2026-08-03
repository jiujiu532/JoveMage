<template>
  <div v-if="tasks.length" class="account-task-strips" aria-label="账号批量任务进度">
    <div
      v-for="task in tasks"
      :key="`${task.tier}-${task.taskId}`"
      class="account-task-strip"
      :class="[
        task.tier === 'light' ? 'account-task-strip--light' : 'account-task-strip--heavy',
        `account-task-strip--${task.uiStatus}`,
        task.fading ? 'account-task-strip--fading' : '',
      ]"
      role="button"
      tabindex="0"
      @click="emit('expand', task.tier)"
      @keydown.enter.prevent="emit('expand', task.tier)"
      @keydown.space.prevent="emit('expand', task.tier)"
    >
      <span class="account-task-strip__badge" :title="task.tier === 'light' ? '轻量任务' : '重量任务'">
        {{ tierBadgeLabel(task.tier) }}
      </span>
      <span class="account-task-strip__body">
        <span class="account-task-strip__title">{{ stripTitle(task) }}</span>
        <span class="account-task-strip__meta">
          <span class="tabular-nums">{{ task.progress }}/{{ task.total || '?' }}</span>
          <span v-if="task.uiStatus === 'stopping'" class="account-task-strip__stop-hint">
            · 停止中{{ task.batchRemaining > 0 ? ` 本批剩 ${task.batchRemaining}` : '' }}
          </span>
          <span v-else-if="task.uiStatus === 'completed'"> · 已完成</span>
          <span v-else-if="task.uiStatus === 'stopped'"> · 已停止</span>
          <span v-else-if="task.uiStatus === 'failed'" class="account-task-strip__failed"> · 失败</span>
        </span>
      </span>
      <span class="account-task-strip__actions" @click.stop>
        <Button
          v-if="task.uiStatus === 'running' || task.uiStatus === 'stopping'"
          size="xs"
          variant="outline"
          root-class="min-w-8 justify-center"
          :disabled="task.uiStatus === 'stopping' || task.cancelRequested"
          :title="task.uiStatus === 'stopping' ? '停止中…' : '停止'"
          @click="emit('stop', task.tier)"
        >
          {{ task.uiStatus === 'stopping' || task.cancelRequested ? '…' : '停' }}
        </Button>
        <Button
          v-else-if="task.uiStatus === 'failed'"
          size="xs"
          variant="outline"
          root-class="min-w-8 justify-center"
          title="关闭"
          @click="emit('dismiss', task.tier)"
        >
          ×
        </Button>
        <Button
          size="xs"
          variant="outline"
          root-class="min-w-8 justify-center"
          title="展开进度"
          @click="emit('expand', task.tier)"
        >
          ▣
        </Button>
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Button } from 'nanocat-ui'
import type { AccountTaskTier } from '@/api/accounts'
import { taskTypeLabel, tierBadgeLabel } from '@/views/accounts/accountTaskLabels'
import type { TrackedAccountTask } from '@/views/accounts/useAccountTaskProgress'

const props = defineProps<{
  tasks: TrackedAccountTask[]
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

// template 使用 props.tasks
void props
</script>

<style scoped>
.account-task-strips {
  display: flex;
  min-width: 0;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 4px;
  justify-content: center;
  margin-right: 8px;
}

.account-task-strip {
  display: flex;
  min-width: 0;
  max-width: 28rem;
  align-items: center;
  gap: 6px;
  border: 1px solid hsl(var(--border));
  border-radius: var(--radius);
  background: hsl(var(--card));
  padding: 3px 6px 3px 4px;
  cursor: pointer;
  transition: opacity 0.45s ease, border-color 0.15s ease, background 0.15s ease;
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
