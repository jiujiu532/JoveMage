<template>
  <div class="flex items-center gap-2" :class="alignClass">
    <Button
      size="xs"
      variant="outline"
      root-class="w-14 justify-center"
      :disabled="item.is_demo"
      @click="emit('edit')"
    >
      编辑
    </Button>
    <FloatingActionMenu
      label="更多"
      :items="menuItems"
      :disabled="item.is_demo"
      align="right"
      size="sm"
      trigger-class="h-7 justify-center px-2 text-[11px]"
      :trigger-width="64"
      @select="handleSelect"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Button } from 'nanocat-ui'
import type { ActionMenuItem } from 'nanocat-ui'
import type { Account } from '@/api/accounts'
import FloatingActionMenu from './FloatingActionMenu.vue'
import { actionMenuGroups } from './menuItems'

const props = withDefaults(defineProps<{
  item: Account
  refreshing?: boolean
  resetting?: boolean
  reloginBusy?: boolean
  /** Firefly 账号：刷新/重登为 ChatGPT 专属，禁用并标注 */
  isFirefly?: boolean
  align?: 'start' | 'end'
}>(), {
  refreshing: false,
  resetting: false,
  reloginBusy: false,
  isFirefly: false,
  align: 'start',
})

const emit = defineEmits<{
  (e: 'edit'): void
  (e: 'toggle-enabled'): void
  (e: 'refresh-token'): void
  (e: 'relogin'): void
  (e: 'reset-state'): void
  (e: 'remove'): void
}>()

const alignClass = computed(() => (
  props.align === 'end' ? 'justify-end' : 'justify-start'
))

const menuItems = computed<ActionMenuItem[]>(() => actionMenuGroups(
  [
    {
      key: 'refresh-token',
      label: props.refreshing
        ? '刷新中...'
        : props.isFirefly
          ? '刷新账号信息和额度（仅 ChatGPT）'
          : '刷新账号信息和额度',
      disabled: props.refreshing || props.isFirefly,
    },
    {
      key: 'relogin',
      label: props.reloginBusy
        ? '重登中...'
        : props.isFirefly
          ? '重新登录账号（仅 ChatGPT）'
          : '重新登录账号',
      disabled: props.reloginBusy || props.isFirefly,
    },
    {
      key: 'reset-state',
      label: props.resetting ? '重置中...' : '重置状态',
      disabled: props.resetting,
    },
  ],
  [
    {
      key: 'toggle-enabled',
      label: props.item.enabled ? '禁用账号' : '启用账号',
    },
  ],
  [
    {
      key: 'remove',
      label: '删除账号',
      danger: true,
    },
  ],
))

function handleSelect(key: string) {
  if (key === 'toggle-enabled') emit('toggle-enabled')
  if (key === 'refresh-token') emit('refresh-token')
  if (key === 'relogin') emit('relogin')
  if (key === 'reset-state') emit('reset-state')
  if (key === 'remove') emit('remove')
}
</script>
