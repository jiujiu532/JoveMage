<template>
  <ModalShell :open="open" max-width="28rem" :z-index="160" :close-on-backdrop="false">
    <ModalHeader
      :title="title"
      :bordered="false"
      compact
      @close="handleCancel"
    />
    <ModalBody density="compact" class="space-y-3">
      <div class="account-global-confirm__meta space-y-1.5 text-sm">
        <p>
          <span class="text-muted-foreground">渠道：</span>
          <span class="font-medium text-foreground">{{ channelLabel }}</span>
        </p>
        <p>
          <span class="text-muted-foreground">范围：</span>
          <span class="font-medium text-foreground">{{ scopeText }}</span>
        </p>
        <p>
          <span class="text-muted-foreground">数量：</span>
          <span class="font-medium tabular-nums text-foreground">{{ count }}</span>
        </p>
        <p v-if="consequence" class="leading-relaxed text-muted-foreground">
          <span class="text-muted-foreground">后果：</span>{{ consequence }}
        </p>
      </div>

      <div
        v-if="policyLines.length"
        class="account-global-confirm__policy rounded-md border border-border bg-muted/20 px-3 py-2 text-xs leading-relaxed text-muted-foreground"
      >
        <p v-for="(line, index) in policyLines" :key="index">{{ line }}</p>
      </div>

      <div v-if="requireTypedConfirm" class="space-y-1.5">
        <p class="text-xs font-medium text-rose-600">
          ⚠ 高危操作：请输入 DELETE 以确认
        </p>
        <Input
          :model-value="typedConfirm"
          block
          placeholder="DELETE"
          autocomplete="off"
          @update:model-value="typedConfirm = String($event || '').trim()"
        />
      </div>

      <div v-if="muteOptions.length" class="space-y-1.5">
        <p class="text-xs font-medium text-muted-foreground">提醒设置</p>
        <label
          v-for="option in muteOptions"
          :key="option.value"
          class="flex cursor-pointer items-center gap-2 text-xs text-foreground"
        >
          <input
            v-model="muteMode"
            type="radio"
            class="account-global-confirm__radio"
            :value="option.value"
            name="account-global-confirm-mute"
          >
          <span>{{ option.label }}</span>
        </label>
      </div>
    </ModalBody>
    <ModalFooter compact>
      <Button size="sm" variant="outline" @click="handleCancel">
        {{ cancelText }}
      </Button>
      <Button
        size="sm"
        :variant="danger ? 'primary' : 'primary'"
        :root-class="danger ? 'account-global-confirm__danger-btn' : ''"
        :disabled="!canConfirm"
        @click="handleConfirm"
      >
        {{ confirmText }}
      </Button>
    </ModalFooter>
  </ModalShell>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Button, Input } from 'nanocat-ui'
import ModalBody from './ModalBody.vue'
import ModalFooter from './ModalFooter.vue'
import ModalHeader from './ModalHeader.vue'
import ModalShell from './ModalShell.vue'
import type { ConfirmMuteMode } from '@/views/accounts/accountConfirmMute'

const props = withDefaults(defineProps<{
  open: boolean
  title?: string
  channelLabel?: string
  scopeText?: string
  count?: number
  consequence?: string
  policyLines?: string[]
  requireTypedConfirm?: boolean
  danger?: boolean
  confirmText?: string
  cancelText?: string
  /** 可选的提醒降频档；空数组表示不展示 */
  muteOptions?: Array<{ value: ConfirmMuteMode; label: string }>
}>(), {
  title: '确认操作',
  channelLabel: '当前渠道',
  scopeText: '',
  count: 0,
  consequence: '',
  policyLines: () => [],
  requireTypedConfirm: false,
  danger: false,
  confirmText: '确认',
  cancelText: '取消',
  muteOptions: () => [],
})

const emit = defineEmits<{
  (e: 'confirm', payload: { muteMode: ConfirmMuteMode }): void
  (e: 'cancel'): void
}>()

const typedConfirm = ref('')
const muteMode = ref<ConfirmMuteMode>('always')

watch(() => props.open, (open) => {
  if (open) {
    typedConfirm.value = ''
    muteMode.value = 'always'
  }
})

const canConfirm = computed(() => {
  if (!props.requireTypedConfirm) return true
  return typedConfirm.value === 'DELETE'
})

function handleConfirm() {
  if (!canConfirm.value) return
  emit('confirm', { muteMode: muteMode.value })
}

function handleCancel() {
  emit('cancel')
}
</script>

<style scoped>
.account-global-confirm__radio {
  accent-color: hsl(var(--primary));
}

.account-global-confirm__danger-btn {
  border-color: hsl(var(--destructive) / 0.55) !important;
  background: hsl(var(--destructive)) !important;
  color: hsl(var(--destructive-foreground, 0 0% 100%)) !important;
}

.account-global-confirm__danger-btn:disabled {
  opacity: 0.55;
}
</style>
