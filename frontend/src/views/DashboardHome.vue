<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import {
  Activity,
  AudioLines,
  CircleGauge,
  Move3d,
  RadioTower,
  ShieldAlert,
  ShieldCheck,
  Siren,
  Sparkles,
  TriangleAlert,
} from '@lucide/vue'
import ActuatorSlider from '../components/ActuatorSlider.vue'
import TelemetrySparkline from '../components/TelemetrySparkline.vue'
import TerminalFeed from '../components/TerminalFeed.vue'
import { gatewayApi, getApiError } from '../services/api'
import { useGateway } from '../composables/useGateway'

const {
  connectionState,
  telemetry: telemetryRef,
  heartRateHistory,
  feed,
  appendFeed,
} = useGateway()
const telemetryState = computed(() => telemetryRef.value)

const channels = reactive({ A: 0, B: 0 })
const channelBusy = reactive({ A: false, B: false })
const channelErrors = reactive({ A: '', B: '' })
const gatewayLimit = ref(0)
const settingsWarning = ref('')
const estopBusy = ref(false)
const estopMessage = ref('')
const estopError = ref('')
const sendTimers = new Map()
const playWaves = ref([])
const playWaveError = ref('')
const features = ref([])
const featuresError = ref('')

const featureEnabled = computed(() => {
  const map = {}
  for (const feature of features.value) map[feature.key] = feature.enabled
  return map
})
const telemetryEnabled = computed(() => featureEnabled.value.telemetry !== false)
const manualControlEnabled = computed(() => featureEnabled.value.manual_control !== false)

const normalizedSafetyStatus = computed(() =>
  String(telemetryState.value.safetyStatus || 'unknown').toLowerCase(),
)
const safetyNormal = computed(() =>
  ['normal', 'safe', 'ok', '正常'].includes(normalizedSafetyStatus.value),
)
const effectiveLimit = computed(() => {
  const candidates = [telemetryState.value.maxIntensity, gatewayLimit.value]
    .filter((value) => value !== null && value !== undefined && value !== '')
    .map(Number)
    .filter((value) => Number.isFinite(value) && value >= 0)
  return candidates.length ? Math.min(100, ...candidates) : 0
})
const controlEnabled = computed(
  () =>
    connectionState.value === 'connected' &&
    telemetryState.value.sessionAuthorized === true &&
    safetyNormal.value &&
    effectiveLimit.value > 0 &&
    manualControlEnabled.value,
)

const safetyLabel = computed(() => {
  if (telemetryState.value.estopActive) return '急停已激活'
  if (safetyNormal.value) return '正常'
  if (normalizedSafetyStatus.value === 'unknown') return '等待网关'
  return telemetryState.value.safetyStatus
})

const interlockReason = computed(() => {
  if (connectionState.value !== 'connected') return '遥测链路未连接'
  if (!manualControlEnabled.value) return '手动控制功能已在配置中心停用'
  if (telemetryState.value.sessionAuthorized !== true) return '当前会话未授权设备输出'
  if (!safetyNormal.value) return `安全状态为 ${safetyLabel.value}`
  if (effectiveLimit.value <= 0) return '全局强度上限为 0 或尚未载入'
  return '设备输出已通过本地安全互锁'
})

const metricCards = computed(() => [
  {
    key: 'imu',
    label: 'IMU STRUGGLE',
    title: '身体挣扎加速度',
    value:
      telemetryState.value.imuVariance == null
        ? '—'
        : Number(telemetryState.value.imuVariance).toFixed(2),
    unit: 'g',
    icon: Move3d,
    colorClass: 'text-purple-300',
  },
  {
    key: 'audio',
    label: 'AUDIO VAD',
    title: '当前音频声压',
    value:
      telemetryState.value.audioDb == null ? '—' : Math.round(Number(telemetryState.value.audioDb)),
    unit: 'dB',
    icon: AudioLines,
    colorClass: 'text-cyan-300',
  },
  {
    key: 'anomaly',
    label: 'ANOMALY SCORE',
    title: '异常风险评分',
    value:
      telemetryState.value.anomalyScore == null
        ? '—'
        : Number(telemetryState.value.anomalyScore).toFixed(2),
    unit: '/ 1.0',
    icon: TriangleAlert,
    colorClass:
      Number(telemetryState.value.anomalyScore) >= 0.7 ? 'text-red-300' : 'text-amber-300',
  },
])

async function loadGatewayLimit() {
  try {
    const settings = await gatewayApi.getSettings()
    gatewayLimit.value = Number(settings.max_system_intensity ?? settings.maxSystemIntensity ?? 0)
    settingsWarning.value = ''
  } catch (error) {
    gatewayLimit.value = 0
    settingsWarning.value = `无法读取全局强度上限：${getApiError(error)}`
  }
}

async function loadPlayWaves() {
  try {
    playWaves.value = await gatewayApi.listPlayWaves()
    playWaveError.value = ''
  } catch (error) {
    playWaves.value = []
    playWaveError.value = `无法读取玩法波形：${getApiError(error)}`
  }
}

async function loadFeatures() {
  try {
    features.value = await gatewayApi.listFeatures()
    featuresError.value = ''
  } catch (error) {
    featuresError.value = `无法读取功能开关：${getApiError(error)}`
  }
}

function updateChannel(channel, value) {
  const clamped = Math.max(0, Math.min(effectiveLimit.value, Number(value)))
  channels[channel] = clamped
  channelErrors[channel] = ''

  if (!controlEnabled.value) return

  const existingTimer = sendTimers.get(channel)
  if (existingTimer) window.clearTimeout(existingTimer)
  const timer = window.setTimeout(() => sendIntensity(channel, clamped), 120)
  sendTimers.set(channel, timer)
}

async function sendIntensity(channel, intensity) {
  if (!controlEnabled.value) return
  channelBusy[channel] = true
  try {
    await gatewayApi.setActuator({ channel, intensity })
    appendFeed('system', `通道 ${channel} 已同步至 ${intensity}/${effectiveLimit.value}`)
  } catch (error) {
    channelErrors[channel] = getApiError(error)
    channels[channel] = 0
  } finally {
    channelBusy[channel] = false
  }
}

async function emergencyStop() {
  for (const timer of sendTimers.values()) window.clearTimeout(timer)
  sendTimers.clear()
  channels.A = 0
  channels.B = 0
  estopBusy.value = true
  estopMessage.value = ''
  estopError.value = ''

  try {
    await gatewayApi.emergencyStop()
    estopMessage.value = '急停指令已由网关确认，所有通道目标值已清零。'
    appendFeed('system', estopMessage.value)
  } catch (error) {
    estopError.value = `急停确认失败：${getApiError(error)}。请立即使用设备物理断电。`
    appendFeed('system', estopError.value)
  } finally {
    estopBusy.value = false
  }
}

watch(effectiveLimit, (limit) => {
  channels.A = Math.min(channels.A, limit)
  channels.B = Math.min(channels.B, limit)
})

watch(controlEnabled, (enabled) => {
  if (!enabled) {
    for (const timer of sendTimers.values()) window.clearTimeout(timer)
    sendTimers.clear()
    channels.A = 0
    channels.B = 0
  }
})

onMounted(() => Promise.all([loadGatewayLimit(), loadPlayWaves(), loadFeatures()]))
onBeforeUnmount(() => {
  for (const timer of sendTimers.values()) window.clearTimeout(timer)
})
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
          <RadioTower
            class="size-4"
            aria-hidden="true"
          />
          Live Operations
        </div>
        <h1 class="font-display text-3xl font-bold tracking-tight text-white sm:text-4xl">
          遥测与控制中枢
        </h1>
        <p class="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
          实时读取网关遥测、执行人工授权的设备控制，并将每次安全状态变化写入终端事件流。
        </p>
      </div>

      <div class="panel-surface flex min-w-64 items-center gap-3 px-4 py-3">
        <component
          :is="safetyNormal ? ShieldCheck : ShieldAlert"
          :class="safetyNormal ? 'text-emerald-300' : 'text-amber-300'"
          class="size-5"
          aria-hidden="true"
        />
        <div>
          <p class="font-mono text-[0.65rem] uppercase tracking-[0.2em] text-zinc-500">
            Safety interlock
          </p>
          <p
            class="mt-0.5 text-sm font-medium"
            :class="controlEnabled ? 'text-emerald-200' : 'text-amber-100'"
          >
            {{ interlockReason }}
          </p>
        </div>
      </div>
    </header>

    <p
      v-if="settingsWarning"
      class="status-warning"
      role="status"
    >
      {{ settingsWarning }}
    </p>
    <p
      v-if="featuresError"
      class="status-warning"
      role="status"
    >
      {{ featuresError }}
    </p>

    <div
      v-if="!telemetryEnabled"
      class="status-warning flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"
      role="status"
    >
      <span class="flex items-center gap-2"
        ><RadioTower
          class="size-4 shrink-0"
          aria-hidden="true"
        />遥测采集已停用，实时体征与事件流将停止更新。</span
      >
      <RouterLink
        to="/settings"
        class="cyber-button-secondary shrink-0"
      >
        前往配置中心启用
      </RouterLink>
    </div>

    <div
      v-if="!manualControlEnabled"
      class="status-warning flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"
      role="status"
    >
      <span class="flex items-center gap-2"
        ><CircleGauge
          class="size-4 shrink-0"
          aria-hidden="true"
        />手动控制已停用，设备输出指令将被网关拒绝。</span
      >
      <RouterLink
        to="/settings"
        class="cyber-button-secondary shrink-0"
      >
        前往配置中心启用
      </RouterLink>
    </div>

    <section aria-labelledby="telemetry-heading">
      <div class="mb-3 flex items-center justify-between">
        <h2
          id="telemetry-heading"
          class="section-label"
        >
          01 / REAL-TIME BIOMETRICS
        </h2>
        <span class="font-mono text-[0.65rem] uppercase tracking-wider text-zinc-600">
          {{
            telemetryState.timestamp
              ? `Last frame ${new Date(telemetryState.timestamp > 1e12 ? telemetryState.timestamp : telemetryState.timestamp * 1000).toLocaleTimeString()}`
              : 'No telemetry frame'
          }}
        </span>
      </div>

      <div class="grid gap-4 xl:grid-cols-[1.45fr_repeat(3,minmax(0,1fr))]">
        <article class="panel-surface relative min-h-52 overflow-hidden p-5">
          <div
            class="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-cyan-400/80 via-purple-400/70 to-transparent"
          />
          <div class="flex items-start justify-between">
            <div>
              <p class="font-mono text-[0.68rem] uppercase tracking-[0.25em] text-cyan-300">
                HEART RATE
              </p>
              <p class="mt-1 text-sm text-zinc-500">心率 / 每分钟心跳</p>
            </div>
            <Activity
              class="size-5 text-cyan-300"
              aria-hidden="true"
            />
          </div>
          <div class="mt-4 flex items-end gap-2">
            <span class="font-mono text-6xl font-semibold leading-none tabular-nums text-white">{{
              telemetryState.heartRate == null ? '—' : Math.round(telemetryState.heartRate)
            }}</span>
            <span class="pb-1 font-mono text-sm uppercase tracking-widest text-cyan-300">BPM</span>
          </div>
          <TelemetrySparkline
            class="mt-5 h-16 w-full"
            :points="heartRateHistory"
          />
        </article>

        <article
          v-for="metric in metricCards"
          :key="metric.key"
          class="panel-surface relative min-h-52 overflow-hidden p-5"
        >
          <div class="flex h-full flex-col justify-between">
            <div class="flex items-start justify-between">
              <div>
                <p class="font-mono text-[0.68rem] uppercase tracking-[0.22em] text-zinc-400">
                  {{ metric.label }}
                </p>
                <p class="mt-1 text-sm text-zinc-500">{{ metric.title }}</p>
              </div>
              <component
                :is="metric.icon"
                class="size-5"
                :class="metric.colorClass"
                aria-hidden="true"
              />
            </div>
            <div>
              <span class="font-mono text-4xl font-semibold tabular-nums text-white">{{
                metric.value
              }}</span>
              <span class="ml-2 font-mono text-xs uppercase tracking-wider text-zinc-500">{{
                metric.unit
              }}</span>
            </div>
          </div>
        </article>
      </div>
    </section>

    <section aria-labelledby="play-heading">
      <div class="mb-3 flex items-end justify-between gap-4">
        <div>
          <h2
            id="play-heading"
            class="section-label"
          >
            02 / CONVERSATIONAL PLAY
          </h2>
          <p class="mt-2 max-w-3xl text-sm leading-6 text-zinc-500">
            AI 可以推荐节奏、降强、暂停或停止；波形卡仅为预览，不会直接驱动物理设备。
          </p>
        </div>
        <Sparkles
          class="size-5 text-purple-300"
          aria-hidden="true"
        />
      </div>
      <p
        v-if="playWaveError"
        class="status-warning"
        role="status"
      >
        {{ playWaveError }}
      </p>
      <div
        v-else
        class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"
      >
        <article
          v-for="wave in playWaves"
          :key="wave.key"
          class="panel-surface p-4"
        >
          <div class="flex items-center justify-between gap-3">
            <div>
              <p class="font-display font-semibold text-white">{{ wave.name }}</p>
              <p class="font-mono text-[0.62rem] uppercase tracking-wider text-purple-300">
                {{ wave.key }} · {{ wave.frame_count }} frames
              </p>
            </div>
          </div>
          <div
            class="mt-4 flex h-10 items-end gap-1"
            aria-hidden="true"
          >
            <span
              v-for="(frame, index) in wave.normalized_preview"
              :key="index"
              class="min-w-1 flex-1 rounded-t bg-gradient-to-t from-purple-600 to-cyan-300"
              :style="{ height: `${Math.max(4, frame)}%` }"
            />
          </div>
          <p class="mt-3 text-xs leading-5 text-zinc-500">{{ wave.description }}</p>
        </article>
      </div>
    </section>

    <section aria-labelledby="control-heading">
      <div class="mb-3 flex items-center justify-between gap-4">
        <h2
          id="control-heading"
          class="section-label"
        >
          03 / MANUAL ACTUATOR CONTROL
        </h2>
        <div
          class="flex items-center gap-2 font-mono text-[0.65rem] uppercase tracking-wider text-zinc-500"
        >
          <CircleGauge
            class="size-4"
            aria-hidden="true"
          />
          Hardware cap {{ effectiveLimit }} / 100
        </div>
      </div>

      <div class="grid gap-4 xl:grid-cols-[1fr_1fr_0.82fr]">
        <div>
          <ActuatorSlider
            channel="A"
            :model-value="channels.A"
            :max="effectiveLimit"
            :disabled="!controlEnabled"
            :busy="channelBusy.A"
            @update:model-value="updateChannel('A', $event)"
          />
          <p
            v-if="channelErrors.A"
            class="status-error mt-2"
            role="alert"
          >
            通道 A：{{ channelErrors.A }}
          </p>
        </div>

        <div>
          <ActuatorSlider
            channel="B"
            :model-value="channels.B"
            :max="effectiveLimit"
            :disabled="!controlEnabled"
            :busy="channelBusy.B"
            @update:model-value="updateChannel('B', $event)"
          />
          <p
            v-if="channelErrors.B"
            class="status-error mt-2"
            role="alert"
          >
            通道 B：{{ channelErrors.B }}
          </p>
        </div>

        <article
          class="rounded-2xl border border-red-500/35 bg-[linear-gradient(145deg,rgba(127,29,29,0.34),rgba(24,24,27,0.94))] p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.05),0_0_32px_rgba(239,68,68,0.1)]"
        >
          <div class="flex items-center gap-3">
            <Siren
              class="size-5 text-red-300"
              aria-hidden="true"
            />
            <div>
              <p class="font-mono text-[0.68rem] uppercase tracking-[0.22em] text-red-300">
                EMERGENCY OVERRIDE
              </p>
              <p class="mt-1 text-xs text-red-100/60">无需控制会话授权即可触发</p>
            </div>
          </div>
          <button
            class="mt-5 w-full rounded-xl border border-red-300/60 bg-red-600 px-4 py-5 font-display text-lg font-black uppercase tracking-wider text-white shadow-[0_5px_0_#7f1d1d,0_0_25px_rgba(239,68,68,0.3)] transition hover:bg-red-500 active:translate-y-1 active:shadow-[0_1px_0_#7f1d1d] disabled:cursor-wait disabled:opacity-70"
            type="button"
            :disabled="estopBusy"
            @click="emergencyStop"
          >
            {{ estopBusy ? '正在发送急停…' : '🚨 紧急急停' }}
          </button>
          <p
            v-if="estopMessage"
            class="mt-4 text-xs leading-5 text-emerald-200"
            role="status"
          >
            {{ estopMessage }}
          </p>
          <p
            v-if="estopError"
            class="mt-4 text-xs font-semibold leading-5 text-red-200"
            role="alert"
          >
            {{ estopError }}
          </p>
        </article>
      </div>
    </section>

    <section aria-labelledby="terminal-heading">
      <h2
        id="terminal-heading"
        class="section-label mb-3"
      >
        04 / AI INTERROGATION FEED
      </h2>
      <TerminalFeed :items="feed" />
    </section>
  </main>
</template>
