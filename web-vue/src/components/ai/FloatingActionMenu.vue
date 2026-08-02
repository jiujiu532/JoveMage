<template>
  <div ref="rootRef" class="floating-action-menu" :style="rootStyle" :title="disabled && disabledTip ? disabledTip : undefined">
    <Button
      variant="outline"
      :size="size === 'xs' ? 'xs' : 'sm'"
      :disabled="disabled"
      :root-class="triggerRootClass"
      @click.stop="toggleMenu"
    >
      <span>{{ label }}</span>
      <svg
        viewBox="0 0 20 20"
        class="h-3.5 w-3.5 transition-transform"
        :class="open ? 'rotate-180' : ''"
        fill="currentColor"
        aria-hidden="true"
      >
        <path d="M5 7l5 6 5-6H5z" />
      </svg>
    </Button>

    <Teleport to="body">
      <div
        v-if="open && !disabled"
        ref="menuRef"
        class="floating-action-menu-panel ui-floating-panel fixed z-[1000]"
        :class="[panelClass, isNarrow ? 'is-narrow' : '']"
        :style="menuStyle"
        @click.stop
      >
        <template v-for="item in items" :key="item.key">
          <div
            v-if="item.dividerBefore"
            class="floating-menu-divider"
            role="separator"
            aria-hidden="true"
          />
          <template v-if="item.children?.length">
            <button
              type="button"
              class="floating-action-menu-item floating-action-menu-item-parent ui-menu-item"
              :class="[
                item.danger ? 'floating-action-menu-item-danger ui-menu-item-danger' : '',
                activeParentKey === item.key ? 'floating-action-menu-item-active' : '',
              ]"
              :disabled="item.disabled"
              @mouseenter="onParentHover(item, $event)"
              @focusin="onParentHover(item, $event)"
              @click="onParentClick(item, $event)"
            >
              <span>{{ item.label }}</span>
              <svg
                viewBox="0 0 20 20"
                class="h-3.5 w-3.5 transition-transform floating-action-menu-chevron"
                :class="activeParentKey === item.key ? 'is-open' : ''"
                fill="none"
                stroke="currentColor"
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                aria-hidden="true"
              >
                <path d="M8 5l5 5-5 5" />
              </svg>
            </button>
            <!-- 窄屏：子项纵向嵌在父项下方，避免侧开出屏 -->
            <div
              v-if="isNarrow && activeParentKey === item.key"
              class="floating-action-submenu-panel floating-action-submenu-panel--nested"
              @click.stop
            >
              <template v-for="child in item.children" :key="child.key">
                <div
                  v-if="child.dividerBefore"
                  class="floating-menu-divider"
                  role="separator"
                  aria-hidden="true"
                />
                <button
                  type="button"
                  class="floating-action-menu-item floating-action-menu-item-child ui-menu-item"
                  :class="child.danger ? 'floating-action-menu-item-danger ui-menu-item-danger' : ''"
                  :disabled="child.disabled"
                  @click="selectItem(child)"
                >
                  {{ child.label }}
                </button>
              </template>
            </div>
          </template>
          <button
            v-else
            type="button"
            class="floating-action-menu-item ui-menu-item"
            :class="item.danger ? 'floating-action-menu-item-danger ui-menu-item-danger' : ''"
            :disabled="item.disabled"
            @mouseenter="closeSubmenu"
            @focusin="closeSubmenu"
            @click="selectItem(item)"
          >
            {{ item.label }}
          </button>
        </template>
      </div>

      <!-- 桌面：侧开子菜单 -->
      <div
        v-if="open && !disabled && activeChildren.length && !isNarrow"
        ref="submenuRef"
        class="floating-action-menu-panel floating-action-submenu-panel ui-floating-panel fixed z-[1001]"
        :class="panelClass"
        :style="submenuStyle"
        @click.stop
      >
        <template v-for="child in activeChildren" :key="child.key">
          <div
            v-if="child.dividerBefore"
            class="floating-menu-divider"
            role="separator"
            aria-hidden="true"
          />
          <button
            type="button"
            class="floating-action-menu-item floating-action-menu-item-child ui-menu-item"
            :class="child.danger ? 'floating-action-menu-item-danger ui-menu-item-danger' : ''"
            :disabled="child.disabled"
            @click="selectItem(child)"
          >
            {{ child.label }}
          </button>
        </template>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { Button } from 'nanocat-ui'
import type { ActionMenuItem, UiSize } from 'nanocat-ui'
import type { CSSProperties } from 'vue'
import { MQ } from '@/lib/breakpoints'
import { computeFloatingPosition, type FloatingPlacement } from '@/lib/floatingPlacement'

type FloatingActionMenuItem = ActionMenuItem & {
  children?: FloatingActionMenuItem[]
}
type FloatingMenuPlacement = FloatingPlacement

const props = withDefaults(defineProps<{
  label: string
  items: FloatingActionMenuItem[]
  disabled?: boolean
  /** 禁用时 hover 提示（如「仅 ChatGPT 渠道可用」） */
  disabledTip?: string
  align?: 'left' | 'right'
  placement?: FloatingMenuPlacement
  size?: UiSize
  triggerClass?: string
  menuClass?: string
  menuMinWidth?: number
  triggerMinWidth?: number
  triggerWidth?: number
}>(), {
  disabled: false,
  disabledTip: '',
  align: 'right',
  placement: 'auto',
  size: 'sm',
  triggerClass: '',
  menuClass: 'min-w-max',
})

const emit = defineEmits<{
  (e: 'select', key: string): void
}>()

const rootRef = ref<HTMLElement | null>(null)
const menuRef = ref<HTMLElement | null>(null)
const submenuRef = ref<HTMLElement | null>(null)
const open = ref(false)
const activeParentKey = ref('')
const isNarrow = ref(false)
const menuPosition = ref({ left: 0, top: 0, minWidth: 0, maxHeight: 0 })
const submenuPosition = ref({ left: 0, top: 0, minWidth: 0, maxHeight: 0 })
const menuId = `floating-menu-${Math.random().toString(36).slice(2)}`
let activeParentElement: HTMLElement | null = null
let narrowMql: MediaQueryList | null = null

const hasTriggerSizing = computed(() => Boolean(props.triggerWidth || props.triggerMinWidth))
const triggerRootClass = computed(() => [
  'floating-action-menu-trigger justify-between gap-2',
  hasTriggerSizing.value ? 'w-full' : '',
  props.triggerClass,
].filter(Boolean).join(' '))
const panelClass = computed(() => props.menuClass)
const activeParentItem = computed(() => props.items.find((item) => item.key === activeParentKey.value))
const activeChildren = computed(() => activeParentItem.value?.children || [])
const rootStyle = computed<CSSProperties>(() => {
  const style: CSSProperties = {}
  if (props.triggerWidth) {
    style.width = `${props.triggerWidth}px`
  } else if (props.triggerMinWidth) {
    style.minWidth = `${props.triggerMinWidth}px`
  }
  return style
})

const menuStyle = computed<CSSProperties>(() => {
  const minWidth = Math.max(menuPosition.value.minWidth, props.menuMinWidth || 0)
  const narrow = isNarrow.value

  return {
    left: `${menuPosition.value.left}px`,
    top: `${menuPosition.value.top}px`,
    minWidth: narrow ? undefined : `${minWidth}px`,
    width: narrow ? 'min(20rem, calc(100vw - 1rem))' : 'max-content',
    maxWidth: 'min(20rem, calc(100vw - 1rem))',
    maxHeight: menuPosition.value.maxHeight ? `${menuPosition.value.maxHeight}px` : undefined,
  }
})

const submenuStyle = computed<CSSProperties>(() => ({
  left: `${submenuPosition.value.left}px`,
  top: `${submenuPosition.value.top}px`,
  minWidth: `${submenuPosition.value.minWidth}px`,
  width: 'max-content',
  maxWidth: 'min(18rem, calc(100vw - 1rem))',
  maxHeight: submenuPosition.value.maxHeight ? `${submenuPosition.value.maxHeight}px` : undefined,
}))

function syncNarrow(list?: MediaQueryList | MediaQueryListEvent) {
  if (list && 'matches' in list) {
    isNarrow.value = list.matches
    return
  }
  isNarrow.value = narrowMql?.matches ?? false
}

function closeMenu() {
  open.value = false
  closeSubmenu()
}

async function toggleMenu() {
  if (props.disabled) return
  open.value = !open.value
  if (open.value) {
    window.dispatchEvent(new CustomEvent('ai-floating-menu-open', { detail: menuId }))
    await nextTick()
    updatePosition()
    requestAnimationFrame(updatePosition)
  }
}

function closeSubmenu() {
  activeParentKey.value = ''
  activeParentElement = null
}

function onParentHover(item: FloatingActionMenuItem, event?: Event) {
  // 窄屏仅点击展开，避免触控误触 hover
  if (isNarrow.value) return
  void openSubmenu(item, event)
}

async function onParentClick(item: FloatingActionMenuItem, event?: Event) {
  if (item.disabled || !item.children?.length) return
  if (isNarrow.value && activeParentKey.value === item.key) {
    closeSubmenu()
    return
  }
  await openSubmenu(item, event)
}

async function openSubmenu(item: FloatingActionMenuItem, event?: Event) {
  if (item.disabled || !item.children?.length) return
  activeParentElement = event?.currentTarget instanceof HTMLElement ? event.currentTarget : activeParentElement
  activeParentKey.value = item.key
  await nextTick()
  if (!isNarrow.value) {
    updateSubmenuPosition()
  }
  // 嵌套展开后主面板高度变化，重新贴边
  updatePosition()
}

function selectItem(item: FloatingActionMenuItem) {
  if (item.disabled) return
  closeMenu()
  emit('select', item.key)
}

function updatePosition() {
  const root = rootRef.value
  const menu = menuRef.value
  if (!root || !menu) return

  const rect = root.getBoundingClientRect()
  const viewportWidth = window.innerWidth || document.documentElement.clientWidth
  const margin = 8
  const menuWidth = Math.max(
    menu.offsetWidth || 0,
    isNarrow.value ? Math.min(viewportWidth - margin * 2, 320) : rect.width,
  )
  const menuHeight = menu.offsetHeight || 0
  // 窄屏优先上下展开，避免侧开；对齐/宽高仍由本组件控制
  const { left, top, maxHeight } = computeFloatingPosition(
    rect,
    { width: menuWidth, height: menuHeight },
    {
      placement: props.placement,
      align: props.align,
      gap: 8,
      margin,
      verticalOnly: isNarrow.value,
      viewportWidth,
    },
  )

  menuPosition.value = {
    left,
    top,
    minWidth: isNarrow.value
      ? Math.min(viewportWidth - margin * 2, Math.max(rect.width, 200))
      : rect.width,
    maxHeight,
  }

  if (activeParentKey.value && !isNarrow.value) {
    void nextTick(updateSubmenuPosition)
  }
}

function updateSubmenuPosition() {
  const anchor = activeParentElement
  const submenu = submenuRef.value
  if (!anchor || !anchor.isConnected || !submenu || activeChildren.value.length === 0) return
  if (isNarrow.value) return

  const rect = anchor.getBoundingClientRect()
  const viewportWidth = window.innerWidth || document.documentElement.clientWidth
  const viewportHeight = window.innerHeight || document.documentElement.clientHeight
  const menuRect = menuRef.value?.getBoundingClientRect()
  const margin = 8
  const gap = 6
  const submenuWidth = Math.max(submenu.offsetWidth || 0, rect.width)
  const submenuHeight = submenu.offsetHeight || 0
  const rightEdge = Math.max(rect.right, menuRect?.right || rect.right)
  const leftEdge = Math.min(rect.left, menuRect?.left || rect.left)
  const rightLeft = rightEdge + gap
  const left = rightLeft + submenuWidth <= viewportWidth - margin
    ? rightLeft
    : Math.max(margin, leftEdge - gap - submenuWidth)
  const rawTop = rect.top
  const top = Math.max(margin, Math.min(rawTop, viewportHeight - margin - submenuHeight))
  const maxHeight = Math.max(96, Math.floor(viewportHeight - margin - top))

  submenuPosition.value = {
    left,
    top,
    minWidth: rect.width,
    maxHeight,
  }
}

function handleDocumentClick(event: MouseEvent) {
  const target = event.target as Node | null
  if (!target) return
  if (rootRef.value?.contains(target) || menuRef.value?.contains(target) || submenuRef.value?.contains(target)) return
  closeMenu()
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') closeMenu()
}

function handleOtherMenuOpen(event: Event) {
  if ((event as CustomEvent<string>).detail === menuId) return
  closeMenu()
}

function handleViewportChange() {
  syncNarrow()
  if (open.value) {
    updatePosition()
    if (activeParentKey.value && !isNarrow.value) {
      updateSubmenuPosition()
    }
  }
}

onMounted(() => {
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    narrowMql = window.matchMedia(MQ.phone)
    syncNarrow(narrowMql)
    if (typeof narrowMql.addEventListener === 'function') {
      narrowMql.addEventListener('change', syncNarrow)
    } else {
      narrowMql.addListener(syncNarrow)
    }
  }
  document.addEventListener('click', handleDocumentClick)
  window.addEventListener('resize', handleViewportChange)
  window.addEventListener('scroll', updatePosition, true)
  window.addEventListener('ai-floating-menu-open', handleOtherMenuOpen)
  document.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  if (narrowMql) {
    if (typeof narrowMql.removeEventListener === 'function') {
      narrowMql.removeEventListener('change', syncNarrow)
    } else {
      narrowMql.removeListener(syncNarrow)
    }
    narrowMql = null
  }
  document.removeEventListener('click', handleDocumentClick)
  window.removeEventListener('resize', handleViewportChange)
  window.removeEventListener('scroll', updatePosition, true)
  window.removeEventListener('ai-floating-menu-open', handleOtherMenuOpen)
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<style scoped>
.floating-action-menu {
  position: relative;
  display: inline-flex;
}

.floating-action-menu-panel {
  padding: 6px !important;
  border-radius: var(--radius) !important;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.floating-action-menu-item {
  width: 100%;
  justify-content: flex-start !important;
  white-space: nowrap;
  text-align: left;
  border-radius: var(--radius);
}

.floating-action-menu-item-parent {
  justify-content: space-between !important;
  gap: 12px;
}

.floating-action-menu-item-active {
  background: hsl(var(--accent));
  color: hsl(var(--accent-foreground));
}

.floating-action-submenu-panel {
  overflow-y: auto;
  overscroll-behavior: contain;
}

.floating-action-menu-item-child {
  font-size: 12px;
}

.floating-action-menu-item:disabled {
  opacity: 0.48;
}

.floating-action-menu-item-danger {
  color: hsl(var(--tone-error-foreground));
}

.floating-menu-divider {
  height: 0;
  margin: 4px 8px;
  flex-shrink: 0;
  border-top: 1px solid hsl(var(--border) / 0.82);
}

/* 窄屏：主菜单更宽可点；子菜单纵向嵌套，避免侧开出屏 */
@media (max-width: 640px) {
  .floating-action-menu-panel {
    padding: 4px !important;
  }

  .floating-action-menu-item {
    min-height: 40px;
    padding-inline: 12px;
  }

  .floating-action-menu-chevron {
    transform: rotate(90deg);
  }

  .floating-action-menu-chevron.is-open {
    transform: rotate(-90deg);
  }

  .floating-action-submenu-panel--nested {
    position: static;
    width: 100%;
    margin: 2px 0 4px;
    padding: 2px;
    border: 1px solid hsl(var(--border) / 0.7);
    border-radius: var(--radius);
    background: hsl(var(--muted) / 0.35);
    box-shadow: none;
    max-height: min(40vh, 16rem);
    overflow-y: auto;
  }

  .floating-action-menu-item-child {
    min-height: 38px;
    padding-left: 1.25rem;
    white-space: normal;
  }
}
</style>
