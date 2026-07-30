<template>
  <article class="proxy-node-summary-card" :class="{ 'proxy-node-summary-card--disabled': !isEnabled }">
    <div class="proxy-node-summary-card__header">
      <p class="proxy-node-summary-card__name">{{ displayName }}</p>
      <span
        class="proxy-node-summary-card__status"
        :class="isEnabled ? 'proxy-node-summary-card__status--enabled' : 'proxy-node-summary-card__status--disabled'"
      >
        {{ isEnabled ? '启用' : '停用' }}
      </span>
    </div>
    <p class="proxy-node-summary-card__url">{{ maskedUrl || emptyText }}</p>
    <p class="proxy-node-summary-card__meta">
      <span class="proxy-node-summary-card__meta-key">图片并发</span>
      <span class="proxy-node-summary-card__meta-value">{{ imageLimit > 0 ? imageLimit : '不限' }}</span>
    </p>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ProxyNode } from '@/api/proxy'

const props = withDefaults(defineProps<{
  node: Pick<ProxyNode, 'id' | 'name' | 'url' | 'enabled' | 'image_concurrency_limit'>
  emptyText?: string
}>(), {
  emptyText: '未设置',
})

const isEnabled = computed(() => props.node.enabled !== false)
const displayName = computed(() => props.node.name || props.node.id)
const imageLimit = computed(() => Math.max(0, Number(props.node.image_concurrency_limit || 0)))
const maskedUrl = computed(() => maskProxy(props.node.url))

function maskProxy(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  return raw.replace(/:\/\/([^/@:]+):([^/@]+)@/, (_match, user) => `://${user}:***@`)
}
</script>

<style scoped>
.proxy-node-summary-card {
  position: relative;
  min-width: 0;
  overflow: hidden;
  border: 1.5px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  background: hsl(var(--card));
  box-shadow: var(--shadow-hard-sm, 2px 2px 0 0 var(--bauhaus-ink, #2d2d2d));
  padding: 8px 10px 8px;
}
/* 顶部 Bauhaus 色条 */
.proxy-node-summary-card::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: 3px;
  background: var(--bauhaus-blue, #2d5da1);
}

.proxy-node-summary-card--disabled {
  background: color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 5%, hsl(var(--card)));
  box-shadow: none;
  border-color: color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 40%, transparent);
}
.proxy-node-summary-card--disabled::before {
  background: color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 40%, transparent);
}

.proxy-node-summary-card__header {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 2px;
}

.proxy-node-summary-card__name {
  min-width: 0;
  overflow: hidden;
  color: hsl(var(--foreground));
  font-size: 12px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.proxy-node-summary-card--disabled .proxy-node-summary-card__name {
  color: hsl(var(--muted-foreground));
}

.proxy-node-summary-card__status {
  flex: 0 0 auto;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.05em;
}

.proxy-node-summary-card__status--enabled {
  color: var(--bauhaus-blue, #2d5da1);
}

.proxy-node-summary-card__status--disabled {
  color: hsl(var(--muted-foreground));
}

.proxy-node-summary-card__url {
  margin-top: 4px;
  overflow-wrap: anywhere;
  color: hsl(var(--muted-foreground));
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 10.5px;
  line-height: 1.4;
}

.proxy-node-summary-card__meta {
  margin-top: 5px;
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: 10.5px;
  line-height: 1.4;
}
.proxy-node-summary-card__meta-key {
  color: hsl(var(--muted-foreground));
}
.proxy-node-summary-card__meta-value {
  color: var(--bauhaus-ink, #2d2d2d);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.proxy-node-summary-card--disabled .proxy-node-summary-card__meta-value {
  color: hsl(var(--muted-foreground));
}
</style>
