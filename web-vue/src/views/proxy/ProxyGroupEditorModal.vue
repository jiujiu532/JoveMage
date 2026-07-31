<template>
  <ModalShell :open="open" max-width="56rem" :z-index="120">
    <ModalHeader
      :title="editingGroupId ? '编辑代理组' : '新建代理组'"
      :close-disabled="saving"
      :bordered="false"
      compact
      @close="$emit('close')"
    />

    <ModalBody class="space-y-4">
      <FormSection title="基础信息" surface="plain">
        <div class="grid grid-cols-1 gap-2.5 md:grid-cols-[minmax(0,1fr)_16rem]">
          <label class="text-xs">
            <span class="ui-field-label">代理组名称</span>
            <Input
              :model-value="groupForm.name"
              block
              placeholder="香港代理池"
              @update:model-value="groupForm.name = $event.trim()"
            />
          </label>
          <label class="text-xs">
            <span class="ui-field-label">代理组 ID</span>
            <Input
              :model-value="groupForm.id"
              block
              root-class="font-mono"
              :disabled="Boolean(editingGroupId)"
              @update:model-value="groupForm.id = normalizeGroupId($event)"
            />
          </label>
        </div>
        <div class="grid grid-cols-1 gap-2.5 md:grid-cols-[minmax(0,1fr)_auto]">
          <label class="text-xs">
            <span class="ui-field-label">备注</span>
            <Input
              :model-value="groupForm.notes"
              block
              placeholder="可选"
              @update:model-value="groupForm.notes = $event.trim()"
            />
          </label>
          <div class="flex items-end">
            <Checkbox v-model="groupForm.enabled">启用代理组</Checkbox>
          </div>
        </div>
      </FormSection>

      <div class="space-y-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <p class="text-xs font-medium text-foreground">代理节点</p>
          <Button size="xs" variant="outline" @click="$emit('add-node')">添加节点</Button>
        </div>
        <div class="space-y-3">
          <FormSection
            v-for="(node, index) in groupForm.nodes"
            :key="`${node.id}-${index}`"
            surface="muted"
          >
            <div class="grid grid-cols-1 gap-2 md:grid-cols-[10rem_minmax(0,1fr)_8rem_auto]">
              <label class="text-xs">
                <span class="ui-field-label">名称</span>
                <Input
                  :model-value="node.name"
                  block
                  @update:model-value="node.name = $event.trim()"
                />
              </label>
              <label class="text-xs">
                <span class="ui-field-label">代理 URL</span>
                <Input
                  :model-value="node.url"
                  block
                  root-class="font-mono"
                  placeholder="http://user:password@host:port"
                  @update:model-value="node.url = $event.trim()"
                />
              </label>
              <label class="text-xs">
                <span class="ui-field-label">图片并发</span>
                <Input
                  :model-value="String(node.image_concurrency_limit ?? 0)"
                  block
                  type="number"
                  min="0"
                  step="1"
                  placeholder="默认 30，0 不限"
                  title="限制该节点同时处理的图片请求数；超出后等待同组节点空位，不会改走直连。0 表示不限制。"
                  @update:model-value="node.image_concurrency_limit = normalizeImageConcurrencyLimit($event)"
                />
              </label>
              <div class="flex items-end gap-2">
                <Checkbox v-model="node.enabled">启用</Checkbox>
              </div>
            </div>
            <div class="mt-2 flex flex-wrap items-center justify-between gap-2">
              <label class="min-w-[12rem] flex-1 text-xs">
                <span class="ui-field-label">备注</span>
                <Input
                  :model-value="node.notes || ''"
                  block
                  placeholder="可选"
                  @update:model-value="node.notes = $event.trim()"
                />
              </label>
              <div class="flex items-end gap-2 pt-5">
                <Button
                  size="xs"
                  variant="outline"
                  :disabled="!editingGroupId || !node.url || testingKey === `group:${editingGroupId}:${node.id}`"
                  @click="$emit('test-node', node)"
                >
                  {{ testingKey === `group:${editingGroupId}:${node.id}` ? '检测中...' : '检测' }}
                </Button>
                <Button size="xs" variant="outline" root-class="text-rose-600" @click="$emit('remove-node', index)">
                  删除
                </Button>
              </div>
            </div>
          </FormSection>
        </div>
      </div>
    </ModalBody>

    <ModalFooter :bordered="false">
      <Button size="xs" variant="outline" root-class="min-w-14 justify-center" :disabled="saving" @click="$emit('close')">
        取消
      </Button>
      <Button size="xs" variant="primary" root-class="min-w-14 justify-center" :disabled="saving" @click="$emit('save')">
        {{ saving ? '保存中...' : editingGroupId ? '更新' : '保存' }}
      </Button>
    </ModalFooter>
  </ModalShell>
</template>

<script setup lang="ts">
import { Button, Checkbox, Input } from 'nanocat-ui'
import type { ProxyNode } from '@/api/proxy'
import FormSection from '@/components/ai/FormSection.vue'
import ModalBody from '@/components/ai/ModalBody.vue'
import ModalFooter from '@/components/ai/ModalFooter.vue'
import ModalHeader from '@/components/ai/ModalHeader.vue'
import ModalShell from '@/components/ai/ModalShell.vue'
import type { ProxyGroupForm } from './useProxyGroups'

defineProps<{
  open: boolean
  saving: boolean
  editingGroupId: string
  testingKey: string
  groupForm: ProxyGroupForm
  normalizeGroupId: (value: string) => string
  normalizeImageConcurrencyLimit: (value: unknown) => number
}>()

defineEmits<{
  close: []
  save: []
  'add-node': []
  'remove-node': [index: number]
  'test-node': [node: ProxyNode]
}>()
</script>
