<template>
  <div class="max-w-3xl">
    <FormSection collapsible title="画布入口" subtitle="开启后顶部导航会显示无限画布入口，并自动带上当前接口地址和密钥。">
      <div class="settings-block-stack">
        <section class="settings-block">
          <header class="settings-block__header">
            <p class="settings-block__title">开关</p>
            <p class="settings-block__desc">关闭后隐藏导航入口。</p>
          </header>
          <div class="settings-check-grid settings-check-grid--single">
            <div class="settings-check-item">
              <div class="settings-check-control">
                <Checkbox v-model="canvas.enabled">启用无限画布入口</Checkbox>
              </div>
            </div>
          </div>
        </section>
        <section class="settings-block">
          <header class="settings-block__header">
            <p class="settings-block__title">地址</p>
            <p class="settings-block__desc">入口会附带当前服务地址与密钥参数。</p>
          </header>
          <FormField label="无限画布地址">
            <Input
              v-model.trim="canvas.url"
              block
              root-class="font-mono"
              placeholder="https://canvas.best"
            />
          </FormField>
        </section>
      </div>
    </FormSection>
  </div>
</template>

<script setup lang="ts">
import { Checkbox, FormField, Input } from 'nanocat-ui'
import FormSection from '@/components/ai/FormSection.vue'
import type { Settings } from '@/types/api'

type CanvasSettings = Settings['third_party_apps']['infinite_canvas']

defineProps<{
  canvas: CanvasSettings
}>()
</script>
