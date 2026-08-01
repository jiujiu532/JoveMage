<template>
  <div class="relative space-y-8">
    <PagePanel class="space-y-5">
      <!-- 渠道 Tab：全部 | ChatGPT · N | Firefly · N；数据来自 channels.ts（将来 /api/channels） -->
      <ConsoleSegmentedTabs
        :model-value="sourceFilter"
        :options="channelTabOptions"
        aria-label="账号渠道"
        fit="content"
        @update:model-value="setSourceFilter"
      />

      <div class="accounts-toolbar">
        <div class="accounts-toolbar-row accounts-toolbar-row-main">
          <FilterToolbar class="accounts-toolbar-filters" :bordered="false">
            <Input
              :model-value="keyword"
              type="text"
              placeholder="搜索账号 ID / 邮箱 / Token / 类型 / 来源"
              block
              root-class="min-w-[14rem] flex-1 md:max-w-sm"
              @update:model-value="keyword = $event.trim()"
            />
            <GroupedSelectMenu
              v-model="statusFilter"
              :options="statusFilterOptions"
              placeholder="状态筛选"
              selected-indicator="none"
              aria-label="账号状态筛选"
            />
            <GroupedSelectMenu
              v-model="groupFilter"
              :options="groupFilterOptions"
              placeholder="账号组"
              selected-indicator="none"
              aria-label="账号组筛选"
            />
          </FilterToolbar>

          <div class="accounts-toolbar-summary">
            <AccountSelectionSummary
              :all-selected="allVisibleSelected"
              :total-count="accountListTotal"
              :selected-count="selectedCount"
              :view-mode="viewMode"
              @toggle-all="toggleSelectAllVisible"
              @update:view-mode="setViewMode"
            />
          </div>
        </div>

        <div class="accounts-toolbar-row accounts-toolbar-row-actions">
          <div class="accounts-toolbar-action-cluster">
            <FilterToolbar class="accounts-toolbar-group accounts-toolbar-group-ops" :bordered="false" gap="tight">
              <Button
                size="sm"
                variant="outline"
                :root-class="accountToolbarButtonClass"
                :disabled="accountGroupsLoading"
                @click="openAccountGroupsModal"
              >
                账号组管理
              </Button>
              <FloatingActionMenu
                label="导入 / 添加"
                :items="accountEntryItems"
                :disabled="importBusy"
                align="left"
                :trigger-class="accountToolbarMenuClass"
                @select="handleAccountEntryAction"
              />
              <FloatingActionMenu
                label="导出"
                :items="exportMenuItems"
                :disabled="exportBusy"
                align="left"
                :trigger-class="accountToolbarMenuClass"
                @select="handleExportAction"
              />
            </FilterToolbar>
          </div>

          <FilterToolbar class="accounts-toolbar-group accounts-toolbar-group-refresh" :bordered="false" gap="tight">
            <Button
              size="sm"
              variant="outline"
              :root-class="accountToolbarSecondaryClass"
              :disabled="loading"
              @click="loadData"
            >
              刷新列表
            </Button>
          </FilterToolbar>
        </div>
      </div>

      <PageLoadingState
        v-if="loading && filteredAccounts.length === 0"
        title="正在加载账号"
        description="读取账号列表、分组和分页状态。"
      />

      <!-- 紧凑：表格式 -->
      <TableShell v-else-if="effectiveViewMode === 'compact'">
        <table class="account-compact-table min-w-[1080px] w-full text-left text-sm">
          <thead>
            <tr>
              <th class="w-11">
                <Checkbox
                  :model-value="allVisibleSelected"
                  @update:model-value="toggleSelectAllVisible"
                />
              </th>
              <th>{{ sourceFilter === 'firefly' ? 'COOKIE' : 'TOKEN' }}</th>
              <th>类型</th>
              <th>渠道</th>
              <th>状态</th>
              <th>账户信息</th>
              <th class="table-num">创建时间</th>
              <th class="table-num">{{ sourceFilter === 'firefly' ? 'Credits' : '图片额度' }}</th>
              <th class="table-num">恢复时间</th>
              <th class="table-num">成功 / 失败</th>
              <th class="text-right">操作</th>
            </tr>
          </thead>
          <tbody class="text-sm text-foreground">
            <tr v-if="!loading && filteredAccounts.length === 0">
              <td colspan="11" class="py-6">
                <EmptyState
                  plain
                  title="暂无账号数据"
                  description="可以先导入 Access Token、Session JSON 或 CPA JSON 文件。"
                />
              </td>
            </tr>
            <tr
              v-for="item in pagedAccounts"
              :key="item.id"
              class="border-t border-border"
              :class="[rowClass(item), isSelected(item.id) ? 'is-selected' : '']"
            >
              <td class="align-middle">
                <Checkbox
                  :model-value="isSelected(item.id)"
                  :disabled="item.is_demo"
                  @update:model-value="(checked) => toggleSelect(item.id, checked)"
                />
              </td>
              <td class="align-middle">
                <button
                  type="button"
                  class="text-left"
                  title="点击复制完整 Token"
                  @click="copyAccountToken(item)"
                >
                  <StatusPill
                    :label="accountTokenPreview(item)"
                    tone-class="border-muted bg-muted/20 text-muted-foreground"
                    title="Access Token"
                    detail="点击复制完整 Token"
                    card-class="w-48"
                  />
                </button>
              </td>
              <td class="align-middle">
                <span class="account-compact-table__tag" :class="`account-compact-table__tag--${accountTypeTone(item)}`">
                  {{ accountTypeLabel(item) }}
                </span>
              </td>
              <td class="align-middle">
                <div class="flex items-center gap-1.5">
                  <ChannelBadge
                    :channel="accountChannelId(item)"
                    size="xs"
                  />
                  <span class="text-xs text-muted-foreground">{{ accountSourceLabel(item) }}</span>
                </div>
              </td>
              <td class="align-middle">
                <StatusDetailPill
                  :label="statusText(item)"
                  :tone-class="`${statusClass(item)} border-border`"
                  title="状态详情"
                  detail-label="状态说明"
                  raw-error-label="原始报错"
                  :card-class="accountStatusDetailCardClass"
                  :detail="accountStatusDetailText(item)"
                  :raw-error="statusRawError(item)"
                />
              </td>
              <td class="align-middle">
                <p class="max-w-[16rem] truncate text-sm font-medium leading-tight text-foreground">{{ accountPrimaryText(item) }}</p>
                <p class="mt-0.5 max-w-[16rem] truncate font-mono text-xs leading-tight text-muted-foreground">{{ accountSecondaryText(item) }}</p>
              </td>
              <td class="align-middle text-xs text-muted-foreground table-num">
                {{ accountCreatedText(item) }}
              </td>
              <td class="align-middle table-num">
                <div class="space-y-0.5">
                  <QuotaBadge :account="item" />
                  <p
                    v-if="accountCreditsHint(item)"
                    class="max-w-[8rem] truncate text-[11px] leading-tight text-muted-foreground"
                    :title="accountCreditsHint(item)"
                  >
                    {{ accountCreditsHint(item) }}
                  </p>
                </div>
              </td>
              <td class="align-middle text-xs text-muted-foreground table-num">
                {{ accountRestoreText(item) }}
              </td>
              <td class="align-middle table-num">
                <div class="font-mono text-sm tabular-nums">
                  <span class="text-emerald-600">{{ item.success_count || 0 }}</span>
                  <span class="mx-1 text-muted-foreground/60">/</span>
                  <span class="text-rose-600">{{ item.failure_count || 0 }}</span>
                </div>
              </td>
              <td class="text-right align-middle">
                <AccountActionButtons
                  :item="item"
                  :refreshing="refreshingAccountId === item.id"
                  :resetting="resettingAccountId === item.id"
                  :relogin-busy="reloginAccountId === item.id"
                  align="end"
                  @edit="openEditModal(item)"
                  @toggle-enabled="toggleEnabled(item)"
                  @refresh-token="refreshToken(item.id)"
                  @relogin="reloginAccount(item.id)"
                  @reset-state="resetAccountState(item.id)"
                  @remove="removeAccount(item.id)"
                />
              </td>
            </tr>
          </tbody>
        </table>
      </TableShell>

      <!-- 卡片：多列网格 -->
      <div v-else-if="effectiveViewMode === 'cards'" class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <div v-if="!loading && filteredAccounts.length === 0" class="col-span-full">
          <EmptyState
            plain
            title="暂无账号数据"
            description="可以先导入 Access Token、Session JSON 或 CPA JSON 文件。"
          />
        </div>

        <article
          v-for="item in pagedAccounts"
          :key="`${item.id}-card`"
          class="account-card-tile ui-card flex h-full flex-col transition-all"
          :class="[rowClass(item), isSelected(item.id) ? 'is-selected-anchor ring-2 ring-primary/30' : '']"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="flex min-w-0 items-start gap-2.5">
              <Checkbox
                class="mt-0.5"
                :model-value="isSelected(item.id)"
                :disabled="item.is_demo"
                @update:model-value="(checked) => toggleSelect(item.id, checked)"
              />
              <div class="min-w-0">
                <h3 class="truncate text-sm font-semibold leading-tight text-foreground">{{ accountPrimaryText(item) }}</h3>
                <p class="mt-0.5 truncate font-mono text-xs leading-tight text-muted-foreground">{{ accountSecondaryText(item) }}</p>
              </div>
            </div>
            <StatusDetailPill
              :label="statusText(item)"
              :tone-class="`${statusClass(item)} border-border`"
              title="状态详情"
              detail-label="状态说明"
              raw-error-label="原始报错"
              :card-class="accountStatusDetailCardClass"
              :detail="accountStatusDetailText(item)"
              :raw-error="statusRawError(item)"
            />
          </div>

          <div class="mt-2.5 flex flex-wrap items-center gap-1.5">
            <ChannelBadge :channel="accountChannelId(item)" size="xs" />
            <StatusPill
              :label="accountSourceText(item)"
              tone-class="border-cyan-500/40 bg-cyan-500/10 text-cyan-600"
            />
            <button
              type="button"
              class="text-left"
              title="点击复制完整 Token"
              @click="copyAccountToken(item)"
            >
              <StatusPill
                :label="accountTokenPreview(item)"
                tone-class="border-muted bg-muted/20 text-muted-foreground"
                title="Access Token"
                detail="点击复制完整 Token"
                card-class="w-48"
              />
            </button>
          </div>

          <div class="account-card-tile__metrics mt-3">
            <div class="account-card-tile__metric">
              <span class="account-card-tile__metric-label">图片额度</span>
              <span class="account-card-tile__metric-value account-card-tile__metric-value--quota table-num">
                {{ accountQuotaText(item) }}
              </span>
              <span
                v-if="accountCreditsHint(item)"
                class="mt-0.5 block max-w-full truncate text-[11px] text-muted-foreground"
                :title="accountCreditsHint(item)"
              >
                {{ accountCreditsHint(item) }}
              </span>
            </div>
            <div class="account-card-tile__metric">
              <span class="account-card-tile__metric-label">成功 / 失败</span>
              <span class="account-card-tile__metric-value font-mono tabular-nums">
                <span class="text-emerald-600">{{ item.success_count || 0 }}</span>
                <span class="mx-0.5 text-muted-foreground/60">/</span>
                <span class="text-rose-600">{{ item.failure_count || 0 }}</span>
              </span>
            </div>
            <div class="account-card-tile__metric">
              <span class="account-card-tile__metric-label">创建时间</span>
              <span class="account-card-tile__metric-value table-num">{{ accountCreatedText(item) }}</span>
            </div>
            <div class="account-card-tile__metric">
              <span class="account-card-tile__metric-label">恢复时间</span>
              <span class="account-card-tile__metric-value table-num">{{ accountRestoreText(item) }}</span>
            </div>
          </div>

          <div class="mt-3 flex justify-end border-t border-border/60 pt-2.5">
            <AccountActionButtons
              :item="item"
              :refreshing="refreshingAccountId === item.id"
              :resetting="resettingAccountId === item.id"
              :relogin-busy="reloginAccountId === item.id"
              align="end"
              @edit="openEditModal(item)"
              @toggle-enabled="toggleEnabled(item)"
              @refresh-token="refreshToken(item.id)"
              @relogin="reloginAccount(item.id)"
              @reset-state="resetAccountState(item.id)"
              @remove="removeAccount(item.id)"
            />
          </div>
        </article>
      </div>

      <!-- 单列 / 双列：流式条带 -->
      <div
        v-else
        class="account-stream-grid"
        :class="effectiveViewMode === 'double' ? 'account-stream-grid--double' : 'account-stream-grid--single'"
      >
        <div v-if="!loading && filteredAccounts.length === 0" class="col-span-full">
          <EmptyState
            plain
            title="暂无账号数据"
            description="可以先导入 Access Token、Session JSON 或 CPA JSON 文件。"
          />
        </div>

        <AccountStreamCard
          v-for="item in pagedAccounts"
          :key="`${item.id}-${effectiveViewMode}`"
          :item="item"
          :selected="isSelected(item.id)"
          :status-detail="accountStatusDetailText(item)"
          :status-card-class="accountStatusDetailCardClass"
          :refreshing="refreshingAccountId === item.id"
          :resetting="resettingAccountId === item.id"
          :relogin-busy="reloginAccountId === item.id"
          :density="effectiveViewMode === 'double' ? 'dense' : 'comfortable'"
          @toggle-select="(checked) => toggleSelect(item.id, checked)"
          @copy-token="copyAccountToken(item)"
          @edit="openEditModal(item)"
          @toggle-enabled="toggleEnabled(item)"
          @refresh-token="refreshToken(item.id)"
          @relogin="reloginAccount(item.id)"
          @reset-state="resetAccountState(item.id)"
          @remove="removeAccount(item.id)"
        />
      </div>

      <ListPagination
        v-model:page="currentPage"
        v-model:page-size="pageSize"
        :total-count="accountListTotal"
        :page-size-options="pageSizeOptions"
        unit="个账号"
        :disabled="loading"
      />
    </PagePanel>

    <AccountBulkBar
      :selected-count="selectedCount"
      :busy="batchBusy"
      :busy-label="batchActionLabel"
      :items="batchMenuItems"
      @select="handleBatchAction"
      @clear="clearSelection"
    />

    <ModalShell :open="showModal" max-width="44rem" :z-index="120">
            <ModalHeader :title="editingId ? '编辑账号' : '添加账号'" :bordered="false" compact @close="closeModal" />

            <ModalBody density="compact" class="space-y-3">
                <FormSection title="基础信息" surface="plain">
                  <div class="grid grid-cols-1 gap-2.5 md:grid-cols-4">
                    <label v-if="editingId" class="text-xs md:col-span-2">
                      <span class="ui-field-label">账号 ID</span>
                      <Input :model-value="form.id" disabled block />
                    </label>
                    <label class="text-xs">
                      <span class="ui-field-label">类型</span>
                      <Input
                        :model-value="form.type"
                        block
                        placeholder="free / Plus / Pro"
                        @update:model-value="form.type = $event.trim()"
                      />
                    </label>
                    <div class="text-xs">
                      <span class="ui-field-label">状态</span>
                      <GroupedSelectMenu
                        v-model="form.status"
                        :options="accountStatusOptions"
                        placeholder="状态"
                        selected-indicator="none"
                        aria-label="账号状态"
                        block
                      />
                    </div>
                  </div>
                </FormSection>

                <FormSection surface="plain">
                  <div class="space-y-3">
                    <template v-if="isFireflyForm">
                      <label class="block text-xs">
                        <span class="ui-field-label">Adobe Express Cookie（必填）</span>
                        <textarea
                          v-model.trim="form.cookie"
                          rows="4"
                          class="ui-textarea-sm font-mono"
                          placeholder="粘贴 new.express.adobe.com 登录后的完整 Cookie"
                        ></textarea>
                      </label>
                      <label class="block text-xs">
                        <span class="ui-field-label">Access Token（可选）</span>
                        <textarea
                          v-model.trim="form.access_token"
                          rows="2"
                          class="ui-textarea-sm font-mono"
                          placeholder="可留空，保存后由 Cookie 自动刷新 IMS token"
                          :disabled="!!editingId"
                        ></textarea>
                      </label>
                      <SurfaceBox tone="muted" density="compact" class="text-[11px] leading-5 text-muted-foreground">
                        Firefly 账号以 Cookie 为刷新源，不使用 ChatGPT 的 refresh_token / id_token；无密码字段。
                      </SurfaceBox>
                      <SurfaceBox
                        v-if="editingFireflyCreditsText"
                        tone="muted"
                        density="compact"
                        class="space-y-1"
                      >
                        <span class="ui-field-label">Credits（远端）</span>
                        <p class="font-mono text-xs text-foreground">{{ editingFireflyCreditsText }}</p>
                      </SurfaceBox>
                    </template>
                    <template v-else>
                      <label class="block text-xs">
                        <span class="ui-field-label">Access Token（必填）</span>
                        <textarea
                          v-model.trim="form.access_token"
                          rows="3"
                          class="ui-textarea-sm font-mono"
                          placeholder="粘贴完整 access token"
                          :disabled="!!editingId"
                        ></textarea>
                      </label>
                    </template>
                  </div>
                </FormSection>

                <FormSection title="调度属性" surface="plain">
                  <div class="grid grid-cols-1 gap-2 md:grid-cols-3">
                    <div class="text-xs">
                      <span class="ui-field-label">来源</span>
                      <GroupedSelectMenu
                        v-model="form.source_type"
                        :options="accountSourceTypeOptions"
                        placeholder="选择来源"
                        selected-indicator="none"
                        aria-label="账号来源"
                        block
                      />
                    </div>
                    <label class="text-xs">
                      <span class="ui-field-label">{{ isFireflyForm ? '本地额度（可选）' : '图片额度' }}</span>
                      <Input
                        :model-value="form.quota"
                        type="number"
                        block
                        :placeholder="isFireflyForm ? '留空，优先展示 credits' : '留空表示未知'"
                        @update:model-value="form.quota = $event.trim()"
                      />
                    </label>
                    <label class="text-xs">
                      <span class="ui-field-label">账号组</span>
                      <GroupedSelectMenu
                        v-model="form.group_id"
                        :options="accountGroupOptions"
                        :disabled="accountGroupsLoading"
                        aria-label="账号组"
                        selected-indicator="none"
                        block
                      />
                    </label>
                    <div class="space-y-2 text-xs md:col-span-3">
                      <div class="grid grid-cols-1 gap-2 md:grid-cols-[11rem_minmax(0,1fr)]">
                        <label>
                          <span class="ui-field-label">代理模式</span>
                          <GroupedSelectMenu
                            :model-value="proxyMode"
                            :options="accountProxyModeOptions"
                            aria-label="代理模式"
                            selected-indicator="none"
                            block
                            @update:model-value="setProxyMode"
                          />
                        </label>

                        <label v-if="proxyMode === 'group'">
                          <span class="ui-field-label">代理组（多节点）</span>
                          <GroupedSelectMenu
                            :model-value="selectedProxyGroupId"
                            :options="proxyGroupOptions"
                            :disabled="accountGroupsLoading"
                            aria-label="代理组"
                            selected-indicator="none"
                            block
                            @update:model-value="selectProxyGroup"
                          />
                        </label>

                        <label v-else-if="proxyMode === 'custom'">
                          <span class="ui-field-label">自定义代理</span>
                          <Input
                            :model-value="customProxyInput"
                            block
                            root-class="font-mono"
                            placeholder="http://127.0.0.1:7890"
                            @update:model-value="setCustomProxyInput"
                          />
                        </label>

                        <SurfaceBox v-else tone="muted" dashed density="compact" class="flex min-h-[3.25rem] items-center">
                          {{ proxyMode === 'direct' ? '该账号强制直连，不读取账号组或默认出口。' : '该账号不单独指定代理，会按账号组代理、默认出口顺序回退。' }}
                        </SurfaceBox>
                      </div>

                      <SurfaceBox tone="muted" density="compact" class="flex flex-wrap items-center justify-between gap-2">
                        <div class="min-w-0">
                          <span class="ui-field-label">当前代理</span>
                          <p class="mt-1 max-w-full truncate text-xs text-foreground" :title="accountProxyPreview">{{ accountProxyPreview }}</p>
                        </div>
                        <div class="flex flex-wrap items-center gap-2">
                          <Button
                            v-if="proxyMode === 'group'"
                            size="xs"
                            variant="outline"
                            root-class="min-w-24 justify-center"
                            :disabled="accountGroupsLoading"
                            @click="loadAccountGroups()"
                          >
                            {{ accountGroupsLoading ? '刷新中...' : '刷新代理组' }}
                          </Button>
                          <Button
                            v-if="proxyMode !== 'direct'"
                            size="xs"
                            variant="outline"
                            root-class="min-w-24 justify-center"
                            :disabled="proxyTesting || accountGroupsLoading"
                            @click="testAccountProxy"
                          >
                            {{ proxyTesting ? '测试中...' : '测试当前代理' }}
                          </Button>
                          <span v-else class="text-[11px] text-muted-foreground">直连模式无需测试出口</span>
                        </div>
                      </SurfaceBox>
                    </div>
                  </div>
                </FormSection>
            </ModalBody>

            <ModalFooter :bordered="false">
              <Button size="xs" variant="primary" root-class="min-w-14 justify-center" :disabled="saving" @click="saveAccount">
                {{ saving ? '保存中...' : '保存' }}
              </Button>
            </ModalFooter>
    </ModalShell>

    <ModalShell :open="showAccountGroupsModal" max-width="58rem" :z-index="130">
            <ModalHeader
              title="账号组管理"
              subtitle="先创建账号组，再在账号列表勾选账号批量绑定。"
              :close-disabled="accountGroupSaving"
              compact
              @close="closeAccountGroupsModal"
            />

            <div class="grid grid-cols-1 gap-0 md:grid-cols-[18rem_1fr]">
              <div class="border-b border-border bg-muted/20 p-4 md:border-b-0 md:border-r">
                <div class="space-y-3">
                  <p class="text-sm font-medium text-foreground">
                    {{ editingAccountGroupId ? '编辑账号组' : '新建账号组' }}
                  </p>

                  <label class="block text-xs">
                    <span class="ui-field-label">账号组名称</span>
                    <Input
                      :model-value="accountGroupForm.name"
                      block
                      placeholder="高额度账号 / Codex / 手动 Token"
                      @update:model-value="accountGroupForm.name = $event.trim()"
                    />
                  </label>

                  <div class="space-y-2 text-xs">
                    <label class="block">
                      <span class="ui-field-label">默认出口</span>
                      <GroupedSelectMenu
                        :model-value="accountGroupProxyMode"
                        :options="accountProxyModeOptions"
                        aria-label="账号组默认代理模式"
                        selected-indicator="none"
                        block
                        @update:model-value="setAccountGroupProxyMode"
                      />
                    </label>

                    <label v-if="accountGroupProxyMode === 'group'" class="block">
                      <span class="ui-field-label">代理组（多节点）</span>
                      <GroupedSelectMenu
                        :model-value="selectedAccountGroupProxyGroupId"
                        :options="accountGroupProxyOptions"
                        :disabled="accountGroupsLoading"
                        aria-label="账号组默认代理组"
                        selected-indicator="none"
                        block
                        @update:model-value="selectAccountGroupProxyGroup"
                      />
                    </label>

                    <label v-else-if="accountGroupProxyMode === 'custom'" class="block">
                      <span class="ui-field-label">自定义代理</span>
                      <Input
                        :model-value="accountGroupCustomProxyInput"
                        block
                        root-class="font-mono"
                        placeholder="http://127.0.0.1:7890"
                        @update:model-value="setAccountGroupCustomProxyInput"
                      />
                    </label>

                    <SurfaceBox v-else tone="muted" dashed density="compact" class="min-h-[2.75rem]">
                      {{ accountGroupProxyMode === 'direct' ? '该账号组强制直连，组内账号不会回退默认出口。' : '账号组不单独指定代理，组内账号会继续回退默认出口。' }}
                    </SurfaceBox>

                    <SurfaceBox tone="muted" density="compact">
                      <span class="ui-field-label">当前代理</span>
                      <p class="mt-1 truncate text-xs text-foreground" :title="accountGroupProxyPreview">{{ accountGroupProxyPreview }}</p>
                    </SurfaceBox>
                  </div>

                  <SurfaceBox tag="label" density="compact" class="flex items-center gap-2">
                    <Checkbox
                      :model-value="accountGroupForm.enabled"
                      @update:model-value="accountGroupForm.enabled = Boolean($event)"
                    />
                    启用账号组
                  </SurfaceBox>

                  <label class="block text-xs">
                    <span class="ui-field-label">备注</span>
                    <textarea
                      v-model.trim="accountGroupForm.notes"
                      rows="3"
                      class="ui-textarea-sm"
                      placeholder="例如：高额度账号默认走香港代理池"
                    ></textarea>
                  </label>

                  <Button size="sm" variant="primary" root-class="w-full justify-center" :disabled="accountGroupSaving" @click="saveAccountGroup">
                    {{ accountGroupSaving ? '保存中...' : editingAccountGroupId ? '保存账号组' : '创建账号组' }}
                  </Button>
                </div>
              </div>

              <div class="max-h-[32rem] overflow-y-auto p-4">
                <StateBlock v-if="accountGroupRows.length === 0" dashed>
                  还没有账号组。先在左侧创建，比如高额度账号、Codex、手动 Token。
                </StateBlock>

                <div v-else class="space-y-2">
                  <InfoCard
                    v-for="group in accountGroupRows"
                    :key="group.id"
                    tag="article"
                    density="compact"
                  >
                    <div class="flex flex-wrap items-start justify-between gap-3">
                      <div class="min-w-0">
                        <div class="flex flex-wrap items-center gap-2">
                          <p class="font-medium text-foreground">{{ group.name }}</p>
                          <StateBadge :tone="group.enabled ? 'success' : 'muted'" size="xs">
                            {{ group.enabled ? '启用' : '停用' }}
                          </StateBadge>
                        </div>
                        <p class="mt-1 text-xs text-muted-foreground">
                          {{ group.account_count }} 个账号 · 默认出口：{{ group.proxy_label }}
                        </p>
                        <p v-if="group.notes" class="mt-1 line-clamp-2 text-xs text-muted-foreground">{{ group.notes }}</p>
                      </div>

                      <div class="flex shrink-0 items-center gap-2">
                        <Button size="xs" variant="outline" :disabled="accountGroupSaving" @click="editAccountGroup(group.raw)">
                          编辑
                        </Button>
                        <Button size="xs" variant="outline" root-class="text-rose-600" :disabled="accountGroupSaving" @click="deleteAccountGroup(group.raw)">
                          删除
                        </Button>
                      </div>
                    </div>
                  </InfoCard>
                </div>
              </div>
            </div>
    </ModalShell>

    <ModalShell :open="showImportModal" max-width="58rem" :z-index="120">
            <ModalHeader title="导入账号" :close-disabled="importModalBusy" compact @close="closeImportModal" />

            <div class="grid grid-cols-1 gap-0 md:grid-cols-[15rem_1fr]">
              <div class="border-b border-border bg-muted/20 p-3 md:border-b-0 md:border-r">
                <div class="space-y-1">
                  <button
                    v-for="option in importModeOptions"
                    :key="option.value"
                    type="button"
                    class="w-full rounded-sm px-3 py-2 text-left text-sm transition-colors"
                    :class="importMode === option.value ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-card hover:text-foreground'"
                    :disabled="importModalBusy"
                    @click="setImportMode(option.value)"
                  >
                    {{ option.label }}
                  </button>
                </div>
              </div>

              <div class="min-h-[26rem] p-4">
                <div v-if="importMode === 'access_token'" class="space-y-3">
                  <ImportModePanel
                    title="导入 Access Token"
                    description="支持直接粘贴，一行一个；也支持从 TXT 文件读取，一行一个。"
                  />
                  <textarea
                    v-model.trim="manualTokenText"
                    rows="10"
                    class="ui-textarea-sm font-mono"
                    placeholder="一行一个 access token"
                  ></textarea>
                  <div class="flex flex-wrap justify-end gap-2">
                    <Button size="xs" variant="outline" :disabled="importBusy" @click="openManualTokenFile">
                      读取 TXT 文件
                    </Button>
                    <Button size="xs" variant="primary" :disabled="importBusy || !manualTokenText.trim()" @click="importManualTokenText">
                      {{ importBusy ? '导入中...' : '开始导入' }}
                    </Button>
                  </div>
                </div>

                <div v-else-if="importMode === 'session_json'" class="space-y-3">
                  <ImportModePanel
                    title="导入 Session JSON"
                    description="从 chatgpt.com 的 session 接口复制完整 JSON，自动提取 accessToken。"
                  />
                  <textarea v-model.trim="sessionJsonText" rows="12" class="ui-textarea-sm font-mono" placeholder="粘贴完整 session JSON"></textarea>
                  <div class="flex justify-end">
                    <Button size="xs" variant="primary" :disabled="importBusy || !sessionJsonText.trim()" @click="importSessionJson">
                      {{ importBusy ? '导入中...' : '开始导入' }}
                    </Button>
                  </div>
                </div>

                <div v-else-if="importMode === 'cpa_json'" class="space-y-3">
                  <ImportModePanel
                    title="导入 CPA JSON 文件"
                    description="支持一次多选多个本地 JSON 文件，逐个读取对象里的 access_token 后导入。"
                  />
                  <StateBlock dashed compact>
                    <Button size="sm" variant="outline" :disabled="importBusy" @click="openCPAFileDialog">
                      选择 CPA JSON 文件
                    </Button>
                  </StateBlock>
                </div>

                <div v-else-if="importMode === 'remote_cpa'" class="space-y-3">
                  <RemoteAccountImportPanel
                    mode="cpa"
                    @busy-change="remoteImportBusy = $event"
                    @imported="handleRemoteImportDone"
                  />
                </div>

                <div v-else-if="importMode === 'sub2api'" class="space-y-3">
                  <RemoteAccountImportPanel
                    mode="sub2api"
                    @busy-change="remoteImportBusy = $event"
                    @imported="handleRemoteImportDone"
                  />
                </div>
              </div>
            </div>
    </ModalShell>

    <OperationProgressModal
      :open="showRefreshProgress"
      :title="refreshProgressTitle || '刷新账号信息和额度'"
      :total="refreshProgress?.total || 0"
      :current="refreshProgress?.processed || 0"
      :error="refreshProgress?.error || ''"
      :busy="batchBusy && !refreshProgress?.done"
      :can-cancel="canStopRefreshProgress && !bulkStopRequested"
      :z-index="140"
      @close="closeRefreshProgress"
      @cancel="requestStopRefreshProgress"
    >
      <template #metrics>
        <MetricStrip :items="refreshProgressItems" columns-class="grid-cols-2" density="compact" />
      </template>
    </OperationProgressModal>

    <input ref="manualTokenFileInputRef" type="file" accept=".txt,text/plain" class="hidden" @change="handleManualTokenFileChange" />
    <input ref="cpaFileInputRef" type="file" accept=".json,application/json" multiple class="hidden" @change="handleCPAFileChange" />
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, ref } from 'vue'
import { Button, Checkbox, EmptyState, Input, StatusDetailPill, StatusPill } from 'nanocat-ui'
import type { ActionMenuItem } from 'nanocat-ui'
import AccountActionButtons from '@/components/ai/AccountActionButtons.vue'
import AccountBulkBar from '@/components/ai/AccountBulkBar.vue'
import AccountSelectionSummary from '@/components/ai/AccountSelectionSummary.vue'
import AccountStreamCard from '@/components/ai/AccountStreamCard.vue'
import ChannelBadge from '@/components/ai/ChannelBadge.vue'
import ConsoleSegmentedTabs from '@/components/ai/ConsoleSegmentedTabs.vue'
import FilterToolbar from '@/components/ai/FilterToolbar.vue'
import FloatingActionMenu from '@/components/ai/FloatingActionMenu.vue'
import FormSection from '@/components/ai/FormSection.vue'
import ImportModePanel from '@/components/ai/ImportModePanel.vue'
import InfoCard from '@/components/ai/InfoCard.vue'
import ListPagination from '@/components/ai/ListPagination.vue'
import MetricStrip from '@/components/ai/MetricStrip.vue'
import ModalBody from '@/components/ai/ModalBody.vue'
import ModalFooter from '@/components/ai/ModalFooter.vue'
import ModalHeader from '@/components/ai/ModalHeader.vue'
import ModalShell from '@/components/ai/ModalShell.vue'
import PageLoadingState from '@/components/ai/PageLoadingState.vue'
import PagePanel from '@/components/ai/PagePanel.vue'
import QuotaBadge from '@/components/ai/QuotaBadge.vue'
import StateBadge from '@/components/ai/StateBadge.vue'
import StateBlock from '@/components/ai/StateBlock.vue'
import SurfaceBox from '@/components/ai/SurfaceBox.vue'
import TableShell from '@/components/ai/TableShell.vue'
import { actionMenuGroups } from '@/components/ai/menuItems'
import GroupedSelectMenu from '@/components/ui/GroupedSelectMenu.vue'
import type { Account } from '@/api/accounts'
import { parseProxyReference } from '@/api/proxy'
import { resolveAccountChannelId } from '@/config/channels'
import { useAccountsPage, type AccountImportMode } from './accounts/useAccountsPage'
import {
  accountCreatedText,
  accountCreditsText,
  accountPrimaryText,
  accountProxyText,
  accountQuotaText,
  accountRestoreText,
  accountSecondaryText,
  accountSourceText,
  accountTokenPreview,
  rowClass,
  statusClass,
  statusRawError,
  statusReason,
  statusText,
} from './accounts/viewUtils'

const RemoteAccountImportPanel = defineAsyncComponent(() => import('@/components/ai/RemoteAccountImportPanel.vue'))
const OperationProgressModal = defineAsyncComponent(() => import('@/components/ai/OperationProgressModal.vue'))

const {
  loading,
  saving,
  showModal,
  keyword,
  statusFilter,
  groupFilter,
  sourceFilter,
  statusFilterOptions,
  channelTabOptions,
  setSourceFilter,
  groupFilterOptions,
  editingId,
  accounts,
  accountListTotal,
  accountAllTotal,
  selectedCount,
  allVisibleSelected,
  currentPage,
  pageSize,
  pageSizeOptions,
  batchBusy,
  batchActionLabel,
  viewMode,
  effectiveViewMode,
  refreshingAccountId,
  resettingAccountId,
  reloginAccountId,
  importBusy,
  exportBusy,
  showImportModal,
  importMode,
  importModeOptions,
  manualTokenText,
  sessionJsonText,
  accountGroups,
  proxyGroups,
  accountGroupsLoading,
  showAccountGroupsModal,
  accountGroupSaving,
  editingAccountGroupId,
  accountGroupForm,
  accountGroupOptions,
  accountGroupProxyOptions,
  bindAccountGroupOptions,
  selectedBindGroupId,
  proxyTesting,
  proxyMode,
  accountGroupProxyMode,
  accountProxyModeOptions,
  proxyGroupOptions,
  selectedProxyGroupId,
  customProxyInput,
  selectedAccountGroupProxyGroupId,
  accountGroupCustomProxyInput,
  accountProxyPreview,
  accountGroupProxyPreview,
  showRefreshProgress,
  refreshProgressTitle,
  refreshProgress,
  refreshProgressMetricLabel,
  refreshProgressMetricValue,
  refreshProgressStatusText,
  canStopRefreshProgress,
  bulkStopRequested,
  accountStatusOptions,
  accountSourceTypeOptions,
  isFireflyForm,
  editingFireflyCreditsText,
  form,
  filteredAccounts,
  pagedAccounts,
  loadData,
  loadAccountGroups,
  setViewMode,
  isSelected,
  toggleSelect,
  clearSelection,
  toggleSelectAllVisible,
  setImportMode,
  openImportModal,
  closeImportModal,
  testAccountProxy,
  openAccountGroupsModal,
  closeAccountGroupsModal,
  resetAccountGroupForm,
  editAccountGroup,
  saveAccountGroup,
  deleteAccountGroup,
  setProxyMode,
  selectProxyGroup,
  setCustomProxyInput,
  setAccountGroupProxyMode,
  selectAccountGroupProxyGroup,
  setAccountGroupCustomProxyInput,
  importManualTokenText,
  importTokenTextFile,
  importSessionJson,
  importLocalCPAFiles,
  requestStopRefreshProgress,
  closeRefreshProgress,
  copyAccountToken,
  openCreateModal,
  openEditModal,
  closeModal,
  saveAccount,
  toggleEnabled,
  refreshToken,
  reloginAccount,
  resetAccountState,
  removeAccount,
  runBulkAction,
  bindSelectedAccountsToGroup,
  exportAccounts,
} = useAccountsPage()

type BatchAction = 'refresh' | 'reset' | 'enable' | 'disable' | 'delete'
type AccountActionMenuItem = ActionMenuItem & {
  children?: AccountActionMenuItem[]
}

const manualTokenFileInputRef = ref<HTMLInputElement | null>(null)
const cpaFileInputRef = ref<HTMLInputElement | null>(null)
const remoteImportBusy = ref(false)
const accountToolbarMenuClass = 'shrink-0 whitespace-nowrap'
const accountToolbarButtonClass = 'shrink-0 whitespace-nowrap justify-between gap-2'
const accountStatusDetailCardClass = 'w-72 account-status-detail-card'
const accountToolbarSecondaryClass = `${accountToolbarButtonClass} text-muted-foreground`
const importModalBusy = computed(() => importBusy.value || remoteImportBusy.value)

const accountGroupNameMap = computed(() => new Map(
  accountGroups.value.map((group) => [group.id, group.name || group.id]),
))

const accountGroupRows = computed(() => accountGroups.value.map((group) => {
  const legacyProxyGroupId = String(group.proxy_group_id || '').trim()
  const proxyReference = parseProxyReference(group.proxy || (legacyProxyGroupId ? `group:${legacyProxyGroupId}` : ''))
  const proxyGroup = proxyReference.mode === 'group'
    ? proxyGroups.value.find((item) => item.id === proxyReference.value)
    : null
  const proxyLabel = (() => {
    if (proxyReference.mode === 'global') return '使用默认出口'
    if (proxyReference.mode === 'direct') return '强制直连'
    if (proxyReference.mode === 'group') return `代理组：${proxyGroup?.name || proxyReference.value || '-'}`
    if (proxyReference.mode === 'profile') return `历史代理：${proxyReference.value || '-'}`
    return `自定义代理：${proxyReference.value || '-'}`
  })()
  return {
    ...group,
    raw: group,
    name: group.name || group.id,
    account_count: Number(group.account_count || 0),
    proxy_label: proxyLabel,
  }
}))

function accountGroupLabel(groupId: string | undefined) {
  const id = String(groupId || '').trim()
  if (!id) return '未分组'
  return accountGroupNameMap.value.get(id) || id
}

function accountStatusDetailText(item: Account) {
  return [
    statusReason(item),
    `账号组：${accountGroupLabel(item.group_id)}`,
    `代理：${accountProxyText(item)}`,
  ].filter(Boolean).join('\n')
}

function accountTypeLabel(item: Account) {
  return String(item.type || '').trim() || 'free'
}

type AccountTypeTone = 'plus' | 'team' | 'free'

function accountTypeTone(item: Account): AccountTypeTone {
  const value = String(item.type || '').trim().toLowerCase()
  if (value === 'plus' || value === 'pro' || value === 'premium') return 'plus'
  if (value === 'team' || value === 'enterprise' || value === 'business') return 'team'
  return 'free'
}

function accountSourceLabel(item: Account) {
  const source = String(item.source_type || '').trim() || 'web'
  if (source === 'firefly') return 'Firefly'
  return source
}

function accountChannelId(item: Account) {
  return resolveAccountChannelId(item.source_type)
}

function accountCreditsHint(item: Account) {
  return accountCreditsText(item)
}

const refreshProgressItems = computed(() => [
  {
    key: 'metric',
    label: refreshProgressMetricLabel.value,
    value: refreshProgressMetricValue.value,
  },
  {
    key: 'status',
    label: '状态',
    value: refreshProgressStatusText.value,
  },
])

const bindAccountGroupBatchItems = computed<AccountActionMenuItem[]>(() => {
  const disabled = selectedCount.value === 0 || accountGroupsLoading.value
  const normalOptions = bindAccountGroupOptions.value.filter((option) => option.value && option.value !== '__ungrouped__')
  const ungroupedOptions = bindAccountGroupOptions.value.filter((option) => option.value === '__ungrouped__')
  const children = actionMenuGroups<AccountActionMenuItem>(
    normalOptions.map((option) => ({
      key: `bind_group:${option.value}`,
      label: `绑定到 ${option.label}`,
      disabled,
    })),
    ungroupedOptions.map((option) => ({
      key: `bind_group:${option.value}`,
      label: option.label,
      disabled,
    })),
  )

  return [{
    key: 'bind_group_menu',
    label: '绑定分组',
    disabled: disabled || children.length === 0,
    children,
  }]
})

const importActionKeys = new Set<AccountImportMode>([
  'access_token',
  'session_json',
  'cpa_json',
  'remote_cpa',
  'sub2api',
])

const accountEntryItems = computed<ActionMenuItem[]>(() => actionMenuGroups(
  [
    { key: 'create', label: '手动添加账号' },
  ],
  [
    { key: 'access_token', label: '导入 Access Token' },
    { key: 'session_json', label: '导入 Session JSON' },
    { key: 'cpa_json', label: '导入 CPA JSON 文件' },
    { key: 'remote_cpa', label: '从远程 CPA 服务器导入' },
    { key: 'sub2api', label: '从 Sub2API 服务器导入' },
  ],
))

const exportMenuItems = computed<ActionMenuItem[]>(() => actionMenuGroups(
  [
    {
      key: 'selected',
      label: `导出选中${selectedCount.value ? ` (${selectedCount.value})` : ''}`,
      disabled: selectedCount.value === 0,
    },
  ],
  [
    {
      key: 'all',
      label: '导出全部',
      disabled: accountAllTotal.value === 0,
    },
  ],
))

const batchMenuItems = computed<AccountActionMenuItem[]>(() => actionMenuGroups<AccountActionMenuItem>(
  [
    { key: 'refresh', label: '批量刷新账号信息和额度' },
    { key: 'relogin', label: '批量重新登录' },
    { key: 'reset', label: '批量重置' },
  ],
  bindAccountGroupBatchItems.value,
  [
    { key: 'enable', label: '批量启用' },
    { key: 'disable', label: '批量禁用' },
    { key: 'delete', label: '批量删除', danger: true },
  ],
))

async function handleBatchAction(action: string) {
  if (action.startsWith('bind_group:')) {
    selectedBindGroupId.value = action.slice('bind_group:'.length)
    await bindSelectedAccountsToGroup()
    return
  }
  await runBulkAction(action as BatchAction)
}

function handleAccountEntryAction(key: string) {
  if (key === 'create') {
    openCreateModal()
    return
  }
  if (importActionKeys.has(key as AccountImportMode)) {
    openImportModal(key as AccountImportMode)
  }
}

async function handleExportAction(key: string) {
  if (key === 'selected') {
    await handleExportSelected()
    return
  }
  if (key === 'all') {
    await handleExportAll()
  }
}

async function handleExportSelected() {
  await exportAccounts('selected')
}

async function handleExportAll() {
  await exportAccounts('all')
}

function openManualTokenFile() {
  if (!manualTokenFileInputRef.value || importBusy.value) return
  manualTokenFileInputRef.value.value = ''
  manualTokenFileInputRef.value.click()
}

async function handleManualTokenFileChange(event: Event) {
  const target = event.target as HTMLInputElement | null
  const file = target?.files?.[0]
  await importTokenTextFile(file)
  if (target) target.value = ''
}

function openCPAFileDialog() {
  if (!cpaFileInputRef.value || importBusy.value) return
  cpaFileInputRef.value.value = ''
  cpaFileInputRef.value.click()
}

async function handleCPAFileChange(event: Event) {
  const target = event.target as HTMLInputElement | null
  await importLocalCPAFiles(target?.files)
  if (target) target.value = ''
}

function handleRemoteImportDone() {
  void loadData({ silentErrorToast: true })
}
</script>

<style scoped>
.accounts-toolbar {
  display: flex;
  flex-direction: column;
  gap: 12px;
  /* 与下方账号列表拉开距离 */
  margin-bottom: 6px;
  padding-bottom: 16px;
  border-bottom: 2px solid hsl(var(--border) / 0.5);
}

.accounts-toolbar-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.accounts-toolbar-row-main {
  justify-content: space-between;
}

.accounts-toolbar-row-actions {
  align-items: flex-start;
  justify-content: space-between;
  padding-top: 10px;
  border-top: 1px solid hsl(var(--border) / 0.62);
}

.accounts-toolbar-filters {
  min-width: min(100%, 34rem);
  flex: 1 1 34rem;
}

.accounts-toolbar-summary {
  display: flex;
  flex: 0 0 auto;
  justify-content: flex-end;
}

.accounts-toolbar-group {
  min-width: 0;
}

.accounts-toolbar-action-cluster {
  display: flex;
  min-width: 0;
  flex: 1 1 auto;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
}

.accounts-toolbar-group-ops {
  flex: 0 1 auto;
}

.accounts-toolbar-group-refresh {
  margin-left: auto;
  justify-content: flex-end;
}

/* 与 md 断点对齐：<768（max-width:767 = mqDown(md)） */
@media (max-width: 767px) {
  .accounts-toolbar {
    gap: 10px;
    padding-bottom: 12px;
  }

  .accounts-toolbar-row-main {
    flex-direction: column;
    align-items: stretch;
  }

  .accounts-toolbar-filters {
    min-width: 0;
    flex: 1 1 auto;
    width: 100%;
  }

  .accounts-toolbar-summary {
    justify-content: flex-start;
    width: 100%;
  }

  .accounts-toolbar-row-actions {
    flex-direction: column;
    gap: 8px;
  }

  .accounts-toolbar-group-refresh {
    margin-left: 0;
    width: 100%;
    justify-content: flex-start;
  }
}

.account-compact-table {
  border-collapse: separate;
  border-spacing: 0;
}

.account-compact-table th {
  padding: 0.55rem 0.9rem 0.55rem 0;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: hsl(var(--muted-foreground));
  border-bottom: 2px solid var(--bauhaus-ink, #2d2d2d);
  white-space: nowrap;
}

.account-compact-table th:first-child,
.account-compact-table td:first-child {
  padding-left: 0.2rem;
}

.account-compact-table td {
  padding: 0.6rem 0.9rem 0.6rem 0;
  vertical-align: middle;
}

.account-compact-table tbody tr {
  transition: background-color 0.12s ease;
}

.account-compact-table tbody tr:hover {
  background: color-mix(in srgb, var(--bauhaus-postit, #f4e7c4) 22%, transparent);
}

.account-compact-table tbody tr.is-selected {
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 8%, transparent);
}

.account-compact-table__tag {
  display: inline-block;
  padding: 0.15rem 0.45rem;
  border: 1.5px solid color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 40%, transparent);
  border-radius: var(--radius, 0.125rem);
  background: color-mix(in srgb, var(--bauhaus-card, #fff) 60%, transparent);
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  line-height: 1.2;
  color: hsl(var(--foreground));
  white-space: nowrap;
}

/* 类型徽章：付费=蓝、团队=紫、免费=墨 */
.account-compact-table__tag--plus {
  border-color: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 45%, transparent);
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 13%, transparent);
  color: var(--bauhaus-blue, #2d5da1);
}

.account-compact-table__tag--team {
  border-color: color-mix(in srgb, #6a4c93 42%, transparent);
  background: color-mix(in srgb, #6a4c93 12%, transparent);
  color: #5d4184;
}

.account-compact-table__tag--free {
  border-color: color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 32%, transparent);
  background: color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 6%, transparent);
  color: hsl(var(--muted-foreground));
}

html[data-theme='dark'] .account-compact-table__tag--team {
  color: #b7a8d6;
}

.account-stream-grid {
  display: grid;
  gap: 0.75rem;
}

.account-stream-grid--single {
  grid-template-columns: minmax(0, 1fr);
}

.account-stream-grid--double {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.account-card-tile {
  border-width: 2px;
  border-color: var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius, 0.125rem);
  box-shadow: var(--shadow-hard-sm, 2px 2px 0 0 var(--bauhaus-ink, #2d2d2d));
}

.account-card-tile:hover {
  transform: translate(-1px, -1px);
  box-shadow: var(--shadow-hard, 3px 3px 0 0 var(--bauhaus-ink, #2d2d2d));
}

.account-card-tile__metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.5rem 0.75rem;
  border: 1.5px solid color-mix(in srgb, var(--bauhaus-ink, #2d2d2d) 35%, transparent);
  border-radius: var(--radius, 0.125rem);
  background: color-mix(in srgb, var(--bauhaus-postit, #f4e7c4) 18%, transparent);
  padding: 0.55rem 0.65rem;
}

.account-card-tile__metric {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 0.1rem;
}

.account-card-tile__metric-label {
  font-size: 0.64rem;
  font-weight: 600;
  letter-spacing: 0.03em;
  color: hsl(var(--muted-foreground));
  text-transform: uppercase;
  white-space: nowrap;
}

.account-card-tile__metric-value {
  font-size: 0.82rem;
  line-height: 1.1;
  color: hsl(var(--foreground));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.account-card-tile__metric-value--quota {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-weight: 700;
  color: var(--bauhaus-blue, #2d5da1);
}

html[data-theme='dark'] .account-card-tile {
  box-shadow: var(--shadow-hard-sm, 0 2px 8px rgba(0, 0, 0, 0.45));
}

html[data-theme='dark'] .account-card-tile__metrics {
  background: color-mix(in srgb, var(--bauhaus-card, #fff) 4%, transparent);
}

@media (max-width: 1100px) {
  .account-stream-grid--double {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 900px) {
  .accounts-toolbar-summary {
    width: 100%;
    justify-content: flex-start;
  }

  .accounts-toolbar-group-refresh {
    width: 100%;
    margin-left: 0;
    justify-content: flex-start;
  }
}
</style>
