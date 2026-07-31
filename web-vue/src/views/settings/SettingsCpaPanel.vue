<template>
  <PagePanel class="space-y-4">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p class="ui-section-title">CPA</p>
        <p class="mt-1 text-xs text-muted-foreground">
          账号管理页的远程导入会读取这里保存的连接。
        </p>
      </div>
      <Button size="sm" variant="outline" :disabled="cpaLoading" @click="loadCPAPools">
        {{ cpaLoading ? '刷新中...' : '刷新连接' }}
      </Button>
    </div>

    <div class="settings-panel-card">
      <div class="flex items-center justify-between gap-3">
        <div>
          <p class="text-sm font-semibold text-foreground">CPA 连接管理</p>
          <p class="mt-1 text-xs text-muted-foreground">保存 CLIProxyAPI 地址和管理密钥，供远程 CPA 导入使用。</p>
        </div>
        <div class="flex shrink-0 items-center gap-2">
          <span class="text-xs text-muted-foreground">{{ cpaPools.length }} 个连接</span>
          <Button size="xs" variant="outline" :disabled="savingExternalSource === 'cpa'" @click="openCPAModal()">
            新增
          </Button>
        </div>
      </div>

      <div class="mt-4 space-y-2">
        <div
          v-for="pool in cpaPools"
          :key="pool.id"
          class="settings-list-row"
        >
          <div class="flex flex-wrap items-start justify-between gap-2">
            <div class="min-w-0">
              <p class="truncate font-medium text-foreground">{{ pool.name || pool.id }}</p>
              <p class="mt-1 truncate font-mono text-muted-foreground">{{ pool.base_url }}</p>
            </div>
            <div class="flex gap-1.5">
              <Button size="xs" variant="outline" root-class="w-14 justify-center whitespace-nowrap" @click="openCPAImport(pool)">导入</Button>
              <Button size="xs" variant="outline" root-class="w-14 justify-center whitespace-nowrap" :disabled="testingExternalSource === pool.id" @click="testCPAPool(pool)">
                {{ testingExternalSource === pool.id ? '测试中' : '测试' }}
              </Button>
              <Button size="xs" variant="outline" root-class="w-14 justify-center whitespace-nowrap" @click="editCPAPool(pool)">编辑</Button>
              <Button size="xs" variant="outline" root-class="w-14 justify-center whitespace-nowrap text-rose-600" :disabled="savingExternalSource === pool.id" @click="deleteCPAPool(pool)">
                删除
              </Button>
            </div>
          </div>
        </div>
        <StateBlock v-if="!cpaLoading && cpaPools.length === 0" tag="p" compact dashed>
          暂无 CPA 连接。
        </StateBlock>
      </div>
    </div>
  </PagePanel>

  <ModalShell
    :open="externalSourceModal"
    max-width="38rem"
    :z-index="130"
    close-on-backdrop
    @close="closeExternalSourceModal"
  >
    <ModalHeader
      :title="editingCPAPoolId ? '编辑 CPA 连接' : '新增 CPA 连接'"
      subtitle="用于账号管理里的远程 CPA 导入。"
      :close-disabled="savingExternalSource === 'cpa'"
      :bordered="false"
      @close="closeExternalSourceModal"
    />
    <ModalBody class="space-y-3">
      <div class="grid gap-3 md:grid-cols-2">
        <FormField label="名称">
          <Input v-model.trim="cpaForm.name" block placeholder="主 CPA" />
        </FormField>
        <FormField label="CPA 地址">
          <Input v-model.trim="cpaForm.base_url" block placeholder="http://your-cpa-host:8317" />
        </FormField>
      </div>
      <FormField label="管理密钥">
        <Input v-model="cpaForm.secret_key" type="password" block :placeholder="editingCPAPoolId ? '留空则不修改密钥' : 'CPA 管理密钥'" />
      </FormField>
    </ModalBody>
    <ModalFooter :bordered="false">
      <Button size="sm" variant="outline" :disabled="savingExternalSource === 'cpa'" @click="closeExternalSourceModal">取消</Button>
      <Button size="sm" variant="primary" :disabled="savingExternalSource === 'cpa'" @click="saveCPAPool">
        {{ savingExternalSource === 'cpa' ? '保存中...' : '保存' }}
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
      title="从 CPA 导入账号"
      subtitle="读取已保存 CPA 连接中的账号文件。"
      :close-disabled="remoteImportBusy"
      :bordered="false"
      @close="closeRemoteImportModal"
    />
    <ModalBody>
      <RemoteAccountImportPanel
        v-if="remoteImportOpen"
        mode="cpa"
        :cpa-pool-id="remoteImportCPAPoolId"
        @busy-change="remoteImportBusy = $event"
        @imported="handleRemoteImportDone"
      />
    </ModalBody>
  </ModalShell>
</template>

<script setup lang="ts">
import { defineAsyncComponent, onMounted, ref } from 'vue'
import { Button, FormField, Input } from 'nanocat-ui'
import { accountImportsApi, type CPAPool } from '@/api/accountImports'
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

const cpaLoading = ref(false)
const savingExternalSource = ref('')
const testingExternalSource = ref('')
const externalSourceModal = ref(false)
const remoteImportOpen = ref(false)
const remoteImportCPAPoolId = ref('')
const remoteImportBusy = ref(false)
const cpaPools = ref<CPAPool[]>([])
const editingCPAPoolId = ref('')
const cpaForm = ref({
  name: '',
  base_url: '',
  secret_key: '',
})

function resetCPAForm() {
  editingCPAPoolId.value = ''
  cpaForm.value = {
    name: '',
    base_url: '',
    secret_key: '',
  }
}

function openCPAModal(pool?: CPAPool) {
  if (pool) {
    editCPAPool(pool)
    return
  }
  resetCPAForm()
  externalSourceModal.value = true
}

function editCPAPool(pool: CPAPool) {
  editingCPAPoolId.value = pool.id
  cpaForm.value = {
    name: pool.name || '',
    base_url: pool.base_url || '',
    secret_key: '',
  }
  externalSourceModal.value = true
}

function closeExternalSourceModal() {
  if (savingExternalSource.value === 'cpa') return
  externalSourceModal.value = false
  resetCPAForm()
}

async function loadCPAPools() {
  cpaLoading.value = true
  try {
    const response = await accountImportsApi.listCPAPools()
    cpaPools.value = Array.isArray(response.pools) ? response.pools : []
  } catch (error: any) {
    cpaPools.value = []
    toast.error(error.message || '加载 CPA 连接失败')
  } finally {
    cpaLoading.value = false
  }
}

async function saveCPAPool() {
  const payload = {
    name: cpaForm.value.name.trim(),
    base_url: cpaForm.value.base_url.trim(),
    secret_key: cpaForm.value.secret_key.trim(),
  }
  if (!payload.base_url) {
    toast.warning('请输入 CPA 地址')
    return
  }
  if (!editingCPAPoolId.value && !payload.secret_key) {
    toast.warning('新增 CPA 连接需要管理密钥')
    return
  }

  savingExternalSource.value = 'cpa'
  try {
    const response = editingCPAPoolId.value
      ? await accountImportsApi.updateCPAPool(editingCPAPoolId.value, {
          name: payload.name,
          base_url: payload.base_url,
          ...(payload.secret_key ? { secret_key: payload.secret_key } : {}),
        })
      : await accountImportsApi.createCPAPool(payload)
    cpaPools.value = response.pools || []
    resetCPAForm()
    externalSourceModal.value = false
    toast.success('CPA 连接已保存')
  } catch (error: any) {
    toast.error(error.message || '保存 CPA 连接失败')
  } finally {
    savingExternalSource.value = ''
  }
}

async function deleteCPAPool(pool: CPAPool) {
  const confirmed = await confirmDialog.ask({
    title: '删除 CPA 连接',
    message: `确定删除 ${pool.name || pool.base_url}？账号页将不能再从这个 CPA 连接导入。`,
    confirmText: '删除',
    cancelText: '取消',
  })
  if (!confirmed) return

  savingExternalSource.value = pool.id
  try {
    const response = await accountImportsApi.deleteCPAPool(pool.id)
    cpaPools.value = response.pools || []
    if (editingCPAPoolId.value === pool.id) resetCPAForm()
    toast.success('CPA 连接已删除')
  } catch (error: any) {
    toast.error(error.message || '删除 CPA 连接失败')
  } finally {
    savingExternalSource.value = ''
  }
}

async function testCPAPool(pool: CPAPool) {
  const confirmed = await confirmDialog.ask({
    title: '测试 CPA 连接',
    message: `即将访问 CPA 连接 ${pool.name || pool.base_url || pool.id} 并读取远程文件列表。请确认当前允许连接该外部服务。`,
    confirmText: '开始测试',
    cancelText: '取消',
  })
  if (!confirmed) return

  testingExternalSource.value = pool.id
  try {
    const response = await accountImportsApi.listCPAPoolFiles(pool.id)
    toast.success(`CPA 连接可用，读取到 ${response.files?.length || 0} 个文件`)
  } catch (error: any) {
    toast.error(error.message || 'CPA 连接测试失败')
  } finally {
    testingExternalSource.value = ''
  }
}

function openCPAImport(pool: CPAPool) {
  remoteImportCPAPoolId.value = pool.id
  remoteImportBusy.value = false
  remoteImportOpen.value = true
}

function closeRemoteImportModal() {
  if (remoteImportBusy.value) return
  remoteImportOpen.value = false
  remoteImportCPAPoolId.value = ''
}

function handleRemoteImportDone() {
  void loadCPAPools()
}

onMounted(() => {
  void loadCPAPools()
})
</script>
