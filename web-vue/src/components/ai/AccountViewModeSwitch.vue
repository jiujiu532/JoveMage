<template>
  <div class="account-view-mode" role="group" aria-label="账号视图切换">
    <button
      v-for="mode in modes"
      :key="mode.id"
      type="button"
      class="account-view-mode__btn"
      :class="{ 'is-active': modelValue === mode.id }"
      :title="mode.label"
      :aria-pressed="modelValue === mode.id"
      @click="emit('update:modelValue', mode.id)"
    >
      <span class="account-view-mode__icon" aria-hidden="true" v-html="mode.icon" />
      <span class="account-view-mode__label">{{ mode.label }}</span>
    </button>
  </div>
</template>

<script setup lang="ts">
export type AccountViewMode = 'cards' | 'compact' | 'single' | 'double'

defineProps<{
  modelValue: AccountViewMode
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: AccountViewMode): void
}>()

const modes: { id: AccountViewMode; label: string; icon: string }[] = [
  {
    id: 'compact',
    label: '紧凑',
    icon: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M3 4h10M3 8h10M3 12h10"/></svg>',
  },
  {
    id: 'cards',
    label: '卡片',
    icon: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="2" y="2" width="5" height="5" rx="0.5"/><rect x="9" y="2" width="5" height="5" rx="0.5"/><rect x="2" y="9" width="5" height="5" rx="0.5"/><rect x="9" y="9" width="5" height="5" rx="0.5"/></svg>',
  },
  {
    id: 'single',
    label: '单列',
    icon: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M3 3.5h10M3 8h10M3 12.5h10"/><path d="M3 5.5h7M3 10h7" opacity=".45"/></svg>',
  },
  {
    id: 'double',
    label: '双列',
    icon: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="2" y="3" width="5.5" height="10" rx="0.5"/><rect x="8.5" y="3" width="5.5" height="10" rx="0.5"/></svg>',
  },
]
</script>

<style scoped>
.account-view-mode {
  display: inline-flex;
  align-items: stretch;
  overflow: hidden;
  border: 2px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius, 0.125rem);
  background: var(--bauhaus-card, #fff);
  box-shadow: var(--shadow-hard-sm, 2px 2px 0 0 var(--bauhaus-ink, #2d2d2d));
}

.account-view-mode__btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  min-height: 2rem;
  padding: 0 0.7rem;
  border: 0;
  border-right: 2px solid var(--bauhaus-ink, #2d2d2d);
  background: transparent;
  color: var(--bauhaus-ink, #2d2d2d);
  font-family: var(--font-display, inherit);
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.01em;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 0.15s ease, color 0.15s ease;
}

.account-view-mode__btn:last-child {
  border-right: 0;
}

.account-view-mode__btn:hover:not(.is-active) {
  background: color-mix(in srgb, var(--bauhaus-postit, #f4e7c4) 55%, transparent);
}

.account-view-mode__btn.is-active {
  background: var(--bauhaus-ink, #2d2d2d);
  color: var(--bauhaus-paper, #fdfbf7);
}

.account-view-mode__icon {
  display: inline-flex;
  width: 0.9rem;
  height: 0.9rem;
  flex: 0 0 auto;
}

.account-view-mode__icon :deep(svg) {
  width: 100%;
  height: 100%;
  display: block;
}

.account-view-mode__label {
  line-height: 1;
}

html[data-theme='dark'] .account-view-mode {
  box-shadow: var(--shadow-hard-sm, 0 2px 6px rgba(0, 0, 0, 0.45));
}

@media (max-width: 640px) {
  .account-view-mode {
    border-width: 1.5px;
    box-shadow: none;
  }

  .account-view-mode__label {
    display: none;
  }

  .account-view-mode__btn {
    min-width: 36px;
    min-height: 36px;
    justify-content: center;
    gap: 0;
    padding: 0 0.4rem;
    border-right-width: 1.5px;
  }

  .account-view-mode__icon {
    width: 1rem;
    height: 1rem;
  }

  html[data-theme='dark'] .account-view-mode {
    box-shadow: none;
  }
}
</style>
