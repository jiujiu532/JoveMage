<template>
  <div class="modal-body" :class="[`modal-body--density-${density}`]">
    <slot />
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  density?: 'compact' | 'normal' | 'roomy'
}>(), {
  density: 'normal',
})
</script>

<style scoped>
.modal-body {
  min-width: 0;
}

.modal-body--density-compact {
  padding: 12px 16px;
}

.modal-body--density-normal {
  padding: 16px 20px;
}

.modal-body--density-roomy {
  padding: 20px;
}

@media (max-width: 640px) {
  .modal-body--density-compact {
    padding: 10px 12px;
  }

  .modal-body--density-normal {
    padding: 12px 14px;
  }

  .modal-body--density-roomy {
    padding: 14px;
  }
}
</style>
