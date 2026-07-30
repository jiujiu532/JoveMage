<template>
  <Teleport to="body">
    <div v-if="open" class="studio-mobile-history-backdrop" @click.self="$emit('close')">
      <div class="studio-mobile-history">
        <div class="studio-mobile-history-header">
          <p>历史记录</p>
          <button type="button" @click="$emit('close')">
            <Icon icon="lucide:x" class="h-5 w-5" />
          </button>
        </div>
        <div class="studio-mobile-history-list">
          <div
            v-for="conversation in conversations"
            :key="conversation.id"
            class="studio-mobile-history-item"
            :class="{ 'is-active': conversation.id === activeConversationId }"
          >
            <button
              type="button"
              class="studio-mobile-history-main"
              @click="$emit('select', conversation.id); $emit('close')"
            >
              <span class="studio-mobile-history-title">{{ conversation.title || '未命名对话' }}</span>
              <span class="studio-mobile-history-meta">
                {{ conversation.messages.length }} 条 · {{ formatTime(conversation.updatedAt) }}
              </span>
              <span
                v-if="badges[conversation.id]"
                class="studio-mobile-history-badge"
                :class="`is-${badges[conversation.id].state}`"
              >
                {{ badges[conversation.id].label }}
              </span>
            </button>
            <button
              type="button"
              class="studio-mobile-history-delete"
              title="删除对话"
              aria-label="删除对话"
              @click.stop="$emit('delete', conversation.id)"
            >
              <Icon icon="lucide:trash-2" class="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { Icon } from '@iconify/vue'
import type { StudioConversation, StudioConversationBadge } from './types'

defineProps<{
  open: boolean
  conversations: StudioConversation[]
  activeConversationId: string
  badges: Record<string, StudioConversationBadge>
}>()

defineEmits<{
  close: []
  select: [id: string]
  delete: [id: string]
}>()

const historyTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

function formatTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return historyTimeFormatter.format(date)
}
</script>

<style scoped>
.studio-mobile-history-backdrop {
  position: fixed;
  inset: 0;
  z-index: 260;
  background: rgb(15 23 42 / 0.36);
  padding: calc(0.75rem + env(safe-area-inset-top, 0px))
    calc(0.75rem + env(safe-area-inset-right, 0px))
    calc(0.75rem + env(safe-area-inset-bottom, 0px))
    calc(0.75rem + env(safe-area-inset-left, 0px));
}

.studio-mobile-history {
  display: flex;
  width: min(24rem, 92vw);
  max-height: calc(100dvh - 1.5rem - env(safe-area-inset-top, 0px) - env(safe-area-inset-bottom, 0px));
  flex-direction: column;
  gap: 0.75rem;
  overflow: hidden;
  border: 2px solid var(--bauhaus-ink, hsl(var(--border)));
  border-radius: var(--radius);
  background: hsl(var(--card));
  padding: 0.75rem;
  box-shadow: var(--shadow-hard-lg);
}

html[data-theme='dark'] .studio-mobile-history {
  box-shadow: var(--shadow-hard-soft-lg, var(--shadow-hard-soft));
}

.studio-mobile-history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.25rem 0.25rem 0;
  color: hsl(var(--foreground));
  font-weight: 650;
}

.studio-mobile-history-header button,
.studio-mobile-history-delete {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius);
  color: hsl(var(--muted-foreground));
}

.studio-mobile-history-header button {
  width: 2rem;
  height: 2rem;
}

.studio-mobile-history-list {
  display: flex;
  min-height: 0;
  flex-direction: column;
  gap: 0.375rem;
  overflow-y: auto;
}

.studio-mobile-history-item {
  position: relative;
  border: 2px solid transparent;
  border-radius: var(--radius);
  padding: 0.7rem 0.75rem;
}

.studio-mobile-history-item.is-active {
  border-color: var(--bauhaus-ink, hsl(var(--primary) / 0.28));
  background: color-mix(in srgb, var(--bauhaus-blue) 10%, transparent);
}

.studio-mobile-history-main {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 0.25rem;
  padding-right: 1.85rem;
  text-align: left;
}

.studio-mobile-history-delete {
  position: absolute;
  top: 0.5rem;
  right: 0.45rem;
  width: 1.75rem;
  height: 1.75rem;
}

.studio-mobile-history-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.875rem;
  font-weight: 650;
}

.studio-mobile-history-meta {
  font-size: 0.75rem;
  color: hsl(var(--muted-foreground));
}

.studio-mobile-history-badge {
  width: fit-content;
  border-radius: var(--radius);
  padding: 0.125rem 0.5rem;
  font-size: 0.6875rem;
  font-weight: 650;
}

.studio-mobile-history-badge.is-running {
  background: hsl(var(--tone-info-bg));
  color: hsl(var(--tone-info-foreground));
}

.studio-mobile-history-badge.is-done {
  background: hsl(var(--tone-success-bg));
  color: hsl(var(--tone-success-foreground));
}

.studio-mobile-history-badge.is-error {
  background: hsl(var(--tone-error-bg));
  color: hsl(var(--tone-error-foreground));
}
</style>
