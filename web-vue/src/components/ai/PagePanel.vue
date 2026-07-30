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
  /* 浅色硬偏移 / 深色柔和：走 --shadow-card 令牌 */
  box-shadow: var(--shadow-card, 3px 3px 0 0 var(--bauhaus-ink)) !important;
  background: hsl(var(--card)) !important;
  overflow: hidden;
  padding: 0 !important;
  transition:
    transform 0.16s ease,
    border-color 0.16s ease,
    box-shadow 0.16s ease;
}

html[data-theme='dark'] .page-panel {
  border-color: hsl(var(--border)) !important;
  box-shadow: var(--shadow-card-soft, 0 4px 14px rgba(0, 0, 0, 0.45)) !important;
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
  min-width: 0;
  padding: 1.25rem;
}

.page-panel--flush .page-panel__body {
  padding: 0;
}

@media (prefers-reduced-motion: reduce) {
  .page-panel {
    transition: none;
  }
}
</style>
