<template>
  <Teleport to="body">
    <div v-if="file" class="lightbox" @click.self="$emit('close')">
      <div class="lightbox-content">
        <button class="lightbox-close" @click="$emit('close')">
          <Icon icon="lucide:x" />
        </button>
        <img
          :src="imageUrl"
          :alt="file.filename"
          class="lightbox-media"
        />
        <div class="lightbox-info">
          <span class="max-w-[24rem] truncate" :title="file.path">{{ file.filename }}</span>
          <span v-if="sizeLabel">{{ sizeLabel }}</span>
          <span v-if="file.created_at">{{ file.created_at }}</span>
          <button v-if="canShowDownload" class="lightbox-btn" @click="emitFile('download')">
            <Icon icon="lucide:download" />
            下载
          </button>
          <button v-if="canShowCopy" class="lightbox-btn" @click="emitFile('copy')">
            <Icon :icon="copied ? 'lucide:check' : 'lucide:copy'" />
            {{ copied ? '已复制' : '复制链接' }}
          </button>
          <button v-if="canShowTag" class="lightbox-btn" @click="emitFile('edit-tags')">
            <Icon icon="lucide:tag" />
            标签
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Icon } from '@iconify/vue'
import type { GalleryFile } from '@/api/gallery'

const props = withDefaults(defineProps<{
  file: GalleryFile | null
  imageUrl: string
  sizeLabel: string
  copied: boolean
  showActions?: boolean
  showDownloadAction?: boolean
  showCopyAction?: boolean
  showTagAction?: boolean
}>(), {
  showActions: true,
  showDownloadAction: true,
  showCopyAction: true,
  showTagAction: true,
})

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'download', file: GalleryFile): void
  (e: 'copy', file: GalleryFile): void
  (e: 'edit-tags', file: GalleryFile): void
}>()

const canShowDownload = computed(() => props.showActions && props.showDownloadAction)
const canShowCopy = computed(() => props.showActions && props.showCopyAction)
const canShowTag = computed(() => props.showActions && props.showTagAction)

function emitFile(event: 'download' | 'copy' | 'edit-tags') {
  if (!props.file) return
  emit(event, props.file)
}
</script>

<style scoped>
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 140;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: var(--overlay-backdrop);
}

.lightbox-content {
  position: relative;
  display: flex;
  max-width: 92vw;
  max-height: 92vh;
  flex-direction: column;
  align-items: center;
}

.lightbox-close {
  position: absolute;
  top: -40px;
  right: -4px;
  display: flex;
  width: 34px;
  height: 34px;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: var(--radius);
  background: rgba(255, 255, 255, 0.14);
  color: white;
  cursor: pointer;
  transition: background 0.15s;
}

.lightbox-close:hover {
  background: rgba(255, 255, 255, 0.28);
}

.lightbox-media {
  max-width: 100%;
  max-height: 80vh;
  border-radius: var(--gallery-radius, var(--radius));
  object-fit: contain;
}

.lightbox-info {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin-top: 12px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.78);
}

.lightbox-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  border: 1px solid rgba(255, 255, 255, 0.35);
  border-radius: var(--radius);
  background: transparent;
  color: white;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}

.lightbox-btn:hover {
  border-color: rgba(255, 255, 255, 0.65);
  background: rgba(255, 255, 255, 0.1);
}

/* 窄屏：关闭钮收进画面内，操作钮加大，尊重 safe-area */
@media (max-width: 640px) {
  .lightbox {
    padding:
      max(12px, env(safe-area-inset-top, 0px))
      max(12px, env(safe-area-inset-right, 0px))
      max(16px, env(safe-area-inset-bottom, 0px))
      max(12px, env(safe-area-inset-left, 0px));
  }

  .lightbox-content {
    max-width: 100%;
    max-height: 100%;
    width: 100%;
  }

  .lightbox-close {
    top: 8px;
    right: 8px;
    z-index: 3;
    width: 40px;
    height: 40px;
    border-width: 1.5px;
    background: rgba(0, 0, 0, 0.45);
  }

  .lightbox-media {
    max-height: min(70vh, calc(100dvh - 9rem));
  }

  .lightbox-info {
    gap: 8px;
    margin-top: 10px;
    padding-bottom: env(safe-area-inset-bottom, 0px);
    font-size: 12px;
  }

  .lightbox-btn {
    min-height: 40px;
    padding: 8px 14px;
    font-size: 13px;
    gap: 6px;
  }
}
</style>
