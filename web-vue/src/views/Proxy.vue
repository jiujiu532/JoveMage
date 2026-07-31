<template>
  <div class="space-y-6">
    <ProxyEgressPanel
      :loading="loading"
      :saving="savingDefaultProxy"
      :testing="testingKey === DEFAULT_TEST_KEY"
      :can-test-default-proxy="canTestDefaultProxy"
      :default-proxy-mode="defaultProxyMode"
      :selected-default-proxy-group-id="selectedDefaultProxyGroupId"
      :default-custom-proxy-input="defaultCustomProxyInput"
      :fallback-proxy-mode="fallbackProxyMode"
      :selected-fallback-proxy-group-id="selectedFallbackProxyGroupId"
      :fallback-custom-proxy-input="fallbackCustomProxyInput"
      :default-proxy-preview="defaultProxyPreview"
      :fallback-proxy-preview="fallbackProxyPreview"
      :default-test-result="defaultTestResult"
      :default-proxy-mode-options="defaultProxyModeOptions"
      :fallback-proxy-mode-options="fallbackProxyModeOptions"
      :proxy-group-options="defaultProxyGroupOptions"
      @refresh="loadData"
      @save="saveDefaultProxy"
      @set-default-mode="setDefaultProxyMode"
      @select-default-group="selectDefaultProxyGroup"
      @set-default-custom="setDefaultCustomProxyInput"
      @set-fallback-mode="setFallbackProxyMode"
      @select-fallback-group="selectFallbackProxyGroup"
      @set-fallback-custom="setFallbackCustomProxyInput"
      @test-default="testDefaultProxy"
      @set-direct="setDefaultProxyDirect"
    />

    <ProxyGroupList
      :loading="loading"
      :groups-length="groups.length"
      :keyword="groupKeyword"
      :filtered-groups="filteredGroups"
      :is-group-expanded="isGroupExpanded"
      :group-strategy-label="groupStrategyLabel"
      :proxy-group-reference="proxyGroupReference"
      :group-health-summary="groupHealthSummary"
      :proxy-group-action-items="proxyGroupActionItems"
      :node-health-value="nodeHealthValue"
      :node-health-tone="nodeHealthTone"
      :toggle-group-expanded="toggleGroupExpanded"
      :copy-proxy-group-reference="copyProxyGroupReference"
      @update:keyword="setGroupKeyword"
      @create="openCreateGroupModal"
      @edit="openEditGroupModal"
      @action="handleProxyGroupAction"
    />

    <ProxyGroupEditorModal
      :open="showGroupModal"
      :saving="savingGroupId === FORM_TEST_KEY"
      :editing-group-id="editingGroupId"
      :testing-key="testingKey"
      :group-form="groupForm"
      :normalize-group-id="normalizeGroupId"
      :normalize-image-concurrency-limit="normalizeImageConcurrencyLimit"
      @close="closeGroupModal"
      @save="saveProxyGroup"
      @add-node="addGroupNode"
      @remove-node="removeGroupNode"
      @test-node="(node) => testProxyGroupNode({ id: editingGroupId, name: groupForm.name }, node)"
    />
  </div>
</template>

<script setup lang="ts">
import ProxyEgressPanel from './proxy/ProxyEgressPanel.vue'
import ProxyGroupEditorModal from './proxy/ProxyGroupEditorModal.vue'
import ProxyGroupList from './proxy/ProxyGroupList.vue'
import { useProxyGroups } from './proxy/useProxyGroups'

const {
  DEFAULT_TEST_KEY,
  FORM_TEST_KEY,
  loading,
  savingDefaultProxy,
  savingGroupId,
  testingKey,
  groupKeyword,
  showGroupModal,
  editingGroupId,
  defaultProxyMode,
  selectedDefaultProxyGroupId,
  defaultCustomProxyInput,
  fallbackProxyMode,
  selectedFallbackProxyGroupId,
  fallbackCustomProxyInput,
  defaultTestResult,
  groups,
  groupForm,
  defaultProxyModeOptions,
  fallbackProxyModeOptions,
  filteredGroups,
  defaultProxyGroupOptions,
  defaultProxyPreview,
  fallbackProxyPreview,
  canTestDefaultProxy,
  normalizeGroupId,
  normalizeImageConcurrencyLimit,
  proxyGroupReference,
  copyProxyGroupReference,
  setDefaultProxyMode,
  setFallbackProxyMode,
  selectDefaultProxyGroup,
  selectFallbackProxyGroup,
  setDefaultCustomProxyInput,
  setFallbackCustomProxyInput,
  loadData,
  saveDefaultProxy,
  setDefaultProxyDirect,
  testDefaultProxy,
  openCreateGroupModal,
  openEditGroupModal,
  closeGroupModal,
  addGroupNode,
  removeGroupNode,
  saveProxyGroup,
  proxyGroupActionItems,
  handleProxyGroupAction,
  testProxyGroupNode,
  groupStrategyLabel,
  isGroupExpanded,
  toggleGroupExpanded,
  groupHealthSummary,
  nodeHealthValue,
  nodeHealthTone,
  setGroupKeyword,
} = useProxyGroups()
</script>
