<template>
  <PagePanel class="space-y-4">
    <PanelHeader title="代理组 / 多出口">
      <template #copy>
        <p class="mt-1 text-xs text-muted-foreground">
          一个代理组就是一组多出口节点；图片请求会从未满的节点里随机选择一个，请求结束前固定该出口，出口满了会等待，不会自动绕到直连。
        </p>
      </template>
      <template #actions>
        <Input
          :model-value="keyword"
          block
          root-class="min-w-[12rem] md:w-80"
          placeholder="搜索代理组 / 节点 / 地址"
          @update:model-value="$emit('update:keyword', $event)"
        />
        <Button size="sm" variant="primary" @click="$emit('create')">新建代理组</Button>
      </template>
    </PanelHeader>
    <PageLoadingState
      v-if="loading && groupsLength === 0"
      title="正在加载代理组"
      description="读取代理组、节点和健康状态。"
    />
    <StateBlock v-else-if="filteredGroups.length === 0">
      <EmptyState plain title="暂无代理组" description="新建代理组后，可绑定账号组、账号或默认出口使用。" />
    </StateBlock>
    <ul v-else class="proxy-groups">
      <ProxyGroupCard
        v-for="group in filteredGroups"
        :key="group.id"
        :group="group"
        :expanded="isGroupExpanded(group.id)"
        :strategy-label="groupStrategyLabel(group.strategy)"
        :reference="proxyGroupReference(group)"
        :health-summary="groupHealthSummary(group)"
        :action-items="proxyGroupActionItems(group)"
        :node-health-value="(node) => nodeHealthValue(group, node)"
        :node-health-tone="(node) => nodeHealthTone(group, node)"
        @toggle-expand="toggleGroupExpanded(group.id)"
        @edit="$emit('edit', group)"
        @action="$emit('action', group, $event)"
        @copy-reference="copyProxyGroupReference(group)"
      />
    </ul>
  </PagePanel>
</template>

<script setup lang="ts">
import { Button, EmptyState, Input } from 'nanocat-ui'
import type { ActionMenuItem } from 'nanocat-ui'
import type { ProxyGroup, ProxyNode } from '@/api/proxy'
import PageLoadingState from '@/components/ai/PageLoadingState.vue'
import PagePanel from '@/components/ai/PagePanel.vue'
import PanelHeader from '@/components/ai/PanelHeader.vue'
import StateBlock from '@/components/ai/StateBlock.vue'
import ProxyGroupCard from './ProxyGroupCard.vue'

defineProps<{
  loading: boolean
  groupsLength: number
  keyword: string
  filteredGroups: ProxyGroup[]
  isGroupExpanded: (id: string) => boolean
  groupStrategyLabel: (strategy: ProxyGroup['strategy']) => string
  proxyGroupReference: (group: Pick<ProxyGroup, 'id'>) => string
  groupHealthSummary: (group: ProxyGroup) => { ok: number; fail: number; idle: number }
  proxyGroupActionItems: (group: ProxyGroup) => ActionMenuItem[]
  nodeHealthValue: (group: ProxyGroup, node: ProxyNode) => string
  nodeHealthTone: (group: ProxyGroup, node: ProxyNode) => string
  toggleGroupExpanded: (id: string) => void
  copyProxyGroupReference: (group: Pick<ProxyGroup, 'id'>) => void
}>()

defineEmits<{
  'update:keyword': [value: string]
  create: []
  edit: [group: ProxyGroup]
  action: [group: ProxyGroup, key: string]
}>()
</script>

<style scoped>
.proxy-groups {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}
</style>
