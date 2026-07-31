<template>
  <li
    class="proxy-group"
    :class="[
      expanded ? 'proxy-group--open' : '',
      group.enabled ? '' : 'proxy-group--disabled',
    ]"
  >
    <button
      type="button"
      class="proxy-group__summary"
      :aria-expanded="expanded"
      @click="$emit('toggle-expand')"
    >
      <CollapseCaret :open="expanded" />

      <span class="proxy-group__main">
        <span class="proxy-group__name-row">
          <span class="proxy-group__name" :title="group.name || group.id">{{ group.name || group.id }}</span>
          <StateBadge :tone="group.enabled ? 'success' : 'muted'" size="sm">
            {{ group.enabled ? '启用' : '停用' }}
          </StateBadge>
        </span>
        <span class="proxy-group__facts">
          <span class="proxy-group__fact">{{ group.nodes.length }} 节点</span>
          <span class="proxy-group__fact proxy-group__fact--strategy">{{ strategyLabel }}</span>
          <span class="proxy-group__id" :title="group.id">ID:{{ group.id }}</span>
        </span>
        <span v-if="group.notes" class="proxy-group__notes" :title="group.notes">{{ group.notes }}</span>
      </span>

      <span class="proxy-group__health" v-if="group.nodes.length">
        <template v-for="tone in (['ok', 'fail', 'idle'] as const)" :key="tone">
          <span
            v-if="healthSummary[tone]"
            class="proxy-group__health-pill"
            :class="`proxy-group__health-pill--${tone}`"
            :title="tone === 'ok' ? '可用' : tone === 'fail' ? '失败' : '未测'"
          >
            <span class="proxy-group__health-dot" aria-hidden="true"></span>{{ healthSummary[tone] }}
          </span>
        </template>
      </span>

      <span class="proxy-group__actions" @click.stop>
        <Button size="xs" variant="outline" root-class="w-14 justify-center" @click="$emit('edit')">
          编辑
        </Button>
        <FloatingActionMenu
          label="更多"
          :items="actionItems"
          align="right"
          size="sm"
          trigger-class="h-7 justify-center px-2 text-[11px]"
          :trigger-width="64"
          @select="$emit('action', $event)"
        />
      </span>
    </button>

    <div v-show="expanded" class="proxy-group__detail">
      <div class="proxy-group__detail-col proxy-group__detail-col--nodes">
        <p class="proxy-group__detail-label">节点</p>
        <div class="proxy-group__nodes">
          <ProxyNodeSummaryCard
            v-for="node in group.nodes"
            :key="node.id"
            :node="node"
          />
        </div>
      </div>

      <div class="proxy-group__detail-col">
        <p class="proxy-group__detail-label">引用</p>
        <button
          type="button"
          class="proxy-group-ref"
          :title="`点击复制 ${reference}`"
          @click="$emit('copy-reference')"
        >
          <span class="proxy-group-ref__text">{{ reference }}</span>
          <span class="proxy-group-ref__hint">复制</span>
        </button>
      </div>

      <div class="proxy-group__detail-col">
        <p class="proxy-group__detail-label">健康</p>
        <ul class="proxy-group-health">
          <li
            v-for="node in group.nodes"
            :key="`${group.id}-${node.id}-health`"
            class="proxy-group-health__item"
            :class="nodeHealthTone(node)"
            :title="node.last_error || node.last_checked_at || '尚未测试'"
          >
            <span class="proxy-group-health__name">{{ node.name || node.id }}</span>
            <span class="proxy-group-health__value">{{ nodeHealthValue(node) }}</span>
          </li>
        </ul>
      </div>
    </div>
  </li>
</template>

<script setup lang="ts">
import { Button } from 'nanocat-ui'
import type { ActionMenuItem } from 'nanocat-ui'
import type { ProxyGroup, ProxyNode } from '@/api/proxy'
import CollapseCaret from '@/components/ai/CollapseCaret.vue'
import FloatingActionMenu from '@/components/ai/FloatingActionMenu.vue'
import ProxyNodeSummaryCard from '@/components/ai/ProxyNodeSummaryCard.vue'
import StateBadge from '@/components/ai/StateBadge.vue'

defineProps<{
  group: ProxyGroup
  expanded: boolean
  strategyLabel: string
  reference: string
  healthSummary: { ok: number; fail: number; idle: number }
  actionItems: ActionMenuItem[]
  nodeHealthValue: (node: ProxyNode) => string
  nodeHealthTone: (node: ProxyNode) => string
}>()

defineEmits<{
  'toggle-expand': []
  edit: []
  action: [key: string]
  'copy-reference': []
}>()
</script>

<style scoped>
.proxy-group {
  overflow: hidden;
  border: 1.5px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  background: hsl(var(--card));
  box-shadow: var(--shadow-hard-sm, 2px 2px 0 0 var(--bauhaus-ink, #2d2d2d));
}
.proxy-group--disabled {
  background: color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 4%, hsl(var(--card)));
}

/* 概要行（整行可点） */
.proxy-group__summary {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 14px;
  width: 100%;
  padding: 12px 14px;
  background: transparent;
  border: 0;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease;
}
.proxy-group__summary:hover {
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 4%, transparent);
}
.proxy-group__summary:focus-visible {
  outline: 2px solid var(--bauhaus-blue, #2d5da1);
  outline-offset: -2px;
}

.proxy-group__main {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 5px;
}
.proxy-group__name-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.proxy-group__name {
  overflow: hidden;
  color: var(--bauhaus-ink, #2d2d2d);
  font-size: 14px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.proxy-group--disabled .proxy-group__name {
  color: hsl(var(--muted-foreground));
}
.proxy-group__facts {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  min-width: 0;
}
.proxy-group__fact {
  border: 1px solid color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 30%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 7%, transparent);
  padding: 1px 7px;
  color: var(--bauhaus-blue, #2d5da1);
  font-size: 10px;
  font-weight: 600;
  line-height: 1.6;
}
.proxy-group__fact--strategy {
  background: color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 6%, transparent);
  color: hsl(var(--muted-foreground));
}
.proxy-group__id {
  overflow: hidden;
  color: hsl(var(--muted-foreground));
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 10.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.proxy-group__notes {
  overflow: hidden;
  color: hsl(var(--muted-foreground));
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 概要行右侧健康胶囊 */
.proxy-group__health {
  display: flex;
  flex: 0 0 auto;
  gap: 6px;
}
.proxy-group__health-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1.5px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.proxy-group__health-dot {
  width: 7px;
  height: 7px;
  border: 1.5px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: 50%;
}
.proxy-group__health-pill--ok { color: var(--bauhaus-blue, #2d5da1); }
.proxy-group__health-pill--ok .proxy-group__health-dot { background: var(--bauhaus-blue, #2d5da1); }
.proxy-group__health-pill--fail { color: var(--bauhaus-red, #ff4d4d); }
.proxy-group__health-pill--fail .proxy-group__health-dot { background: var(--bauhaus-red, #ff4d4d); }
.proxy-group__health-pill--idle { color: hsl(var(--muted-foreground)); }
.proxy-group__health-pill--idle .proxy-group__health-dot {
  background: color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 30%, transparent);
}

.proxy-group__actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 8px;
}

/* 展开详情 */
.proxy-group__detail {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) minmax(0, 1fr);
  gap: 18px;
  border-top: 1.5px solid color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 16%, transparent);
  background: color-mix(in srgb, var(--bauhaus-paper-2, #f5f0e6) 55%, transparent);
  padding: 14px 16px 16px;
}
@media (max-width: 900px) {
  .proxy-group__detail {
    grid-template-columns: 1fr;
  }
}
.proxy-group__detail-label {
  margin: 0 0 8px;
  color: hsl(var(--muted-foreground));
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}
.proxy-group__nodes {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* 局部布局断点：分组摘要栅格改排；取 720 为「小平板」改排，区别于全局 sm(640)/md(768) */
@media (max-width: 720px) {
  .proxy-group__summary {
    grid-template-columns: auto minmax(0, 1fr);
    row-gap: 8px;
  }
  .proxy-group__health,
  .proxy-group__actions {
    grid-column: 2;
  }
}

/* 引用按钮 */
.proxy-group-ref {
  display: inline-flex;
  max-width: 100%;
  align-items: center;
  gap: 6px;
  border: 1.5px solid color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 28%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--bauhaus-card, #fff) 70%, transparent);
  padding: 4px 8px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  color: hsl(var(--muted-foreground));
  cursor: pointer;
  transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;
}
.proxy-group-ref:hover {
  border-color: var(--bauhaus-blue, #2d5da1);
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 7%, transparent);
  color: var(--bauhaus-blue, #2d5da1);
}
.proxy-group-ref__text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.proxy-group-ref__hint {
  flex: 0 0 auto;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  opacity: 0;
  transition: opacity 0.15s ease;
}
.proxy-group-ref:hover .proxy-group-ref__hint {
  opacity: 1;
}

/* 健康列 */
.proxy-group-health {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.proxy-group-health__item {
  display: flex;
  align-items: baseline;
  gap: 7px;
  min-width: 0;
  font-size: 11px;
  line-height: 1.4;
}
.proxy-group-health__item::before {
  content: '';
  flex: 0 0 auto;
  align-self: center;
  width: 7px;
  height: 7px;
  border: 1.5px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: 50%;
  background: color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 25%, transparent);
}
.proxy-group-health__item.is-ok::before { background: var(--bauhaus-blue, #2d5da1); }
.proxy-group-health__item.is-fail::before { background: var(--bauhaus-red, #ff4d4d); }
.proxy-group-health__item.is-testing::before { background: var(--bauhaus-postit, #f4e7c4); }
.proxy-group-health__name {
  flex: 0 0 auto;
  color: var(--bauhaus-ink, #2d2d2d);
  font-weight: 600;
}
.proxy-group-health__value {
  min-width: 0;
  overflow: hidden;
  font-variant-numeric: tabular-nums;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.proxy-group-health__item.is-ok .proxy-group-health__value { color: var(--bauhaus-blue, #2d5da1); }
.proxy-group-health__item.is-fail .proxy-group-health__value { color: var(--bauhaus-red, #ff4d4d); }
.proxy-group-health__item.is-testing .proxy-group-health__value { color: hsl(var(--muted-foreground)); }
.proxy-group-health__item.is-idle .proxy-group-health__value { color: hsl(var(--muted-foreground)); }
</style>
