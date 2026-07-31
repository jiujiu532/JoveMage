<template>
  <span
    class="quota-badge inline-flex min-w-[2.75rem] items-center justify-center border px-2.5 py-1 font-mono text-xs font-semibold leading-none tabular-nums"
    :class="quotaClass"
  >
    {{ quotaText }}
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Account } from '@/api/accounts'

const props = defineProps<{
  account: Account
}>()

const quotaValue = computed(() => {
  const creditsAvailable = Number(props.account.credits?.available)
  if (Number.isFinite(creditsAvailable)) return creditsAvailable
  return Number(props.account.quota || 0)
})

const quotaText = computed(() => {
  const credits = props.account.credits
  if (credits && (credits.available != null || credits.total != null)) {
    if (credits.available != null && credits.total != null) {
      return `${Math.max(0, Math.trunc(Number(credits.available)))}/${Math.max(0, Math.trunc(Number(credits.total)))}`
    }
    if (credits.available != null) return String(Math.max(0, Math.trunc(Number(credits.available))))
  }
  if (props.account.image_quota_unknown) return '未知'
  return String(Math.max(0, Math.trunc(Number(props.account.quota || 0))))
})

const quotaClass = computed(() => {
  if (props.account.image_quota_unknown && !(props.account.credits && props.account.credits.available != null)) {
    return 'quota-badge--muted'
  }
  if (quotaValue.value <= 0) return 'quota-badge--danger'
  if (quotaValue.value <= 3) return 'quota-badge--warning'
  return 'quota-badge--success'
})
</script>

<style scoped>
.quota-badge {
  border-radius: var(--radius);
}

.quota-badge--muted {
  border-color: hsl(var(--border));
  background: hsl(var(--muted) / 0.4);
  color: hsl(var(--muted-foreground));
}

/* 成功 = 蓝（对齐 StateBadge）；warning/danger 走 tone 令牌 */
.quota-badge--success {
  border-color: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 40%, transparent);
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 12%, transparent);
  color: var(--bauhaus-blue, #2d5da1);
}

.quota-badge--warning {
  border-color: hsl(var(--tone-warning-border) / 0.45);
  background: hsl(var(--tone-warning-bg));
  color: hsl(var(--tone-warning-foreground));
}

.quota-badge--danger {
  border-color: hsl(var(--tone-error-border) / 0.45);
  background: hsl(var(--tone-error-bg));
  color: hsl(var(--tone-error-foreground));
}

html[data-theme='dark'] .quota-badge--success {
  border-color: color-mix(in srgb, var(--bauhaus-blue, #3d8fd9) 45%, transparent);
  background: color-mix(in srgb, var(--bauhaus-blue, #3d8fd9) 18%, transparent);
  color: var(--bauhaus-blue, #3d8fd9);
}

html[data-theme='dark'] .quota-badge--warning {
  border-color: hsl(var(--tone-warning-border));
  background: hsl(var(--tone-warning-bg));
  color: hsl(var(--tone-warning-foreground));
}

html[data-theme='dark'] .quota-badge--danger {
  border-color: hsl(var(--tone-error-border));
  background: hsl(var(--tone-error-bg));
  color: hsl(var(--tone-error-foreground));
}

html[data-theme='dark'] .quota-badge--muted {
  border-color: var(--bauhaus-line-soft, #3d3d3d);
  color: var(--bauhaus-grey, #a3a3a3);
}
</style>
