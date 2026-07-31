<template>
  <PagePanel class="space-y-4">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p class="ui-section-title">Sub2API</p>
        <p class="mt-1 text-xs text-muted-foreground">
          账号管理页的远程导入会读取这里保存的连接。
        </p>
      </div>
      <Button size="sm" variant="outline" :disabled="sub2apiLoading" @click="loadSub2APIServers">
        {{ sub2apiLoading ? '刷新中...' : '刷新连接' }}
      </Button>
    </div>

    <div class="settings-panel-card">
      <div class="flex items-center justify-between gap-3">
        <div>
          <p class="text-sm font-semibold text-foreground">Sub2API 连接管理</p>
          <p class="mt-1 text-xs text-muted-foreground">保存 Sub2API 服务器，用于读取 OpenAI OAuth 账号并导入本地号池。</p>
        </div>
        <div class="flex shrink-0 items-center gap-2">
          <span class="text-xs text-muted-foreground">{{ sub2apiServers.length }} 个连接</span>
          <Button size="xs" variant="outline" :disabled="savingExternalSource === 'sub2api'" @click="openSub2APIModal()">
            新增
          </Button>
        </div>
      </div>

      <div class="mt-4 space-y-2">
        <div
          v-for="server in sub2apiServers"
          :key="server.id"
          class="settings-list-row"
        >
          <div class="flex flex-wrap items-start justify-between gap-2">
            <div class="min-w-0">
              <p class="truncate font-medium text-foreground">{{ server.name || server.id }}</p>
              <p class="mt-1 truncate font-mono text-muted-foreground">{{ server.base_url }}</p>
              <p class="mt-1 text-muted-foreground">
                {{ server.email || '未填邮箱' }} · {{ server.has_api_key ? '已配置 API Key' : '未配置 API Key' }}
                <span v-if="server.group_id"> · 分组 {{ server.group_id }}</span>
              </p>
            </div>
            <div class="flex flex-wrap justify-end gap-1.5">
              <Button size="xs" variant="outline" root-class="w-14 justify-center whitespace-nowrap" @click="openSub2APIImport(server)">导入</Button>
              <Button size="xs" variant="outline" root-class="w-14 justify-center whitespace-nowrap" :disabled="testingExternalSource === server.id" @click="testSub2APIServer(server)">
                {{ testingExternalSource === server.id ? '测试中' : '测试' }}
              </Button>
              <Button size="xs" variant="outline" root-class="w-16 justify-center whitespace-nowrap" :disabled="sub2apiGroupsLoadingId === server.id" @click="loadSub2APIGroups(server)">
                {{ sub2apiGroupsLoadingId === server.id ? '读取中' : '读分组' }}
              </Button>
              <Button size="xs" variant="outline" root-class="w-14 justify-center whitespace-nowrap" @click="editSub2APIServer(server)">编辑</Button>
              <Button size="xs" variant="outline" root-class="w-14 justify-center whitespace-nowrap text-rose-600" :disabled="savingExternalSource === server.id" @click="deleteSub2APIServer(server)">
                删除
              </Button>
            </div>
          </div>

          <div v-if="sub2apiGroups[server.id]?.length" class="mt-2 flex flex-wrap gap-1.5">
            <button
              v-for="group in sub2apiGroups[server.id]"
              :key="group.id"
              type="button"
              class="rounded-md border border-border bg-card px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
              @click="openSub2APIImport(server, group.id)"
            >
              {{ group.name || group.id }} · {{ group.active_account_count }}/{{ group.account_count }}
            </button>
          </div>
        </div>
        <StateBlock v-if="!sub2apiLoading && sub2apiServers.length === 0" tag="p" compact dashed>
          暂无 Sub2API 连接。
        </StateBlock>
      </div>
    </div>
  </PagePanel>

  <ModalShell
    :open="externalSourceModal"
    max-width="42rem"
    :z-index="130"
    close-on-backdrop
    @close="closeExternalSourceModal"
  >
    <ModalHeader
      :title="editingSub2APIId ? '编辑 Sub2API 连接' : '新增 Sub2API 连接'"
      subtitle="用于账号管理里的 Sub2API 远程导入。"
      :close-disabled="savingExternalSource === 'sub2api'"
      :bordered="false"
      @close="closeExternalSourceModal"
    />
    <ModalBody class="space-y-3">
      <div class="grid gap-3 md:grid-cols-2">
        <FormField label="名称">
          <Input v-model.trim="sub2apiForm.name" block placeholder="自建 Sub2API" />
        </FormField>
        <FormField label="Sub2API 地址">
          <Input v-model.trim="sub2apiForm.base_url" block placeholder="http://your-sub2api-host:8080" />
        </FormField>
        <FormField label="管理员邮箱">
          <Input v-model.trim="sub2apiForm.email" block placeholder="admin@example.com" />
        </FormField>
        <FormField label="密码">
          <Input v-model="sub2apiForm.password" type="password" block :placeholder="editingSub2APIId ? '留空则不修改密码' : '管理员密码'" />
        </FormField>
        <FormField label="Admin API Key">
          <Input v-model="sub2apiForm.api_key" type="password" block :placeholder="editingSub2APIId ? '留空则不修改密钥' : '可替代邮箱密码'" />
        </FormField>
        <FormField label="默认分组 ID">
          <Input v-model.trim="sub2apiForm.group_id" block placeholder="可选" />
        </FormField>
      </div>
    </ModalBody>
    <ModalFooter :bordered="false">
      <Button size="sm" variant="outline" :disabled="savingExternalSource === 'sub2api'" @click="closeExternalSourceModal">取消</Button>
      <Button size="sm" variant="primary" :disabled="savingExternalSource === 'sub2api'" @click="saveSub2APIServer">
        {{ savingExternalSource === 'sub2api' ? '保存中...' : '保存' }}
      </Button>
    </ModalFooter>
  </ModalShell>

  <ModalShell
    :open="remoteImportOpen"
    max-width="58rem"
    :z-index="135"
    close-on-backdrop
    @close="closeRemoteImportModal"
  >
    <ModalHeader
      title="从 Sub2API 导入账号"
      subtitle="读取已保存 Sub2API 连接中的 OpenAI 账号。"
      :close-disabled="remoteImportBusy"
      :bordered="false"
      @close="closeRemoteImportModal"
    />
    <ModalBody>
      <RemoteAccountImportPanel
        v-if="remoteImportOpen"
        mode="sub2api"
        :sub2api-server-id="remoteImportSub2APIServerId"
        :sub2api-group-id="remoteImportSub2APIGroupId"
        @busy-change="remoteImportBusy = $event"
        @imported="handleRemoteImportDone"
      />
    </ModalBody>
  </ModalShell>
</template>

<script setup lang="ts">
import { defineAsyncComponent, onMounted, ref } from 'vue'
import { Button, FormField, Input } from 'nanocat-ui'
import { accountImportsApi, type Sub2APIRemoteGroup, type Sub2APIServer } from '@/api/accountImports'
import ModalBody from '@/components/ai/ModalBody.vue'
import ModalFooter from '@/components/ai/ModalFooter.vue'
import ModalHeader from '@/components/ai/ModalHeader.vue'
import ModalShell from '@/components/ai/ModalShell.vue'
import PagePanel from '@/components/ai/PagePanel.vue'
import StateBlock from '@/components/ai/StateBlock.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useToast } from '@/composables/useToast'

const RemoteAccountImportPanel = defineAsyncComponent(() => import('@/components/ai/RemoteAccountImportPanel.vue'))

const toast = useToast()
const confirmDialog = useConfirmDialog()

const sub2apiLoading = ref(false)
const savingExternalSource = ref('')
const testingExternalSource = ref('')
const externalSourceModal = ref(false)
const remoteImportOpen = ref(false)
const remoteImportSub2APIServerId = ref('')
const remoteImportSub2APIGroupId = ref<string | undefined>(undefined)
const remoteImportBusy = ref(false)
const sub2apiServers = ref<Sub2APIServer[]>([])
const sub2apiGroups = ref<Record<string, Sub2APIRemoteGroup[]>>({})
const sub2apiGroupsLoadingId = ref('')
const editingSub2APIId = ref('')
const sub2apiForm = ref({
  name: '',
  base_url: '',
  email: '',
  password: '',
  api_key: '',
  group_id: '',
})

function resetSub2APIForm() {
  editingSub2APIId.value = ''
  sub2apiForm.value = {
    name: '',
    base_url: '',
    email: '',
    password: '',
    api_key: '',
    group_id: '',
  }
}

function openSub2APIModal(server?: Sub2APIServer) {
  if (server) {
    editSub2APIServer(server)
    return
  }
  resetSub2APIForm()
  externalSourceModal.value = true
}

function editSub2APIServer(server: Sub2APIServer) {
  editingSub2APIId.value = server.id
  sub2apiForm.value = {
    name: server.name || '',
    base_url: server.base_url || '',
    email: server.email || '',
    password: '',
    api_key: '',
    group_id: server.group_id || '',
  }
  externalSourceModal.value = true
}

function closeExternalSourceModal() {
  if (savingExternalSource.value === 'sub2api') return
  externalSourceModal.value = false
  resetSub2APIForm()
}

async function loadSub2APIServers() {
  sub2apiLoading.value = true
  try {
    const response = await accountImportsApi.listSub2APIServers()
    sub2apiServers.value = Array.isArray(response.servers) ? response.servers : []
  } catch (error: any) {
    sub2apiServers.value = []
    toast.error(error.message || '加载 Sub2API 连接失败')
  } finally {
    sub2apiLoading.value = false
  }
}

async function saveSub2APIServer() {
  const payload = {
    name: sub2apiForm.value.name.trim(),
    base_url: sub2apiForm.value.base_url.trim(),
    email: sub2apiForm.value.email.trim(),
    password: sub2apiForm.value.password,
    api_key: sub2apiForm.value.api_key.trim(),
    group_id: sub2apiForm.value.group_id.trim(),
  }
  if (!payload.base_url) {
    toast.warning('请输入 Sub2API 地址')
    return
  }
  const hasLogin = Boolean(payload.email && payload.password)
  const hasApiKey = Boolean(payload.api_key)
  if (!editingSub2APIId.value && !hasLogin && !hasApiKey) {
    toast.warning('新增 Sub2API 连接需要邮箱密码或 Admin API Key')
    return
  }

  savingExternalSource.value = 'sub2api'
  try {
    const response = editingSub2APIId.value
      ? await accountImportsApi.updateSub2APIServer(editingSub2APIId.value, {
          name: payload.name,
          base_url: payload.base_url,
          email: payload.email,
          group_id: payload.group_id,
          ...(payload.password ? { password: payload.password } : {}),
          ...(payload.api_key ? { api_key: payload.api_key } : {}),
        })
      : await accountImportsApi.createSub2APIServer(payload)
    sub2apiServers.value = response.servers || []
    resetSub2APIForm()
    externalSourceModal.value = false
    toast.success('Sub2API 连接已保存')
  } catch (error: any) {
    toast.error(error.message || '保存 Sub2API 连接失败')
  } finally {
    savingExternalSource.value = ''
  }
}

async function deleteSub2APIServer(server: Sub2APIServer) {
  const confirmed = await confirmDialog.ask({
    title: '删除 Sub2API 连接',
    message: `确定删除 ${server.name || server.base_url}？账号页将不能再从这个 Sub2API 连接导入。`,
    confirmText: '删除',
    cancelText: '取消',
  })
  if (!confirmed) return

  savingExternalSource.value = server.id
  try {
    const response = await accountImportsApi.deleteSub2APIServer(server.id)
    sub2apiServers.value = response.servers || []
    const nextGroups = { ...sub2apiGroups.value }
    delete nextGroups[server.id]
    sub2apiGroups.value = nextGroups
    if (editingSub2APIId.value === server.id) resetSub2APIForm()
    toast.success('Sub2API 连接已删除')
  } catch (error: any) {
    toast.error(error.message || '删除 Sub2API 连接失败')
  } finally {
    savingExternalSource.value = ''
  }
}

async function loadSub2APIGroups(server: Sub2APIServer) {
  const confirmed = await confirmDialog.ask({
    title: '加载 Sub2API 分组',
    message: `即将访问 Sub2API 连接 ${server.name || server.base_url || server.id} 并读取远程分组列表。请确认当前允许连接该外部服务。`,
    confirmText: '确认加载',
    cancelText: '取消',
  })
  if (!confirmed) return

  sub2apiGroupsLoadingId.value = server.id
  try {
    const response = await accountImportsApi.listSub2APIServerGroups(server.id)
    sub2apiGroups.value = {
      ...sub2apiGroups.value,
      [server.id]: Array.isArray(response.groups) ? response.groups : [],
    }
    if (!response.groups?.length) toast.info('这个 Sub2API 连接没有返回分组')
  } catch (error: any) {
    toast.error(error.message || '读取 Sub2API 分组失败')
  } finally {
    sub2apiGroupsLoadingId.value = ''
  }
}

async function testSub2APIServer(server: Sub2APIServer) {
  const confirmed = await confirmDialog.ask({
    title: '测试 Sub2API 连接',
    message: `即将访问 Sub2API 连接 ${server.name || server.base_url || server.id} 并读取远程分组列表。请确认当前允许连接该外部服务。`,
    confirmText: '开始测试',
    cancelText: '取消',
  })
  if (!confirmed) return

  testingExternalSource.value = server.id
  try {
    const response = await accountImportsApi.listSub2APIServerGroups(server.id)
    sub2apiGroups.value = {
      ...sub2apiGroups.value,
      [server.id]: response.groups || [],
    }
    toast.success(`Sub2API 连接可用，读取到 ${response.groups?.length || 0} 个分组`)
  } catch (error: any) {
    toast.error(error.message || 'Sub2API 连接测试失败')
  } finally {
    testingExternalSource.value = ''
  }
}

function openSub2APIImport(server: Sub2APIServer, groupId?: string) {
  remoteImportSub2APIServerId.value = server.id
  remoteImportSub2APIGroupId.value = groupId
  remoteImportBusy.value = false
  remoteImportOpen.value = true
}

function closeRemoteImportModal() {
  if (remoteImportBusy.value) return
  remoteImportOpen.value = false
  remoteImportSub2APIServerId.value = ''
  remoteImportSub2APIGroupId.value = undefined
}

function handleRemoteImportDone() {
  void loadSub2APIServers()
}

onMounted(() => {
  void loadSub2APIServers()
})
</script>
