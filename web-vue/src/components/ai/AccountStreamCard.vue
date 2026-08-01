<template>
  <article
    class="account-stream-card"
    :class="[
      densityClass,
      rowClass(item),
      selected ? 'is-selected' : '',
    ]"
  >
    <div class="account-stream-card__check">
      <Checkbox
        :model-value="selected"
        :disabled="item.is_demo"
        @update:model-value="emit('toggle-select', Boolean($event))"
      />
    </div>

    <div class="account-stream-card__quota" :title="`图片额度：${accountQuotaText(item)}`">
      <span class="account-stream-card__quota-label">额度</span>
      <span class="account-stream-card__quota-value">{{ accountQuotaText(item) }}</span>
    </div>

    <div class="account-stream-card__main min-w-0">
      <div class="account-stream-card__title-row">
        <h3 class="account-stream-card__title truncate" :title="accountPrimaryText(item)">
          {{ accountPrimaryText(item) }}
        </h3>
        <StatusDetailPill
          class="account-stream-card__status"
          :label="statusText(item)"
          :tone-class="`${statusClass(item)} border-border`"
          title="状态详情"
          detail-label="状态说明"
          raw-error-label="原始报错"
          :card-class="statusCardClass"
          :detail="statusDetail"
          :raw-error="statusRawError(item)"
        />
      </div>
      <p class="account-stream-card__sub truncate font-mono" :title="accountSecondaryText(item)">
        {{ accountSecondaryText(item) }}
      </p>
      <div class="account-stream-card__tags">
        <ChannelBadge :channel="accountChannelId" size="xs" />
        <StatusPill
          :label="accountSourceText(item)"
          tone-class="border-cyan-500/40 bg-cyan-500/10 text-cyan-600"
        />
        <button
          type="button"
          class="account-stream-card__token-btn text-left"
          title="点击复制完整 Token"
          @click="emit('copy-token')"
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
    </div>

    <div class="account-stream-card__meta">
      <div class="account-stream-card__metric">
        <span class="account-stream-card__metric-label">成功 / 失败</span>
        <div class="account-stream-card__metric-nums font-mono tabular-nums">
          <span class="text-emerald-600">{{ item.success_count || 0 }}</span>
          <span class="mx-1 text-muted-foreground/60">/</span>
          <span class="text-rose-600">{{ item.failure_count || 0 }}</span>
        </div>
      </div>
      <div class="account-stream-card__metric">
        <span class="account-stream-card__metric-label">创建</span>
        <span class="account-stream-card__metric-value table-num">{{ accountCreatedText(item) }}</span>
      </div>
      <div class="account-stream-card__metric">
        <span class="account-stream-card__metric-label">恢复</span>
        <span class="account-stream-card__metric-value table-num">{{ accountRestoreText(item) }}</span>
      </div>
    </div>

    <div class="account-stream-card__actions">
      <AccountActionButtons
        :item="item"
        :refreshing="refreshing"
        :resetting="resetting"
        :relogin-busy="reloginBusy"
        align="end"
        @edit="emit('edit')"
        @toggle-enabled="emit('toggle-enabled')"
        @refresh-token="emit('refresh-token')"
        @relogin="emit('relogin')"
        @reset-state="emit('reset-state')"
        @remove="emit('remove')"
      />
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Checkbox, StatusDetailPill, StatusPill } from 'nanocat-ui'
import type { Account } from '@/api/accounts'
import AccountActionButtons from '@/components/ai/AccountActionButtons.vue'
import ChannelBadge from '@/components/ai/ChannelBadge.vue'
import { resolveAccountChannelId } from '@/config/channels'
import {
  accountCreatedText,
  accountPrimaryText,
  accountQuotaText,
  accountRestoreText,
  accountSecondaryText,
  accountSourceText,
  accountTokenPreview,
  rowClass,
  statusClass,
  statusRawError,
  statusText,
} from '@/views/accounts/viewUtils'

const props = defineProps<{
  item: Account
  selected: boolean
  statusDetail: string
  statusCardClass?: string
  refreshing?: boolean
  resetting?: boolean
  reloginBusy?: boolean
  density?: 'comfortable' | 'dense'
}>()

const accountChannelId = computed(() => resolveAccountChannelId(props.item.source_type))

const emit = defineEmits<{
  (e: 'toggle-select', value: boolean): void
  (e: 'copy-token'): void
  (e: 'edit'): void
  (e: 'toggle-enabled'): void
  (e: 'refresh-token'): void
  (e: 'relogin'): void
  (e: 'reset-state'): void
  (e: 'remove'): void
}>()

const densityClass = computed(() =>
  props.density === 'dense' ? 'account-stream-card--dense' : 'account-stream-card--comfortable',
)
</script>

<style scoped>
.account-stream-card {
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 0.75rem 1rem;
  border: 2px solid var(--bauhaus-ink, #2d2d2d);
  border-radius: var(--radius, 0.125rem);
  background: var(--bauhaus-card, #fff);
  box-shadow: var(--shadow-hard-sm, 2px 2px 0 0 var(--bauhaus-ink, #2d2d2d));
  transition: transform 0.12s ease, box-shadow 0.12s ease;
}

.account-stream-card--comfortable {
  padding: 0.8rem 0.95rem;
}

.account-stream-card--dense {
  padding: 0.5rem 0.7rem;
  gap: 0.5rem 0.75rem;
}

.account-stream-card--dense .account-stream-card__title {
  font-size: 0.85rem;
}

.account-stream-card--dense .account-stream-card__sub {
  margin-top: 0.12rem;
  font-size: 0.68rem;
}

.account-stream-card--dense .account-stream-card__quota {
  min-width: 3.4rem;
  padding: 0.3rem 0.4rem;
}

.account-stream-card--dense .account-stream-card__quota-value {
  font-size: 0.92rem;
}

.account-stream-card--dense .account-stream-card__tags {
  margin-top: 0.3rem;
  gap: 0.3rem;
}

.account-stream-card--dense .account-stream-card__meta {
  min-width: 7rem;
  gap: 0.2rem;
}

.account-stream-card--dense .account-stream-card__metric-label,
.account-stream-card--dense .account-stream-card__metric-value {
  font-size: 0.68rem;
}

.account-stream-card--dense .account-stream-card__metric-nums {
  font-size: 0.78rem;
}

.account-stream-card:hover {
  transform: translate(-1px, -1px);
  box-shadow: var(--shadow-hard, 3px 3px 0 0 var(--bauhaus-ink, #2d2d2d));
}

.account-stream-card.is-selected {
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 7%, var(--bauhaus-card, #fff));
  box-shadow: 3px 3px 0 0 var(--bauhaus-blue, #2d5da1);
}

.account-stream-card__check {
  display: flex;
  align-items: center;
}

.account-stream-card__quota {
  display: flex;
  min-width: 4.2rem;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.1rem;
  padding: 0.5rem 0.6rem;
  border: 2px solid color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 55%, transparent);
  border-radius: var(--radius, 0.125rem);
  background: color-mix(in srgb, var(--bauhaus-blue, #2d5da1) 14%, transparent);
  color: var(--bauhaus-blue, #2d5da1);
}

.account-stream-card__quota-label {
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  opacity: 0.75;
}

.account-stream-card__quota-value {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 1.05rem;
  font-weight: 700;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.account-stream-card__title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.account-stream-card__title {
  margin: 0;
  font-size: 0.92rem;
  font-weight: 650;
  line-height: 1.2;
  color: hsl(var(--foreground));
}

.account-stream-card__status {
  flex-shrink: 0;
}

.account-stream-card__sub {
  margin: 0.18rem 0 0;
  font-size: 0.72rem;
  line-height: 1.2;
  color: hsl(var(--muted-foreground));
}

.account-stream-card__tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  margin-top: 0.4rem;
}

.account-stream-card__token-btn {
  display: inline-flex;
}

.account-stream-card__meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.3rem;
  min-width: 7.5rem;
}

.account-stream-card__metric {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  width: 100%;
  gap: 0.5rem;
}

.account-stream-card__metric-label {
  font-size: 0.65rem;
  color: hsl(var(--muted-foreground));
  letter-spacing: 0.02em;
  white-space: nowrap;
}

.account-stream-card__metric-value {
  font-size: 0.72rem;
  color: hsl(var(--muted-foreground));
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.account-stream-card__metric-nums {
  font-size: 0.82rem;
  line-height: 1;
}

.account-stream-card__actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
}

html[data-theme='dark'] .account-stream-card {
  box-shadow: var(--shadow-hard-sm, 0 2px 8px rgba(0, 0, 0, 0.45));
}

html[data-theme='dark'] .account-stream-card:hover,
html[data-theme='dark'] .account-stream-card.is-selected {
  box-shadow: var(--shadow-hard, 0 4px 12px rgba(0, 0, 0, 0.55));
}

/* 双列：整体更扁、更紧凑 */
.account-stream-card--dense .account-stream-card__meta {
  min-width: 7rem;
  gap: 0.2rem;
}

@media (max-width: 900px) {
  .account-stream-card {
    grid-template-columns: auto auto minmax(0, 1fr);
    grid-template-areas:
      'check quota main'
      'meta meta meta'
      'actions actions actions';
  }

  .account-stream-card__check { grid-area: check; }
  .account-stream-card__quota { grid-area: quota; }
  .account-stream-card__main { grid-area: main; }
  .account-stream-card__meta {
    grid-area: meta;
    flex-direction: row;
    flex-wrap: wrap;
    justify-content: flex-start;
    align-items: center;
    min-width: 0;
    gap: 0.5rem 1.25rem;
  }
  .account-stream-card__metric {
    width: auto;
    justify-content: flex-start;
    gap: 0.4rem;
  }
  .account-stream-card__actions {
    grid-area: actions;
    justify-content: flex-start;
  }
}

@media (max-width: 640px) {
  .account-stream-card {
    border-width: 1.5px;
    box-shadow: 1.5px 1.5px 0 0 var(--bauhaus-ink, #2d2d2d);
    gap: 0.5rem 0.65rem;
  }

  .account-stream-card--comfortable {
    padding: 0.65rem 0.75rem;
  }

  .account-stream-card--dense {
    padding: 0.45rem 0.55rem;
  }

  .account-stream-card:hover {
    transform: none;
    box-shadow: 2px 2px 0 0 var(--bauhaus-ink, #2d2d2d);
  }

  .account-stream-card.is-selected {
    box-shadow: 2px 2px 0 0 var(--bauhaus-blue, #2d5da1);
  }

  .account-stream-card__quota {
    min-width: 3.2rem;
    padding: 0.35rem 0.4rem;
    border-width: 1.5px;
  }

  .account-stream-card__quota-value {
    font-size: 0.95rem;
  }

  .account-stream-card__title {
    font-size: 0.85rem;
  }

  .account-stream-card__sub {
    font-size: 0.68rem;
  }

  .account-stream-card__tags {
    margin-top: 0.3rem;
    gap: 0.28rem;
  }

  .account-stream-card__meta {
    gap: 0.4rem 0.85rem;
  }

  html[data-theme='dark'] .account-stream-card {
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.4);
  }

  html[data-theme='dark'] .account-stream-card:hover,
  html[data-theme='dark'] .account-stream-card.is-selected {
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.5);
  }
}
</style>
