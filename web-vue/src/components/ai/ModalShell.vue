<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="modal-shell"
      :class="[`modal-shell--align-${align}`, `modal-shell--placement-${placement}`]"
      :style="{ zIndex }"
      @click.self="handleBackdropClick"
    >
      <div class="modal-shell__stage" @click.self="handleBackdropClick">
        <div
          class="modal-shell__panel"
          :class="panelClass"
          :style="{ maxWidth }"
          role="dialog"
          aria-modal="true"
        >
          <slot />
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
const props = withDefaults(defineProps<{
  open: boolean
  maxWidth?: string
  zIndex?: number
  closeOnBackdrop?: boolean
  align?: 'center' | 'start'
  placement?: 'center' | 'end'
  panelClass?: string
}>(), {
  maxWidth: '44rem',
  zIndex: 120,
  closeOnBackdrop: false,
  align: 'center',
  placement: 'center',
  panelClass: '',
})

const emit = defineEmits<{
  close: []
}>()

function handleBackdropClick() {
  if (props.closeOnBackdrop) emit('close')
}
</script>

<style scoped>
.modal-shell {
  position: fixed;
  inset: 0;
  overflow-y: auto;
  background: var(--overlay-backdrop);
  padding: 16px 12px;
}

.modal-shell__stage {
  display: flex;
  width: 100%;
  min-height: 100%;
}

.modal-shell--align-center .modal-shell__stage {
  align-items: center;
}

.modal-shell--align-start .modal-shell__stage {
  align-items: flex-start;
}

.modal-shell--placement-center .modal-shell__stage {
  justify-content: center;
}

.modal-shell--placement-end .modal-shell__stage {
  justify-content: flex-end;
}

.modal-shell__panel {
  width: 100%;
  overflow: hidden;
  border: 2px solid var(--bauhaus-ink);
  border-radius: var(--radius);
  background: var(--bauhaus-card);
  box-shadow: 4px 4px 0 0 var(--bauhaus-ink);
}

/* 深色 ink 近白，硬阴影会变白框 → 柔和深色投影 */
:global(html[data-theme='dark']) .modal-shell__panel {
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.55);
}

@media (max-width: 640px) {
  .modal-shell {
    padding: 12px;
  }
}
</style>
