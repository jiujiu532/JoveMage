<template>
  <div class="shell-root flex h-[100dvh] min-h-0 flex-col">
    <div class="flex min-h-0 flex-1 flex-col lg:flex-row">
      <div
        v-if="isSidebarOpen"
        class="fixed inset-0 z-30 bg-black/20 lg:hidden"
        @click="isSidebarOpen = false"
      ></div>
      <aside
        class="shell-sidebar fixed inset-y-0 left-0 z-40 flex w-64 -translate-x-full flex-col overflow-x-hidden border-r border-border bg-card
               transition-[transform,width] duration-200 ease-out will-change-[transform,width] transform-gpu lg:static lg:h-full lg:w-[var(--sidebar-width)] lg:translate-x-0 lg:bg-card
               lg:sticky lg:top-0 lg:border-b-0 lg:border-r"
        :class="[isSidebarOpen ? 'translate-x-0' : '']"
        :style="sidebarStyle"
        :role="isSidebarOpen ? 'dialog' : undefined"
        :aria-modal="isSidebarOpen ? 'true' : undefined"
        :aria-label="isSidebarOpen ? '导航菜单' : undefined"
      >
        <!-- 侧栏顶：三原色功能条 -->
        <div class="grid h-1.5 shrink-0 grid-cols-3" aria-hidden="true">
          <span class="bg-[var(--bauhaus-blue)]" />
          <span class="bg-[var(--bauhaus-red)]" />
          <span class="bg-[var(--bauhaus-yellow)]" />
        </div>
        <div
          class="flex h-16 items-center pt-3 lg:h-[4.5rem] lg:pt-4"
          :class="isSidebarRail ? 'justify-center px-2' : 'justify-between px-6'"
        >
          <div class="flex items-center gap-2.5" :class="isSidebarRail ? 'gap-0 justify-center w-full' : ''">
            <BauhausBrandMark
              :size="isSidebarRail ? 28 : 32"
              root-class="shrink-0 text-foreground"
            />
            <div v-if="!isSidebarRail" class="min-w-0">
              <p class="ui-section-title tracking-tight">JoveMage</p>
              <p class="mt-0.5 text-[10px] font-medium uppercase tracking-[0.22em] text-muted-foreground">
                Console
              </p>
            </div>
          </div>
        </div>

        <nav
          class="flex-1 pb-3 pt-3 lg:pt-4"
          :class="isSidebarRail ? 'px-2' : 'px-3'"
        >
          <p
            v-if="!isSidebarRail"
            class="bh-kicker px-3 pb-2"
          >
            导航
          </p>
          <div class="space-y-1">
            <RouterLink
              v-for="item in visibleMenuItems"
              :key="item.path"
              :to="item.path"
              class="group flex items-center overflow-hidden rounded-sm border border-transparent py-1.5 text-sm font-medium transition-colors"
              :class="navItemClass(item.path)"
              :title="isSidebarRail ? item.label : undefined"
              @mouseenter="prefetchRouteView(item.path)"
              @focus="prefetchRouteView(item.path)"
              @click="handleNavClick"
            >
              <span
                class="nav-icon inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-sm border transition-all duration-200 ease-out"
                :class="navIconClass(item.path)"
              >
                <svg aria-hidden="true" viewBox="0 0 24 24" class="h-[18px] w-[18px]" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                  <path :d="item.icon" />
                </svg>
              </span>
              <span
                v-if="!isSidebarRail"
                class="nav-label flex-1 min-w-0 truncate font-[family-name:var(--font-display)] tracking-wide transition-all duration-200"
              >{{ item.label }}</span>
            </RouterLink>
          </div>
          <div v-if="visibleUtilityMenuItems.length" class="mt-4 border-t-2 border-border pt-3">
            <p
              v-if="!isSidebarRail"
              class="bh-kicker px-3 pb-2"
            >
              工具
            </p>
            <div class="space-y-1">
              <RouterLink
                v-for="item in visibleUtilityMenuItems"
                :key="item.path"
                :to="item.path"
                class="group flex items-center overflow-hidden rounded-sm border border-transparent py-1.5 text-sm font-medium transition-colors"
                :class="navItemClass(item.path)"
                :title="isSidebarRail ? item.label : undefined"
                @mouseenter="prefetchRouteView(item.path)"
                @focus="prefetchRouteView(item.path)"
              >
                <span
                  class="nav-icon inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-sm border transition-all duration-200 ease-out"
                  :class="navIconClass(item.path)"
                >
                  <svg aria-hidden="true" viewBox="0 0 24 24" class="h-[18px] w-[18px]" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                    <path :d="item.icon" />
                  </svg>
                </span>
                <span
                  v-if="!isSidebarRail"
                  class="nav-label flex-1 min-w-0 truncate font-[family-name:var(--font-display)] tracking-wide transition-all duration-200"
                >{{ item.label }}</span>
              </RouterLink>
            </div>
          </div>
        </nav>

        <div class="mt-auto border-t border-border py-3" :class="isSidebarRail ? 'px-2' : 'px-6'">
          <div
            class="flex items-center gap-3"
            :class="isSidebarRail ? 'justify-center' : ''"
          >
            <Button
              v-if="!isSidebarRail"
              size="sm"
              variant="outline"
              block
              root-class="justify-center rounded-sm text-muted-foreground"
              @click="handleLogout"
            >
              退出登录
            </Button>
            <Button
              v-if="!isImmersivePage"
              size="xs"
              variant="outline"
              icon-only
              root-class="hidden shrink-0 rounded-sm text-muted-foreground lg:inline-flex"
              @click="isSidebarCollapsed = !isSidebarCollapsed"
              :title="isSidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
            >
              <svg
                aria-hidden="true"
                viewBox="0 0 24 24"
                class="h-4 w-4 shrink-0"
                fill="currentColor"
              >
                <path d="M6 4h2v16H6V4zm4 4h8v2h-8V8zm0 6h8v2h-8v-2z" />
              </svg>
            </Button>
          </div>
        </div>
      </aside>

      <main class="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden lg:ml-0">
        <div
          v-if="isRoutePending"
          class="route-pending-bar"
          role="status"
          :aria-label="routePendingText"
        ></div>

        <header
          v-if="!isImmersivePage"
          class="shell-header flex min-w-0 shrink-0 items-center justify-between gap-2 border-b border-border bg-card px-3 py-3 sm:gap-3 sm:px-4 sm:py-4 lg:gap-4 lg:px-10 lg:py-5"
        >
          <div class="flex min-w-0 items-center gap-2 sm:gap-3">
            <Button
              size="xs"
              variant="outline"
              icon-only
              root-class="shrink-0 lg:hidden"
              @click="isSidebarOpen = true"
              aria-label="打开导航"
            >
              <svg aria-hidden="true" viewBox="0 0 24 24" class="h-5 w-5" fill="currentColor">
                <path d="M4 6h16v2H4V6zm0 5h16v2H4v-2zm0 5h16v2H4v-2z" />
              </svg>
            </Button>
            <BauhausBrandMark :size="32" root-class="shrink-0 text-foreground lg:hidden" />
            <BauhausBrandMark :size="36" root-class="hidden shrink-0 text-foreground lg:block" />
            <div class="flex min-w-0 items-center gap-2">
              <h2 class="truncate text-lg font-semibold tracking-tight text-foreground sm:text-xl lg:text-2xl">
                {{ currentPageTitle }}
              </h2>
            </div>
          </div>
          <div class="flex shrink-0 items-center gap-1.5 sm:gap-2 lg:gap-3">
            <Button
              size="sm"
              variant="outline"
              icon-only
              root-class="shell-header-icon-btn"
              @click="cycleThemeMode"
              :title="themeButtonTitle"
              :aria-label="themeButtonTitle"
            >
              <!-- light: 太阳 -->
              <svg
                v-if="themeMode === 'light'"
                aria-hidden="true"
                viewBox="0 0 24 24"
                class="h-[18px] w-[18px]"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <circle cx="12" cy="12" r="4" />
                <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
              </svg>
              <!-- dark: 月亮 -->
              <svg
                v-else-if="themeMode === 'dark'"
                aria-hidden="true"
                viewBox="0 0 24 24"
                class="h-[18px] w-[18px]"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M21 14.5A8.5 8.5 0 0 1 9.5 3 7 7 0 1 0 21 14.5z" />
              </svg>
              <!-- system: 显示器 -->
              <svg
                v-else
                aria-hidden="true"
                viewBox="0 0 24 24"
                class="h-[18px] w-[18px]"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <rect x="3" y="4" width="18" height="12" rx="1.5" />
                <path d="M8 20h8M12 16v4" />
              </svg>
            </Button>
            <Button
              v-if="canvasHref"
              size="sm"
              variant="outline"
              root-class="hidden sm:inline-flex"
              @click="openInfiniteCanvas"
              title="打开外部无限画布"
            >
              画布
            </Button>
            <Button
              size="sm"
              variant="outline"
              icon-only
              root-class="shell-header-icon-btn"
              @click="refreshPage"
              title="刷新"
              aria-label="刷新"
            >
              <svg
                aria-hidden="true"
                viewBox="0 0 24 24"
                class="h-[18px] w-[18px]"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M21 12a9 9 0 1 1-2.64-6.36" />
                <path d="M21 3v6h-6" />
              </svg>
            </Button>
            <Button
              size="sm"
              variant="outline"
              icon-only
              v-if="authStore.isAdmin"
              root-class="shell-header-icon-btn"
              @click="openUpdateDialog"
              :title="`版本 ${versionButtonText}，查看更新`"
              :aria-label="`版本 ${versionButtonText}，查看更新`"
            >
              <!-- GitHub Mark：版本 / 更新 -->
              <svg
                aria-hidden="true"
                viewBox="0 0 24 24"
                class="h-[18px] w-[18px]"
                fill="currentColor"
              >
                <path d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0 1 12 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0 0 22 12.017C22 6.484 17.522 2 12 2z" />
              </svg>
            </Button>
            <Button
              size="sm"
              variant="outline"
              icon-only
              v-if="authStore.isAdmin"
              root-class="shell-header-icon-btn"
              @click="openApiInfo"
              title="接口信息"
              aria-label="接口信息"
            >
              <!-- 代码括号：接口 -->
              <svg
                aria-hidden="true"
                viewBox="0 0 24 24"
                class="h-[18px] w-[18px]"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M8 6 3 12l5 6" />
                <path d="m16 6 5 6-5 6" />
              </svg>
            </Button>
          </div>
        </header>

        <!-- immersive：仅移动端保留极简汉堡，lg 无顶栏 -->
        <header
          v-else
          class="shell-header shell-header--immersive flex shrink-0 items-center gap-2 border-b border-border bg-card px-3 py-2 lg:hidden"
        >
          <Button
            size="xs"
            variant="outline"
            icon-only
            root-class="shrink-0"
            @click="isSidebarOpen = true"
            aria-label="打开导航"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" class="h-5 w-5" fill="currentColor">
              <path d="M4 6h16v2H4V6zm0 5h16v2H4v-2zm0 5h16v2H4v-2z" />
            </svg>
          </Button>
          <p class="truncate text-sm font-semibold tracking-tight text-foreground">
            {{ currentPageTitle }}
          </p>
        </header>

        <div
          class="shell-content relative min-h-0 flex-1 overflow-x-hidden overflow-y-auto bg-background"
          :class="isImmersivePage || isStudioLayoutPage
            ? (isImmersivePage ? 'p-0' : 'px-3 pb-4 pt-3 lg:px-6 lg:pb-6 lg:pt-5')
            : 'px-3 pb-6 pt-4 lg:px-10 lg:pb-10 lg:pt-10'"
        >
          <RouterView v-slot="{ Component, route: currentRoute }">
            <Suspense :timeout="120">
              <template #default>
                <div
                  class="route-view-content"
                  :class="isStudioLayoutPage ? 'h-full min-h-0' : ''"
                >
                  <KeepAlive :include="cachedRouteNames" :max="cachedRouteMax">
                    <component
                      :is="Component"
                      :key="String(currentRoute.name || currentRoute.path)"
                    />
                  </KeepAlive>
                </div>
              </template>
              <template #fallback>
                <PageLoadingState
                  :title="routePendingText"
                  description="正在准备页面内容..."
                  compact
                  dashed
                />
              </template>
            </Suspense>
          </RouterView>
        </div>
      </main>
    </div>
    <ConfirmDialog
      :open="confirmDialog.open.value"
      :title="confirmDialog.title.value"
      :message="confirmDialog.message.value"
      :confirm-text="confirmDialog.confirmText.value"
      :cancel-text="confirmDialog.cancelText.value"
      @confirm="confirmDialog.confirm"
      @cancel="confirmDialog.cancel"
    />
    <ApiInfoModal
      :open="isApiInfoOpen"
      :api-base-url="apiBaseUrl"
      :api-sdk-url="apiSdkUrl"
      :api-full-url="apiFullUrl"
      :api-key-display="apiKeyDisplay"
      :current-auth-token="currentAuthToken"
      :supported-chat-models="supportedChatModels"
      :supported-image-models="supportedImageModels"
      @close="isApiInfoOpen = false"
    />
    <ReleaseNotesModal
      :open="isUpdateDialogOpen"
      :current-version-label="currentVersionLabel"
      :latest-version-label="latestVersionLabel"
      :is-checking-update="isCheckingUpdate"
      :update-check-message="updateCheckMessage"
      :release-entries="releaseEntries"
      @close="isUpdateDialogOpen = false"
      @check-updates="checkForUpdates(true)"
      @open-release-page="openReleasePage"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { settingsApi } from '@/api/settings'
import { getAuthToken } from '@/api/client'
import { useSettingsStore } from '@/stores/settings'
import { useAuthStore } from '@/stores/auth'
import { useModelCatalog } from '@/composables/useModelCatalog'
import { Button } from 'nanocat-ui'
import ConfirmDialog from '@/components/ui/AppConfirmDialog.vue'
import BauhausBrandMark from '@/components/ui/BauhausBrandMark.vue'
import PageLoadingState from '@/components/ai/PageLoadingState.vue'
import ApiInfoModal from '@/components/shell/ApiInfoModal.vue'
import ReleaseNotesModal from '@/components/shell/ReleaseNotesModal.vue'
import { useAppVersion } from '@/composables/useAppVersion'
import { useChannels } from '@/composables/useChannels'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useMediaQuery } from '@/composables/useMediaQuery'
import { MQ } from '@/lib/breakpoints'
import { getBooleanPreference, preferenceKeys, setBooleanPreference } from '@/lib/preferences'
import { applyThemeMode, getStoredThemeMode, setStoredThemeMode, type ThemeMode } from '@/lib/theme'
import type { Settings } from '@/types/api'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const settingsStore = useSettingsStore()
const isSidebarOpen = ref(false)
const isSidebarCollapsed = ref(false)
const confirmDialog = useConfirmDialog()
const isApiInfoOpen = ref(false)
const {
  isUpdateDialogOpen,
  isCheckingUpdate,
  releaseEntries,
  updateCheckMessage,
  currentVersionLabel,
  latestVersionLabel,
  versionButtonText,
  loadCurrentVersion,
  checkForUpdates,
  openUpdateDialog,
  openReleasePage,
} = useAppVersion()
const currentAuthToken = ref('')
const thirdPartyApps = ref<Settings['third_party_apps'] | null>(null)
const themeMode = ref<ThemeMode>(getStoredThemeMode())
const isRoutePending = ref(false)
const pendingRouteTitle = ref('')
const cachedRouteNames = ['Studio', 'Dashboard']
const cachedRouteMax = cachedRouteNames.length
const themeOptions: { label: string; value: ThemeMode }[] = [
  { label: '浅色', value: 'light' },
  { label: '深色', value: 'dark' },
  { label: '系统', value: 'system' },
]
const {
  chatModels: supportedChatModels,
  imageModels: supportedImageModels,
  loadModelCatalog,
} = useModelCatalog(() => settingsStore.settings)
const { loadChannels } = useChannels()

const menuItems = [
  {
    path: '/',
    label: '概览中心',
    // 四宫格仪表盘
    icon: 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z',
  },
  {
    path: '/monitor',
    label: '实时监控',
    // 心跳/脉冲线
    icon: 'M3 12h4l2.5-6 4 12 2.5-6h5',
  },
  {
    path: '/studio',
    label: '对话画图',
    // 气泡 + 画笔
    icon: 'M4 5h13a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H9l-4 3.5V15H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zm10 8 5-5M13 16l2 2 5-5-2-2z',
  },
  {
    path: '/accounts',
    label: '账号管理',
    // 用户 + 小徽章
    icon: 'M12 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM5 20c0-3.3 3.1-5.5 7-5.5s7 2.2 7 5.5',
  },
  {
    path: '/register',
    label: '注册账号',
    // 用户加号
    icon: 'M10 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM3.5 20c0-3.3 2.9-5.5 6.5-5.5 1.5 0 2.9.4 4 1.1M18 14v6M15 17h6',
  },
  {
    path: '/logs',
    label: '日志管理',
    // 列表行
    icon: 'M8 6h13M8 12h13M8 18h13M3.5 6h.5M3.5 12h.5M3.5 18h.5',
  },
  {
    path: '/gallery',
    label: '图片管理',
    // 图片（山+太阳）
    icon: 'M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zm4 4.5A1.5 1.5 0 1 0 8 6.5a1.5 1.5 0 0 0 0 3zM3 17l5-4 4 3 4-4 5 4',
  },
  {
    path: '/proxy',
    label: '代理管理',
    // 盾牌 + 锁孔
    icon: 'M12 3l7 3v5c0 4.5-3 8-7 9.5C8 19 5 15.5 5 11V6zm0 6.5a1.5 1.5 0 0 1 1 2.8V15h-2v-2.7a1.5 1.5 0 0 1 1-2.8z',
  },
  {
    path: '/settings',
    label: '系统设置',
    // 齿轮
    icon: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm7.5-3a7.6 7.6 0 0 0-.1-1.2l2-1.5-2-3.4-2.3 1a7.7 7.7 0 0 0-2-1.2L14.5 3h-5l-.6 2.7a7.7 7.7 0 0 0-2 1.2l-2.3-1-2 3.4 2 1.5a7.6 7.6 0 0 0 0 2.4l-2 1.5 2 3.4 2.3-1a7.7 7.7 0 0 0 2 1.2l.6 2.7h5l.6-2.7a7.7 7.7 0 0 0 2-1.2l2.3 1 2-3.4-2-1.5c.06-.4.1-.8.1-1.2z',
  },
]

const utilityMenuItems = [
  {
    path: '/debug',
    label: '调试中心',
    // 扳手 + 螺丝刀（工具）
    icon: 'M14.5 6.5a4 4 0 0 0-5.6 5L4 16.4V20h3.6l4.9-4.9a4 4 0 0 0 5-5.6l-2.8 2.8-2.1-2.1zM17 3l4 4-1.5 1.5-4-4z',
  },
]

const routeTitleMap: Record<string, string> = {
  dashboard: '概览中心',
  accounts: '账号管理',
  logs: '日志管理',
  gallery: '图片管理',
  proxy: '代理管理',
  register: '注册账号',
  settings: '系统设置',
  debug: '调试中心',
  monitor: '实时监控',
  docs: '文档教程',
  studio: '对话画图',
}

const visibleMenuItems = computed(() => {
  if (authStore.isUser) {
    return menuItems.filter(item => item.path === '/studio')
  }
  return menuItems
})

const visibleUtilityMenuItems = computed(() => (authStore.isAdmin ? utilityMenuItems : []))

const currentPageTitle = computed(() => {
  const routeName = String(route.name || '')
  const item = [...visibleMenuItems.value, ...visibleUtilityMenuItems.value].find(item => isNavActive(item.path))
  return item?.label || routeTitleMap[routeName] || '概览中心'
})

function titleForRoute(name: unknown, path: string) {
  const routeName = String(name || '')
  const item = [...menuItems, ...utilityMenuItems].find((menuItem) => menuItem.path === path)
  return item?.label || routeTitleMap[routeName] || '页面'
}

/** Studio 等沉浸路由：仅 <lg 隐藏壳顶栏；PC 保留完整侧栏+顶栏 */
const isNarrowShell = useMediaQuery(MQ.notDesktop)
const isStudioLayoutPage = computed(() => Boolean(route.meta.immersive))
const isImmersivePage = computed(() => isStudioLayoutPage.value && isNarrowShell.value)
const isSidebarRail = computed(() => isSidebarCollapsed.value)
const sidebarStyle = computed(() => ({
  '--sidebar-width': isSidebarRail.value ? '4rem' : '16rem',
}))

const navItemBaseClass = computed(() => isSidebarRail.value ? 'px-2 justify-center gap-0' : 'px-2.5 gap-3')
const activeNavPathSet = computed(() => {
  const name = String(route.name || '')
  const currentPath = route.path
  return new Set(
    [...visibleMenuItems.value, ...visibleUtilityMenuItems.value]
      .filter((item) => isRoutePathActive(item.path, name, currentPath))
      .map((item) => item.path),
  )
})

function isRoutePathActive(path: string, name: string, currentPath: string) {
  const normalized = path.replace(/^\/+/, '')
  if (!normalized) return name === 'dashboard' || currentPath === '/'
  return currentPath === path || name === normalized
}

const isNavActive = (path: string) => {
  return activeNavPathSet.value.has(path)
}

const navItemClass = (path: string) => {
  const base = navItemBaseClass.value
  if (isNavActive(path)) {
    return `${base} nav-item--active rounded-sm border-y-transparent border-r-transparent bg-[color-mix(in_srgb,var(--bauhaus-blue)_12%,transparent)] font-semibold text-foreground`
  }
  return `${base} rounded-sm border-transparent text-muted-foreground hover:bg-secondary hover:text-foreground`
}

const navIconClass = (path: string) => {
  if (isNavActive(path)) {
    return 'border-[var(--bauhaus-blue)] bg-[var(--bauhaus-blue)] text-white'
  }
  return 'border-border bg-card text-muted-foreground group-hover:border-foreground/28 group-hover:text-foreground'
}


const apiBaseUrl = computed(() => {
  const raw = settingsStore.settings?.basic?.base_url
    || import.meta.env.VITE_API_URL
    || window.location.origin
  return raw.replace(/\/$/, '')
})

const apiSdkUrl = computed(() => `${apiBaseUrl.value}/v1`)
const apiFullUrl = computed(() => `${apiBaseUrl.value}/v1/chat/completions`)
const apiKeyDisplay = computed(() => currentAuthToken.value || '未登录')
const activeThirdPartyApps = computed(() => settingsStore.settings?.third_party_apps || thirdPartyApps.value)
const canvasHref = computed(() => {
  const canvas = activeThirdPartyApps.value?.infinite_canvas
  const token = getAuthToken()
  if (!canvas?.enabled || !canvas.url.trim() || !token) return ''
  return buildThirdPartyHref(canvas.url, apiBaseUrl.value, token)
})
const themeButtonText = computed(() => themeOptions.find(option => option.value === themeMode.value)?.label || '系统')
const themeButtonTitle = computed(() => `当前主题：${themeButtonText.value}，点击切换`)
const routePendingText = computed(() => `正在打开${pendingRouteTitle.value || currentPageTitle.value}`)
let systemThemeMedia: MediaQueryList | null = null
let routePendingTimer: number | null = null
let stopRoutePendingBeforeEach: (() => void) | null = null
let stopRoutePendingAfterEach: (() => void) | null = null
let stopRoutePendingError: (() => void) | null = null
const prefetchedRoutePaths = new Set<string>()
const routeViewLoaders: Record<string, () => Promise<unknown>> = {
  '/': () => import('@/views/Dashboard.vue'),
  '/accounts': () => import('@/views/Accounts.vue'),
  '/logs': () => import('@/views/Logs.vue'),
  '/gallery': () => import('@/views/Gallery.vue'),
  '/monitor': () => import('@/views/Monitor.vue'),
  '/proxy': () => import('@/views/Proxy.vue'),
  '/settings': () => import('@/views/Settings.vue'),
  '/register': () => import('@/views/Register.vue'),
  '/debug': () => import('@/views/DebugCenter.vue'),
  '/studio': () => import('@/views/Studio.vue'),
}

watch(
  () => route.path,
  () => {
    isSidebarOpen.value = false
  }
)

watch(isSidebarOpen, (open) => {
  if (typeof document === 'undefined') return
  document.body.style.overflow = open ? 'hidden' : ''
})

isSidebarCollapsed.value = getBooleanPreference(preferenceKeys.sidebarCollapsed, false)

watch(isSidebarCollapsed, (value) => {
  setBooleanPreference(preferenceKeys.sidebarCollapsed, value)
})

function handleSidebarEscape(event: KeyboardEvent) {
  if (event.key === 'Escape' && isSidebarOpen.value) {
    isSidebarOpen.value = false
  }
}

function buildThirdPartyHref(appUrl: string, baseUrl: string, apiKey: string) {
  const url = appUrl.trim()
  try {
    const target = new URL(url)
    target.searchParams.set('apiKey', apiKey)
    target.searchParams.set('baseUrl', baseUrl)
    return target.toString()
  } catch {
    return `${url}${url.includes('?') ? '&' : '?'}apiKey=${encodeURIComponent(apiKey)}&baseUrl=${encodeURIComponent(baseUrl)}`
  }
}

function refreshPage() {
  window.location.reload()
}

async function handleLogout() {
  await authStore.logout()
  await router.replace({ name: 'login' })
}

async function openApiInfo() {
  currentAuthToken.value = getAuthToken()
  isApiInfoOpen.value = true
  if (!settingsStore.settings && !settingsStore.isLoading) {
    await settingsStore.loadSettings()
  }
  await loadModelCatalog()
}

async function openInfiniteCanvas() {
  if (!canvasHref.value) return
  const ok = await confirmDialog.ask({
    title: '打开无限画布',
    message: '即将打开外部画布，并附带当前接口地址和当前调用密钥。是否继续？',
    confirmText: '打开',
    cancelText: '取消',
  })
  if (ok) {
    window.open(canvasHref.value, '_blank', 'noopener,noreferrer')
  }
}

function setThemeMode(mode: ThemeMode) {
  themeMode.value = mode
  setStoredThemeMode(mode)
}

function cycleThemeMode() {
  const index = themeOptions.findIndex(option => option.value === themeMode.value)
  const next = themeOptions[(index + 1) % themeOptions.length]
  setThemeMode(next.value)
}

function handleSystemThemeChange() {
  if (themeMode.value === 'system') {
    applyThemeMode(themeMode.value)
  }
}

function setupSystemThemeListener() {
  if (typeof window === 'undefined') return
  systemThemeMedia = window.matchMedia('(prefers-color-scheme: dark)')
  systemThemeMedia.addEventListener('change', handleSystemThemeChange)
}

async function loadThirdPartyApps() {
  try {
    thirdPartyApps.value = await settingsApi.getThirdPartyApps()
  } catch {
    thirdPartyApps.value = null
  }
}

function normalizedRoutePath(path: string) {
  if (!path || path === '/') return '/'
  return `/${path.replace(/^\/+/, '').split(/[?#]/)[0]}`
}

function prefetchRouteView(path: string) {
  const normalizedPath = normalizedRoutePath(path)
  const loader = routeViewLoaders[normalizedPath]
  if (!loader || prefetchedRoutePaths.has(normalizedPath)) return
  prefetchedRoutePaths.add(normalizedPath)
  void loader().catch(() => {
    prefetchedRoutePaths.delete(normalizedPath)
  })
}

function handleNavClick() {
  isSidebarOpen.value = false
}

function stopRoutePending() {
  if (routePendingTimer !== null) {
    window.clearTimeout(routePendingTimer)
    routePendingTimer = null
  }
  isRoutePending.value = false
}

function startRoutePending(title: string) {
  stopRoutePending()
  pendingRouteTitle.value = title
  routePendingTimer = window.setTimeout(() => {
    isRoutePending.value = true
  }, 120)
}

function setupRoutePendingGuards() {
  stopRoutePendingBeforeEach = router.beforeEach((to, from) => {
    if (to.fullPath !== from.fullPath) {
      startRoutePending(titleForRoute(to.name, to.path))
    }
    return true
  })
  stopRoutePendingAfterEach = router.afterEach(() => {
    stopRoutePending()
  })
  stopRoutePendingError = router.onError(() => {
    stopRoutePending()
  })
}

function teardownRoutePendingGuards() {
  stopRoutePendingBeforeEach?.()
  stopRoutePendingAfterEach?.()
  stopRoutePendingError?.()
  stopRoutePendingBeforeEach = null
  stopRoutePendingAfterEach = null
  stopRoutePendingError = null
  stopRoutePending()
}

onMounted(() => {
  applyThemeMode(themeMode.value)
  setupSystemThemeListener()
  setupRoutePendingGuards()
  document.addEventListener('keydown', handleSidebarEscape)
  void loadCurrentVersion()
  void loadThirdPartyApps()
  // 渠道描述符：壳层挂载时拉一次，失败回落本地默认表
  if (authStore.isLoggedIn) {
    void loadChannels()
  }
})

onBeforeUnmount(() => {
  systemThemeMedia?.removeEventListener('change', handleSystemThemeChange)
  systemThemeMedia = null
  document.removeEventListener('keydown', handleSidebarEscape)
  document.body.style.overflow = ''
  teardownRoutePendingGuards()
})

</script>

<style scoped>
.route-view-content {
  min-width: 0;
}

.shell-sidebar {
  padding-top: env(safe-area-inset-top, 0px);
  padding-bottom: env(safe-area-inset-bottom, 0px);
  padding-left: env(safe-area-inset-left, 0px);
}

.shell-header {
  padding-top: max(0.75rem, env(safe-area-inset-top, 0px));
  padding-right: max(0.75rem, env(safe-area-inset-right, 0px));
}

.shell-header-icon-btn {
  min-width: 2.25rem;
  width: 2.25rem;
  height: 2.25rem;
  padding: 0;
}

@media (min-width: 640px) {
  .shell-header {
    padding-top: max(1rem, env(safe-area-inset-top, 0px));
    padding-right: max(1rem, env(safe-area-inset-right, 0px));
  }

  .shell-header-icon-btn {
    min-width: 2.5rem;
    width: 2.5rem;
    height: 2.5rem;
  }
}

@media (min-width: 1024px) {
  .shell-header {
    padding-top: max(1.25rem, env(safe-area-inset-top, 0px));
    padding-right: max(2.5rem, env(safe-area-inset-right, 0px));
  }

  .shell-header--immersive {
    display: none;
  }
}

/* ========== 侧栏导航切换动效 ========== */
/* 选中项：左侧指示条滑入 + 整体轻移，图标缩放上色 */
.group {
  position: relative;
}

.group::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  height: 0;
  width: 4px;
  border-radius: 0 var(--radius) var(--radius) 0;
  background: var(--bauhaus-blue);
  transform: translateY(-50%) scaleY(0.3);
  opacity: 0;
  transition: height 0.22s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.22s cubic-bezier(0.22, 1, 0.36, 1),
    opacity 0.18s ease;
}

.group.nav-item--active::before {
  height: 62%;
  transform: translateY(-50%) scaleY(1);
  opacity: 1;
}

.group .nav-icon {
  transform: translateX(0) scale(1);
}

.group.nav-item--active {
  transition: background-color 0.22s ease, color 0.18s ease;
}

.group.nav-item--active .nav-icon {
  transform: scale(1.04);
  box-shadow: 2px 2px 0 0 var(--bauhaus-ink);
  animation: nav-icon-pop 0.26s cubic-bezier(0.34, 1.56, 0.64, 1);
}

html[data-theme='dark'] .group.nav-item--active .nav-icon {
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.5);
}

.group.nav-item--active .nav-label {
  transform: translateX(2px);
}

.group:not(.nav-item--active):hover .nav-icon {
  transform: translateX(1px);
  transition: transform 0.18s ease;
}

@keyframes nav-icon-pop {
  0% {
    transform: scale(0.82);
  }
  60% {
    transform: scale(1.08);
  }
  100% {
    transform: scale(1.04);
  }
}

@media (prefers-reduced-motion: reduce) {
  .group::before,
  .group.nav-item--active .nav-icon,
  .group.nav-item--active .nav-label,
  .group:not(.nav-item--active):hover .nav-icon {
    transition: none;
    animation: none;
    transform: none;
  }
}

.route-pending-bar {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  z-index: 80;
  height: 2px;
  overflow: hidden;
  background: hsl(var(--primary) / 0.16);
  pointer-events: none;
}

.route-pending-bar::after {
  display: block;
  width: 100%;
  height: 100%;
  content: '';
  background: hsl(var(--primary));
  box-shadow: 0 0 14px hsl(var(--primary) / 0.3);
  animation: route-pending-pulse 0.9s ease-in-out infinite alternate;
}

@keyframes route-pending-pulse {
  from { opacity: 0.36; }
  to { opacity: 1; }
}
</style>
