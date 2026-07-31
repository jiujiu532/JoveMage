<template>
  <PagePanel class="space-y-4">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p class="ui-section-title">用户密钥管理</p>
        <p class="mt-1 text-xs text-muted-foreground">
          创建给普通用户使用的调用密钥；普通用户登录后只进入对话画图页。
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" :disabled="userKeysLoading" @click="loadUserKeys">
          {{ userKeysLoading ? '刷新中...' : '刷新密钥' }}
        </Button>
        <Button size="sm" variant="primary" :disabled="userKeyBusy === 'create'" @click="openUserKeyCreateModal">
          创建用户密钥
        </Button>
      </div>
    </div>

    <div
      v-if="newUserKey"
      class="settings-banner-ok"
    >
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="min-w-0">
          <p class="font-medium">新密钥只展示一次，请现在复制保存。</p>
          <p class="mt-2 break-all font-mono text-xs">{{ newUserKey }}</p>
        </div>
        <Button size="xs" variant="outline" root-class="shrink-0" @click="copyUserKey(newUserKey)">
          复制
        </Button>
      </div>
    </div>

    <PageLoadingState
      v-if="userKeysLoading"
      compact
      dashed
      title="正在加载用户密钥"
      subtitle="读取普通用户密钥列表。"
    />
    <StateBlock v-else-if="userKeys.length === 0" compact dashed>
      暂无普通用户密钥。创建后可以分发给只需要画图入口的用户。
    </StateBlock>
    <div v-else class="space-y-2">
      <div
        v-for="item in userKeys"
        :key="item.id"
        class="settings-list-row settings-list-row--lg md:flex-row md:items-center md:justify-between"
      >
        <div class="min-w-0">
          <div class="flex flex-wrap items-center gap-2">
            <p class="truncate text-sm font-medium text-foreground">{{ item.name || '普通用户' }}</p>
            <span
              class="rounded-md px-2 py-0.5 text-xs"
              :class="item.enabled ? 'settings-badge-ok' : 'settings-badge-muted'"
            >
              {{ item.enabled ? '已启用' : '已禁用' }}
            </span>
          </div>
          <p class="mt-1 text-xs text-muted-foreground">
            创建 {{ formatDateTime(item.created_at) }} · 最近使用 {{ formatDateTime(item.last_used_at) }}
          </p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <Button
            size="xs"
            variant="outline"
            :disabled="userKeyBusy === item.id"
            @click="openUserKeyEditModal(item)"
          >
            编辑
          </Button>
          <Button
            size="xs"
            variant="outline"
            :disabled="userKeyBusy === item.id"
            @click="toggleUserKey(item)"
          >
            {{ item.enabled ? '禁用' : '启用' }}
          </Button>
          <Button
            size="xs"
            variant="outline"
            root-class="text-rose-600"
            :disabled="userKeyBusy === item.id"
            @click="deleteUserKey(item)"
          >
            删除
          </Button>
        </div>
      </div>
    </div>
  </PagePanel>

  <ModalShell
    :open="userKeyModal === 'create'"
    max-width="34rem"
    :z-index="130"
    close-on-backdrop
    @close="closeUserKeyModal"
  >
    <ModalHeader
      title="创建用户密钥"
      subtitle="名称只是备注；创建后会生成一条只展示一次的原始密钥。"
      :close-disabled="userKeyBusy === 'create'"
      :bordered="false"
      @close="closeUserKeyModal"
    />
    <ModalBody class="space-y-3">
      <FormField label="名称">
        <Input v-model.trim="userKeyForm.name" block placeholder="例如：运营画图账号" />
      </FormField>
    </ModalBody>
    <ModalFooter :bordered="false">
      <Button size="sm" variant="outline" :disabled="userKeyBusy === 'create'" @click="closeUserKeyModal">取消</Button>
      <Button size="sm" variant="primary" :disabled="userKeyBusy === 'create'" @click="createUserKey">
        {{ userKeyBusy === 'create' ? '创建中...' : '创建' }}
      </Button>
    </ModalFooter>
  </ModalShell>

  <ModalShell
    :open="userKeyModal === 'edit'"
    max-width="34rem"
    :z-index="130"
    close-on-backdrop
    @close="closeUserKeyModal"
  >
    <ModalHeader
      title="编辑用户密钥"
      subtitle="可以修改备注名称；填写新的专用密钥会让旧密钥失效。"
      :close-disabled="Boolean(editingUserKey && userKeyBusy === editingUserKey.id)"
      :bordered="false"
      @close="closeUserKeyModal"
    />
    <ModalBody class="space-y-3">
      <FormField label="名称">
        <Input v-model.trim="userKeyForm.name" block placeholder="例如：运营画图账号" />
      </FormField>
      <FormField label="新的专用密钥（可选）">
        <Input v-model.trim="userKeyForm.key" block root-class="font-mono" placeholder="留空则不修改当前密钥" />
      </FormField>
    </ModalBody>
    <ModalFooter :bordered="false">
      <Button size="sm" variant="outline" :disabled="Boolean(editingUserKey && userKeyBusy === editingUserKey.id)" @click="closeUserKeyModal">取消</Button>
      <Button size="sm" variant="primary" :disabled="Boolean(editingUserKey && userKeyBusy === editingUserKey.id)" @click="updateUserKey">
        {{ editingUserKey && userKeyBusy === editingUserKey.id ? '保存中...' : '保存' }}
      </Button>
    </ModalFooter>
  </ModalShell>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Button, FormField, Input } from 'nanocat-ui'
import { userKeysApi, type UserKey } from '@/api/userKeys'
import ModalBody from '@/components/ai/ModalBody.vue'
import ModalFooter from '@/components/ai/ModalFooter.vue'
import ModalHeader from '@/components/ai/ModalHeader.vue'
import ModalShell from '@/components/ai/ModalShell.vue'
import PageLoadingState from '@/components/ai/PageLoadingState.vue'
import PagePanel from '@/components/ai/PagePanel.vue'
import StateBlock from '@/components/ai/StateBlock.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useClipboard } from '@/composables/useClipboard'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const { copy } = useClipboard()
const confirmDialog = useConfirmDialog()

const userKeys = ref<UserKey[]>([])
const userKeysLoading = ref(false)
const userKeyBusy = ref('')
const userKeyModal = ref<'create' | 'edit' | ''>('')
const editingUserKey = ref<UserKey | null>(null)
const newUserKey = ref('')
const userKeyForm = ref({
  name: '',
  key: '',
})

function formatDateTime(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw) return '-'
  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) return raw
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(parsed)
}

async function copyUserKey(value: string) {
  if (!value) return
  await copy(value, {
    success: '已复制密钥',
    error: '复制失败，请手动复制',
  })
}

function resetUserKeyForm() {
  userKeyForm.value = { name: '', key: '' }
  editingUserKey.value = null
}

function openUserKeyCreateModal() {
  resetUserKeyForm()
  userKeyModal.value = 'create'
}

function openUserKeyEditModal(item: UserKey) {
  editingUserKey.value = item
  userKeyForm.value = {
    name: item.name || '',
    key: '',
  }
  userKeyModal.value = 'edit'
}

function closeUserKeyModal() {
  if (userKeyBusy.value === 'create') return
  if (editingUserKey.value && userKeyBusy.value === editingUserKey.value.id) return
  userKeyModal.value = ''
  resetUserKeyForm()
}

async function loadUserKeys() {
  userKeysLoading.value = true
  try {
    const response = await userKeysApi.list()
    userKeys.value = Array.isArray(response.items) ? response.items : []
  } catch (error: any) {
    userKeys.value = []
    toast.error(error.message || '加载用户密钥失败')
  } finally {
    userKeysLoading.value = false
  }
}

async function createUserKey() {
  userKeyBusy.value = 'create'
  try {
    const response = await userKeysApi.create(userKeyForm.value.name.trim())
    userKeys.value = response.items || []
    newUserKey.value = response.key || ''
    toast.success('用户密钥已创建')
    userKeyModal.value = ''
    resetUserKeyForm()
  } catch (error: any) {
    toast.error(error.message || '创建用户密钥失败')
  } finally {
    userKeyBusy.value = ''
  }
}

async function updateUserKey() {
  const item = editingUserKey.value
  if (!item) return
  const nextName = userKeyForm.value.name.trim()
  const nextKey = userKeyForm.value.key.trim()
  const updates: { name?: string; key?: string } = {}
  if (nextName !== item.name) updates.name = nextName
  if (nextKey) updates.key = nextKey
  if (!Object.keys(updates).length) {
    closeUserKeyModal()
    return
  }

  userKeyBusy.value = item.id
  try {
    const response = await userKeysApi.update(item.id, updates)
    userKeys.value = response.items || []
    toast.success(nextKey ? '用户密钥已更新' : '用户名称已更新')
    userKeyModal.value = ''
    resetUserKeyForm()
  } catch (error: any) {
    toast.error(error.message || '更新用户密钥失败')
  } finally {
    userKeyBusy.value = ''
  }
}

async function toggleUserKey(item: UserKey) {
  userKeyBusy.value = item.id
  try {
    const response = await userKeysApi.update(item.id, { enabled: !item.enabled })
    userKeys.value = response.items || []
    toast.success(item.enabled ? '用户密钥已禁用' : '用户密钥已启用')
  } catch (error: any) {
    toast.error(error.message || '更新用户密钥失败')
  } finally {
    userKeyBusy.value = ''
  }
}

async function deleteUserKey(item: UserKey) {
  const confirmed = await confirmDialog.ask({
    title: '删除用户密钥',
    message: `确定删除用户密钥「${item.name || item.id}」吗？删除后这条密钥将无法继续调用接口。`,
    confirmText: '删除',
    cancelText: '取消',
  })
  if (!confirmed) return

  userKeyBusy.value = item.id
  try {
    const response = await userKeysApi.delete(item.id)
    userKeys.value = response.items || []
    if (editingUserKey.value?.id === item.id) {
      userKeyModal.value = ''
      resetUserKeyForm()
    }
    toast.success('用户密钥已删除')
  } catch (error: any) {
    toast.error(error.message || '删除用户密钥失败')
  } finally {
    userKeyBusy.value = ''
  }
}

onMounted(() => {
  void loadUserKeys()
})
</script>
