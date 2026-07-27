<template>
  <div class="login-page min-h-[100dvh] px-4">
    <div class="login-grid">
      <!-- 左：色块宣言（不对称构图） -->
      <aside class="login-manifesto" aria-hidden="true">
        <div class="login-manifesto__block login-manifesto__block--blue" />
        <div class="login-manifesto__block login-manifesto__block--red" />
        <div class="login-manifesto__block login-manifesto__block--yellow" />
        <div class="login-manifesto__block login-manifesto__block--ink" />
        <p class="login-manifesto__word">FORM</p>
        <p class="login-manifesto__word login-manifesto__word--offset">FOLLOWS</p>
        <p class="login-manifesto__word">FUNCTION</p>
      </aside>

      <!-- 右：登录卡 -->
      <div class="login-card w-full max-w-md overflow-hidden border-2 border-[var(--bauhaus-ink)] bg-card">
        <div class="grid h-2 grid-cols-3" aria-hidden="true">
          <span class="bg-[var(--bauhaus-blue)]" />
          <span class="bg-[var(--bauhaus-red)]" />
          <span class="bg-[var(--bauhaus-yellow)]" />
        </div>

        <div class="p-10">
          <div>
            <div class="mb-6 flex items-center gap-4">
              <BauhausBrandMark :size="48" root-class="text-foreground shrink-0" />
              <div class="min-w-0">
                <p class="bh-kicker">Console</p>
                <h1 class="mt-1 text-3xl font-bold tracking-tight text-foreground">
                  JoveMage
                </h1>
              </div>
            </div>
            <p class="text-sm text-[var(--bauhaus-grey)]">
              使用管理密钥进入控制台
            </p>
          </div>

          <form class="mt-8 space-y-6" @submit.prevent="handleLogin">
            <div class="space-y-2">
              <label for="password" class="ui-field-label">
                管理密钥
              </label>
              <Input
                id="password"
                v-model="password"
                type="password"
                size="md"
                block
                placeholder="输入 Bearer key"
                :disabled="isLoading"
              />
            </div>

            <Button
              type="submit"
              size="md"
              variant="primary"
              block
              :disabled="isLoading || !password"
            >
              {{ isLoading ? '登录中...' : '登录' }}
            </Button>
          </form>

          <div class="mt-8 flex items-center gap-3 text-xs text-[var(--bauhaus-grey)]">
            <a
              href="https://github.com/jiujiu532/JoveMage"
              target="_blank"
              rel="noopener noreferrer"
              class="underline-offset-2 transition-colors hover:text-foreground hover:underline"
            >
              源码仓库
            </a>
            <span class="inline-block h-1 w-1 bg-[var(--bauhaus-grey)]" aria-hidden="true" />
            <span>自托管控制台</span>
          </div>
        </div>

        <div class="flex items-end justify-end gap-0" aria-hidden="true">
          <span class="h-3 w-3 bg-[var(--bauhaus-blue)]" />
          <span class="h-3 w-3 bg-[var(--bauhaus-red)]" />
          <span class="h-3 w-3 bg-[var(--bauhaus-yellow)]" />
          <span class="h-3 w-3 bg-[var(--bauhaus-ink)]" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Input } from 'nanocat-ui'
import BauhausBrandMark from '@/components/ui/BauhausBrandMark.vue'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const toast = useToast()

const password = ref('')
const isLoading = ref(false)

async function handleLogin() {
  if (!password.value) return

  isLoading.value = true

  try {
    const loggedIn = await authStore.login(password.value)
    if (!loggedIn) {
      toast.error('密钥无效或已失效。')
      return
    }
    await router.push(authStore.isUser ? { name: 'studio' } : { name: 'dashboard' })
  } catch (error: any) {
    toast.error(error.message || '登录失败，请检查密码。')
  } finally {
    isLoading.value = false
  }
}
</script>

<style scoped>
.login-page {
  background-color: var(--bauhaus-paper, #fdfbf7);
  background-image: var(--paper-dots, radial-gradient(#c9c2b4 1px, transparent 1px));
  background-size: 24px 24px;
  background-attachment: fixed;
}

.login-grid {
  display: grid;
  min-height: 100dvh;
  place-items: center;
  gap: 2.5rem;
  padding: 2rem 0;
}

@media (min-width: 1024px) {
  .login-grid {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 0;
    place-items: stretch;
    padding: 0;
  }

  .login-card {
    align-self: center;
    justify-self: start;
    margin-left: 8%;
  }
}

.login-manifesto {
  display: none;
}

@media (min-width: 1024px) {
  .login-manifesto {
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: 1fr 1fr auto auto auto;
    gap: 8px;
    padding: 12% 10% 12% 14%;
    background: var(--bauhaus-ink, #2d2d2d);
    color: var(--bauhaus-paper, #fdfbf7);
    min-height: 100dvh;
  }
}

.login-manifesto__block {
  min-height: 0;
}

.login-manifesto__block--blue {
  background: var(--bauhaus-blue, #2d5da1);
  grid-column: 1;
  grid-row: 1;
}

.login-manifesto__block--red {
  background: var(--bauhaus-red, #ff4d4d);
  grid-column: 2;
  grid-row: 1 / span 2;
  clip-path: polygon(0 0, 100% 0, 100% 100%, 0 70%);
}

.login-manifesto__block--yellow {
  background: var(--bauhaus-yellow, #fff9c4);
  grid-column: 1;
  grid-row: 2;
  border-radius: 50%;
  aspect-ratio: 1;
  width: 70%;
  justify-self: start;
  align-self: end;
  border: 2px solid var(--bauhaus-ink, #2d2d2d);
}

.login-manifesto__block--ink {
  background: var(--bauhaus-paper, #fdfbf7);
  grid-column: 1 / span 2;
  height: 8px;
  align-self: end;
  margin-top: 1rem;
}

.login-manifesto__word {
  grid-column: 1 / span 2;
  font-family: var(--font-display);
  font-size: clamp(2rem, 4vw, 3.25rem);
  font-weight: 700;
  letter-spacing: -0.04em;
  line-height: 0.95;
  margin: 0;
}

.login-manifesto__word--offset {
  color: #fff9c4;
  padding-left: 12%;
}

.login-card {
  border-radius: var(--radius);
  box-shadow: none;
}

html[data-theme='dark'] .login-page {
  background-color: #141414;
  background-image:
    linear-gradient(to right, rgba(250, 250, 250, 0.04) 1px, transparent 1px),
    linear-gradient(to bottom, rgba(250, 250, 250, 0.04) 1px, transparent 1px);
}

html[data-theme='dark'] .login-card {
  border-color: hsl(var(--border));
}
</style>
