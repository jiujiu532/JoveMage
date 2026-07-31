<template>
  <PagePanel class="space-y-5">
    <PanelHeader title="代理管理" align="start">
      <template #copy>
        <p class="mt-1 text-xs text-muted-foreground">
          出口优先级：账号个人代理 > 账号组代理/代理组 > 默认出口；默认出口可配置代理组、代理 URL 或直连。
        </p>
      </template>
      <template #actions>
        <Button size="sm" variant="outline" :disabled="loading" @click="$emit('refresh')">
          {{ loading ? '刷新中...' : '刷新' }}
        </Button>
        <Button size="sm" variant="primary" :disabled="saving || loading" @click="$emit('save')">
          {{ saving ? '保存中...' : '保存出口配置' }}
        </Button>
      </template>
    </PanelHeader>

    <div class="proxy-egress">
      <FormSection density="roomy" class="proxy-egress__form">
        <div class="proxy-egress__row">
          <label class="block text-xs">
            <span class="ui-field-label">默认出口模式</span>
            <GroupedSelectMenu
              :model-value="defaultProxyMode"
              :options="defaultProxyModeOptions"
              aria-label="默认出口模式"
              selected-indicator="none"
              block
              @update:model-value="$emit('set-default-mode', $event)"
            />
          </label>

          <label v-if="defaultProxyMode === 'group'" class="block text-xs">
            <span class="ui-field-label">默认出口代理组</span>
            <GroupedSelectMenu
              :model-value="selectedDefaultProxyGroupId"
              :options="proxyGroupOptions"
              :disabled="loading"
              aria-label="默认出口代理组"
              selected-indicator="none"
              block
              @update:model-value="$emit('select-default-group', $event)"
            />
          </label>

          <label v-else-if="defaultProxyMode === 'custom'" class="block text-xs">
            <span class="ui-field-label">自定义代理 URL</span>
            <Input
              :model-value="defaultCustomProxyInput"
              block
              root-class="font-mono"
              placeholder="http://127.0.0.1:7890 或 socks5://127.0.0.1:7890"
              @update:model-value="$emit('set-default-custom', $event)"
            />
          </label>

          <div v-else class="proxy-egress__hint">未指定账号或账号组代理时直连。</div>
        </div>
        <ActionRow class="mt-3" gap="tight">
          <Button
            size="xs"
            variant="outline"
            :disabled="testing || !canTestDefaultProxy"
            @click="$emit('test-default')"
          >
            {{ testing ? '测试中...' : '测试默认出口' }}
          </Button>
          <Button
            size="xs"
            variant="outline"
            :disabled="saving || testing"
            @click="$emit('set-direct')"
          >
            设为直连
          </Button>
        </ActionRow>
        <p class="proxy-egress__current" :title="defaultProxyPreview">
          <span class="proxy-egress__current-label">当前默认出口</span>
          <span class="proxy-egress__current-value">{{ defaultProxyPreview }}</span>
        </p>

        <div class="proxy-egress__divider"></div>

        <div class="proxy-egress__row">
          <label class="block text-xs">
            <span class="ui-field-label">备用出口模式</span>
            <GroupedSelectMenu
              :model-value="fallbackProxyMode"
              :options="fallbackProxyModeOptions"
              aria-label="备用出口模式"
              selected-indicator="none"
              block
              @update:model-value="$emit('set-fallback-mode', $event)"
            />
          </label>

          <label v-if="fallbackProxyMode === 'group'" class="block text-xs">
            <span class="ui-field-label">备用出口代理组</span>
            <GroupedSelectMenu
              :model-value="selectedFallbackProxyGroupId"
              :options="proxyGroupOptions"
              :disabled="loading"
              aria-label="备用出口代理组"
              selected-indicator="none"
              block
              @update:model-value="$emit('select-fallback-group', $event)"
            />
          </label>

          <label v-else-if="fallbackProxyMode === 'custom'" class="block text-xs">
            <span class="ui-field-label">备用代理 URL</span>
            <Input
              :model-value="fallbackCustomProxyInput"
              block
              root-class="font-mono"
              placeholder="http://127.0.0.1:7890 或 socks5://127.0.0.1:7890"
              @update:model-value="$emit('set-fallback-custom', $event)"
            />
          </label>

          <div v-else class="proxy-egress__hint">
            {{ fallbackProxyMode === 'direct' ? '早期连接失败时重试直连一次。' : '未启用备用出口。' }}
          </div>
        </div>
        <p class="proxy-egress__note">仅图片请求在早期 TLS / 连接超时且尚未收到上游事件时重试一次；生成中断和轮询超时不会切换。</p>
        <p class="proxy-egress__current" :title="fallbackProxyPreview">
          <span class="proxy-egress__current-label">当前备用出口</span>
          <span class="proxy-egress__current-value">{{ fallbackProxyPreview }}</span>
        </p>
      </FormSection>

      <FormSection density="roomy" surface="background" class="proxy-egress__test">
        <p class="proxy-egress__test-title">默认出口测试结果</p>
        <div v-if="defaultTestResult" class="proxy-egress__test-body">
          <div class="proxy-egress__test-status" :class="defaultTestResult.ok ? 'is-ok' : 'is-fail'">
            <span class="proxy-egress__test-dot" aria-hidden="true"></span>
            <span class="proxy-egress__test-word">{{ defaultTestResult.ok ? '可用' : '不可用' }}</span>
          </div>
          <dl class="proxy-egress__test-meta">
            <div class="proxy-egress__test-kv">
              <dt>HTTP</dt>
              <dd>{{ defaultTestResult.status || '-' }}</dd>
            </div>
            <div class="proxy-egress__test-kv">
              <dt>延迟</dt>
              <dd>{{ defaultTestResult.latency_ms || 0 }}ms</dd>
            </div>
          </dl>
          <p v-if="defaultTestResult.error" class="proxy-egress__test-error">{{ defaultTestResult.error }}</p>
        </div>
        <div v-else class="proxy-egress__test-empty">
          <span class="proxy-egress__test-empty-bar" aria-hidden="true"></span>
          <span>尚未测试</span>
        </div>
      </FormSection>
    </div>
  </PagePanel>
</template>

<script setup lang="ts">
import { Button, Input } from 'nanocat-ui'
import type { ProxyTestResult } from '@/api/proxy'
import ActionRow from '@/components/ai/ActionRow.vue'
import FormSection from '@/components/ai/FormSection.vue'
import PagePanel from '@/components/ai/PagePanel.vue'
import PanelHeader from '@/components/ai/PanelHeader.vue'
import GroupedSelectMenu from '@/components/ui/GroupedSelectMenu.vue'
import type { DefaultProxyMode, FallbackProxyMode } from './useProxyGroups'

defineProps<{
  loading: boolean
  saving: boolean
  testing: boolean
  canTestDefaultProxy: boolean
  defaultProxyMode: DefaultProxyMode
  selectedDefaultProxyGroupId: string
  defaultCustomProxyInput: string
  fallbackProxyMode: FallbackProxyMode
  selectedFallbackProxyGroupId: string
  fallbackCustomProxyInput: string
  defaultProxyPreview: string
  fallbackProxyPreview: string
  defaultTestResult: ProxyTestResult | null
  defaultProxyModeOptions: ReadonlyArray<{ label: string; value: string }>
  fallbackProxyModeOptions: ReadonlyArray<{ label: string; value: string }>
  proxyGroupOptions: Array<{ label: string; value: string }>
}>()

defineEmits<{
  refresh: []
  save: []
  'set-default-mode': [value: string | string[]]
  'select-default-group': [value: string | string[]]
  'set-default-custom': [value: string]
  'set-fallback-mode': [value: string | string[]]
  'select-fallback-group': [value: string | string[]]
  'set-fallback-custom': [value: string]
  'test-default': []
  'set-direct': []
}>()
</script>

<style scoped>
/* ============ 出口配置区（上） ============ */
.proxy-egress {
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(0, 1fr) 300px;
}
@media (max-width: 960px) {
  .proxy-egress {
    grid-template-columns: 1fr;
  }
}

.proxy-egress__row {
  display: grid;
  gap: 10px;
  grid-template-columns: minmax(0, 220px) minmax(0, 1fr);
  align-items: end;
}
/* 局部布局断点：出口行双列→单列；取 720 为「小平板」改排，区别于全局 sm(640)/md(768) */
@media (max-width: 720px) {
  .proxy-egress__row {
    grid-template-columns: 1fr;
    align-items: stretch;
  }
}

.proxy-egress__hint {
  display: flex;
  min-height: 2.5rem;
  align-items: center;
  border: 1.5px dashed color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 30%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--bauhaus-card, #fff) 55%, transparent);
  padding: 0 12px;
  color: hsl(var(--muted-foreground));
  font-size: 12px;
}

.proxy-egress__current {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-top: 12px;
  font-size: 12px;
  min-width: 0;
}
.proxy-egress__current-label {
  flex: 0 0 auto;
  color: hsl(var(--muted-foreground));
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.proxy-egress__current-value {
  min-width: 0;
  overflow: hidden;
  color: var(--bauhaus-blue, #2d5da1);
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.proxy-egress__divider {
  margin: 16px 0;
  border-top: 2px solid color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 14%, transparent);
}

.proxy-egress__note {
  margin-top: 8px;
  color: hsl(var(--muted-foreground));
  font-size: 11px;
  line-height: 1.5;
}

/* 测试结果卡 */
.proxy-egress__test-title {
  color: hsl(var(--muted-foreground));
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.proxy-egress__test-body {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.proxy-egress__test-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 1.5px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius);
  padding: 6px 12px;
  box-shadow: var(--shadow-hard-sm, 2px 2px 0 0 var(--bauhaus-ink, #2d2d2d));
  align-self: flex-start;
}
.proxy-egress__test-status.is-ok {
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 10%, var(--bauhaus-card, #fff));
}
.proxy-egress__test-status.is-fail {
  background: color-mix(in srgb, var(--bauhaus-red, #ff4d4d) 10%, var(--bauhaus-card, #fff));
}
.proxy-egress__test-dot {
  width: 9px;
  height: 9px;
  border: 1.5px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: 50%;
  background: var(--bauhaus-blue, #2d5da1);
}
.proxy-egress__test-status.is-fail .proxy-egress__test-dot {
  background: var(--bauhaus-red, #ff4d4d);
}
.proxy-egress__test-word {
  font-size: 13px;
  font-weight: 700;
}
.proxy-egress__test-status.is-ok .proxy-egress__test-word {
  color: var(--bauhaus-blue, #2d5da1);
}
.proxy-egress__test-status.is-fail .proxy-egress__test-word {
  color: var(--bauhaus-red, #ff4d4d);
}
.proxy-egress__test-meta {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin: 0;
}
.proxy-egress__test-kv {
  display: flex;
  flex-direction: column;
  gap: 2px;
  border: 1px solid color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 18%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--bauhaus-card, #fff) 70%, transparent);
  padding: 8px 10px;
}
.proxy-egress__test-kv dt {
  color: hsl(var(--muted-foreground));
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.proxy-egress__test-kv dd {
  margin: 0;
  color: var(--bauhaus-ink, #2d2d2d);
  font-size: 15px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.proxy-egress__test-error {
  overflow-wrap: anywhere;
  border-left: 3px solid var(--bauhaus-red, #ff4d4d);
  padding-left: 8px;
  color: var(--bauhaus-red, #ff4d4d);
  font-size: 11px;
  line-height: 1.5;
}
.proxy-egress__test-empty {
  margin-top: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: hsl(var(--muted-foreground));
  font-size: 12px;
}
.proxy-egress__test-empty-bar {
  width: 14px;
  height: 3px;
  background: color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 30%, transparent);
}
</style>
