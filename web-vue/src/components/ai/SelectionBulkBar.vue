<template>
  <Teleport to="body">
    <transition :name="transitionName">
      <div
        v-if="selectedCount > 0"
        class="selection-bulk-bar-host"
        :style="{ zIndex }"
      >
        <div
          class="selection-bulk-bar"
          :class="`selection-bulk-bar--${density}`"
          :style="{ maxWidth }"
        >
          <div class="selection-bulk-bar__summary">
            <slot name="summary">
              <p class="selection-bulk-bar__title">{{ resolvedSummary }}</p>
            </slot>
          </div>
          <ActionRow
            class="selection-bulk-bar__actions"
            justify="end"
            gap="tight"
            mobile-justify="start"
          >
            <slot />
          </ActionRow>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ActionRow from './ActionRow.vue'

const props = withDefaults(defineProps<{
  selectedCount: number
  summaryText?: string
  maxWidth?: string
  transitionName?: string
  density?: 'compact' | 'normal'
  zIndex?: number
}>(), {
  summaryText: '',
  maxWidth: '34rem',
  transitionName: 'selection-bulk-bar',
  density: 'normal',
  zIndex: 130,
})

const resolvedSummary = computed(() => props.summaryText || `已选择 ${props.selectedCount} 项`)
</script>

<style scoped>
.selection-bulk-bar-host {
  position: fixed;
  inset-inline: 0;
  bottom: 20px;
  display: flex;
  justify-content: center;
  padding-inline: 16px;
  pointer-events: none;
}

.selection-bulk-bar {
  display: flex;
  width: 100%;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 2px solid var(--bauhaus-ink);
  border-radius: var(--radius);
  background: hsl(var(--card));
  padding: 10px 12px 10px 16px;
  box-shadow: var(--shadow-hard-lg);
  pointer-events: auto;
}

html[data-theme="dark"] .selection-bulk-bar {
  box-shadow: var(--shadow-hard-soft-lg);
}

.selection-bulk-bar--compact {
  gap: 10px;
  padding-block: 9px;
}

.selection-bulk-bar__summary {
  min-width: 0;
}

.selection-bulk-bar__title {
  margin: 0;
  color: hsl(var(--foreground));
  font-size: 14px;
  font-weight: 600;
}

.selection-bulk-bar__actions {
  min-width: 0;
}

.selection-bulk-bar-enter-active,
.selection-bulk-bar-leave-active {
  transition: all 0.2s ease;
}

.selection-bulk-bar-enter-from,
.selection-bulk-bar-leave-to {
  opacity: 0;
  transform: translateY(12px);
}

@media (max-width: 640px) {
  .selection-bulk-bar-host {
    bottom: max(10px, env(safe-area-inset-bottom, 0px));
    padding-inline: max(10px, env(safe-area-inset-left, 0px)) max(10px, env(safe-area-inset-right, 0px));
  }

  .selection-bulk-bar {
    flex-wrap: nowrap;
    align-items: center;
    gap: 10px;
    border-width: 1.5px;
    border-radius: var(--radius);
    padding: 10px 12px;
    /* 窄屏减轻硬阴影，避免压住内容 */
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.12);
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;
    overscroll-behavior-x: contain;
    scrollbar-width: none;
  }

  .selection-bulk-bar::-webkit-scrollbar {
    display: none;
  }

  html[data-theme="dark"] .selection-bulk-bar {
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.4);
  }

  .selection-bulk-bar__summary {
    flex: 0 0 auto;
  }

  .selection-bulk-bar__title {
    font-size: 13px;
    white-space: nowrap;
  }

  .selection-bulk-bar__actions {
    width: auto;
    flex: 1 1 auto;
    min-width: max-content;
  }
}
</style>
