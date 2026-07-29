<template>
  <div class="register-page">
    <PagePanel class="space-y-4">
      <PanelHeader title="注册账号" align="start">
        <template #actions>
          <StateBadge :tone="registerStatusBadge.tone" shape="rounded" size="sm">
            {{ registerStatusBadge.label }}
          </StateBadge>
          <MetaChip
            v-if="registerStatusChip"
            size="xs"
            :tone="registerStatusChip.tone"
          >
            {{ registerStatusChip.label }}
          </MetaChip>
          <Button
            size="sm"
            variant="primary"
            :disabled="legacySaving || !registerConfig || registerConfig.enabled"
            @click="saveLegacyConfig"
          >
            保存配置
          </Button>
        </template>
      </PanelHeader>

      <PageLoadingState
        v-if="legacyLoading && !registerConfig"
        title="正在加载注册配置"
        description="读取邮箱来源、任务参数和运行状态。"
      />

      <div v-else-if="registerConfig" class="register-layout">
        <div class="register-config-column">
          <FormSection title="任务参数" density="roomy">
            <div class="register-form-grid">
              <label class="register-field">
                <span class="register-label">任务模式</span>
                <GroupedSelectMenu
                  v-model="registerConfig.mode"
                  :groups="registerModeGroups"
                  selected-indicator="none"
                  :disabled="registerConfig.enabled"
                  block
                />
              </label>

              <label v-if="registerConfig.mode === 'total'" class="register-field">
                <span class="register-label">注册总数</span>
                <Input
                  v-model.number="registerConfig.total"
                  type="number"
                  min="1"
                  block
                  :disabled="registerConfig.enabled || registerConfig.mode !== 'total'"
                />
              </label>

              <label v-else-if="registerConfig.mode === 'quota'" class="register-field">
                <span class="register-label">目标剩余额度</span>
                <Input
                  v-model.number="registerConfig.target_quota"
                  type="number"
                  min="1"
                  block
                  :disabled="registerConfig.enabled"
                />
              </label>

              <label v-else class="register-field">
                <span class="register-label">目标可用账号</span>
                <Input
                  v-model.number="registerConfig.target_available"
                  type="number"
                  min="1"
                  block
                  :disabled="registerConfig.enabled"
                />
              </label>

              <label class="register-field">
                <span class="register-label">线程数</span>
                <Input
                  v-model.number="registerConfig.threads"
                  type="number"
                  min="1"
                  block
                  :disabled="registerConfig.enabled"
                />
              </label>

              <label class="register-field">
                <span class="register-label">日常重登重试</span>
                <Input
                  v-model.number="registerConfig.max_relogin_retries"
                  type="number"
                  min="0"
                  max="10"
                  block
                  :disabled="registerConfig.enabled"
                />
              </label>

              <label v-if="registerConfig.mode !== 'total'" class="register-field">
                <span class="register-label">检查间隔（秒）</span>
                <Input
                  v-model.number="registerConfig.check_interval"
                  type="number"
                  min="1"
                  block
                  :disabled="registerConfig.enabled"
                />
              </label>

              <label class="register-field">
                <span class="register-label">注册代理</span>
                <GroupedSelectMenu
                  :model-value="registerProxyMode"
                  :groups="registerProxyModeGroups"
                  selected-indicator="none"
                  :disabled="registerConfig.enabled"
                  block
                  @update:model-value="setRegisterProxyMode"
                />
              </label>

              <label v-if="registerProxyMode === 'group'" class="register-field">
                <span class="register-label">代理组</span>
                <GroupedSelectMenu
                  :model-value="selectedRegisterProxyGroupId"
                  :groups="registerProxyGroupGroups"
                  selected-indicator="none"
                  :disabled="registerConfig.enabled"
                  block
                  @update:model-value="selectRegisterProxyGroup"
                />
              </label>

              <label v-else-if="registerProxyMode === 'custom'" class="register-field">
                <span class="register-label">自定义代理</span>
                <Input
                  :model-value="customRegisterProxyInput"
                  block
                  root-class="font-mono"
                  placeholder="http://127.0.0.1:7890"
                  :disabled="registerConfig.enabled"
                  @update:model-value="setCustomRegisterProxyInput"
                />
              </label>

              <p class="register-proxy-hint register-field--full">
                {{ registerProxyHint }}
              </p>

              <label class="register-field register-field--full">
                <span class="register-label">注册代理池</span>
                <textarea
                  class="register-textarea register-textarea--tall font-mono"
                  :value="proxyPoolText"
                  placeholder="http://privoxy-1:8118&#10;http://privoxy-2:8118"
                  :disabled="registerConfig.enabled"
                  @input="updateProxyPool(($event.target as HTMLTextAreaElement).value)"
                ></textarea>
              </label>

              <label class="register-checkbox-field register-checkbox-field--compact register-field--full">
                <Checkbox
                  :model-value="registerConfig.schedule?.enabled === true"
                  :disabled="registerConfig.enabled"
                  @update:model-value="setScheduleEnabled"
                >
                  启用定时抢注
                </Checkbox>
              </label>

              <template v-if="registerConfig.schedule?.enabled">
                <label class="register-field register-field--full">
                  <span class="register-label">抢注时段</span>
                  <textarea
                    class="register-textarea font-mono"
                    :value="scheduleWindowsText"
                    placeholder="02:00-03:00&#10;23:00-01:00"
                    :disabled="registerConfig.enabled"
                    @input="updateScheduleWindowsText(($event.target as HTMLTextAreaElement).value)"
                  ></textarea>
                </label>

                <div class="register-form-grid register-form-grid--schedule-params register-field--full">
                  <label class="register-field">
                    <span class="register-label">抢注线程</span>
                    <Input
                      v-model.number="registerConfig.schedule.threads"
                      type="number"
                      min="1"
                      block
                      :disabled="registerConfig.enabled"
                    />
                  </label>

                  <label class="register-field">
                    <span class="register-label">抢注重登重试</span>
                    <Input
                      v-model.number="registerConfig.schedule.max_relogin_retries"
                      type="number"
                      min="0"
                      max="10"
                      block
                      :disabled="registerConfig.enabled"
                    />
                  </label>

                  <label class="register-field">
                    <span class="register-label">开始前收束（分）</span>
                    <Input
                      v-model.number="registerConfig.schedule.preempt_minutes"
                      type="number"
                      min="0"
                      block
                      :disabled="registerConfig.enabled"
                    />
                  </label>

                  <label class="register-field">
                    <span class="register-label">结束后最长等待（分）</span>
                    <Input
                      v-model.number="registerConfig.schedule.drain_timeout_minutes"
                      type="number"
                      min="0"
                      block
                      :disabled="registerConfig.enabled"
                    />
                  </label>
                </div>

                <p class="register-proxy-hint register-field--full">
                  时区 Asia/Shanghai。时段可写多行，每行一个 `HH:MM-HH:MM`（允许跨日）；到点开抢，到结束时刻停止。
                </p>
              </template>
            </div>
          </FormSection>

          <FormSection title="邮箱请求" density="roomy">
            <div class="register-form-grid register-form-grid--mail">
              <label class="register-field">
                <span class="register-label">请求超时（秒）</span>
                <Input
                  v-model.number="registerConfig.mail.request_timeout"
                  type="number"
                  min="1"
                  block
                  :disabled="registerConfig.enabled"
                />
              </label>

              <label class="register-field">
                <span class="register-label">验证码等待（秒）</span>
                <Input
                  v-model.number="registerConfig.mail.wait_timeout"
                  type="number"
                  min="1"
                  block
                  :disabled="registerConfig.enabled"
                />
              </label>

              <label class="register-field">
                <span class="register-label">轮询间隔（秒）</span>
                <Input
                  v-model.number="registerConfig.mail.wait_interval"
                  type="number"
                  min="1"
                  step="0.2"
                  block
                  :disabled="registerConfig.enabled"
                />
              </label>

              <label class="register-field register-field--full">
                <span class="register-label">请求 User-Agent</span>
                <Input
                  v-model.trim="registerConfig.mail.user_agent"
                  block
                  root-class="font-mono"
                  placeholder="默认浏览器 UA"
                  :disabled="registerConfig.enabled"
                />
              </label>
            </div>
          </FormSection>

          <FormSection title="邮箱来源" density="roomy">
            <template #actions>
              <MetaChip v-if="enabledProviderIssueCount" size="xs" tone="danger">
                缺 {{ enabledProviderIssueCount }}
              </MetaChip>
              <MetaChip size="xs" tone="muted">已启用 {{ enabledProviderCount }} / {{ registerProviders.length }}</MetaChip>
              <MetaChip v-if="scheduleProviderCount" size="xs" tone="info">定时 {{ scheduleProviderCount }}</MetaChip>
              <Button
                size="sm"
                variant="outline"
                :disabled="registerConfig.enabled"
                @click="addProvider"
              >
                添加来源
              </Button>
            </template>

            <div class="register-provider-list">
              <FormSection
                v-for="(provider, index) in registerProviders"
                :key="providerKey(provider, index)"
                class="register-provider-card"
                :class="{ 'is-collapsed': !isProviderExpanded(provider, index) }"
                surface="background"
                density="normal"
              >
                <div class="register-provider-head">
                  <button
                    type="button"
                    class="register-provider-toggle"
                    :aria-expanded="isProviderExpanded(provider, index)"
                    :aria-label="isProviderExpanded(provider, index) ? '收起邮箱来源' : '展开邮箱来源'"
                    @click="toggleProviderExpanded(provider, index)"
                  >
                    <span
                      class="register-provider-chevron"
                      :class="{ 'is-open': isProviderExpanded(provider, index) }"
                      aria-hidden="true"
                    />
                    <div class="min-w-0">
                      <div class="register-provider-title">
                        <span>{{ providerTitle(provider, index) }}</span>
                        <MetaChip size="xs" tone="muted">{{ providerTypeLabel(providerType(provider)) }}</MetaChip>
                        <MetaChip
                          v-for="chip in providerStatusChips(provider)"
                          :key="chip.label"
                          size="xs"
                          :tone="chip.tone"
                        >
                          {{ chip.label }}
                        </MetaChip>
                      </div>
                    </div>
                  </button>
                  <div class="register-provider-actions" @click.stop>
                    <Checkbox v-model="provider.enable" :disabled="registerConfig.enabled">
                      启用
                    </Checkbox>
                    <Checkbox v-model="provider.schedule_enable" :disabled="registerConfig.enabled">
                      定时参与
                    </Checkbox>
                    <Button
                      size="sm"
                      variant="ghost"
                      :disabled="registerConfig.enabled || registerProviders.length <= 1"
                      @click="deleteProvider(index)"
                    >
                      删除
                    </Button>
                  </div>
                </div>

                <div v-show="isProviderExpanded(provider, index)" class="register-provider-body">
                <SurfaceBox
                  v-if="provider.enable !== false && providerRequirementMessages(provider).length"
                  class="register-provider-message"
                  tone="danger"
                  density="compact"
                >
                  缺少：{{ providerRequirementMessages(provider).join('、') }}
                </SurfaceBox>

                <div class="register-provider-section">
                  <div class="register-provider-section-title">基础配置</div>
                  <div class="register-form-grid register-form-grid--two">
                    <label class="register-field">
                      <span class="register-label">类型</span>
                      <GroupedSelectMenu
                        :model-value="provider.type || 'cloudmail_gen'"
                        :groups="providerTypeGroups"
                        selected-indicator="none"
                        :disabled="registerConfig.enabled"
                        block
                        @update:model-value="value => updateProviderType(index, String(value))"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'gptmail'" class="register-field">
                      <span class="register-label">Key 来源</span>
                      <GroupedSelectMenu
                        v-model="provider.key_mode"
                        :groups="gptMailKeyModeGroups"
                        selected-indicator="none"
                        :disabled="registerConfig.enabled"
                        block
                      />
                    </label>

                    <label v-if="providerUsesApiBase(provider)" class="register-field">
                      <span class="register-label">{{ apiBaseLabel(provider) }}</span>
                      <Input
                        v-model.trim="provider.api_base"
                        block
                        root-class="font-mono"
                        :disabled="registerConfig.enabled"
                        :placeholder="apiBasePlaceholder(provider)"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'cloudmail_gen'" class="register-field">
                      <span class="register-label">管理员邮箱</span>
                      <Input v-model.trim="provider.admin_email" block :disabled="registerConfig.enabled" />
                    </label>

                    <label v-if="providerUsesAdminPassword(provider)" class="register-field">
                      <span class="register-label">{{ providerType(provider) === 'ddg_mail' ? 'CF Admin Password' : 'Admin Password' }}</span>
                      <Input
                        v-model.trim="provider.admin_password"
                        block
                        root-class="font-mono"
                        :disabled="registerConfig.enabled"
                      />
                    </label>

                    <label v-if="providerUsesApiKey(provider) && !providerUsesPublicGptMailKey(provider)" class="register-field">
                      <span class="register-label">API Key</span>
                      <Input
                        v-model.trim="provider.api_key"
                        block
                        root-class="font-mono"
                        :disabled="registerConfig.enabled"
                      />
                    </label>

                    <label v-if="providerUsesDefaultDomain(provider)" class="register-field">
                      <span class="register-label">默认域名</span>
                      <Input
                        v-model.trim="provider.default_domain"
                        block
                        :placeholder="providerType(provider) === 'duckmail' ? 'duckmail.sbs' : providerType(provider) === 'gptmail' ? 'sk-ai.eu.cc' : ''"
                        :disabled="registerConfig.enabled"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'cloudmail_gen'" class="register-field">
                      <span class="register-label">邮箱前缀</span>
                      <Input
                        v-model.trim="provider.email_prefix"
                        block
                        :disabled="registerConfig.enabled"
                        placeholder="可选"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'moemail'" class="register-field">
                      <span class="register-label">过期时间</span>
                      <Input
                        v-model.number="provider.expiry_time"
                        type="number"
                        min="0"
                        block
                        :disabled="registerConfig.enabled"
                        placeholder="0 表示服务默认"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'ddg_mail'" class="register-field">
                      <span class="register-label">DDG Token</span>
                      <Input
                        v-model.trim="provider.ddg_token"
                        block
                        root-class="font-mono"
                        :disabled="registerConfig.enabled"
                        placeholder="DuckDuckGo Email Protection Bearer Token"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'ddg_mail'" class="register-field">
                      <span class="register-label">CF Inbox JWT</span>
                      <Input
                        v-model.trim="provider.cf_inbox_jwt"
                        block
                        root-class="font-mono"
                        :disabled="registerConfig.enabled"
                        placeholder="固定收件箱 JWT"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'ddg_mail'" class="register-field">
                      <span class="register-label">CF API Key</span>
                      <Input
                        v-model.trim="provider.cf_api_key"
                        block
                        root-class="font-mono"
                        :disabled="registerConfig.enabled"
                        placeholder="可选"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'ddg_mail'" class="register-field">
                      <span class="register-label">CF 鉴权方式</span>
                      <GroupedSelectMenu
                        v-model="provider.cf_auth_mode"
                        :groups="cfAuthModeGroups"
                        selected-indicator="none"
                        :disabled="registerConfig.enabled"
                        block
                      />
                    </label>

                    <label v-if="providerType(provider) === 'ddg_mail'" class="register-field">
                      <span class="register-label">创建路径</span>
                      <Input
                        v-model.trim="provider.cf_create_path"
                        block
                        root-class="font-mono"
                        :disabled="registerConfig.enabled"
                        placeholder="/api/new_address"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'ddg_mail'" class="register-field">
                      <span class="register-label">邮件列表路径</span>
                      <Input
                        v-model.trim="provider.cf_messages_path"
                        block
                        root-class="font-mono"
                        :disabled="registerConfig.enabled"
                        placeholder="/api/mails"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'yyds_mail'" class="register-field">
                      <span class="register-label">Subdomain</span>
                      <Input
                        :model-value="stringValue(provider.subdomain)"
                        block
                        :disabled="registerConfig.enabled"
                        @update:model-value="value => updateProviderField(index, 'subdomain', String(value || ''))"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'inbucket'" class="register-checkbox-field">
                      <Checkbox v-model="provider.random_subdomain" :disabled="registerConfig.enabled">
                        随机子域名
                      </Checkbox>
                    </label>

                    <label v-if="providerType(provider) === 'yyds_mail'" class="register-checkbox-field">
                      <Checkbox v-model="provider.wildcard" :disabled="registerConfig.enabled">
                        Wildcard
                      </Checkbox>
                    </label>

                    <label v-if="providerType(provider) === 'gptmail'" class="register-checkbox-field register-checkbox-field--compact register-field--full">
                      <Checkbox v-model="provider.local_compose" :disabled="registerConfig.enabled">
                        已知域名本地拼接
                      </Checkbox>
                    </label>

                    <label v-if="providerType(provider) === 'outlook_email_api'" class="register-field">
                      <span class="register-label">分组 ID</span>
                      <Input
                        v-model.trim="provider.group_id"
                        block
                        root-class="font-mono"
                        :disabled="registerConfig.enabled"
                        placeholder="可选，对应 group_id"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'outlook_email_api'" class="register-field">
                      <span class="register-label">标签 ID</span>
                      <Input
                        v-model.trim="provider.tag_ids"
                        block
                        root-class="font-mono"
                        :disabled="registerConfig.enabled"
                        placeholder="可选，逗号分隔"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'outlook_email_api'" class="register-field">
                      <span class="register-label">邮件文件夹</span>
                      <GroupedSelectMenu
                        v-model="provider.folder"
                        :groups="outlookEmailFolderGroups"
                        selected-indicator="none"
                        :disabled="registerConfig.enabled"
                        block
                      />
                    </label>

                    <label v-if="providerType(provider) === 'outlook_email_api'" class="register-field">
                      <span class="register-label">拉取数量</span>
                      <Input
                        v-model.number="provider.message_limit"
                        type="number"
                        min="1"
                        max="50"
                        block
                        :disabled="registerConfig.enabled"
                        placeholder="默认 10"
                      />
                    </label>

                    <label v-if="providerType(provider) === 'outlook_email_api'" class="register-checkbox-field register-checkbox-field--compact register-field--full">
                      <Checkbox v-model="provider.include_untagged" :disabled="registerConfig.enabled">
                        含未打标签账号（配合标签 ID）
                      </Checkbox>
                    </label>
                  </div>
                </div>

                <div v-if="providerType(provider) === 'gptmail'" class="register-provider-section register-provider-section--soft">
                  <div class="register-provider-section-title">GPTMail 额度</div>
                  <div class="register-gptmail-panel">
                    <div class="register-gptmail-summary">
                      <MetaChip size="xs" :tone="gptMailStatusTone(index)">
                        {{ gptMailStatusTitle(index, provider) }}
                      </MetaChip>
                      <MetaChip size="xs" tone="muted">Key {{ gptMailKeyModeLabel(provider) }}</MetaChip>
                      <MetaChip v-if="gptMailStatusByIndex(index)?.key_hint" size="xs" tone="muted">
                        {{ gptMailStatusByIndex(index)?.key_hint }}
                      </MetaChip>
                      <MetaChip v-if="gptMailRemainingText(index)" size="xs" tone="info">
                        剩余 {{ gptMailRemainingText(index) }}
                      </MetaChip>
                      <MetaChip v-if="gptMailResetText(index)" size="xs" tone="muted">
                        {{ gptMailResetText(index) }}
                      </MetaChip>
                    </div>
                    <div class="register-provider-actions register-provider-actions--left">
                      <Button
                        size="xs"
                        variant="outline"
                        :disabled="registerConfig.enabled || gptMailStatusBusy(index)"
                        @click="checkGptMailStatus(index, provider)"
                      >
                        {{ gptMailStatusBusy(index) ? '检测中' : '检测额度' }}
                      </Button>
                    </div>
                    <p class="register-preview-line">{{ gptMailStatusHint(index, provider) }}</p>
                  </div>
                </div>

                <div
                  v-if="providerUsesDomainList(provider) || providerType(provider) === 'cloudmail_gen'"
                  class="register-provider-section"
                >
                  <div class="register-provider-section-title">域名配置</div>
                  <div class="register-provider-stack">
                    <label v-if="providerUsesDomainList(provider)" class="register-field">
                      <span class="register-label">{{ domainLabel(provider) }}</span>
                      <textarea
                        class="register-textarea"
                        :disabled="registerConfig.enabled"
                        :placeholder="domainPlaceholder(provider)"
                        :value="arrayText(provider.domain)"
                        @input="updateProviderArray(index, 'domain', $event)"
                      ></textarea>
                    </label>

                    <label v-if="providerType(provider) === 'cloudmail_gen'" class="register-field">
                      <span class="register-label">子域名前缀</span>
                      <textarea
                        class="register-textarea"
                        :disabled="registerConfig.enabled"
                        placeholder="每行一个子域名前缀，留空则直接使用主域名"
                        :value="arrayText(provider.subdomain)"
                        @input="updateProviderArray(index, 'subdomain', $event)"
                      ></textarea>
                    </label>
                  </div>
                </div>

                <div v-if="providerType(provider) === 'outlook_token'" class="register-provider-section register-provider-section--soft">
                  <div class="register-provider-section-title">Outlook 邮箱池</div>

                  <div class="register-form-grid register-form-grid--three">
                    <label class="register-field">
                      <span class="register-label">读取方式</span>
                      <GroupedSelectMenu
                        v-model="provider.mode"
                        :groups="outlookModeGroups"
                        selected-indicator="none"
                        :disabled="registerConfig.enabled"
                        block
                      />
                    </label>

                    <label v-if="provider.mode !== 'graph'" class="register-field">
                      <span class="register-label">IMAP Host</span>
                      <Input
                        v-model.trim="provider.imap_host"
                        block
                        root-class="font-mono"
                        :disabled="registerConfig.enabled"
                        placeholder="outlook.office365.com"
                      />
                    </label>

                    <label class="register-field">
                      <span class="register-label">读取邮件数</span>
                      <Input
                        v-model.number="provider.message_limit"
                        type="number"
                        min="1"
                        block
                        :disabled="registerConfig.enabled"
                      />
                    </label>
                  </div>

                  <div class="register-provider-section register-provider-section--soft">
                    <div class="register-provider-section-title">加号别名</div>
                    <div class="register-form-grid register-form-grid--three">
                      <label class="register-checkbox-field register-checkbox-field--compact register-field--full">
                        <Checkbox v-model="provider.alias_enabled" :disabled="registerConfig.enabled">
                          启用 Outlook / Hotmail 加号别名
                        </Checkbox>
                      </label>

                      <label class="register-field">
                        <span class="register-label">每个邮箱别名数</span>
                        <Input
                          v-model.number="provider.alias_per_email"
                          type="number"
                          min="0"
                          max="200"
                          block
                          :disabled="registerConfig.enabled || !provider.alias_enabled"
                        />
                      </label>

                      <label class="register-field">
                        <span class="register-label">别名前缀</span>
                        <Input
                          v-model.trim="provider.alias_prefix"
                          block
                          root-class="font-mono"
                          placeholder="c2api"
                          :disabled="registerConfig.enabled || !provider.alias_enabled"
                        />
                      </label>

                      <label class="register-checkbox-field register-checkbox-field--compact">
                        <Checkbox v-model="provider.alias_include_original" :disabled="registerConfig.enabled || !provider.alias_enabled">
                          包含原邮箱
                        </Checkbox>
                      </label>
                    </div>
                    <p class="register-preview-line">{{ outlookAliasHint(provider) }}</p>
                  </div>

                  <label class="register-field">
                    <span class="register-label">邮箱池导入</span>
                    <textarea
                      class="register-textarea register-textarea--tall"
                      :disabled="registerConfig.enabled"
                      :value="String(provider.mailboxes || '')"
                      placeholder="每行一个：邮箱----密码----client_id----refresh_token"
                      @input="updateProviderField(index, 'mailboxes', ($event.target as HTMLTextAreaElement).value)"
                    ></textarea>
                  </label>

                  <div class="register-outlook-toolbar">
                    <div class="register-outlook-summary">
                      <MetaChip size="xs" tone="success">可用 {{ outlookPoolSummary(provider).available }}</MetaChip>
                      <MetaChip size="xs" tone="muted">占用 {{ outlookPoolSummary(provider).inUse }}</MetaChip>
                      <MetaChip size="xs" tone="muted">已用 {{ outlookPoolSummary(provider).used }}</MetaChip>
                      <MetaChip size="xs" :tone="outlookPoolSummary(provider).retryable ? 'warning' : 'muted'">
                        临时失败 {{ outlookPoolSummary(provider).retryable }}
                      </MetaChip>
                      <MetaChip size="xs" :tone="outlookPoolSummary(provider).invalid ? 'danger' : 'muted'">
                        异常 {{ outlookPoolSummary(provider).invalid }}
                      </MetaChip>
                      <MetaChip v-if="outlookPoolSummary(provider).pending" size="xs" tone="info">
                        待保存 {{ outlookPoolSummary(provider).pending }}
                      </MetaChip>
                    </div>

                    <FloatingActionMenu
                      label="更多维护"
                      :items="outlookPoolActionItems"
                      :disabled="registerConfig.enabled || legacySaving"
                      align="right"
                      placement="auto"
                      :trigger-min-width="96"
                      @select="handleOutlookPoolAction"
                    />
                  </div>

                  <p class="register-preview-line">{{ outlookPoolHint(provider) }}</p>
                  <details class="register-outlook-details">
                    <summary>邮箱池详情</summary>
                    <div class="register-outlook-detail-chips">
                      <MetaChip size="xs" tone="muted">已保存 {{ outlookPoolSummary(provider).saved }}</MetaChip>
                      <MetaChip size="xs" tone="info">待保存 {{ outlookPoolSummary(provider).pending }}</MetaChip>
                      <MetaChip size="xs" tone="muted">占用 {{ outlookPoolSummary(provider).inUse }}</MetaChip>
                      <MetaChip size="xs" tone="warning">需登录 {{ outlookPoolSummary(provider).loginRequired }}</MetaChip>
                      <MetaChip size="xs" tone="warning">失效 {{ outlookPoolSummary(provider).tokenInvalid }}</MetaChip>
                      <MetaChip size="xs" tone="warning">可重试失败 {{ outlookPoolSummary(provider).failed }}</MetaChip>
                    </div>
                  </details>
                </div>
                </div>
              </FormSection>
            </div>
          </FormSection>
        </div>

        <aside class="register-runtime-column">
          <FormSection title="执行控制" density="roomy" class="register-runtime-section">
            <MetricStrip
              :items="registerMetricItems"
              columns-class="grid-cols-2 md:grid-cols-4"
              density="compact"
            />

            <div class="register-runtime-actions">
              <Button
                block
                variant="primary"
                :disabled="registerActionDisabled"
                @click="toggleLegacyTask"
              >
                {{ registerConfig.enabled ? '停止' : '启动' }}
              </Button>
              <Button
                block
                variant="outline"
                :disabled="legacySaving || !registerConfig || registerConfig.enabled"
                @click="resetLegacyStats"
              >
                重置
              </Button>
            </div>

            <SurfaceBox v-if="scheduleNextWindowHint" tone="muted" density="compact">
              {{ scheduleNextWindowHint }}
            </SurfaceBox>

            <SurfaceBox tone="muted" density="compact">
              {{ registerRuntimeHint }}
            </SurfaceBox>

            <SurfaceBox tone="muted" density="compact" class="register-runtime-tips">
              <p>Cloudflare 拦截：可在系统设置启用 FlareSolverr 清障，并确认相关容器已启动。</p>
              <p>HTTP 400 等注册错误通常与邮箱域名风控有关，建议更换新的域名邮箱后重试。</p>
            </SurfaceBox>
          </FormSection>

          <RuntimeLogPanel
            class="register-runtime-log"
            title="实时日志"
            :lines="runtimeLogLines"
            :empty-title="'暂无日志'"
            min-height="20rem"
            max-height="min(58vh, 38rem)"
          />
        </aside>
      </div>
    </PagePanel>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Button, Checkbox, Input } from 'nanocat-ui'
import type { ActionMenuItem } from 'nanocat-ui'
import { proxyApi } from '@/api/proxy'
import { getAuthToken } from '@/api/client'
import { parseProxyReference, serializeProxyReference, type ProxyGroup } from '@/api/proxy'
import { registerApi, type GptMailStatus, type LegacyRegisterConfig, type OutlookMailboxParseStats, type RegisterProvider, type RegisterScheduleConfig, type RegisterScheduleWindow } from '@/api/register'
import FloatingActionMenu from '@/components/ai/FloatingActionMenu.vue'
import FormSection from '@/components/ai/FormSection.vue'
import MetaChip from '@/components/ai/MetaChip.vue'
import MetricStrip from '@/components/ai/MetricStrip.vue'
import PageLoadingState from '@/components/ai/PageLoadingState.vue'
import PagePanel from '@/components/ai/PagePanel.vue'
import PanelHeader from '@/components/ai/PanelHeader.vue'
import RuntimeLogPanel from '@/components/ai/RuntimeLogPanel.vue'
import type { RuntimeLogPanelLine } from '@/components/ai/RuntimeLogPanel.vue'
import StateBadge from '@/components/ai/StateBadge.vue'
import StateBlock from '@/components/ai/StateBlock.vue'
import SurfaceBox from '@/components/ai/SurfaceBox.vue'
import GroupedSelectMenu from '@/components/ui/GroupedSelectMenu.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useToast } from '@/composables/useToast'

type RegisterMode = 'total' | 'quota' | 'available'
type OutlookResetScope = 'all' | 'retryable' | 'invalid' | 'unused'
type RegisterProxyMode = 'global' | 'direct' | 'group' | 'custom'
type GptMailStatusState = {
  loading: boolean
  error: string
  data: GptMailStatus | null
}
type GptMailCheckOptions = {
  silent?: boolean
  force?: boolean
  reschedule?: boolean
}

const toast = useToast()
const confirmDialog = useConfirmDialog()

const legacyLoading = ref(false)
const legacySaving = ref(false)
const pollTimer = ref<number | null>(null)
const eventSource = ref<EventSource | null>(null)
const proxyGroups = ref<ProxyGroup[]>([])
const registerProxyMode = ref<RegisterProxyMode>('global')
const selectedRegisterProxyGroupId = ref('')
const customRegisterProxyInput = ref('')
const gptMailStatusStates = ref<Record<number, GptMailStatusState>>({})
const gptMailClockNow = ref(Date.now())
const gptMailRefreshTimers = new Map<number, number[]>()
const gptMailClockTimer = ref<number | null>(null)
const gptMailResetFallbackSeconds = 5 * 60
const expandedProviderKeys = ref<Set<string>>(new Set())

const defaultScheduleConfig: RegisterScheduleConfig = {
  enabled: false,
  windows: [],
  windows_text: '',
  threads: 10,
  max_relogin_retries: 3,
  preempt_minutes: 5,
  drain_timeout_minutes: 15,
}

const defaultRegisterConfig: LegacyRegisterConfig = {
  mail: {
    request_timeout: 30,
    wait_timeout: 30,
    wait_interval: 2,
    user_agent: '',
    providers: [],
  },
  proxy: '',
  proxy_pool: [],
  max_relogin_retries: 3,
  total: 10,
  threads: 3,
  mode: 'total',
  target_quota: 100,
  target_available: 10,
  check_interval: 5,
  enabled: false,
  schedule: { ...defaultScheduleConfig },
  stats: {
    success: 0,
    fail: 0,
    done: 0,
    running: 0,
    threads: 3,
    elapsed_seconds: 0,
    avg_seconds: 0,
    success_rate: 0,
    current_quota: 0,
    current_available: 0,
  },
  logs: [],
}

const registerConfig = ref<LegacyRegisterConfig | null>(null)

const registerModeOptions = [
  { value: 'total', label: '按数量注册' },
  { value: 'quota', label: '达到额度停止' },
  { value: 'available', label: '达到账号数停止' },
]
const registerModeGroups = [{ options: registerModeOptions }]
const registerProxyModeOptions = [
  { value: 'global', label: '使用默认代理' },
  { value: 'direct', label: '直连' },
  { value: 'group', label: '代理组' },
  { value: 'custom', label: '自定义代理' },
]
const registerProxyModeGroups = [{ options: registerProxyModeOptions }]

const providerTypeOptions = [
  { value: 'cloudmail_gen', label: 'CloudMail Gen' },
  { value: 'cloudflare_temp_email', label: 'Cloudflare Temp Email' },
  { value: 'tempmail_lol', label: 'TempMail.lol' },
  { value: 'moemail', label: 'MoEmail' },
  { value: 'inbucket', label: 'Inbucket' },
  { value: 'ahem', label: 'AHEM' },
  { value: 'jovemail', label: 'JoveMail' },
  { value: 'duckmail', label: 'DuckMail' },
  { value: 'gptmail', label: 'GPTMail' },
  { value: 'yyds_mail', label: 'YYDS Mail' },
  { value: 'ddg_mail', label: 'DDG + CF 收件箱' },
  { value: 'outlook_token', label: 'Microsoft 邮箱凭据池' },
  { value: 'outlook_email_api', label: 'OutlookEmail 管理端 API' },
]
const providerTypeGroups = [{ options: providerTypeOptions }]

const cfAuthModeOptions = [
  { value: 'none', label: '不附加' },
  { value: 'bearer', label: 'Bearer' },
  { value: 'x-api-key', label: 'X-API-Key' },
  { value: 'query-key', label: 'Query key' },
]
const cfAuthModeGroups = [{ options: cfAuthModeOptions }]
const gptMailKeyModeOptions = [
  { value: 'public', label: '公共测试 Key' },
  { value: 'custom', label: '自定义 Key' },
]
const gptMailKeyModeGroups = [{ options: gptMailKeyModeOptions }]

const outlookModeOptions = [
  { value: 'graph', label: 'Graph API' },
  { value: 'imap', label: 'IMAP' },
  { value: 'auto', label: '自动兜底' },
]
const outlookModeGroups = [{ options: outlookModeOptions }]
const outlookEmailFolderOptions = [
  { value: 'inbox', label: '收件箱' },
  { value: 'junkemail', label: '垃圾邮件' },
]
const outlookEmailFolderGroups = [{ options: outlookEmailFolderOptions }]
const outlookPoolActionItems: ActionMenuItem[] = [
  { key: 'retry_failed', label: '重试临时失败' },
  { key: 'retryable', label: '释放占用/失败' },
  { key: 'invalid', label: '清除异常标记', dividerBefore: true },
  { key: 'unused', label: '删除未使用材料', danger: true, dividerBefore: true },
  { key: 'all', label: '重置邮箱池状态', danger: true },
]
const providerCommonKeys = ['id', 'enable', 'type', 'label', 'schedule_enable'] as const
const providerTypeKeys: Record<string, string[]> = {
  cloudmail_gen: ['api_base', 'admin_email', 'admin_password', 'domain', 'subdomain', 'email_prefix'],
  cloudflare_temp_email: ['api_base', 'admin_password', 'domain'],
  tempmail_lol: ['api_key', 'domain'],
  moemail: ['api_base', 'api_key', 'domain', 'expiry_time'],
  inbucket: ['api_base', 'domain', 'random_subdomain'],
  ahem: ['api_base', 'domain'],
  jovemail: ['api_base', 'api_key', 'domain'],
  duckmail: ['api_key', 'default_domain'],
  gptmail: ['key_mode', 'api_key', 'default_domain', 'local_compose'],
  yyds_mail: ['api_base', 'api_key', 'domain', 'subdomain', 'wildcard'],
  ddg_mail: ['api_base', 'ddg_token', 'cf_inbox_jwt', 'admin_password', 'cf_api_key', 'cf_auth_mode', 'cf_create_path', 'cf_messages_path'],
  outlook_token: ['mailboxes', 'mode', 'imap_host', 'message_limit', 'alias_enabled', 'alias_per_email', 'alias_prefix', 'alias_include_original'],
  outlook_email_api: ['api_base', 'api_key', 'group_id', 'tag_ids', 'folder', 'message_limit', 'include_untagged'],
}
const providerLocalOnlyKeys: Record<string, string[]> = {
  outlook_token: ['mailboxes_count', 'mailboxes_base_count', 'mailboxes_alias_count', 'mailboxes_preview', 'mailboxes_stats', 'mailboxes_parse_stats'],
}

const registerProviders = computed(() => registerConfig.value?.mail.providers || [])
const registerProxyGroupOptions = computed(() => {
  const rows = proxyGroups.value.map((group) => ({
    label: `${group.enabled === false ? '停用 · ' : ''}${group.name || group.id}${Array.isArray(group.nodes) ? ` · ${group.nodes.length} 个节点` : ''}`,
    value: group.id,
  }))
  const selectedId = selectedRegisterProxyGroupId.value
  if (selectedId && !rows.some((item) => item.value === selectedId)) {
    rows.unshift({ label: `未知代理组 · ${selectedId}`, value: selectedId })
  }
  return [
    { label: '选择代理组', value: '' },
    ...rows,
  ]
})
const registerProxyGroupGroups = computed(() => [{ options: registerProxyGroupOptions.value }])
const proxyPoolText = computed(() => (registerConfig.value?.proxy_pool || []).join('\n'))
const registerProxyHint = computed(() => {
  if (registerProxyMode.value === 'direct') return '本次注册任务强制直连，不读取默认代理。'
  if (registerProxyMode.value === 'group') return '注册任务会使用所选代理组；代理组为空时不会偷偷回退到默认代理。'
  if (registerProxyMode.value === 'custom') return '仅本注册任务使用该代理地址。'
  return '默认使用系统设置里的默认代理；默认代理设为直连时不使用代理。'
})
const enabledProviderCount = computed(() => registerProviders.value.filter(provider => provider.enable !== false).length)
const scheduleProviderCount = computed(() => registerProviders.value.filter(provider => provider.schedule_enable === true).length)
const enabledProviderIssueCount = computed(() =>
  registerProviders.value
    .filter(provider => provider.enable !== false)
    .reduce((total, provider) => total + providerRequirementMessages(provider).length, 0),
)
const registerActionDisabled = computed(() => {
  if (legacySaving.value || !registerConfig.value) return true
  if (registerConfig.value.enabled) return false
  return enabledProviderCount.value === 0 || enabledProviderIssueCount.value > 0
})
const legacyStats = computed(() => ({ ...defaultRegisterConfig.stats, ...(registerConfig.value?.stats || {}) }))
const legacyLogs = computed(() => [...(registerConfig.value?.logs || [])])

const registerRunKind = computed(() => {
  const raw = registerConfig.value
  if (!raw) return ''
  return String(raw.run_kind || raw.stats?.run_kind || '').trim().toLowerCase()
})

const registerStatusBadge = computed(() => {
  const cfg = registerConfig.value
  if (!cfg) return { label: '已停止', tone: 'muted' as const }
  if (cfg.enabled) {
    if (registerRunKind.value === 'schedule') {
      return { label: '定时抢注中', tone: 'success' as const }
    }
    return { label: '运行中', tone: 'success' as const }
  }
  if (cfg.schedule?.enabled) {
    return { label: '已停止', tone: 'muted' as const }
  }
  return { label: '已停止', tone: 'muted' as const }
})

const registerStatusChip = computed(() => {
  const cfg = registerConfig.value
  if (!cfg) return null
  if (!cfg.enabled && cfg.schedule?.enabled) {
    return { label: '定时已启用', tone: 'info' as const }
  }
  return null
})

const scheduleWindowsText = computed(() => {
  const schedule = registerConfig.value?.schedule
  if (!schedule) return ''
  if (typeof schedule.windows_text === 'string') return schedule.windows_text
  return formatScheduleWindows(schedule.windows)
})

const scheduleNextWindowHint = computed(() => {
  const schedule = registerConfig.value?.schedule
  if (!schedule?.enabled) return ''
  const next = formatNextWindow(schedule.next_window)
  if (next) return `下次抢注时段：${next}（Asia/Shanghai）`
  if (registerConfig.value?.enabled && registerRunKind.value === 'schedule') {
    return '当前处于定时抢注窗口（Asia/Shanghai）。'
  }
  if (!registerConfig.value?.enabled && schedule.enabled) {
    return '定时抢注已启用，等待窗口到点自动开抢。'
  }
  return ''
})

const registerRuntimeHint = computed(() => {
  if (enabledProviderCount.value === 0) return '至少启用一个邮箱来源。'
  if (enabledProviderIssueCount.value > 0) return `还有 ${enabledProviderIssueCount.value} 项必填配置未完成。`
  if (registerConfig.value?.enabled) return '任务运行中，配置已锁定。'
  if (registerConfig.value?.schedule?.enabled) return '定时抢注已启用；也可手动启动日常任务。启动前会自动保存当前配置。'
  return '启动前会自动保存当前配置。'
})

const registerMetricItems = computed(() => {
  const stats = legacyStats.value
  return [
    { key: 'success', label: '成功', value: stats.success || 0, meta: `成功率 ${stats.success_rate || 0}%` },
    { key: 'fail', label: '失败', value: stats.fail || 0 },
    { key: 'done', label: '完成', value: stats.done || 0 },
    { key: 'running', label: '运行 / 线程', value: `${stats.running || 0} / ${stats.threads || registerConfig.value?.threads || 0}` },
    { key: 'elapsed', label: '运行时间', value: `${stats.elapsed_seconds || 0}s` },
    { key: 'avg', label: '平均耗时', value: `${stats.avg_seconds || 0}s` },
    { key: 'quota', label: '当前额度', value: stats.current_quota || 0 },
    { key: 'available', label: '正常账号', value: stats.current_available || 0 },
  ]
})

const runtimeLogLines = computed<RuntimeLogPanelLine[]>(() => legacyLogs.value.slice().reverse().map((item, index) => ({
  key: `${item.time || 'log'}-${index}`,
  time: formatClock(item.time),
  text: item.text || '-',
  level: normalizeLogLevel(item.level),
})))

function normalizeRegisterConfig(raw: LegacyRegisterConfig): LegacyRegisterConfig {
  const mail = {
    ...defaultRegisterConfig.mail,
    ...(raw.mail || {}),
    providers: Array.isArray(raw.mail?.providers) ? raw.mail.providers.map(item => normalizeProvider(item)) : [],
  }
  if (!mail.providers.length) {
    mail.providers = [defaultProvider()]
  }
  return {
    ...defaultRegisterConfig,
    ...raw,
    mail,
    proxy_pool: Array.isArray(raw.proxy_pool)
      ? raw.proxy_pool.map(item => String(item || '').trim()).filter(Boolean)
      : [],
    max_relogin_retries: Math.max(0, Math.min(10, Number(raw.max_relogin_retries ?? 3) || 0)),
    schedule: normalizeScheduleConfig(raw.schedule),
    phase: raw.phase,
    run_kind: raw.run_kind,
    stats: { ...defaultRegisterConfig.stats, ...(raw.stats || {}) },
    logs: Array.isArray(raw.logs) ? raw.logs : [],
  }
}

function normalizeScheduleConfig(raw?: RegisterScheduleConfig | null): RegisterScheduleConfig {
  const source = raw && typeof raw === 'object' ? raw : {}
  const windows = Array.isArray(source.windows)
    ? source.windows
        .map((item) => ({
          start: String(item?.start || '').trim(),
          end: String(item?.end || '').trim(),
        }))
        .filter(item => item.start && item.end)
    : []
  const windowsText = typeof source.windows_text === 'string' && source.windows_text.trim()
    ? source.windows_text
    : formatScheduleWindows(windows)
  return {
    ...defaultScheduleConfig,
    ...source,
    enabled: source.enabled === true,
    windows,
    windows_text: windowsText,
    threads: Math.max(1, Number(source.threads ?? defaultScheduleConfig.threads) || defaultScheduleConfig.threads || 10),
    max_relogin_retries: Math.max(0, Math.min(10, Number(source.max_relogin_retries ?? defaultScheduleConfig.max_relogin_retries) || 0)),
    preempt_minutes: Math.max(0, Number(source.preempt_minutes ?? defaultScheduleConfig.preempt_minutes) || 0),
    drain_timeout_minutes: Math.max(0, Number(source.drain_timeout_minutes ?? defaultScheduleConfig.drain_timeout_minutes) || 0),
  }
}

function normalizeProvider(provider: RegisterProvider): RegisterProvider {
  const type = providerType(provider)
  const normalized = {
    ...defaultProvider(type),
    ...provider,
    id: String(provider.id || provider.provider_id || '').trim() || createProviderId(type),
    type,
    enable: provider.enable !== false,
    schedule_enable: provider.schedule_enable === true,
  }
  if (type === 'gptmail' && !provider.key_mode && isFilled(provider.api_key)) {
    normalized.key_mode = 'custom'
  }
  return normalized
}

function defaultProvider(type = 'cloudmail_gen'): RegisterProvider {
  const base = { id: createProviderId(type), enable: true, type, schedule_enable: false }
  switch (type) {
    case 'cloudmail_gen':
      return { ...base, api_base: '', admin_email: '', admin_password: '', domain: [], subdomain: [], email_prefix: '' }
    case 'cloudflare_temp_email':
      return { ...base, api_base: '', admin_password: '', domain: [] }
    case 'tempmail_lol':
      return { ...base, api_key: '', domain: [] }
    case 'moemail':
      return { ...base, api_base: '', api_key: '', domain: [], expiry_time: 0 }
    case 'inbucket':
      return { ...base, api_base: '', domain: [], random_subdomain: true }
    case 'ahem':
      return { ...base, api_base: '', domain: [] }
    case 'jovemail':
      return { ...base, api_base: '', api_key: '', domain: [] }
    case 'duckmail':
      return { ...base, api_key: '', default_domain: 'duckmail.sbs' }
    case 'gptmail':
      return { ...base, key_mode: 'public', api_key: '', default_domain: '', local_compose: false }
    case 'yyds_mail':
      return { ...base, api_base: 'https://maliapi.215.im/v1', api_key: '', domain: [], subdomain: '', wildcard: false }
    case 'ddg_mail':
      return {
        ...base,
        api_base: '',
        ddg_token: '',
        cf_inbox_jwt: '',
        admin_password: '',
        cf_api_key: '',
        cf_auth_mode: 'none',
        cf_create_path: '/api/new_address',
        cf_messages_path: '/api/mails',
      }
    case 'outlook_token':
      return {
        ...base,
        mailboxes: '',
        mode: 'auto',
        imap_host: 'outlook.office365.com',
        message_limit: 10,
        alias_enabled: false,
        alias_per_email: 5,
        alias_prefix: 'c2api',
        alias_include_original: true,
      }
    case 'outlook_email_api':
      return {
        ...base,
        api_base: '',
        api_key: '',
        group_id: '',
        tag_ids: '',
        folder: 'inbox',
        message_limit: 10,
        include_untagged: false,
      }
    default:
      return base
  }
}

function providerType(provider: RegisterProvider) {
  return String(provider.type || 'cloudmail_gen')
}

function createProviderId(type = 'provider') {
  const suffix = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID().replace(/-/g, '').slice(0, 12)
    : Math.random().toString(36).slice(2, 14).padEnd(12, '0')
  return `${type}-${suffix}`
}

function providerKey(provider: RegisterProvider, index: number) {
  return String(provider.id || provider.provider_id || '').trim() || `${providerType(provider)}-${index}`
}

function isProviderExpanded(provider: RegisterProvider, index: number) {
  return expandedProviderKeys.value.has(providerKey(provider, index))
}

function setProviderExpanded(key: string, open: boolean) {
  const next = new Set(expandedProviderKeys.value)
  if (open) next.add(key)
  else next.delete(key)
  expandedProviderKeys.value = next
}

function toggleProviderExpanded(provider: RegisterProvider, index: number) {
  const key = providerKey(provider, index)
  setProviderExpanded(key, !expandedProviderKeys.value.has(key))
}

function pruneExpandedProviderKeys(providers: RegisterProvider[] = registerProviders.value) {
  const valid = new Set(providers.map((item, index) => providerKey(item, index)))
  const next = new Set<string>()
  for (const key of expandedProviderKeys.value) {
    if (valid.has(key)) next.add(key)
  }
  // 缺配置的启用项默认展开，避免漏看必填
  providers.forEach((item, index) => {
    if (item.enable === false) return
    if (providerRequirementMessages(item).length) {
      next.add(providerKey(item, index))
    }
  })
  expandedProviderKeys.value = next
}

function providerTitle(provider: RegisterProvider, index: number) {
  return `邮箱来源 ${index + 1}`
}

function providerStatusChips(provider: RegisterProvider) {
  const chips: Array<{ label: string; tone: 'muted' | 'warning' | 'success' | 'info' | 'danger' }> = []
  const dailyEnabled = provider.enable !== false
  const scheduleEnabled = provider.schedule_enable === true
  if (!dailyEnabled && !scheduleEnabled) {
    chips.push({ label: '未启用', tone: 'warning' })
    return chips
  }
  if (dailyEnabled) {
    const missing = providerRequirementMessages(provider).length
    if (missing) {
      chips.push({ label: `缺 ${missing} 项`, tone: 'danger' })
    } else {
      chips.push({ label: '可日常', tone: 'success' })
    }
  }
  if (scheduleEnabled) {
    chips.push({ label: '可定时', tone: 'info' })
  }
  return chips
}

function providerTypeLabel(type: string) {
  return providerTypeOptions.find(item => item.value === type)?.label || type
}

function providerKeysForType(type: string, includeLocalOnly = false) {
  return [
    ...providerCommonKeys,
    ...(providerTypeKeys[type] || []),
    ...(includeLocalOnly ? providerLocalOnlyKeys[type] || [] : []),
  ]
}

function providerHasKnownType(type: string) {
  return Object.prototype.hasOwnProperty.call(providerTypeKeys, type)
}

function listFromDraft(value: unknown) {
  if (Array.isArray(value)) return value.map(String).map(item => item.trim()).filter(Boolean)
  return String(value || '')
    .split(/[\n,]/)
    .map(item => item.trim())
    .filter(Boolean)
}

function providerDraftValue(type: string, key: string, value: unknown) {
  if (key === 'domain') return listFromDraft(value)
  if (key === 'subdomain') {
    if (type === 'cloudmail_gen') return listFromDraft(value)
    if (type === 'yyds_mail') return Array.isArray(value) ? value.join('\n') : String(value || '')
  }
  return value
}

function providerWithTypeDraft(current: RegisterProvider, type: string): RegisterProvider {
  const defaults = defaultProvider(type)
  const next: RegisterProvider = {
    ...current,
    ...defaults,
    id: String(current.id || current.provider_id || defaults.id || '').trim(),
    type,
    enable: current.enable !== false,
    schedule_enable: current.schedule_enable === true,
  }

  for (const key of providerKeysForType(type, true)) {
    if (key === 'type' || key === 'enable' || key === 'schedule_enable') continue
    if (current[key] !== undefined) {
      next[key] = providerDraftValue(type, key, current[key])
    }
  }

  next.type = type
  next.enable = current.enable !== false
  next.schedule_enable = current.schedule_enable === true

  return next
}

function isFilled(value: unknown) {
  return String(value ?? '').trim().length > 0
}

function listHasValue(value: unknown) {
  if (Array.isArray(value)) return value.some(item => isFilled(item))
  return isFilled(value)
}

function providerRequirementMessages(provider: RegisterProvider) {
  const type = providerType(provider)
  const missing: string[] = []
  const requireValue = (value: unknown, label: string) => {
    if (!isFilled(value)) missing.push(label)
  }
  const requireList = (value: unknown, label: string) => {
    if (!listHasValue(value)) missing.push(label)
  }

  switch (type) {
    case 'cloudmail_gen':
      requireValue(provider.api_base, 'CloudMail URL')
      requireValue(provider.admin_email, '管理员邮箱')
      requireValue(provider.admin_password, 'Admin Password')
      requireList(provider.domain, '邮箱域名')
      break
    case 'cloudflare_temp_email':
      requireValue(provider.api_base, 'API Base')
      requireValue(provider.admin_password, 'Admin Password')
      requireList(provider.domain, '域名')
      break
    case 'moemail':
      requireValue(provider.api_base, 'API Base')
      requireValue(provider.api_key, 'API Key')
      requireList(provider.domain, '域名')
      break
    case 'inbucket':
      requireValue(provider.api_base, 'API Base')
      requireList(provider.domain, '基础域名')
      break
    case 'ahem':
      requireValue(provider.api_base, 'API Base')
      break
    case 'jovemail':
      requireValue(provider.api_base, '服务地址')
      requireValue(provider.api_key, 'API Key')
      break
    case 'duckmail':
      requireValue(provider.api_key, 'API Key')
      break
    case 'gptmail':
      if (!providerUsesPublicGptMailKey(provider)) requireValue(provider.api_key, 'API Key')
      if (provider.local_compose) requireValue(provider.default_domain, '默认域名')
      break
    case 'yyds_mail':
      requireValue(provider.api_key, 'API Key')
      break
    case 'ddg_mail':
      requireValue(provider.api_base, 'CF API Base')
      requireValue(provider.ddg_token, 'DDG Token')
      requireValue(provider.cf_inbox_jwt, 'CF Inbox JWT')
      break
    case 'outlook_token': {
      const savedCount = Number(provider.mailboxes_count || 0)
      if (savedCount <= 0 && pendingOutlookCount(provider) <= 0) missing.push('Microsoft 邮箱凭据池')
      break
    }
    case 'outlook_email_api':
      requireValue(provider.api_base, '服务地址')
      requireValue(provider.api_key, 'API Key')
      break
    default:
      break
  }

  return missing
}

function updateProviderType(index: number, type: string) {
  if (!registerConfig.value) return
  clearGptMailState(index)
  const providers = [...registerProviders.value]
  const current = providers[index] || {}
  providers[index] = providerWithTypeDraft(current, type)
  registerConfig.value.mail.providers = providers
}

function updateProviderField(index: number, key: string, value: unknown) {
  const provider = registerProviders.value[index]
  if (!provider) return
  provider[key] = value
}

function providerUsesApiBase(provider: RegisterProvider) {
  return ['cloudmail_gen', 'cloudflare_temp_email', 'moemail', 'inbucket', 'ahem', 'jovemail', 'yyds_mail', 'ddg_mail', 'outlook_email_api'].includes(providerType(provider))
}

function providerUsesApiKey(provider: RegisterProvider) {
  return ['tempmail_lol', 'moemail', 'duckmail', 'gptmail', 'yyds_mail', 'jovemail', 'outlook_email_api'].includes(providerType(provider))
}

function providerUsesPublicGptMailKey(provider: RegisterProvider) {
  return providerType(provider) === 'gptmail' && String(provider.key_mode || 'public') !== 'custom'
}

function providerUsesAdminPassword(provider: RegisterProvider) {
  return ['cloudmail_gen', 'cloudflare_temp_email', 'ddg_mail'].includes(providerType(provider))
}

function providerUsesDefaultDomain(provider: RegisterProvider) {
  return ['duckmail', 'gptmail'].includes(providerType(provider))
}

function providerUsesDomainList(provider: RegisterProvider) {
  return ['cloudmail_gen', 'tempmail_lol', 'cloudflare_temp_email', 'moemail', 'inbucket', 'ahem', 'jovemail', 'yyds_mail'].includes(providerType(provider))
}

function apiBaseLabel(provider: RegisterProvider) {
  const type = providerType(provider)
  if (type === 'cloudmail_gen') return 'CloudMail URL'
  if (type === 'ddg_mail') return 'CF API Base'
  if (type === 'outlook_email_api' || type === 'jovemail') return '服务地址'
  return 'API Base'
}

function apiBasePlaceholder(provider: RegisterProvider) {
  const type = providerType(provider)
  if (type === 'yyds_mail') return 'https://maliapi.215.im/v1'
  if (type === 'ahem') return 'https://your-ahem-host/api'
  if (type === 'jovemail') return 'https://your-jovemail-host'
  if (type === 'outlook_email_api') return 'https://your-outlook-email-host'
  return ''
}

function domainLabel(provider: RegisterProvider) {
  const type = providerType(provider)
  if (type === 'inbucket') return '基础域名'
  if (type === 'ahem') return '允许域名'
  if (type === 'jovemail') return '优先域名'
  if (type === 'cloudmail_gen') return '邮箱域名'
  return '域名'
}

function domainPlaceholder(provider: RegisterProvider) {
  const type = providerType(provider)
  if (type === 'inbucket') return '每行一个基础域名，可配合随机子域名'
  if (type === 'ahem') return '每行一个允许域名；可留空，运行时拉取可用域名并排除拉黑后轮询'
  if (type === 'jovemail') return '每行一个优先域名；可留空，运行时拉取可用域名并排除拉黑后轮询'
  if (type === 'cloudmail_gen') return '每行一个邮箱域名'
  if (type === 'cloudflare_temp_email') return '每行一个域名'
  if (type === 'moemail') return '每行一个域名'
  if (type === 'tempmail_lol') return '每行一个域名；可留空则服务端分配，建箱后校验黑名单'
  if (type === 'yyds_mail') return '每行一个域名；可留空，运行时拉取可用域名并排除拉黑后轮询'
  return '每行一个域名'
}

function gptMailKeyModeLabel(provider: RegisterProvider) {
  return providerUsesPublicGptMailKey(provider) ? '公共' : '自定义'
}

function outlookPoolStats(provider: RegisterProvider) {
  return provider.mailboxes_stats || {}
}

function numeric(value: unknown) {
  return Number(value || 0) || 0
}

function pendingOutlookCount(provider: RegisterProvider) {
  return String(provider.mailboxes || '')
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(line => line && line.split('----').length >= 4)
    .length
}

function outlookPoolSummary(provider: RegisterProvider) {
  const stats = outlookPoolStats(provider)
  const inUse = numeric(stats.in_use)
  const loginRequired = numeric(stats.login_required)
  const tokenInvalid = numeric(stats.token_invalid)
  const failed = numeric(stats.failed)
  const retryable = numeric(stats.retryable) || failed
  const invalid = numeric(stats.invalid) || loginRequired + tokenInvalid

  return {
    saved: numeric(provider.mailboxes_count),
    pending: pendingOutlookCount(provider),
    available: numeric(stats.available) || numeric(stats.unused),
    used: numeric(stats.used),
    inUse,
    loginRequired,
    tokenInvalid,
    failed,
    retryable,
    invalid,
    abnormal: retryable + invalid,
  }
}

function outlookAliasSummary(provider: RegisterProvider) {
  const base = numeric(provider.mailboxes_base_count || provider.mailboxes_count)
  const alias = numeric(provider.mailboxes_alias_count)
  const perEmail = numeric(provider.alias_per_email)
  const includeOriginal = provider.alias_include_original !== false
  const multiplier = provider.alias_enabled ? perEmail + (includeOriginal ? 1 : 0) : 1
  const pending = pendingOutlookCount(provider)
  return {
    enabled: Boolean(provider.alias_enabled),
    base,
    alias,
    perEmail,
    includeOriginal,
    multiplier,
    pending,
    pendingExpanded: provider.alias_enabled ? pending * multiplier : pending,
  }
}

function outlookAliasHint(provider: RegisterProvider) {
  const summary = outlookAliasSummary(provider)
  if (!summary.enabled) return '未启用加号别名，注册时直接使用导入邮箱。'
  if (summary.pending > 0) {
    return `保存后本次导入约展开为 ${summary.pendingExpanded} 个注册地址；登录和收信仍使用原邮箱凭据。`
  }
  if (summary.base > 0) {
    return `已保存 ${summary.base} 个原邮箱，当前规则生成 ${summary.alias} 个别名地址；登录和收信仍使用原邮箱凭据。`
  }
  return '保存后会为 Outlook / Hotmail 地址生成加号别名；登录和收信仍使用原邮箱凭据。'
}

function outlookPoolHint(provider: RegisterProvider) {
  const summary = outlookPoolSummary(provider)
  if (summary.pending > 0) return `有 ${summary.pending} 个待保存，保存配置后进入 Microsoft 邮箱池。`
  if (summary.saved <= 0) return '还没有保存 Microsoft 邮箱材料。'
  if (summary.invalid > 0) return `有 ${summary.invalid} 个异常邮箱，需要重新获取 refresh_token 或重新导入材料。`
  if (summary.retryable > 0 || summary.inUse > 0) return `有 ${summary.retryable} 个临时失败、${summary.inUse} 个占用，可在更多维护里释放后重试。`
  if (summary.available <= 0) return '库存已用完，请导入新的 Microsoft 邮箱材料。'
  return `已保存 ${summary.saved} 个 Microsoft 邮箱材料。`
}

function gptMailState(index: number): GptMailStatusState {
  return gptMailStatusStates.value[index] || { loading: false, error: '', data: null }
}

function setGptMailState(index: number, state: GptMailStatusState) {
  gptMailStatusStates.value = { ...gptMailStatusStates.value, [index]: state }
}

function clearGptMailRefreshTimer(index: number) {
  const timers = gptMailRefreshTimers.get(index) || []
  timers.forEach(timer => window.clearTimeout(timer))
  if (timers.length) {
    gptMailRefreshTimers.delete(index)
  }
}

function clearAllGptMailRefreshTimers() {
  gptMailRefreshTimers.forEach(timers => timers.forEach(timer => window.clearTimeout(timer)))
  gptMailRefreshTimers.clear()
}

function clearGptMailState(index: number) {
  clearGptMailRefreshTimer(index)
  const next = { ...gptMailStatusStates.value }
  delete next[index]
  gptMailStatusStates.value = next
}

function pruneGptMailStates() {
  const next: Record<number, GptMailStatusState> = {}
  Object.entries(gptMailStatusStates.value).forEach(([key, state]) => {
    const index = Number(key)
    const provider = registerProviders.value[index]
    if (provider && providerType(provider) === 'gptmail') {
      next[index] = state
    } else {
      clearGptMailRefreshTimer(index)
    }
  })
  Array.from(gptMailRefreshTimers.keys()).forEach((index) => {
    const provider = registerProviders.value[index]
    if (!provider || providerType(provider) !== 'gptmail') clearGptMailRefreshTimer(index)
  })
  gptMailStatusStates.value = next
}

function gptMailSecondsUntilReset(status: GptMailStatus, now = gptMailClockNow.value) {
  const resetAt = Date.parse(String(status.reset_at || ''))
  if (Number.isFinite(resetAt)) {
    return Math.ceil((resetAt - now) / 1000)
  }
  const seconds = Number(status.seconds_until_reset)
  if (!Number.isFinite(seconds) || seconds <= 0) return null
  const checkedAt = Date.parse(String(status.checked_at || ''))
  if (Number.isFinite(checkedAt)) {
    return Math.ceil((checkedAt + seconds * 1000 - now) / 1000)
  }
  return Math.ceil(seconds)
}

function gptMailTimerDelay(seconds: number) {
  return Math.min(Math.max(seconds * 1000, 1000), 2_147_483_000)
}

function gptMailResetDelays(status: GptMailStatus) {
  const seconds = gptMailSecondsUntilReset(status, Date.now())
  if (seconds === null) return []
  const resetSeconds = Math.max(0, seconds)
  return [
    { delay: gptMailTimerDelay(resetSeconds), reschedule: false },
    { delay: gptMailTimerDelay(resetSeconds + gptMailResetFallbackSeconds), reschedule: true },
  ]
}

function scheduleGptMailRefresh(index: number, status: GptMailStatus) {
  clearGptMailRefreshTimer(index)
  if (String(status.key_mode || 'public') !== 'public') return
  const timers = gptMailResetDelays(status).map(({ delay, reschedule }) => {
    let timer = 0
    timer = window.setTimeout(() => {
      const activeTimers = gptMailRefreshTimers.get(index) || []
      const nextTimers = activeTimers.filter(item => item !== timer)
      if (nextTimers.length) {
        gptMailRefreshTimers.set(index, nextTimers)
      } else {
        gptMailRefreshTimers.delete(index)
      }
      const provider = registerProviders.value[index]
      if (!provider || providerType(provider) !== 'gptmail') return
      void refreshGptMailPublicKey(index, provider, { reschedule })
    }, delay)
    return timer
  })
  if (timers.length) gptMailRefreshTimers.set(index, timers)
}

function gptMailStatusByIndex(index: number) {
  return gptMailState(index).data
}

function gptMailStatusBusy(index: number) {
  return gptMailState(index).loading
}

function gptMailStatusTone(index: number) {
  const state = gptMailState(index)
  if (state.loading) return 'info'
  if (state.error) return 'danger'
  if (!state.data) return 'muted'
  if (state.data.is_active === false) return 'warning'
  return 'success'
}

function gptMailStatusTitle(index: number, provider: RegisterProvider) {
  const state = gptMailState(index)
  if (state.loading) return '检测中'
  if (state.error) return '检测失败'
  if (!state.data) return providerUsesPublicGptMailKey(provider) ? '公共 Key' : '未检测'
  return state.data.is_active === false ? '不可用' : '可用'
}

function formatGptMailNumber(value: unknown) {
  const number = Number(value)
  if (!Number.isFinite(number)) return ''
  if (number < 0) return '不限'
  return new Intl.NumberFormat().format(number)
}

function formatGptMailDuration(seconds: unknown) {
  const total = Number(seconds)
  if (!Number.isFinite(total) || total <= 0) return ''
  if (total < 60) return `${Math.ceil(total)}s 后重置`
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  if (hours > 0) return `${hours}h ${minutes}m 后重置`
  return `${Math.max(1, minutes)}m 后重置`
}

function gptMailRemainingText(index: number) {
  const status = gptMailStatusByIndex(index)
  if (!status) return ''
  if (String(status.key_mode || '') === 'custom') {
    const remaining = formatGptMailNumber(status.remaining_total)
    const total = formatGptMailNumber(status.total_limit)
    if (remaining && total) return `${remaining} / ${total}`
    if (remaining) return remaining
  }
  return formatGptMailNumber(status.remaining_today ?? status.remaining_total)
}

function gptMailResetText(index: number) {
  const status = gptMailStatusByIndex(index)
  if (!status) return ''
  if (String(status.key_mode || '') === 'custom' && !status.reset_at && !status.seconds_until_reset) return ''
  const seconds = gptMailSecondsUntilReset(status)
  const countdown = formatGptMailDuration(seconds)
  if (countdown) return countdown
  if (seconds !== null && seconds <= 0) return '等待刷新'
  if (status.reset_at) return `${formatClock(status.reset_at)} 重置`
  return ''
}

function gptMailStatusHint(index: number, provider: RegisterProvider) {
  const state = gptMailState(index)
  if (state.error) return state.error
  if (provider.local_compose && !String(provider.default_domain || '').trim()) {
    return '本地拼接模式需要填写默认域名。'
  }
  if (provider.local_compose) {
    return '本地拼接会少调用一次生成邮箱接口；请确认默认域名当前可用。'
  }
  if (!state.data) {
    return providerUsesPublicGptMailKey(provider)
      ? '使用 GPTMail 公共测试 Key，启动注册时后端会自动获取并缓存。'
      : '填写自定义 Key 后可检测总额度和剩余额度。'
  }
  if (String(state.data.key_mode || provider.key_mode || '') === 'custom') {
    const totalUsed = formatGptMailNumber(state.data.total_usage)
    const totalLimit = formatGptMailNumber(state.data.total_limit)
    const totalRemaining = formatGptMailNumber(state.data.remaining_total)
    const checkedText = state.data.checked_at ? `检测于 ${formatClock(state.data.checked_at)}` : '状态已更新'
    const resetText = state.data.reset_at ? `重置时间 ${formatClock(state.data.reset_at)}` : '自定义 Key 未返回独立重置时间'
    if (totalUsed && totalLimit) {
      return `总计已用 ${totalUsed} / ${totalLimit}${totalRemaining ? `，剩余 ${totalRemaining}` : ''}，${checkedText}；${resetText}。`
    }
    if (totalRemaining) return `总剩余 ${totalRemaining}，${checkedText}；${resetText}。`
    return `${checkedText}；${resetText}。`
  }
  const used = formatGptMailNumber(state.data.used_today)
  const limit = formatGptMailNumber(state.data.daily_limit)
  if (used && limit) return `今日已用 ${used} / ${limit}，${state.data.checked_at ? `检测于 ${formatClock(state.data.checked_at)}` : '状态已更新'}。`
  return state.data.checked_at ? `状态已更新，检测于 ${formatClock(state.data.checked_at)}。` : '状态已更新。'
}

async function checkGptMailStatus(index: number, provider: RegisterProvider, options: GptMailCheckOptions = {}) {
  const previous = gptMailState(index).data
  setGptMailState(index, { ...gptMailState(index), loading: true, error: '' })
  try {
    const response = await registerApi.getGptMailStatus(sanitizeProvider(provider), options.force ?? true)
    setGptMailState(index, { loading: false, error: '', data: response.status })
    if (options.reschedule !== false) scheduleGptMailRefresh(index, response.status)
    if (!options.silent) toast.success('GPTMail 额度已更新')
  } catch (error: any) {
    const message = error?.message || '检测 GPTMail 额度失败'
    setGptMailState(index, { loading: false, error: message, data: previous })
    if (!options.silent) toast.error(message)
  }
}

async function refreshGptMailPublicKey(index: number, provider: RegisterProvider, options: GptMailCheckOptions = {}) {
  const previous = gptMailState(index).data
  try {
    const response = await registerApi.refreshGptMailKey(sanitizeProvider(provider), options.force ?? true)
    setGptMailState(index, { loading: false, error: '', data: response.status })
    if (options.reschedule !== false) scheduleGptMailRefresh(index, response.status)
  } catch (error: any) {
    const message = error?.message || '刷新 GPTMail 公共 Key 失败'
    setGptMailState(index, { loading: false, error: message, data: previous })
  }
}

function handleOutlookPoolAction(key: string) {
  if (key === 'retry_failed') {
    void retryFailedOutlookPool()
    return
  }
  if (key === 'retryable' || key === 'invalid' || key === 'unused' || key === 'all') {
    void resetOutlookPool(key)
  }
}

function addProvider() {
  if (!registerConfig.value) return
  const next = [...registerProviders.value, defaultProvider()]
  registerConfig.value.mail.providers = next
  const index = next.length - 1
  setProviderExpanded(providerKey(next[index], index), true)
}

async function deleteProvider(index: number) {
  if (!registerConfig.value || registerProviders.value.length <= 1) return
  const ok = await confirmDialog.ask({
    title: '删除邮箱来源',
    message: `确认删除邮箱来源 ${index + 1} 吗？`,
    confirmText: '删除',
  })
  if (!ok) return
  clearAllGptMailRefreshTimers()
  gptMailStatusStates.value = {}
  const next = registerProviders.value.filter((_, itemIndex) => itemIndex !== index)
  registerConfig.value.mail.providers = next
  pruneExpandedProviderKeys(next)
}

function arrayText(value: unknown) {
  if (Array.isArray(value)) return value.map(String).join('\n')
  return String(value || '')
}

function stringValue(value: unknown) {
  if (Array.isArray(value)) return value.join('\n')
  return String(value || '')
}

function applyRegisterConfig(config: LegacyRegisterConfig) {
  registerConfig.value = normalizeRegisterConfig(config)
  syncRegisterProxyControlsFromValue(registerConfig.value.proxy)
  pruneGptMailStates()
  pruneExpandedProviderKeys(registerConfig.value.mail.providers || [])
}

function syncRegisterProxyControlsFromValue(value: unknown) {
  const reference = parseProxyReference(value)
  customRegisterProxyInput.value = ''
  selectedRegisterProxyGroupId.value = ''
  if (reference.mode === 'group') {
    registerProxyMode.value = 'group'
    selectedRegisterProxyGroupId.value = reference.value
    return
  }
  if (reference.mode === 'direct') {
    registerProxyMode.value = 'direct'
    return
  }
  if (reference.mode === 'custom' || reference.mode === 'profile') {
    registerProxyMode.value = 'custom'
    customRegisterProxyInput.value = reference.mode === 'profile' ? String(value || '').trim() : reference.value
    return
  }
  registerProxyMode.value = 'global'
}

function setRegisterProxyMode(mode: string) {
  const nextMode = ['global', 'direct', 'group', 'custom'].includes(mode)
    ? mode as RegisterProxyMode
    : 'global'
  registerProxyMode.value = nextMode
  if (!registerConfig.value) return
  if (nextMode === 'global') {
    registerConfig.value.proxy = serializeProxyReference('global')
  } else if (nextMode === 'direct') {
    registerConfig.value.proxy = serializeProxyReference('direct')
  } else if (nextMode === 'group') {
    registerConfig.value.proxy = serializeProxyReference('group', selectedRegisterProxyGroupId.value)
  } else {
    registerConfig.value.proxy = serializeProxyReference('custom', customRegisterProxyInput.value)
  }
}

function selectRegisterProxyGroup(groupId: string) {
  selectedRegisterProxyGroupId.value = String(groupId || '').trim()
  registerProxyMode.value = 'group'
  if (registerConfig.value) {
    registerConfig.value.proxy = serializeProxyReference('group', selectedRegisterProxyGroupId.value)
  }
}

function setCustomRegisterProxyInput(value: string) {
  customRegisterProxyInput.value = String(value || '').trim()
  registerProxyMode.value = 'custom'
  if (registerConfig.value) {
    registerConfig.value.proxy = serializeProxyReference('custom', customRegisterProxyInput.value)
  }
}

function updateProxyPool(value: string) {
  if (!registerConfig.value) return
  registerConfig.value.proxy_pool = String(value || '')
    .split(/[\n,]/)
    .map(item => item.trim())
    .filter(Boolean)
}

function ensureScheduleConfig() {
  if (!registerConfig.value) return null
  if (!registerConfig.value.schedule) {
    registerConfig.value.schedule = normalizeScheduleConfig()
  }
  return registerConfig.value.schedule
}

function setScheduleEnabled(value: boolean | string | number) {
  const schedule = ensureScheduleConfig()
  if (!schedule) return
  schedule.enabled = value === true || value === 'true' || value === 1
}

function updateScheduleWindowsText(value: string) {
  const schedule = ensureScheduleConfig()
  if (!schedule) return
  schedule.windows_text = value
}

function formatScheduleWindows(windows?: RegisterScheduleWindow[] | null) {
  if (!Array.isArray(windows) || !windows.length) return ''
  return windows
    .map((item) => {
      const start = String(item?.start || '').trim()
      const end = String(item?.end || '').trim()
      if (!start || !end) return ''
      return `${start}-${end}`
    })
    .filter(Boolean)
    .join('\n')
}

function parseScheduleWindowsText(text: string): { windows: RegisterScheduleWindow[]; error?: string } {
  const lines = String(text || '')
    .split(/\n/)
    .map(item => item.trim())
    .filter(Boolean)
  if (!lines.length) return { windows: [] }

  const windows: RegisterScheduleWindow[] = []
  const hhmm = /^([01]\d|2[0-3]):([0-5]\d)$/
  for (const line of lines) {
    const match = line.match(/^(\d{1,2}:\d{2})\s*[-~～—–]\s*(\d{1,2}:\d{2})$/)
    if (!match) {
      return { windows: [], error: `时段格式无效：${line}（示例 02:00-03:00）` }
    }
    const start = normalizeClockToken(match[1])
    const end = normalizeClockToken(match[2])
    if (!hhmm.test(start) || !hhmm.test(end)) {
      return { windows: [], error: `时段时间无效：${line}（须为 HH:MM）` }
    }
    windows.push({ start, end })
  }
  return { windows }
}

function normalizeClockToken(value: string) {
  const [h, m] = String(value || '').split(':')
  const hour = String(Math.max(0, Math.min(23, Number(h) || 0))).padStart(2, '0')
  const minute = String(Math.max(0, Math.min(59, Number(m) || 0))).padStart(2, '0')
  return `${hour}:${minute}`
}

function formatNextWindow(value: RegisterScheduleConfig['next_window']) {
  if (!value) return ''
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'object') {
    const start = String(value.start || '').trim()
    const end = String(value.end || '').trim()
    if (start && end) return `${start}-${end}`
    if (start) return start
  }
  return ''
}

function updateProviderArray(index: number, key: 'domain' | 'subdomain', event: Event) {
  const provider = registerProviders.value[index]
  if (!provider) return
  const value = (event.target as HTMLTextAreaElement).value
  provider[key] = value.split(/[\n,]/).map(item => item.trim()).filter(Boolean)
}

function sanitizeProvider(provider: RegisterProvider): RegisterProvider {
  const type = providerType(provider)
  const output: RegisterProvider = providerHasKnownType(type) ? {} : { ...provider }

  if (providerHasKnownType(type)) {
    for (const key of providerKeysForType(type)) {
      if (provider[key] !== undefined) {
        output[key] = providerDraftValue(type, key, provider[key])
      }
    }
  }

  output.enable = provider.enable !== false
  output.schedule_enable = provider.schedule_enable === true

  delete output.mailboxes_count
  delete output.mailboxes_base_count
  delete output.mailboxes_alias_count
  delete output.mailboxes_preview
  delete output.mailboxes_stats
  delete output.mailboxes_parse_stats
  delete output.provider_ref
  return output
}

function legacyPayload(): Partial<LegacyRegisterConfig> | null {
  if (!registerConfig.value) return {}
  const scheduleSource = registerConfig.value.schedule || defaultScheduleConfig
  const scheduleEnabled = scheduleSource.enabled === true
  const windowsText = typeof scheduleSource.windows_text === 'string'
    ? scheduleSource.windows_text
    : formatScheduleWindows(scheduleSource.windows)
  const parsed = parseScheduleWindowsText(windowsText)
  if (scheduleEnabled) {
    if (parsed.error) {
      toast.error(parsed.error)
      return null
    }
    if (!parsed.windows.length) {
      toast.error('已启用定时抢注，请至少填写一个有效时段（HH:MM-HH:MM）')
      return null
    }
  }

  return {
    mail: {
      ...registerConfig.value.mail,
      providers: registerProviders.value.map(sanitizeProvider),
    },
    proxy: String(registerConfig.value.proxy || '').trim(),
    proxy_pool: Array.isArray(registerConfig.value.proxy_pool)
      ? registerConfig.value.proxy_pool.map(item => String(item || '').trim()).filter(Boolean)
      : [],
    max_relogin_retries: Math.max(0, Math.min(10, Number(registerConfig.value.max_relogin_retries ?? 3) || 0)),
    total: Math.max(1, Number(registerConfig.value.total) || 1),
    threads: Math.max(1, Number(registerConfig.value.threads) || 1),
    mode: (registerConfig.value.mode || 'total') as RegisterMode,
    target_quota: Math.max(1, Number(registerConfig.value.target_quota) || 1),
    target_available: Math.max(1, Number(registerConfig.value.target_available) || 1),
    check_interval: Math.max(1, Number(registerConfig.value.check_interval) || 5),
    schedule: {
      enabled: scheduleEnabled,
      windows: parsed.error ? [] : parsed.windows,
      threads: Math.max(1, Number(scheduleSource.threads ?? 10) || 10),
      max_relogin_retries: Math.max(0, Math.min(10, Number(scheduleSource.max_relogin_retries ?? 3) || 0)),
      preempt_minutes: Math.max(0, Number(scheduleSource.preempt_minutes ?? 5) || 0),
      drain_timeout_minutes: Math.max(0, Number(scheduleSource.drain_timeout_minutes ?? 15) || 0),
    },
  }
}

async function loadRegisterConfig(silent = false) {
  if (!silent) legacyLoading.value = true
  try {
    const response = await registerApi.getConfig()
    applyRegisterConfig(response.register)
  } catch (error: any) {
    if (!silent) toast.error(error?.message || '加载注册配置失败')
  } finally {
    if (!silent) legacyLoading.value = false
  }
}

async function loadProxyGroups() {
  try {
    const response = await proxyApi.listGroups()
    proxyGroups.value = Array.isArray(response.groups)
      ? response.groups.filter((group) => String(group?.id || '').trim())
      : []
  } catch {
    proxyGroups.value = []
  }
}

async function saveLegacyConfig() {
  if (!registerConfig.value) return
  const payload = legacyPayload()
  if (!payload) return
  legacySaving.value = true
  try {
    const response = await registerApi.updateConfig(payload)
    applyRegisterConfig(response.register)
    toast.success('注册配置已保存')
  } catch (error: any) {
    toast.error(error?.message || '保存注册配置失败')
  } finally {
    legacySaving.value = false
  }
}

async function toggleLegacyTask() {
  if (!registerConfig.value) return
  const starting = !registerConfig.value.enabled
  const ok = await confirmDialog.ask({
    title: starting ? '启动注册任务' : '停止注册任务',
    message: starting ? '启动前会先保存当前注册配置。确认启动吗？' : '确认请求停止当前注册任务吗？',
    confirmText: starting ? '启动' : '停止',
  })
  if (!ok) return
  legacySaving.value = true
  try {
    if (starting) {
      const payload = legacyPayload()
      if (!payload) {
        legacySaving.value = false
        return
      }
      await registerApi.updateConfig(payload)
    }
    const response = starting ? await registerApi.startLegacy() : await registerApi.stopLegacy()
    applyRegisterConfig(response.register)
    toast.success(starting ? '注册任务已启动' : '已请求停止注册任务')
    if (starting) startLiveUpdates()
  } catch (error: any) {
    toast.error(error?.message || '切换注册任务失败')
  } finally {
    legacySaving.value = false
  }
}

async function resetLegacyStats() {
  const ok = await confirmDialog.ask({
    title: '重置注册统计',
    message: '确认清空当前注册统计和实时日志吗？',
    confirmText: '重置',
  })
  if (!ok) return
  legacySaving.value = true
  try {
    const response = await registerApi.resetLegacy()
    applyRegisterConfig(response.register)
    toast.success('注册统计已重置')
  } catch (error: any) {
    toast.error(error?.message || '重置注册统计失败')
  } finally {
    legacySaving.value = false
  }
}

async function resetOutlookPool(scope: OutlookResetScope) {
  const copy: Record<OutlookResetScope, { title: string; message: string; confirmText: string }> = {
    retryable: {
      title: '释放占用/临时失败',
      message: '只清除 in_use 和 failed 状态，已成功使用和异常邮箱不会释放。',
      confirmText: '释放',
    },
    invalid: {
      title: '清除异常标记',
      message: '只清除 token_invalid 和 login_required 状态，不会修复 refresh_token。请确认这些邮箱已经重新授权或重新导入新的 refresh_token，否则会再次失败。',
      confirmText: '清除',
    },
    unused: {
      title: '清空未使用邮箱',
      message: '从已保存 Outlook 邮箱池中移除还没有状态记录的邮箱凭据。',
      confirmText: '清空',
    },
    all: {
      title: '重置全部邮箱状态',
      message: '清空 Outlook 邮箱池状态记录，所有已保存邮箱会重新变成可领取状态。',
      confirmText: '重置',
    },
  }
  const ok = await confirmDialog.ask(copy[scope])
  if (!ok) return
  legacySaving.value = true
  try {
    const response = await registerApi.resetOutlookPool(scope)
    applyRegisterConfig(response.register)
    toast.success('邮箱池状态已更新')
  } catch (error: any) {
    toast.error(error?.message || '更新邮箱池状态失败')
  } finally {
    legacySaving.value = false
  }
}

async function retryFailedOutlookPool() {
  const ok = await confirmDialog.ask({
    title: '重试临时失败邮箱',
    message: '会先释放 in_use 和 failed 状态，然后按当前注册任务配置启动。已成功使用和异常邮箱不会释放。',
    confirmText: '重试',
  })
  if (!ok) return
  legacySaving.value = true
  try {
    const resetResponse = await registerApi.resetOutlookPool('retryable')
    applyRegisterConfig(resetResponse.register)
    const startResponse = await registerApi.startLegacy()
    applyRegisterConfig(startResponse.register)
    toast.success('已释放临时失败邮箱并启动注册任务')
  } catch (error: any) {
    toast.error(error?.message || '重试临时失败邮箱失败')
  } finally {
    legacySaving.value = false
  }
}

function startLiveUpdates() {
  stopLiveUpdates()
  const token = getAuthToken()
  if (!token) {
    startPolling()
    return
  }
  try {
    const baseUrl = String(import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
    const source = new EventSource(`${baseUrl}/api/register/events?token=${encodeURIComponent(token)}`)
    source.onmessage = (event) => {
      try {
        applyRegisterConfig(JSON.parse(event.data) as LegacyRegisterConfig)
      } catch {
        // ignore malformed event payload
      }
    }
    source.onerror = () => {
      stopLiveUpdates()
      startPolling()
    }
    eventSource.value = source
  } catch {
    startPolling()
  }
}

function stopLiveUpdates() {
  if (eventSource.value) {
    eventSource.value.close()
    eventSource.value = null
  }
}

function startPolling() {
  stopPolling()
  pollTimer.value = window.setInterval(async () => {
    await loadRegisterConfig(true)
    if (!registerConfig.value?.enabled) {
      stopPolling()
    }
  }, 2000)
}

function stopPolling() {
  if (pollTimer.value) {
    window.clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

function startGptMailClock() {
  stopGptMailClock()
  gptMailClockNow.value = Date.now()
  gptMailClockTimer.value = window.setInterval(() => {
    gptMailClockNow.value = Date.now()
  }, 10_000)
}

function stopGptMailClock() {
  if (gptMailClockTimer.value) {
    window.clearInterval(gptMailClockTimer.value)
    gptMailClockTimer.value = null
  }
}

function formatClock(value?: string | null) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleTimeString()
}

function normalizeLogLevel(level?: string) {
  if (level === 'red' || level === 'error') return 'error'
  if (level === 'green' || level === 'success') return 'success'
  if (level === 'yellow' || level === 'warning') return 'warning'
  return 'info'
}

onMounted(async () => {
  startGptMailClock()
  await Promise.all([loadRegisterConfig(), loadProxyGroups()])
  startLiveUpdates()
})

onBeforeUnmount(() => {
  stopLiveUpdates()
  stopPolling()
  stopGptMailClock()
  clearAllGptMailRefreshTimers()
})
</script>

<style scoped>
.register-layout {
  display: grid;
  gap: 18px;
}

@media (min-width: 1280px) {
  .register-layout {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    align-items: start;
  }
}

.register-config-column,
.register-runtime-column {
  min-width: 0;
}

.register-config-column {
  display: grid;
  gap: 16px;
}

.register-runtime-column {
  display: grid;
  gap: 16px;
  position: sticky;
  top: 16px;
}

.register-runtime-section {
  display: grid;
  gap: 12px;
}

.register-runtime-log {
  min-width: 0;
}

.register-runtime-tips {
  display: grid;
  gap: 4px;
  color: hsl(var(--muted-foreground));
  line-height: 1.6;
}

.register-runtime-tips p {
  margin: 0;
}

.register-form-grid {
  display: grid;
  gap: 12px;
}

@media (min-width: 720px) {
  .register-form-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .register-field--full {
    grid-column: 1 / -1;
  }

  .register-form-grid--two {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .register-form-grid--mail {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .register-form-grid--schedule-params {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

.register-form-grid--schedule-params {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.register-form-grid--three {
  grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
}

.register-field {
  display: grid;
  min-width: 0;
  gap: 7px;
}

.register-label {
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

.register-proxy-hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: hsl(var(--muted-foreground));
}

.register-checkbox-field {
  display: flex;
  min-height: 62px;
  align-items: end;
  padding-bottom: 8px;
}

.register-checkbox-field--compact {
  min-height: 0;
  align-items: center;
  padding-bottom: 0;
}

.register-provider-list {
  display: grid;
  gap: 14px;
}

.register-provider-card {
  display: grid;
  gap: 14px;
}

.register-provider-card.is-collapsed {
  gap: 0;
}

.register-provider-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.register-provider-toggle {
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: center;
  gap: 10px;
  margin: 0;
  border: 0;
  background: transparent;
  padding: 0;
  text-align: left;
  color: inherit;
  cursor: pointer;
}

.register-provider-toggle:focus-visible {
  outline: 2px solid hsl(var(--ring) / 0.55);
  outline-offset: 2px;
  border-radius: 4px;
}

.register-provider-chevron {
  flex: 0 0 auto;
  width: 0.55rem;
  height: 0.55rem;
  border-right: 1.5px solid hsl(var(--muted-foreground));
  border-bottom: 1.5px solid hsl(var(--muted-foreground));
  transform: rotate(-45deg);
  transition: transform 0.15s ease;
}

.register-provider-chevron.is-open {
  transform: rotate(45deg);
  margin-top: -2px;
}

.register-provider-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 650;
  color: hsl(var(--foreground));
}

.register-provider-body {
  display: grid;
  gap: 14px;
}

.register-provider-message {
  margin-top: -2px;
}

.register-provider-section {
  display: grid;
  gap: 10px;
}

.register-provider-section--soft {
  border: 1px solid hsl(var(--border) / 0.82);
  border-radius: var(--radius);
  background: hsl(var(--muted) / 0.16);
  padding: 12px;
}

.register-provider-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: hsl(var(--muted-foreground));
  font-size: 11px;
  line-height: 1.25;
}

.register-provider-section-title::after {
  content: "";
  height: 1px;
  min-width: 24px;
  flex: 1;
  background: hsl(var(--border) / 0.72);
}

.register-provider-stack {
  display: grid;
  gap: 12px;
}

.register-preview-line {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.45;
  color: hsl(var(--muted-foreground));
}

.register-outlook-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.register-gptmail-panel {
  display: grid;
  gap: 8px;
}

.register-gptmail-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.register-provider-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.register-provider-actions--left {
  justify-content: flex-start;
}

.register-textarea {
  min-height: 80px;
  width: 100%;
  resize: vertical;
  border: 1px solid hsl(var(--border));
  border-radius: var(--radius);
  background: hsl(var(--card));
  padding: 10px 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 12px;
  line-height: 1.55;
  color: hsl(var(--foreground));
  outline: none;
}

.register-textarea--tall {
  min-height: 124px;
}

.register-textarea:focus {
  border-color: hsl(var(--ring));
  box-shadow: 0 0 0 2px hsl(var(--ring) / 0.14);
}

.register-textarea:disabled {
  cursor: not-allowed;
  opacity: 0.65;
}

.register-outlook-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.register-outlook-details {
  border-top: 1px solid hsl(var(--border) / 0.68);
  padding-top: 8px;
}

.register-outlook-details summary {
  cursor: pointer;
  width: fit-content;
  color: hsl(var(--muted-foreground));
  font-size: 12px;
  line-height: 1.4;
}

.register-outlook-details summary:hover {
  color: hsl(var(--foreground));
}

.register-outlook-detail-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-top: 8px;
}

.register-runtime-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

@media (max-width: 1279px) {
  .register-runtime-column {
    position: static;
  }
}

@media (max-width: 640px) {
  .register-provider-head {
    display: grid;
    align-items: start;
  }

  .register-provider-actions,
  .register-outlook-toolbar,
  .register-runtime-actions {
    grid-template-columns: 1fr;
    justify-content: flex-start;
  }

  .register-outlook-toolbar {
    display: grid;
  }

  .register-runtime-actions {
    display: grid;
  }
}
</style>
