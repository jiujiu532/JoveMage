<template>
  <section class="ui-panel page-panel" :class="{ 'page-panel--flush': flush }">
    <div class="page-panel__stripe" aria-hidden="true">
      <span class="bg-[var(--bauhaus-blue)]" />
      <span class="bg-[var(--bauhaus-red)]" />
      <span class="bg-[var(--bauhaus-yellow)]" />
    </div>
    <div class="page-panel__body">
      <slot />
    </div>
  </section>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  flush?: boolean
}>(), {
  flush: false,
})
</script>

<style scoped>
.page-panel {
  position: relative;
  border: 2px solid var(--bauhaus-ink, #2d2d2d) !important;
  border-radius: var(--radius) !important;
  box-shadow: none !important;
  background: hsl(var(--card)) !important;
  overflow: hidden;
  padding: 0 !important;
}

html[data-theme='dark'] .page-panel {
  border-color: hsl(var(--border)) !important;
}

.page-panel__stripe {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  height: 5px;
}

.page-panel__stripe span {
  display: block;
  min-height: 5px;
}

.page-panel__body {
  padding: 1.25rem;
}

.page-panel--flush .page-panel__body {
  padding: 0;
}
</style>
