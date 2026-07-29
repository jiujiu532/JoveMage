<template>
  <div v-if="totalCount > 0" class="nb-pager">
    <div class="nb-pager__group">
      <button
        type="button"
        class="nb-pager__btn nb-pager__btn--pill"
        :disabled="disabled || safePage <= 1"
        :aria-label="'上一页'"
        @click="emit('update:page', safePage - 1)"
      >
        <span aria-hidden="true">上一页</span>
      </button>

      <template v-for="item in pageItems" :key="item.key">
        <span v-if="item.gap" class="nb-pager__gap" aria-hidden="true">…</span>
        <button
          v-else
          type="button"
          class="nb-pager__dot"
          :class="{ 'nb-pager__dot--active': item.page === safePage }"
          :aria-label="`第 ${item.page} 页`"
          :aria-current="item.page === safePage ? 'page' : undefined"
          :disabled="disabled"
          @click="emit('update:page', item.page)"
        >
          {{ item.page }}
        </button>
      </template>

      <button
        type="button"
        class="nb-pager__btn nb-pager__btn--pill"
        :disabled="disabled || safePage >= pageCount"
        :aria-label="'下一页'"
        @click="emit('update:page', safePage + 1)"
      >
        <span aria-hidden="true">下一页</span>
      </button>
    </div>

    <div class="nb-pager__meta">
      第 {{ safePage }} / {{ pageCount }} 页 · 共 {{ totalCount }} {{ unit }}
    </div>

    <div class="nb-pager__size">
      <span class="nb-pager__size-label">每页</span>
      <div class="nb-pager__size-trigger">
        <GroupedSelectMenu
          :model-value="String(pageSize)"
          :groups="pageSizeMenuGroups"
          :placement="placement"
          :aria-label="`${unit}每页数量`"
          @update:model-value="setPageSize"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import GroupedSelectMenu from '../ui/GroupedSelectMenu.vue'

type MenuPlacement = 'auto' | 'top' | 'bottom' | 'left' | 'right' | 'up' | 'down'

const props = withDefaults(defineProps<{
  page: number
  pageSize: number
  totalCount: number
  pageSizeOptions?: number[]
  unit?: string
  disabled?: boolean
  placement?: MenuPlacement
}>(), {
  pageSizeOptions: () => [20, 50, 100],
  unit: '条',
  disabled: false,
  placement: 'auto',
})

const emit = defineEmits<{
  (e: 'update:page', value: number): void
  (e: 'update:pageSize', value: number): void
}>()

const pageCount = computed(() => Math.max(1, Math.ceil(props.totalCount / Math.max(1, props.pageSize))))
const safePage = computed(() => Math.min(pageCount.value, Math.max(1, props.page)))
const pageSizeMenuGroups = computed(() => [{
  options: props.pageSizeOptions.map((value) => ({
    label: `${value} / 页`,
    value: String(value),
  })),
}])

/** 页码序列：7 页内全显，超出收为 首 … 中段 … 尾 */
const pageItems = computed<{ key: string; page: number; gap?: boolean }[]>(() => {
  const count = pageCount.value
  const current = safePage.value
  if (count <= 7) {
    return Array.from({ length: count }, (_, i) => ({ key: `p${i + 1}`, page: i + 1 }))
  }
  const pages = new Set<number>([1, count])
  for (let value = current - 1; value <= current + 1; value += 1) {
    if (value >= 2 && value <= count - 1) pages.add(value)
  }
  const sorted = Array.from(pages).sort((a, b) => a - b)
  const items: { key: string; page: number; gap?: boolean }[] = []
  let previous = 0
  for (const page of sorted) {
    if (page - previous > 1) items.push({ key: `gap-${previous}-${page}`, page: 0, gap: true })
    items.push({ key: `p${page}`, page })
    previous = page
  }
  return items
})

function setPageSize(value: string | string[]) {
  const rawValue = Array.isArray(value) ? value[0] : value
  const next = Number(rawValue)
  if (!Number.isFinite(next) || next <= 0) return
  emit('update:pageSize', next)
}
</script>

<style scoped>
/* 新粗野主义分页：黑粗边 + 硬偏移阴影 + 米色选中，呼应 ops-theme 草图风 */
.nb-pager {
  --nb-ink: var(--bauhaus-ink, #2d2d2d);
  --nb-postit: var(--bauhaus-postit, #fff9c4);
  --nb-grey: var(--bauhaus-grey, #6b6560);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 16px;
  border-top: 1.5px solid hsl(var(--border));
  padding-top: 14px;
}

.nb-pager__group {
  display: flex;
  align-items: center;
  gap: 7px;
}

.nb-pager__btn,
.nb-pager__dot {
  -webkit-appearance: none;
  appearance: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 2px solid var(--nb-ink);
  background: hsl(var(--card));
  color: var(--nb-ink);
  font-family: var(--font-display, inherit);
  font-weight: 700;
  cursor: pointer;
  transition: transform 0.08s ease, box-shadow 0.08s ease, background-color 0.12s ease, color 0.12s ease;
}

.nb-pager__btn--pill {
  border-radius: var(--radius, 2px);
  padding: 0.4rem 0.9rem;
  font-size: 0.78rem;
  letter-spacing: 0.02em;
}

.nb-pager__dot {
  width: 2rem;
  height: 2rem;
  min-width: 2rem;
  border-radius: var(--radius, 2px);
  font-size: 0.8rem;
  font-variant-numeric: tabular-nums;
}

.nb-pager__btn:not(:disabled),
.nb-pager__dot:not(:disabled) {
  box-shadow: 3px 3px 0 0 var(--nb-ink);
}

.nb-pager__btn:hover:not(:disabled),
.nb-pager__dot:hover:not(:disabled) {
  transform: translate(-1px, -1px);
  box-shadow: 4px 4px 0 0 var(--nb-ink);
  background: var(--nb-postit);
}

.nb-pager__btn:active:not(:disabled),
.nb-pager__dot:active:not(:disabled) {
  transform: translate(2px, 2px);
  box-shadow: 1px 1px 0 0 var(--nb-ink);
}

.nb-pager__dot--active {
  background: var(--nb-postit) !important;
  color: var(--nb-ink) !important;
}

.nb-pager__btn:disabled,
.nb-pager__dot:disabled {
  border-color: var(--nb-grey);
  color: var(--nb-grey);
  cursor: not-allowed;
  opacity: 0.75;
  box-shadow: none;
}

.nb-pager__gap {
  padding: 0 1px;
  color: var(--nb-grey);
  font-weight: 700;
}

.nb-pager__meta {
  color: var(--nb-grey);
  font-size: 0.75rem;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.nb-pager__size {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-left: auto;
}

.nb-pager__size-label {
  color: var(--nb-ink);
  font-family: var(--font-display, inherit);
  font-size: 0.8rem;
  font-weight: 700;
}

.nb-pager__size-trigger {
  width: 96px;
  flex: 0 0 auto;
}

/* 让触发器也变成粗野风直边小块（作用于 GroupedSelectMenu 内部类，需深选） */
.nb-pager__size-trigger :deep(.grouped-select-trigger) {
  border: 2px solid var(--nb-ink) !important;
  border-radius: var(--radius, 2px) !important;
  background: hsl(var(--card)) !important;
  box-shadow: 2px 2px 0 0 var(--nb-ink) !important;
  font-weight: 700 !important;
  min-height: 2rem !important;
  padding-top: 0.2rem !important;
  padding-bottom: 0.2rem !important;
  transition: transform 0.08s ease, box-shadow 0.08s ease, background-color 0.12s ease;
}

.nb-pager__size-trigger :deep(.grouped-select-trigger:hover) {
  border-color: var(--nb-ink) !important;
  background: var(--nb-postit) !important;
  transform: translate(-1px, -1px);
  box-shadow: 3px 3px 0 0 var(--nb-ink) !important;
}

html[data-theme="dark"] .nb-pager__btn,
html[data-theme="dark"] .nb-pager__dot {
  background: var(--bauhaus-card);
  /* 深色 ink 是近白，硬阴影会变成白框；改用柔和深色投影 */
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.5) !important;
}

html[data-theme="dark"] .nb-pager__btn:hover:not(:disabled),
html[data-theme="dark"] .nb-pager__dot:hover:not(:disabled) {
  box-shadow: 0 3px 9px rgba(0, 0, 0, 0.55) !important;
  transform: translate(-1px, -1px);
}

html[data-theme="dark"] .nb-pager__dot--active,
html[data-theme="dark"] .nb-pager__btn:hover:not(:disabled),
html[data-theme="dark"] .nb-pager__dot:hover:not(:disabled) {
  background: var(--bauhaus-postit) !important;
  color: var(--nb-ink) !important;
}

html[data-theme="dark"] .nb-pager__size-trigger :deep(.grouped-select-trigger) {
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.5) !important;
}

html[data-theme="dark"] .nb-pager__size-trigger :deep(.grouped-select-trigger:hover) {
  box-shadow: 0 3px 9px rgba(0, 0, 0, 0.55) !important;
}
</style>
