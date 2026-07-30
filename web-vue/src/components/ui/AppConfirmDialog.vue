<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="confirm-dialog"
      @click.self="emit('cancel')"
    >
      <div class="confirm-dialog__stage">
        <div
          class="confirm-dialog__panel"
          role="dialog"
          aria-modal="true"
        >
          <div class="px-5 pb-0 pt-5">
            <h4 class="ui-dialog-title">{{ title || '确认操作' }}</h4>
          </div>
          <div class="ui-dialog-body whitespace-pre-line px-5 pb-5 pt-3">
            {{ message }}
          </div>
          <div class="flex items-center justify-end gap-2 px-5 pb-5 pt-0">
            <Button
              size="xs"
              variant="outline"
              root-class="min-w-14 justify-center text-muted-foreground"
              @click="emit('cancel')"
            >
              {{ cancelText || '取消' }}
            </Button>
            <Button
              size="xs"
              variant="primary"
              root-class="min-w-14 justify-center"
              @click="emit('confirm')"
            >
              {{ confirmText || '确定' }}
            </Button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import { Button } from 'nanocat-ui'

const props = defineProps<{
  open: boolean
  title?: string
  message: string
  confirmText?: string
  cancelText?: string
}>()

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && props.open) {
    event.preventDefault()
    emit('cancel')
  }
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      document.addEventListener('keydown', handleKeydown)
      return
    }
    document.removeEventListener('keydown', handleKeydown)
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<style scoped>
.confirm-dialog {
  position: fixed;
  inset: 0;
  z-index: 300;
  overflow-y: auto;
  background: var(--overlay-backdrop);
  padding:
    max(16px, env(safe-area-inset-top, 0px))
    max(12px, env(safe-area-inset-right, 0px))
    max(16px, env(safe-area-inset-bottom, 0px))
    max(12px, env(safe-area-inset-left, 0px));
}

.confirm-dialog__stage {
  display: flex;
  min-height: 100%;
  align-items: center;
  justify-content: center;
}

.confirm-dialog__panel {
  width: 100%;
  max-width: 24rem;
  border: 2px solid var(--bauhaus-ink);
  border-radius: var(--radius);
  background: var(--bauhaus-card);
  box-shadow: 4px 4px 0 0 var(--bauhaus-ink);
}

:global(html[data-theme='dark']) .confirm-dialog__panel {
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.55);
}
</style>
