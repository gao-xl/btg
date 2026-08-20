<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import {
  Bot,
  CircleGauge,
  Clock3,
  Cpu,
  KeyRound,
  Link2,
  Lock,
  Power,
  RefreshCcw,
  Save,
  Server,
  Settings2,
  ShieldAlert,
  ShieldCheck,
  WifiOff,
} from '@lucide/vue'
import ToggleSwitch from '../components/ToggleSwitch.vue'
import { gatewayApi, getApiError } from '../services/api'

const settings = reactive({
  maxSystemIntensity: 0,
  watchdogTimeoutSec: 3,
  edgingTargetHr: 135,
  systemMode: 'manual',
  ai: {
    provider: 'mock',
    baseUrl: '',
    model: '',
    apiKey: '',
    hasApiKey: false,
  },
})
const loadedSnapshot = ref(null)
const loading = ref(true)
const saving = ref(false)
const loadError = ref('')
const saveError = ref('')
const saveMessage = ref('')
const confirmIncrease = ref(false)

const features = ref([])
const featuresLoading = ref(true)
const featuresError = ref('')
const featuresSaving = ref(false)
const featuresMessage = ref('')

const moduleFeatures = computed(() => features.value.filter((f) => f.group === 'module'))
const serviceFeatures = computed(() => features.value.filter((f) => f.group === 'service'))

const validationErrors = computed(() => {
  const errors = []
  if (
    !Number.isFinite(Number(settings.maxSystemIntensity)) ||
    settings.maxSystemIntensity < 0 ||
    settings.maxSystemIntensity > 100
  ) {
    errors.push('全局最高强度必须在 0–100。')
  }
  if (
    !Number.isFinite(Number(settings.watchdogTimeoutSec)) ||
    settings.watchdogTimeoutSec < 0.25 ||
    settings.watchdogTimeoutSec > 60
  ) {
    errors.push('看门狗超时必须在 0.25–60 秒。')
  }
  if (
    !Number.isFinite(Number(settings.edgingTargetHr)) ||
    settings.edgingTargetHr < 0 ||
    settings.edgingTargetHr > 240
  ) {
    errors.push('心率目标值必须在 0–240 BPM。')
  }
  const aiProviders = ['mock', 'openai', 'anthropic']
  if (!aiProviders.includes(settings.ai.provider)) {
    errors.push('AI 厂商必须是 mock / openai / anthropic 之一。')
  }
  if (settings.ai.provider !== 'mock') {
    const hasNewKey = !!settings.ai.apiKey.trim()
    if (!hasNewKey && !settings.ai.hasApiKey) {
      errors.push('启用真实 AI 前必须先填写 API Key。')
    }
    if (!settings.ai.model.trim()) {
      errors.push('openai / anthropic 必须填写模型名。')
    }
    if (settings.ai.baseUrl.trim() && !/^https?:\/\/.+/i.test(settings.ai.baseUrl.trim())) {
      errors.push('自定义 API 地址必须以 http:// 或 https:// 开头。')
    }
  }
  return errors
})

const isDirty = computed(() => {
  if (!loadedSnapshot.value) return false
  return JSON.stringify(settings) !== JSON.stringify(loadedSnapshot.value)
})

const raisesIntensity = computed(() => {
  if (!loadedSnapshot.value) return false
  return Number(settings.maxSystemIntensity) > Number(loadedSnapshot.value.maxSystemIntensity)
})

const canSave = computed(
  () =>
    isDirty.value &&
    validationErrors.value.length === 0 &&
    (!raisesIntensity.value || confirmIncrease.value) &&
    !saving.value,
)

function numberFrom(source, snakeKey, camelKey, fallback) {
  const value = source?.[snakeKey] ?? source?.[camelKey]
  return value == null || !Number.isFinite(Number(value)) ? fallback : Number(value)
}

function applySettings(payload) {
  const ai = payload?.ai ?? {}
  const next = {
    maxSystemIntensity: numberFrom(payload, 'max_system_intensity', 'maxSystemIntensity', 0),
    watchdogTimeoutSec: numberFrom(payload, 'watchdog_timeout_sec', 'watchdogTimeoutSec', 3),
    edgingTargetHr: numberFrom(payload, 'edging_target_hr', 'edgingTargetHr', 135),
    systemMode: payload?.system_mode ?? payload?.systemMode ?? 'manual',
    ai: {
      provider: ai.provider ?? 'mock',
      baseUrl: ai.base_url ?? ai.baseUrl ?? '',
      model: ai.model ?? '',
      apiKey: ai.api_key ?? ai.apiKey ?? '',
      hasApiKey: !!ai.has_api_key,
    },
  }
  Object.assign(settings, next)
  // 深拷贝快照（含嵌套 ai），避免 isDirty 比较受引用共享影响
  loadedSnapshot.value = JSON.parse(JSON.stringify(next))
  confirmIncrease.value = false
}

async function loadSettings() {
  loading.value = true
  loadError.value = ''
  saveMessage.value = ''
  try {
    const payload = await gatewayApi.getSettings()
    applySettings(payload)
  } catch (error) {
    loadedSnapshot.value = null
    loadError.value = `无法读取网关设置：${getApiError(error)}`
  } finally {
    loading.value = false
  }
}

function resetForm() {
  if (!loadedSnapshot.value) return
  Object.assign(settings, loadedSnapshot.value)
  confirmIncrease.value = false
  saveError.value = ''
  saveMessage.value = ''
}

async function saveSettings() {
  if (!canSave.value) return
  saving.value = true
  saveError.value = ''
  saveMessage.value = ''

  const payload = {
    max_system_intensity: Number(settings.maxSystemIntensity),
    watchdog_timeout_sec: Number(settings.watchdogTimeoutSec),
    edging_target_hr: Number(settings.edgingTargetHr),
    system_mode: settings.systemMode,
    ai: {
      provider: settings.ai.provider,
      base_url: settings.ai.baseUrl.trim(),
      model: settings.ai.model.trim(),
      // 空字符串表示“不修改已存密钥”，由后端保留原值；填入新值则覆盖。
      api_key: settings.ai.apiKey.trim(),
    },
  }

  try {
    const result = await gatewayApi.updateSettings(payload)
    applySettings({ ...payload, ...result })
    saveMessage.value = '网关已确认热更新。新上限只约束后续输出，不会恢复已急停的会话。'
  } catch (error) {
    saveError.value = `更新失败：${getApiError(error)}`
  } finally {
    saving.value = false
  }
}

async function loadFeatures() {
  featuresLoading.value = true
  featuresError.value = ''
  featuresMessage.value = ''
  try {
    features.value = await gatewayApi.listFeatures()
  } catch (error) {
    featuresError.value = `无法读取功能开关：${getApiError(error)}`
  } finally {
    featuresLoading.value = false
  }
}

async function toggleFeature(feature) {
  if (feature.locked || featuresSaving.value) return
  const previous = feature.enabled
  const next = !previous
  feature.enabled = next
  featuresSaving.value = true
  featuresMessage.value = ''
  featuresError.value = ''
  try {
    features.value = await gatewayApi.updateFeatures({ [feature.key]: next })
    featuresMessage.value = `功能「${feature.label}」已${next ? '启用' : '停用'}并热更新。`
  } catch (error) {
    feature.enabled = previous
    featuresError.value = `更新功能开关失败：${getApiError(error)}`
  } finally {
    featuresSaving.value = false
  }
}

onMounted(() => {
  loadSettings()
  loadFeatures()
})

function reloadAll() {
  loadSettings()
  loadFeatures()
}
</script>

<template>
  <main
    id="main-content"
    class="space-y-6"
    tabindex="-1"
  >
    <header class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div>
        <div
          class="mb-2 flex items-center gap-2 font-mono text-xs uppercase tracking-[0.28em] text-cyan-300"
        >
          <Settings2
            class="size-4"
            aria-hidden="true"
          />
          System Configuration
        </div>
        <h1 class="font-display text-3xl font-bold tracking-tight text-white sm:text-4xl">
          全局配置中心
        </h1>
        <p class="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
          通过
          <code class="font-mono text-cyan-200">/api/v1/settings</code>
          热更新网关边界。提高强度上限需要单独确认。
        </p>
      </div>
      <button
        class="cyber-button-secondary"
        type="button"
        :disabled="loading || saving || featuresSaving"
        @click="reloadAll"
      >
        <RefreshCcw
          class="size-4"
          :class="loading ? 'animate-spin' : ''"
          aria-hidden="true"
        />
        重新读取
      </button>
    </header>

    <div
      v-if="loadError"
      class="status-error flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
      role="alert"
    >
      <span class="flex items-center gap-2"
        ><WifiOff
          class="size-4 shrink-0"
          aria-hidden="true"
        />{{ loadError }}</span
      >
      <button
        class="cyber-button-secondary shrink-0"
        type="button"
        @click="loadSettings"
      >
        重试
      </button>
    </div>

    <div
      v-if="loading"
      class="panel-surface grid min-h-80 place-items-center"
      aria-live="polite"
    >
      <div class="text-center">
        <RefreshCcw
          class="mx-auto size-6 animate-spin text-cyan-300"
          aria-hidden="true"
        />
        <p class="mt-3 font-mono text-xs uppercase tracking-[0.2em] text-zinc-500">
          Loading gateway policy…
        </p>
      </div>
    </div>

    <template v-else-if="loadedSnapshot">
      <p
        v-if="saveMessage"
        class="status-success"
        role="status"
      >
        {{ saveMessage }}
      </p>
      <p
        v-if="saveError"
        class="status-error"
        role="alert"
      >
        {{ saveError }}
      </p>

      <section
        class="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(20rem,0.6fr)]"
        aria-label="网关设置表单"
      >
        <form
          class="space-y-5"
          @submit.prevent="saveSettings"
        >
          <article class="panel-surface p-5 sm:p-6">
            <div class="mb-6 flex items-center gap-3 border-b border-white/10 pb-5">
              <div
                class="grid size-11 place-items-center rounded-xl border border-red-400/20 bg-red-400/5 text-red-300"
              >
                <ShieldAlert
                  class="size-5"
                  aria-hidden="true"
                />
              </div>
              <div>
                <p class="section-label">HARD SAFETY LIMITS</p>
                <h2 class="mt-1 text-lg font-semibold text-white">不可绕过的系统边界</h2>
              </div>
            </div>

            <div class="space-y-6">
              <label class="block">
                <span class="field-label flex items-center justify-between gap-4">
                  <span>全局最高强度硬截断</span>
                  <span class="font-mono text-cyan-300"
                    >{{ settings.maxSystemIntensity }} / 100</span
                  >
                </span>
                <input
                  v-model.number="settings.maxSystemIntensity"
                  class="cyber-range mt-3"
                  type="range"
                  min="0"
                  max="100"
                  step="1"
                  aria-describedby="max-intensity-help"
                />
                <span
                  id="max-intensity-help"
                  class="mt-3 block text-xs leading-5 text-zinc-500"
                  >所有设备命令都必须在网关层再次截断；设置为 0 将阻止新的非零输出。</span
                >
              </label>

              <label class="block">
                <span class="field-label">看门狗超时（秒）</span>
                <div class="relative max-w-sm">
                  <Clock3
                    class="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-zinc-500"
                    aria-hidden="true"
                  />
                  <input
                    v-model.number="settings.watchdogTimeoutSec"
                    class="field-input pl-10"
                    type="number"
                    min="0.25"
                    max="60"
                    step="0.25"
                  />
                </div>
                <span class="mt-2 block text-xs leading-5 text-zinc-500"
                  >超过该时间未收到有效控制心跳时，所有输出清零。</span
                >
              </label>
            </div>
          </article>

          <article class="panel-surface p-5 sm:p-6">
            <div class="mb-6 flex items-center gap-3 border-b border-white/10 pb-5">
              <div
                class="grid size-11 place-items-center rounded-xl border border-purple-400/20 bg-purple-400/5 text-purple-300"
              >
                <CircleGauge
                  class="size-5"
                  aria-hidden="true"
                />
              </div>
              <div>
                <p class="section-label">RUNTIME POLICY</p>
                <h2 class="mt-1 text-lg font-semibold text-white">运行时策略</h2>
              </div>
            </div>

            <div class="grid gap-4 md:grid-cols-2">
              <label>
                <span class="field-label">心率玩法目标值（BPM）</span>
                <input
                  v-model.number="settings.edgingTargetHr"
                  class="field-input"
                  type="number"
                  min="0"
                  max="240"
                  step="1"
                />
                <span class="mt-2 block text-xs leading-5 text-zinc-500"
                  >仅作为玩法判断目标，不授权 AI 自动提高设备输出。</span
                >
              </label>

              <label>
                <span class="field-label">系统模式</span>
                <select
                  v-model="settings.systemMode"
                  class="field-input"
                >
                  <option value="manual">人工控制 Manual</option>
                  <option value="api_script">API 剧本 API Script</option>
                </select>
                <span class="mt-2 block text-xs leading-5 text-zinc-500"
                  >切换模式不会自动启动设备或恢复既有会话。</span
                >
              </label>
            </div>
          </article>

          <article class="panel-surface p-5 sm:p-6">
            <div class="mb-6 flex items-center gap-3 border-b border-white/10 pb-5">
              <div
                class="grid size-11 place-items-center rounded-xl border border-emerald-400/20 bg-emerald-400/5 text-emerald-300"
              >
                <Bot
                  class="size-5"
                  aria-hidden="true"
                />
              </div>
              <div>
                <p class="section-label">AI CONTROL</p>
                <h2 class="mt-1 text-lg font-semibold text-white">AI 主控配置</h2>
              </div>
            </div>

            <div class="grid gap-4 md:grid-cols-2">
              <label>
                <span class="field-label">AI 厂商</span>
                <select
                  v-model="settings.ai.provider"
                  class="field-input"
                >
                  <option value="mock">Mock（离线兜底，不联网）</option>
                  <option value="openai">OpenAI 兼容</option>
                  <option value="anthropic">Anthropic</option>
                </select>
                <span class="mt-2 block text-xs leading-5 text-zinc-500"
                  >Mock 模式不调用任何外部模型；切换真实厂商需填写密钥与模型。</span
                >
              </label>

              <label>
                <span class="field-label">模型名</span>
                <input
                  v-model.trim="settings.ai.model"
                  class="field-input"
                  type="text"
                  :disabled="settings.ai.provider === 'mock'"
                  :placeholder="settings.ai.provider === 'anthropic' ? 'claude-sonnet-4-20250514' : 'gpt-4.1-mini'"
                />
                <span class="mt-2 block text-xs leading-5 text-zinc-500"
                  >留空则使用厂商默认模型。</span
                >
              </label>

              <label class="md:col-span-2">
                <span class="field-label flex items-center gap-2">
                  <Link2 class="size-3.5" aria-hidden="true" /> 自定义 API 地址（可选）
                </span>
                <input
                  v-model.trim="settings.ai.baseUrl"
                  class="field-input"
                  type="text"
                  :disabled="settings.ai.provider === 'mock'"
                  :placeholder="settings.ai.provider === 'anthropic' ? 'https://api.anthropic.com' : 'https://api.openai.com'"
                />
                <span class="mt-2 block text-xs leading-5 text-zinc-500"
                  >用于私有部署 / 兼容网关 / 反向代理；留空则用厂商官方地址。</span
                >
              </label>

              <label class="md:col-span-2">
                <span class="field-label flex items-center gap-2">
                  <KeyRound class="size-3.5" aria-hidden="true" /> API Key
                </span>
                <input
                  v-model="settings.ai.apiKey"
                  class="field-input"
                  type="password"
                  autocomplete="new-password"
                  :disabled="settings.ai.provider === 'mock'"
                  :placeholder="settings.ai.hasApiKey ? '已设置，留空则不修改' : '填写后保存即生效'"
                />
                <span class="mt-2 block text-xs leading-5 text-zinc-500"
                  >仅保存在本机
                  <code class="font-mono text-cyan-200">settings.yaml</code
                  >，不会回传到前端；修改为真实厂商后，主控代理下次循环即生效。</span
                >
              </label>
            </div>
          </article>

          <div
            v-if="raisesIntensity"
            class="rounded-2xl border border-amber-400/30 bg-amber-400/10 p-4"
          >
            <label class="flex cursor-pointer items-start gap-3">
              <input
                v-model="confirmIncrease"
                class="mt-1 size-4 rounded border-white/20 bg-zinc-950 text-cyan-400"
                type="checkbox"
              />
              <span>
                <span class="block text-sm font-semibold text-amber-100">确认提高全局强度上限</span>
                <span class="mt-1 block text-xs leading-5 text-amber-100/65"
                  >我确认这是人工安全审查后的变更。该确认只适用于本次保存。</span
                >
              </span>
            </label>
          </div>

          <div
            v-if="validationErrors.length"
            class="status-warning"
            role="alert"
          >
            <ul class="list-disc space-y-1 pl-5 text-xs">
              <li
                v-for="error in validationErrors"
                :key="error"
              >
                {{ error }}
              </li>
            </ul>
          </div>

          <div class="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
            <button
              class="cyber-button-secondary"
              type="button"
              :disabled="!isDirty || saving"
              @click="resetForm"
            >
              撤销更改
            </button>
            <button
              class="cyber-button"
              type="submit"
              :disabled="!canSave"
            >
              <Save
                class="size-4"
                aria-hidden="true"
              />
              {{ saving ? '正在热更新…' : '保存并热更新' }}
            </button>
          </div>
        </form>

        <aside
          class="space-y-4 xl:sticky xl:top-6 xl:self-start"
          aria-label="配置安全说明"
        >
          <article class="panel-surface p-5">
            <div class="flex items-center gap-3">
              <ShieldCheck
                class="size-5 text-emerald-300"
                aria-hidden="true"
              />
              <h2 class="font-semibold text-white">安全生效原则</h2>
            </div>
            <ul class="mt-4 space-y-3 text-sm leading-6 text-zinc-400">
              <li class="flex gap-2">
                <span class="text-cyan-300">01</span
                ><span>设置由后端验证后才视为成功，前端不会伪造成功状态。</span>
              </li>
              <li class="flex gap-2">
                <span class="text-cyan-300">02</span
                ><span>遥测与 AI 只能降低、暂停或清零输出，不能据此自动提高强度。</span>
              </li>
              <li class="flex gap-2">
                <span class="text-cyan-300">03</span
                ><span>急停后必须建立新的有效控制会话，设置热更新不会自动恢复。</span>
              </li>
            </ul>
          </article>

          <article class="rounded-2xl border border-cyan-400/15 bg-cyan-400/5 p-5">
            <p class="section-label text-cyan-300">UNSAVED STATE</p>
            <p
              class="mt-3 text-2xl font-semibold"
              :class="isDirty ? 'text-amber-200' : 'text-emerald-200'"
            >
              {{ isDirty ? '存在未保存更改' : '配置已同步' }}
            </p>
            <p class="mt-2 text-xs leading-5 text-zinc-500">
              {{
                isDirty ? '网关仍在使用上一次确认的配置。' : '此页面显示最近一次由网关返回的设置。'
              }}
            </p>
          </article>
        </aside>
      </section>

      <section
        class="panel-surface p-5 sm:p-6"
        aria-labelledby="features-heading"
      >
        <div class="mb-6 flex items-center gap-3 border-b border-white/10 pb-5">
          <div
            class="grid size-11 place-items-center rounded-xl border border-cyan-400/20 bg-cyan-400/5 text-cyan-300"
          >
            <Power
              class="size-5"
              aria-hidden="true"
            />
          </div>
          <div>
            <p class="section-label">FEATURE FLAGS</p>
            <h2
              id="features-heading"
              class="mt-1 text-lg font-semibold text-white"
            >
              功能开关
            </h2>
            <p class="mt-1 text-xs leading-5 text-zinc-500">
              通过
              <code class="font-mono text-cyan-200">/api/v1/features</code>
              热更新平台模块与内置服务的启停，立即生效并持久化。
            </p>
          </div>
        </div>

        <p
          v-if="featuresMessage"
          class="status-success"
          role="status"
        >
          {{ featuresMessage }}
        </p>
        <p
          v-if="featuresError"
          class="status-error"
          role="alert"
        >
          {{ featuresError }}
        </p>

        <div
          v-if="featuresLoading"
          class="grid min-h-40 place-items-center"
          aria-live="polite"
        >
          <p class="font-mono text-xs uppercase tracking-[0.2em] text-zinc-500">
            Loading feature flags…
          </p>
        </div>

        <div
          v-else
          class="space-y-8"
        >
          <div>
            <h3 class="section-label mb-3 flex items-center gap-2 text-cyan-300">
              <Cpu
                class="size-4"
                aria-hidden="true"
              />
              平台模块
            </h3>
            <div class="grid gap-3 md:grid-cols-2">
              <article
                v-for="feature in moduleFeatures"
                :key="feature.key"
                class="rounded-xl border border-white/10 bg-zinc-950/50 p-4"
              >
                <div class="flex items-start justify-between gap-3">
                  <div class="min-w-0">
                    <p class="truncate text-sm font-semibold text-white">{{ feature.label }}</p>
                    <p
                      class="mt-1 font-mono text-[0.62rem] uppercase tracking-wider text-cyan-300/80"
                    >
                      {{ feature.kind }}
                    </p>
                  </div>
                  <div class="flex shrink-0 items-center gap-2">
                    <Lock
                      v-if="feature.locked"
                      class="size-4 text-zinc-600"
                      aria-label="安全项不可关闭"
                    />
                    <ToggleSwitch
                      :model-value="feature.enabled"
                      :disabled="feature.locked || featuresSaving"
                      :label="`${feature.label} 开关`"
                      @update:model-value="toggleFeature(feature)"
                    />
                  </div>
                </div>
                <p
                  v-if="feature.description"
                  class="mt-3 text-xs leading-5 text-zinc-500"
                >
                  {{ feature.description }}
                </p>
              </article>
            </div>
          </div>

          <div>
            <h3 class="section-label mb-3 flex items-center gap-2 text-cyan-300">
              <Server
                class="size-4"
                aria-hidden="true"
              />
              内置服务
            </h3>
            <div class="grid gap-3 md:grid-cols-2">
              <article
                v-for="feature in serviceFeatures"
                :key="feature.key"
                class="rounded-xl border border-white/10 bg-zinc-950/50 p-4"
              >
                <div class="flex items-start justify-between gap-3">
                  <div class="min-w-0">
                    <p class="truncate text-sm font-semibold text-white">{{ feature.label }}</p>
                    <p
                      class="mt-1 font-mono text-[0.62rem] uppercase tracking-wider text-purple-300/80"
                    >
                      {{ feature.key }}
                    </p>
                  </div>
                  <div class="flex shrink-0 items-center gap-2">
                    <Lock
                      v-if="feature.locked"
                      class="size-4 text-zinc-600"
                      aria-label="安全项不可关闭"
                    />
                    <ToggleSwitch
                      :model-value="feature.enabled"
                      :disabled="feature.locked || featuresSaving"
                      :label="`${feature.label} 开关`"
                      @update:model-value="toggleFeature(feature)"
                    />
                  </div>
                </div>
                <p
                  v-if="feature.description"
                  class="mt-3 text-xs leading-5 text-zinc-500"
                >
                  {{ feature.description }}
                </p>
              </article>
            </div>
          </div>

          <p class="text-xs leading-5 text-zinc-600">
            安全项（看门狗、黑盒审计）不可关闭；未知开关会被后端忽略。停用遥测后事件流将停止推送，停用手动控制后控制指令将被网关拒绝。
          </p>
        </div>
      </section>
    </template>
  </main>
</template>
