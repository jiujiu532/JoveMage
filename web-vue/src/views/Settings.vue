<template>
  <div class="space-y-6">
    <PagePanel v-if="localSettings">
      <div class="space-y-5">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p class="ui-section-title">设置</p>
          <p class="mt-1 text-xs text-muted-foreground">按原版模块分组维护系统配置。</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" :disabled="settingsStore.isLoading || isSaving" @click="reloadSettings">
            {{ settingsStore.isLoading ? '刷新中...' : '刷新' }}
          </Button>
          <Button size="sm" variant="primary" :disabled="isSaving || !localSettings" @click="handleSave">
            {{ isSaving ? '保存中...' : '保存设置' }}
          </Button>
        </div>
      </div>

      <ConsoleSegmentedTabs
        :model-value="activeSettingsTab"
        :options="settingsTabs"
        aria-label="设置分组"
        @update:model-value="handleSettingsTabChange"
      />

      <div v-if="activeSettingsTab === 'basic'" class="space-y-4">
        <SurfaceBox density="compact">
          <p class="text-xs leading-5 text-muted-foreground">
            管理员登录密钥继续从部署配置读取，不在此页面展示；如需分发给其他人，请到“用户密钥”创建普通用户密钥。
          </p>
        </SurfaceBox>

        <div class="grid gap-4 xl:grid-cols-3">
          <div class="space-y-4 xl:col-span-2">
            <FormSection collapsible icon="mdi:cog-outline" title="基础配置" subtitle="按连接、清理、生图超时拆开，先改常用项。">
              <div class="settings-block-stack">
                <section class="settings-block">
                  <header class="settings-block__header">
                    <span class="settings-block__icon" aria-hidden="true"><Icon icon="mdi:lan-connect" /></span>
                    <div class="settings-block__headtext">
                      <p class="settings-block__title">连接与访问</p>
                      <p class="settings-block__desc">账号刷新、图片访问前缀与默认出站。</p>
                    </div>
                  </header>
                  <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <FormField label="账号刷新间隔">
                      <template #label-extra>
                        <HelpTip text="单位分钟，控制账号自动刷新频率。" />
                      </template>
                      <Input
                        :model-value="refreshAccountIntervalField.input.value"
                        type="number"
                        block
                        placeholder="5"
                        @update:model-value="refreshAccountIntervalField.update"
                      />
                    </FormField>

                    <FormField label="图片访问地址">
                      <template #label-extra>
                        <HelpTip text="用于生成图片结果的访问前缀地址。" />
                      </template>
                      <Input
                        v-model.trim="localSettings.base_url"
                        block
                        placeholder="https://example.com"
                      />
                    </FormField>

                    <FormField label="默认出口" class="md:col-span-2">
                      <template #label-extra>
                        <HelpTip text="账号个人代理、账号组代理优先于默认出口。可填写代理 URL、direct 或 group:代理组ID；完整选择可到代理管理维护。" />
                      </template>
                      <div class="flex flex-col gap-2 sm:flex-row">
                        <Input
                          v-model.trim="localSettings.proxy"
                          block
                          root-class="font-mono"
                          placeholder="http://127.0.0.1:7890"
                          @update:model-value="proxyTestResult = null"
                        />
                        <Button
                          size="sm"
                          variant="outline"
                          root-class="shrink-0"
                          :disabled="proxyBusy === 'test'"
                          @click="testDefaultProxy"
                        >
                          {{ proxyBusy === 'test' ? '测试中...' : '测试出口' }}
                        </Button>
                      </div>
                      <div v-if="proxyTestResult" class="settings-result-box">
                        <p :class="proxyTestResult.ok ? 'settings-tone-ok' : 'settings-tone-bad'">
                          {{ proxyTestResult.ok ? `出口可用：HTTP ${proxyTestResult.status}，${proxyTestResult.latency_ms} ms` : `出口不可用：${proxyTestResult.error || '未知错误'}` }}
                        </p>
                      </div>
                    </FormField>
                  </div>
                </section>

                <section class="settings-block">
                  <header class="settings-block__header">
                    <span class="settings-block__icon" aria-hidden="true"><Icon icon="mdi:broom" /></span>
                    <div class="settings-block__headtext">
                      <p class="settings-block__title">自动清理</p>
                      <p class="settings-block__desc">按天数清理本地图片与调用日志。</p>
                    </div>
                  </header>
                  <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <FormField label="图片自动清理">
                      <template #label-extra>
                        <HelpTip text="自动删除多少天前的本地图片。" />
                      </template>
                      <Input
                        :model-value="imageRetentionDaysField.input.value"
                        type="number"
                        block
                        placeholder="15"
                        @update:model-value="imageRetentionDaysField.update"
                      />
                    </FormField>

                    <FormField label="日志自动清理">
                      <template #label-extra>
                        <HelpTip text="自动删除多少天前的控制台调用日志，清理对象是 data/logs.jsonl。" />
                      </template>
                      <Input
                        :model-value="logRetentionDaysField.input.value"
                        type="number"
                        block
                        placeholder="30"
                        @update:model-value="logRetentionDaysField.update"
                      />
                    </FormField>
                  </div>
                </section>

                <section class="settings-block">
                  <header class="settings-block__header">
                    <span class="settings-block__icon" aria-hidden="true"><Icon icon="mdi:timer-sand" /></span>
                    <div class="settings-block__headtext">
                      <p class="settings-block__title">图片任务超时</p>
                      <p class="settings-block__desc">轮询、SSE 流与超时后的额外等待。</p>
                    </div>
                  </header>
                  <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <FormField label="图片轮询超时">
                      <template #label-extra>
                        <HelpTip text="单位秒，等待上游图片结果的最长时间。" />
                      </template>
                      <Input
                        :model-value="imagePollTimeoutField.input.value"
                        type="number"
                        block
                        placeholder="120"
                        @update:model-value="imagePollTimeoutField.update"
                      />
                    </FormField>

                    <FormField label="上游流超时">
                      <template #label-extra>
                        <HelpTip text="单位秒，限制 ChatGPT 生图 SSE 流最长等待时间。" />
                      </template>
                      <Input
                        :model-value="imageStreamTimeoutField.input.value"
                        type="number"
                        block
                        placeholder="300"
                        @update:model-value="imageStreamTimeoutField.update"
                      />
                    </FormField>

                    <FormField label="单账号图片并发">
                      <template #label-extra>
                        <HelpTip text="限制每个账号同时处理的图片请求数量。" />
                      </template>
                      <Input
                        :model-value="imageAccountConcurrencyField.input.value"
                        type="number"
                        block
                        placeholder="3"
                        @update:model-value="imageAccountConcurrencyField.update"
                      />
                    </FormField>

                    <FormField label="超时继续等待">
                      <template #label-extra>
                        <HelpTip text="单位秒，图片超时后继续等待的额外时间。" />
                      </template>
                      <Input
                        :model-value="imageTimeoutRetryField.input.value"
                        type="number"
                        block
                        placeholder="30"
                        @update:model-value="imageTimeoutRetryField.update"
                      />
                    </FormField>
                  </div>
                </section>
              </div>
            </FormSection>

            <FormSection collapsible icon="mdi:shield-link-variant-outline" title="稳定代理 / Cloudflare 清障" subtitle="先看运行状态，再改开关与出站参数。">
              <div class="settings-block-stack">
                <section class="settings-block settings-block--status">
                  <header class="settings-block__header">
                    <span class="settings-block__icon" aria-hidden="true"><Icon icon="mdi:heart-pulse" /></span>
                    <div class="settings-block__headtext">
                      <p class="settings-block__title">运行状态</p>
                      <p class="settings-block__desc">只读摘要，保存配置后会刷新。</p>
                    </div>
                  </header>
                  <div class="settings-status-grid">
                    <div
                      v-for="item in proxyRuntimeSummaryItems"
                      :key="item.label"
                      class="settings-status-chip"
                    >
                      <p class="settings-status-chip__label">{{ item.label }}</p>
                      <p class="settings-status-chip__value">{{ item.value }}</p>
                    </div>
                  </div>
                  <p v-if="proxyRuntimeStatus?.cached_clearance_hosts?.length" class="settings-block__note">
                    已缓存：{{ proxyRuntimeStatus.cached_clearance_hosts.join(' / ') }}
                  </p>
                </section>

                <section class="settings-block">
                  <header class="settings-block__header">
                    <span class="settings-block__icon" aria-hidden="true"><Icon icon="mdi:toggle-switch-outline" /></span>
                    <div class="settings-block__headtext">
                      <p class="settings-block__title">开关</p>
                      <p class="settings-block__desc">运行时、清障与启动预热。</p>
                    </div>
                  </header>
                  <div class="settings-check-grid">
                    <div class="settings-check-item">
                      <div class="settings-check-control">
                        <Checkbox v-model="localSettings.proxy_runtime.enabled">启用稳定代理运行时</Checkbox>
                        <HelpTip text="关闭时不会接管上游请求。" />
                      </div>
                    </div>
                    <div class="settings-check-item">
                      <div class="settings-check-control">
                        <Checkbox v-model="localSettings.proxy_runtime.clearance.enabled">启用 Cloudflare 清障</Checkbox>
                        <HelpTip text="只关闭清障时，可保留代理出站但不会注入 clearance。" />
                      </div>
                    </div>
                    <div class="settings-check-item">
                      <div class="settings-check-control">
                        <Checkbox v-model="localSettings.proxy_runtime.skip_ssl_verify">跳过上游 SSL 校验</Checkbox>
                        <HelpTip text="仅在代理或上游证书链异常时使用。" />
                      </div>
                    </div>
                    <div class="settings-check-item">
                      <div class="settings-check-control">
                        <Checkbox v-model="localSettings.proxy_runtime.clearance.warm_up_on_start">启动后预热 clearance</Checkbox>
                        <HelpTip text="服务启动后主动获取一次 clearance，减少首个请求等待。" />
                      </div>
                    </div>
                  </div>
                </section>

                <section class="settings-block">
                  <header class="settings-block__header">
                    <span class="settings-block__icon" aria-hidden="true"><Icon icon="mdi:transit-connection-variant" /></span>
                    <div class="settings-block__headtext">
                      <p class="settings-block__title">出站与清障</p>
                      <p class="settings-block__desc">代理地址、清障方式与超时。</p>
                    </div>
                  </header>
                  <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <FormField label="出站方式">
                      <GroupedSelectMenu
                        v-model="localSettings.proxy_runtime.egress_mode"
                        :options="proxyRuntimeEgressOptions"
                        selected-indicator="none"
                        aria-label="稳定代理出站方式"
                        block
                      />
                    </FormField>

                    <FormField label="清障方式">
                      <GroupedSelectMenu
                        v-model="localSettings.proxy_runtime.clearance.mode"
                        :options="proxyClearanceModeOptions"
                        selected-indicator="none"
                        aria-label="Cloudflare 清障方式"
                        block
                      />
                    </FormField>

                    <FormField label="代理地址">
                      <template #label-extra>
                        <HelpTip text="Docker 清障编排默认使用 Privoxy HTTP 代理。" />
                      </template>
                      <Input
                        v-model.trim="localSettings.proxy_runtime.proxy_url"
                        block
                        root-class="font-mono"
                        placeholder="http://privoxy:8118"
                        @update:model-value="clearanceTestResult = null"
                      />
                    </FormField>

                    <FormField label="资源代理地址">
                      <Input
                        v-model.trim="localSettings.proxy_runtime.resource_proxy_url"
                        block
                        root-class="font-mono"
                        placeholder="留空则复用代理地址"
                        @update:model-value="clearanceTestResult = null"
                      />
                    </FormField>

                    <FormField
                      v-if="localSettings.proxy_runtime.clearance.mode === 'flaresolverr'"
                      label="FlareSolverr URL"
                      class="md:col-span-2"
                    >
                      <Input
                        v-model.trim="localSettings.proxy_runtime.clearance.flaresolverr_url"
                        block
                        root-class="font-mono"
                        placeholder="http://flaresolverr:8191"
                        @update:model-value="clearanceTestResult = null"
                      />
                    </FormField>

                    <template v-if="localSettings.proxy_runtime.clearance.mode === 'manual'">
                      <FormField label="cf_clearance">
                        <Input
                          v-model.trim="localSettings.proxy_runtime.clearance.cf_clearance"
                          block
                          root-class="font-mono"
                          :placeholder="localSettings.proxy_runtime.clearance.has_cf_clearance ? '已保存，留空则沿用' : '手动填写 cf_clearance'"
                          @update:model-value="clearanceTestResult = null"
                        />
                      </FormField>

                      <FormField label="Cookie">
                        <Input
                          v-model.trim="localSettings.proxy_runtime.clearance.cf_cookies"
                          block
                          root-class="font-mono"
                          :placeholder="localSettings.proxy_runtime.clearance.has_cf_cookies ? '已保存，留空则沿用' : '可粘贴完整 Cookie'"
                          @update:model-value="clearanceTestResult = null"
                        />
                      </FormField>
                    </template>

                    <FormField label="User-Agent" class="md:col-span-2">
                      <Input
                        v-model.trim="localSettings.proxy_runtime.clearance.user_agent"
                        block
                        root-class="font-mono"
                        placeholder="Mozilla/5.0 ..."
                        @update:model-value="clearanceTestResult = null"
                      />
                    </FormField>

                    <FormField label="清障超时">
                      <template #label-extra>
                        <HelpTip text="单位秒。" />
                      </template>
                      <Input
                        :model-value="clearanceTimeoutField.input.value"
                        type="number"
                        block
                        placeholder="60"
                        @update:model-value="clearanceTimeoutField.update"
                      />
                    </FormField>

                    <FormField label="缓存刷新间隔">
                      <template #label-extra>
                        <HelpTip text="单位秒，最小 60。" />
                      </template>
                      <Input
                        :model-value="clearanceRefreshIntervalField.input.value"
                        type="number"
                        block
                        placeholder="3600"
                        @update:model-value="clearanceRefreshIntervalField.update"
                      />
                    </FormField>
                  </div>
                </section>

                <section class="settings-block">
                  <header class="settings-block__header">
                    <span class="settings-block__icon" aria-hidden="true"><Icon icon="mdi:network-outline" /></span>
                    <div class="settings-block__headtext">
                      <p class="settings-block__title">连通性测试</p>
                      <p class="settings-block__desc">不改配置，仅探测当前清障是否可用。</p>
                    </div>
                  </header>
                  <FormField label="测试目标">
                    <div class="flex flex-col gap-2 sm:flex-row">
                      <Input
                        v-model.trim="clearanceTestTarget"
                        block
                        root-class="font-mono"
                        placeholder="https://chatgpt.com"
                      />
                      <Button
                        size="sm"
                        variant="outline"
                        root-class="shrink-0"
                        :disabled="proxyRuntimeLoading"
                        @click="loadProxyRuntimeStatus(false)"
                      >
                        {{ proxyRuntimeLoading ? '刷新中...' : '刷新状态' }}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        root-class="shrink-0"
                        :disabled="proxyRuntimeTesting"
                        @click="testProxyClearance"
                      >
                        {{ proxyRuntimeTesting ? '测试中...' : '测试清障' }}
                      </Button>
                    </div>
                  </FormField>
                  <div v-if="clearanceTestResult" class="settings-result-box">
                    <p :class="clearanceTestResult.ok ? 'settings-tone-ok' : 'settings-tone-bad'">
                      {{ clearanceTestResult.ok ? `清障可用：${clearanceTestResult.latency_ms} ms` : `清障不可用：${clearanceTestResult.error || '未知错误'}` }}
                    </p>
                    <p v-if="clearanceTestResult.user_agent" class="mt-1 break-all text-muted-foreground">
                      User-Agent：{{ clearanceTestResult.user_agent }}
                    </p>
                  </div>
                </section>
              </div>
            </FormSection>

            <FormSection collapsible icon="mdi:script-text-outline" title="全局附加指令" subtitle="注入到每次请求的系统提示与敏感词拦截。">
              <div class="settings-block-stack">
                <section class="settings-block">
                  <header class="settings-block__header">
                    <span class="settings-block__icon" aria-hidden="true"><Icon icon="mdi:message-text-outline" /></span>
                    <div class="settings-block__headtext">
                      <p class="settings-block__title">系统提示词</p>
                      <p class="settings-block__desc">每次请求都会作为 system 消息注入。</p>
                    </div>
                  </header>
                  <FormField label="全局系统提示词">
                    <textarea
                      v-model="localSettings.global_system_prompt"
                      rows="5"
                      class="ui-textarea-sm"
                      placeholder="例如：先判断用户提示词是否合规；遇到违法、色情、暴力、仇恨等请求时拒绝回答。"
                    ></textarea>
                  </FormField>
                </section>
                <section class="settings-block">
                  <header class="settings-block__header">
                    <span class="settings-block__icon" aria-hidden="true"><Icon icon="mdi:shield-alert-outline" /></span>
                    <div class="settings-block__headtext">
                      <p class="settings-block__title">敏感词</p>
                      <p class="settings-block__desc">一行一个，命中即拒绝。</p>
                    </div>
                  </header>
                  <FormField label="敏感词列表">
                    <textarea
                      v-model="sensitiveWordsText"
                      rows="5"
                      class="ui-textarea-sm"
                      placeholder="一行一个，命中即拒绝"
                    ></textarea>
                  </FormField>
                </section>
              </div>
            </FormSection>
          </div>

          <div class="space-y-4">
            <FormSection collapsible icon="mdi:account-cog-outline" title="账号策略" subtitle="异常与额度耗尽后的账号处理。">
              <div class="settings-check-grid settings-check-grid--single">
                <div class="settings-check-item">
                  <div class="settings-check-control">
                    <Checkbox v-model="localSettings.auto_remove_invalid_accounts">自动移除异常账号</Checkbox>
                    <HelpTip text="确认鉴权无效的账号会进入异常处理；开启后直接移除，关闭后保留异常状态。" />
                  </div>
                </div>
                <div class="settings-check-item">
                  <div class="settings-check-control">
                    <Checkbox v-model="localSettings.auto_remove_rate_limited_accounts">自动移除额度耗尽账号</Checkbox>
                    <HelpTip text="只有远程明确确认图片额度为 0 时才会处理，代理错误、断流或上游 429 不会删除账号。" />
                  </div>
                </div>
              </div>
            </FormSection>

            <FormSection collapsible icon="mdi:image-check-outline" title="图片确认" subtitle="结果稳定后再返回，可选清理官网会话。">
              <div class="settings-check-grid settings-check-grid--single">
                <div class="settings-check-item">
                  <div class="settings-check-control">
                    <Checkbox v-model="localSettings.image_settle_enabled">图片二次确认机制</Checkbox>
                    <HelpTip text="找到图片结果后再等待指定秒数复查一次，减少结果尚未稳定时提前返回。" />
                  </div>
                </div>
                <div class="settings-check-item">
                  <div class="settings-check-control">
                    <Checkbox v-model="localSettings.image_remove_conversation_after_result">图片成功后删除官网会话</Checkbox>
                    <HelpTip text="默认关闭。仅在图片已成功保存后尝试隐藏 ChatGPT 官网 conversation；失败只记录日志，不影响图片返回。关闭时保留官网会话，便于恢复和排查。" />
                  </div>
                </div>
              </div>
              <div class="mt-3">
                <FormField label="二次确认等待（秒）">
                  <Input
                    :model-value="imageSettleSecondsField.input.value"
                    type="number"
                    block
                    placeholder="5"
                    :disabled="!localSettings.image_settle_enabled"
                    @update:model-value="imageSettleSecondsField.update"
                  />
                </FormField>
              </div>
            </FormSection>

            <FormSection collapsible icon="mdi:console" title="控制台日志级别" subtitle="至少保留一类级别；全不选时回落默认 info / warning / error。">
              <div class="settings-check-grid settings-check-grid--single">
                <div
                  v-for="level in logLevelOptions"
                  :key="level"
                  class="settings-check-item"
                >
                  <div class="settings-check-control">
                    <Checkbox
                      :model-value="localSettings.log_levels.includes(level)"
                      @update:model-value="setLogLevel(level, Boolean($event))"
                    >
                      {{ level }}
                    </Checkbox>
                    <HelpTip v-if="level === 'debug'" text="不选择任何级别时使用默认 info / warning / error。" />
                  </div>
                </div>
              </div>
            </FormSection>
          </div>
        </div>
      </div>

      <SettingsImageErrorsPanel
        v-else-if="activeSettingsTab === 'image-errors'"
        :settings="localSettings"
      />

      <SettingsPromptSourcesPanel
        v-else-if="activeSettingsTab === 'prompts'"
      />

      <SettingsDomainBlacklistPanel
        v-else-if="activeSettingsTab === 'domain-blacklist' && localSettings"
        :rules="localSettings.domain_ban_rules || []"
        @update:rules="onDomainBanRulesUpdate"
      />

      <SettingsStoragePanel
        v-else-if="activeSettingsTab === 'storage' && localSettings.image_storage"
        :image-storage="localSettings.image_storage"
        :ai-review="localSettings.ai_review"
        :require-saved-settings="requireSavedSettings"
      />

      <div v-else-if="activeSettingsTab === 'backup' && localSettings.backup" class="space-y-4">
        <SettingsBackupPanel
          :backup="localSettings.backup"
          :require-saved-settings="requireSavedSettings"
        />
      </div>

      <SettingsCanvasPanel
        v-else-if="activeSettingsTab === 'canvas'"
        :canvas="localSettings.third_party_apps.infinite_canvas"
      />

      <SettingsFireflyPanel
        v-else-if="isFireflySettingsTab && localSettings"
        :settings="localSettings"
      />

      <SettingsApiDocsPanel
        v-else-if="activeSettingsTab === 'api-docs'"
      />
      </div>
    </PagePanel>

    <SettingsUserKeysPanel v-if="localSettings && activeSettingsTab === 'keys'" />
    <SettingsCpaPanel v-if="localSettings && activeSettingsTab === 'cpa'" />
    <SettingsSub2ApiPanel v-if="localSettings && activeSettingsTab === 'sub2api'" />

    <PagePanel v-if="!localSettings" class="py-10 text-center text-sm text-muted-foreground">
      <PageLoadingState
        v-if="settingsStore.isLoading"
        title="正在加载设置"
        subtitle="读取系统配置、存储配置和外部连接。"
      />
      <StateBlock
        v-else
        title="设置加载失败"
        :description="settingsLoadError || '未获取到系统配置，请重新加载。'"
      >
        <Button size="sm" variant="outline" root-class="mt-4" @click="reloadSettings">
          重新加载
        </Button>
      </StateBlock>
    </PagePanel>
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, onActivated, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { storeToRefs } from 'pinia'
import { Button, Checkbox, FormField, HelpTip, Input } from 'nanocat-ui'
import { Icon } from '@iconify/vue'
import FormSection from '@/components/ai/FormSection.vue'
import GroupedSelectMenu from '@/components/ui/GroupedSelectMenu.vue'
import {
  normalizeProxyRuntime,
  prepareSettingsForEdit,
  prepareSettingsForSave,
  prepareSettingsPatch,
} from '@/api/settings'
import { parseProxyReference, proxyApi, type ClearanceTestResult, type ProxyRuntimeStatus, type ProxyTestResult } from '@/api/proxy'
import { useChannels } from '@/composables/useChannels'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useSettingsStore } from '@/stores/settings'
import { useToast } from '@/composables/useToast'
import ConsoleSegmentedTabs from '@/components/ai/ConsoleSegmentedTabs.vue'
import PageLoadingState from '@/components/ai/PageLoadingState.vue'
import PagePanel from '@/components/ai/PagePanel.vue'
import StateBlock from '@/components/ai/StateBlock.vue'
import SurfaceBox from '@/components/ai/SurfaceBox.vue'
import SettingsBackupPanel from '@/views/settings/SettingsBackupPanel.vue'
import SettingsCpaPanel from '@/views/settings/SettingsCpaPanel.vue'
import SettingsSub2ApiPanel from '@/views/settings/SettingsSub2ApiPanel.vue'
import SettingsUserKeysPanel from '@/views/settings/SettingsUserKeysPanel.vue'
import type { DomainBanRule, Settings } from '@/types/api'

const SettingsPromptSourcesPanel = defineAsyncComponent(() => import('@/views/settings/SettingsPromptSourcesPanel.vue'))
const SettingsDomainBlacklistPanel = defineAsyncComponent(() => import('@/views/settings/SettingsDomainBlacklistPanel.vue'))
const SettingsImageErrorsPanel = defineAsyncComponent(() => import('@/views/settings/SettingsImageErrorsPanel.vue'))
const SettingsStoragePanel = defineAsyncComponent(() => import('@/views/settings/SettingsStoragePanel.vue'))
const SettingsCanvasPanel = defineAsyncComponent(() => import('@/views/settings/SettingsCanvasPanel.vue'))
const SettingsApiDocsPanel = defineAsyncComponent(() => import('@/views/settings/SettingsApiDocsPanel.vue'))
const SettingsFireflyPanel = defineAsyncComponent(() => import('@/views/settings/SettingsFireflyPanel.vue'))

type NumberFieldBinding = {
  input: ReturnType<typeof ref<string>>
  update: (value: string) => void
}

const settingsStore = useSettingsStore()
const { settings } = storeToRefs(settingsStore)
const toast = useToast()
const confirmDialog = useConfirmDialog()
const { bypassChannels, loadChannels } = useChannels()

const localSettings = ref<Settings | null>(null)
const savedSettingsBaseline = ref<Settings | null>(null)
const activeSettingsTab = ref('basic')
const isSaving = ref(false)
const settingsLoadError = ref('')
const proxyBusy = ref('')
const proxyTestResult = ref<ProxyTestResult | null>(null)
const proxyRuntimeLoading = ref(false)
const proxyRuntimeTesting = ref(false)
const proxyRuntimeStatus = ref<ProxyRuntimeStatus | null>(null)
const clearanceTestTarget = ref('https://chatgpt.com')
const clearanceTestResult = ref<ClearanceTestResult | null>(null)
let hasActivatedOnce = false

const settingsTabs = computed(() => {
  // 设置页展示全部已注册旁路渠道（含未启用），否则关了开关就回不去
  const channelTabs = bypassChannels.value.map((channel) => ({
    value: `channel:${channel.id}`,
    label: channel.id === 'firefly' ? 'Firefly' : channel.name,
  }))
  return [
    { value: 'basic', label: '基础配置' },
    { value: 'image-errors', label: '图片错误' },
    ...channelTabs,
    { value: 'storage', label: '图片存储与审核' },
    { value: 'prompts', label: '提示词源' },
    { value: 'domain-blacklist', label: '域名黑名单' },
    { value: 'backup', label: 'R2 备份' },
    { value: 'keys', label: '用户密钥' },
    { value: 'api-docs', label: '接口接入' },
    { value: 'canvas', label: '画布入口' },
    { value: 'cpa', label: 'CPA' },
    { value: 'sub2api', label: 'Sub2API' },
  ]
})

const isFireflySettingsTab = computed(() => {
  if (activeSettingsTab.value === 'firefly') return true
  return activeSettingsTab.value === 'channel:firefly'
})

watch(settingsTabs, (tabs) => {
  // 当前 Tab 对应渠道关掉后，回落到基础配置
  if (!tabs.some((tab) => tab.value === activeSettingsTab.value)) {
    activeSettingsTab.value = 'basic'
  }
})

const logLevelOptions = ['debug', 'info', 'warning', 'error']

const proxyRuntimeEgressOptions = [
  { label: '直连', value: 'direct' },
  { label: '单代理', value: 'single_proxy' },
]

const proxyClearanceModeOptions = [
  { label: '关闭', value: 'none' },
  { label: 'FlareSolverr', value: 'flaresolverr' },
  { label: '手动 Cookie', value: 'manual' },
]

const proxyRuntimeSummaryItems = computed(() => {
  const status = proxyRuntimeStatus.value
  return [
    { label: '运行时', value: status ? (status.enabled ? '已启用' : '关闭') : '-' },
    { label: '出站方式', value: status ? (status.egress_mode === 'single_proxy' ? '单代理' : '直连') : '-' },
    { label: '代理', value: status ? (status.has_proxy ? '已配置' : '未配置') : '-' },
    { label: '清障', value: status ? (status.clearance_enabled ? `已启用 / ${status.clearance_mode}` : '关闭') : '-' },
    { label: '缓存', value: status ? (status.has_clearance_bundle ? '已有 clearance' : '暂无缓存') : '-' },
  ]
})

const sensitiveWordsText = computed({
  get: () => (localSettings.value?.sensitive_words || []).join('\n'),
  set: (value: string) => {
    if (!localSettings.value) return
    localSettings.value.sensitive_words = value
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean)
  },
})

const numberValue = (value: unknown, fallback: number, min: number, max?: number): number => {
  const parsed = Number(value)
  const finite = Number.isFinite(parsed) ? parsed : fallback
  const bounded = Math.max(min, finite)
  return typeof max === 'number' ? Math.min(max, bounded) : bounded
}

const intValue = (value: unknown, fallback: number, min: number, max?: number): number => (
  Math.round(numberValue(value, fallback, min, max))
)

const createNumberField = (
  getter: () => number,
  setter: (value: number) => void,
  options: { integer?: boolean; min?: number; max?: number; fallback?: number } = {},
): NumberFieldBinding => {
  const input = ref('')

  watch(getter, (value) => {
    const next = String(value)
    if (input.value !== next) {
      input.value = next
    }
  }, { immediate: true })

  const update = (value: string) => {
    input.value = value
    const parsed = Number(value)
    if (value.trim() === '' || !Number.isFinite(parsed)) return
    const min = options.min ?? 0
    const fallback = options.fallback ?? getter()
    const next = options.integer
      ? intValue(parsed, fallback, min, options.max)
      : numberValue(parsed, fallback, min, options.max)
    setter(next)
  }

  return { input, update }
}

const settingsFingerprint = (value: Settings | null | undefined): string => (
  value ? JSON.stringify(prepareSettingsForSave(value)) : ''
)

const hasUnsavedSettings = computed(() => {
  if (!localSettings.value || !savedSettingsBaseline.value) return false
  return settingsFingerprint(localSettings.value) !== settingsFingerprint(savedSettingsBaseline.value)
})

function discardUnsavedSettings() {
  if (!savedSettingsBaseline.value) return
  localSettings.value = prepareSettingsForEdit(savedSettingsBaseline.value)
}

async function confirmDiscardUnsavedSettings(message: string) {
  if (!hasUnsavedSettings.value) return true
  const confirmed = await confirmDialog.ask({
    title: '未保存的更改',
    message,
    confirmText: '丢弃并继续',
    cancelText: '取消',
  })
  if (!confirmed) return false
  discardUnsavedSettings()
  return true
}

function onDomainBanRulesUpdate(rules: DomainBanRule[]) {
  if (!localSettings.value) return
  localSettings.value.domain_ban_rules = Array.isArray(rules) ? rules : []
}

async function handleSettingsTabChange(nextTab: string | number) {
  const target = String(nextTab || '').trim()
  if (!target || target === activeSettingsTab.value) return
  const allowed = await confirmDiscardUnsavedSettings(
    '当前设置有未保存的更改。切换标签将丢弃这些更改，是否继续？',
  )
  if (!allowed) return
  activeSettingsTab.value = target
}

function requireSavedSettings(actionLabel: string) {
  if (!localSettings.value) return false
  if (hasUnsavedSettings.value) {
    toast.warning(`请先保存设置，再${actionLabel}`)
    return false
  }
  return true
}

const imageRetentionDaysField = createNumberField(
  () => localSettings.value?.image_retention_days ?? 15,
  (value) => {
    if (!localSettings.value) return
    localSettings.value.image_retention_days = value
  },
  { integer: true, min: 1, fallback: 15 },
)
const logRetentionDaysField = createNumberField(
  () => localSettings.value?.log_retention_days ?? 30,
  (value) => {
    if (!localSettings.value) return
    localSettings.value.log_retention_days = value
  },
  { integer: true, min: 1, fallback: 30 },
)
const refreshAccountIntervalField = createNumberField(
  () => localSettings.value?.refresh_account_interval_minute ?? 5,
  (value) => {
    if (!localSettings.value) return
    localSettings.value.refresh_account_interval_minute = value
  },
  { integer: true, min: 1, fallback: 5 },
)
const imagePollTimeoutField = createNumberField(
  () => localSettings.value?.image_poll_timeout_secs ?? 120,
  (value) => {
    if (!localSettings.value) return
    localSettings.value.image_poll_timeout_secs = value
  },
  { integer: true, min: 1, fallback: 120 },
)
const imageStreamTimeoutField = createNumberField(
  () => localSettings.value?.image_stream_timeout_secs ?? 300,
  (value) => {
    if (!localSettings.value) return
    localSettings.value.image_stream_timeout_secs = value
  },
  { integer: true, min: 1, fallback: 300 },
)
const imageAccountConcurrencyField = createNumberField(
  () => localSettings.value?.image_account_concurrency ?? 3,
  (value) => {
    if (!localSettings.value) return
    localSettings.value.image_account_concurrency = value
  },
  { integer: true, min: 1, fallback: 3 },
)
const imageTimeoutRetryField = createNumberField(
  () => localSettings.value?.image_timeout_retry_secs ?? 30,
  (value) => {
    if (!localSettings.value) return
    localSettings.value.image_timeout_retry_secs = value
  },
  { integer: true, min: 1, fallback: 30 },
)
const imageSettleSecondsField = createNumberField(
  () => localSettings.value?.image_settle_secs ?? 5,
  (value) => {
    if (!localSettings.value) return
    localSettings.value.image_settle_secs = value
  },
  { min: 0.5, fallback: 5 },
)
const clearanceTimeoutField = createNumberField(
  () => localSettings.value?.proxy_runtime?.clearance.timeout_sec ?? 60,
  (value) => {
    if (!localSettings.value) return
    localSettings.value.proxy_runtime = normalizeProxyRuntime(localSettings.value.proxy_runtime)
    localSettings.value.proxy_runtime.clearance.timeout_sec = value
  },
  { integer: true, min: 1, fallback: 60 },
)
const clearanceRefreshIntervalField = createNumberField(
  () => localSettings.value?.proxy_runtime?.clearance.refresh_interval ?? 3600,
  (value) => {
    if (!localSettings.value) return
    localSettings.value.proxy_runtime = normalizeProxyRuntime(localSettings.value.proxy_runtime)
    localSettings.value.proxy_runtime.clearance.refresh_interval = value
  },
  { integer: true, min: 60, fallback: 3600 },
)
function setLogLevel(level: string, enabled: boolean) {
  if (!localSettings.value) return
  const current = Array.isArray(localSettings.value.log_levels)
    ? localSettings.value.log_levels
    : []
  localSettings.value.log_levels = enabled
    ? Array.from(new Set([...current, level]))
    : current.filter((item) => item !== level)
}

async function testDefaultProxy() {
  const candidate = String(localSettings.value?.proxy || '').trim()
  const reference = parseProxyReference(candidate)
  if (reference.mode === 'global' || reference.mode === 'direct') {
    toast.info('直连模式无需测试出口')
    return
  }
  if (reference.mode === 'group' && !reference.value) {
    toast.warning('请填写代理组 ID')
    return
  }
  if ((reference.mode === 'custom' || reference.mode === 'profile') && !reference.value) {
    toast.warning('请先填写默认出口')
    return
  }
  const confirmed = await confirmDialog.ask({
    title: '测试默认出口',
    message: '即将使用当前填写的默认出口发起连接测试，不会保存设置。是否继续？',
    confirmText: '开始测试',
    cancelText: '取消',
  })
  if (!confirmed) return

  proxyBusy.value = 'test'
  proxyTestResult.value = null
  try {
    if (reference.mode === 'group') {
      const response = await proxyApi.testGroup({ id: reference.value })
      const results = response.results || []
      const failed = results.filter((item) => !item.result.ok)
      const firstResult = results[0]?.result
      proxyTestResult.value = {
        ok: results.length > 0 && failed.length === 0,
        status: firstResult?.status || 0,
        latency_ms: results.reduce((max, item) => Math.max(max, Number(item.result.latency_ms || 0)), 0),
        error: failed.length ? `代理组检测完成，失败 ${failed.length} 个节点` : null,
      }
      if (proxyTestResult.value.ok) {
        toast.success(`默认出口代理组可用：${results.length} 个节点`)
      } else {
        toast.warning(proxyTestResult.value.error || '代理组测试失败')
      }
      return
    }
    if (reference.mode === 'profile') {
      const response = await proxyApi.testProfile({ id: reference.value })
      proxyTestResult.value = response.result
      if (response.result.ok) {
        toast.success(`出口可用：${response.result.latency_ms} ms`)
      } else {
        toast.warning(response.result.error || '出口测试失败')
      }
      return
    }
    const response = await proxyApi.test(candidate)
    proxyTestResult.value = response.result
    if (response.result.ok) {
      toast.success(`出口可用：${response.result.latency_ms} ms`)
    } else {
      toast.warning(response.result.error || '出口测试失败')
    }
  } catch (error: any) {
    proxyTestResult.value = {
      ok: false,
      status: 0,
      latency_ms: 0,
      error: error.message || '出口测试失败',
    }
    toast.error(error.message || '出口测试失败')
  } finally {
    proxyBusy.value = ''
  }
}

async function loadProxyRuntimeStatus(silent = false) {
  proxyRuntimeLoading.value = true
  try {
    const response = await proxyApi.getRuntime()
    proxyRuntimeStatus.value = response.status
    if (localSettings.value && !localSettings.value.proxy_runtime) {
      localSettings.value.proxy_runtime = normalizeProxyRuntime(response.runtime)
    }
  } catch (error: any) {
    proxyRuntimeStatus.value = null
    if (!silent) toast.error(error.message || '加载稳定代理状态失败')
  } finally {
    proxyRuntimeLoading.value = false
  }
}

async function testProxyClearance() {
  if (!requireSavedSettings('测试 Cloudflare 清障')) return
  proxyRuntimeTesting.value = true
  clearanceTestResult.value = null
  try {
    const response = await proxyApi.testClearance(clearanceTestTarget.value)
    clearanceTestResult.value = response.result
    if (response.result.runtime) proxyRuntimeStatus.value = response.result.runtime
    if (response.result.ok) {
      toast.success(`Cloudflare 清障可用：${response.result.latency_ms} ms`)
    } else {
      toast.warning(response.result.error || 'Cloudflare 清障测试失败')
    }
  } catch (error: any) {
    clearanceTestResult.value = {
      ok: false,
      status: 'error',
      latency_ms: 0,
      has_cookies: false,
      user_agent: '',
      error: error.message || 'Cloudflare 清障测试失败',
    }
    toast.error(error.message || 'Cloudflare 清障测试失败')
  } finally {
    proxyRuntimeTesting.value = false
  }
}

async function persistSettings(showToast = false) {
  if (!localSettings.value) return null
  const payload = prepareSettingsPatch(localSettings.value, savedSettingsBaseline.value)
  const result = await settingsStore.updateSettingsPatch(payload)
  if (result.config) {
    const next = prepareSettingsForEdit(result.config)
    localSettings.value = next
    savedSettingsBaseline.value = prepareSettingsForEdit(next)
  }
  await loadProxyRuntimeStatus(true)
  if (showToast) toast.success('设置保存成功')
  return result
}

watch(settings, (value) => {
  if (!value) return
  const next = prepareSettingsForEdit(value)
  if (localSettings.value && savedSettingsBaseline.value && hasUnsavedSettings.value) {
    return
  }
  localSettings.value = next
  savedSettingsBaseline.value = prepareSettingsForEdit(next)
}, { immediate: true })

const reloadSettings = async () => {
  settingsLoadError.value = ''
  try {
    await Promise.all([
      settingsStore.loadSettings(),
      loadChannels(true),
    ])
    await loadProxyRuntimeStatus(true)
  } catch (error: any) {
    settingsLoadError.value = error.message || '设置加载失败'
    toast.error(settingsLoadError.value)
  }
}

function shouldSkipActivatedReload() {
  return Boolean(
    hasUnsavedSettings.value ||
    isSaving.value ||
    settingsStore.isLoading ||
    proxyBusy.value ||
    proxyRuntimeTesting.value,
  )
}

onMounted(async () => {
  await reloadSettings()
})

onActivated(() => {
  if (!hasActivatedOnce) {
    hasActivatedOnce = true
    return
  }
  if (shouldSkipActivatedReload()) return
  void reloadSettings()
})

onBeforeRouteLeave(async (_to, _from, next) => {
  if (!hasUnsavedSettings.value) {
    next()
    return
  }
  const confirmed = await confirmDialog.ask({
    title: '未保存的更改',
    message: '当前设置有未保存的更改。离开页面将丢弃这些更改，是否继续？',
    confirmText: '丢弃并离开',
    cancelText: '取消',
  })
  if (confirmed) {
    discardUnsavedSettings()
    next()
    return
  }
  next(false)
})

const handleSave = async () => {
  if (!localSettings.value) return
  const confirmed = await confirmDialog.ask({
    title: '确认保存系统设置',
    message: '即将保存当前系统设置，可能影响接口地址、并发、存储和备份策略。是否继续？',
    confirmText: '保存',
    cancelText: '取消',
  })
  if (!confirmed) return

  isSaving.value = true

  try {
    await persistSettings(true)
  } catch (error: any) {
    toast.error(error.message || '保存失败')
  } finally {
    isSaving.value = false
  }
}
</script>

<style scoped>
/* 设置页块/字段/KV/文档样式已上移到全局 style.css，供子面板共用 */
</style>
