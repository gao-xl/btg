import { computed, onMounted, onUnmounted, readonly, ref } from 'vue'

const MAX_HEART_RATE_SAMPLES = 60
const MAX_FEED_ITEMS = 80

const connectionState = ref('connecting')
const telemetry = ref({
  heartRate: null,
  imuVariance: null,
  audioDb: null,
  anomalyScore: null,
  safetyStatus: 'unknown',
  maxIntensity: null,
  sessionAuthorized: false,
  estopActive: false,
  timestamp: null,
})
const heartRateHistory = ref([])
const feed = ref([])

let socket = null
let reconnectTimer = null
let consumers = 0
let reconnectAttempt = 0

function websocketUrl() {
  if (import.meta.env.VITE_WS_URL) return import.meta.env.VITE_WS_URL
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws/events`
}

function appendFeed(kind, message, timestamp = Date.now()) {
  feed.value = [
    ...feed.value,
    {
      id: `${timestamp}-${Math.random().toString(16).slice(2)}`,
      kind,
      message,
      timestamp,
    },
  ].slice(-MAX_FEED_ITEMS)
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function applyTelemetry(event) {
  const payload =
    event.telemetry && typeof event.telemetry === 'object'
      ? { ...event, ...event.telemetry }
      : event

  const heartRate = numberOrNull(payload.heart_rate_bpm ?? payload.heart_rate)
  const next = {
    heartRate,
    imuVariance: numberOrNull(payload.imu_variance ?? payload.imu_struggle),
    audioDb: numberOrNull(payload.audio_db ?? payload.vad_db),
    anomalyScore: numberOrNull(payload.anomaly_score),
    safetyStatus: payload.safety_status ?? payload.safety?.status ?? 'unknown',
    maxIntensity: numberOrNull(
      payload.max_system_intensity ?? payload.safety?.max_system_intensity,
    ),
    sessionAuthorized:
      payload.session_authorized === true || payload.safety?.session_authorized === true,
    estopActive: payload.estop_active === true || payload.safety?.estop_active === true,
    timestamp: payload.timestamp ?? Date.now() / 1000,
  }

  telemetry.value = next
  if (heartRate !== null) {
    heartRateHistory.value = [
      ...heartRateHistory.value,
      { value: heartRate, timestamp: next.timestamp },
    ].slice(-MAX_HEART_RATE_SAMPLES)
  }
}

function handleEvent(event) {
  if (!event || typeof event !== 'object') return

  if (event.type === 'telemetry' || event.type === 'telemetry.frame') {
    applyTelemetry(event)
    return
  }

  if (event.type === 'tts.request' || event.type === 'llm.dialogue') {
    appendFeed('ai', event.text ?? event.dialogue ?? '收到空文本事件')
    return
  }

  if (event.type === 'telemetry.injected') {
    appendFeed('telemetry', event.message ?? '生物体征已注入 LLM 上下文')
    return
  }

  if (event.type?.startsWith('scenario.') || event.type === 'emergency_stop') {
    appendFeed('system', event.message ?? event.type)
  }
}

function scheduleReconnect() {
  if (!consumers || reconnectTimer) return
  const delay = Math.min(1000 * 2 ** reconnectAttempt, 15000)
  reconnectAttempt += 1
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null
    connect()
  }, delay)
}

function connect() {
  if (!consumers || socket?.readyState === WebSocket.OPEN) return

  connectionState.value = 'connecting'
  socket = new WebSocket(websocketUrl())

  socket.addEventListener('open', () => {
    connectionState.value = 'connected'
    reconnectAttempt = 0
    appendFeed('system', '网关遥测通道已连接')
  })

  socket.addEventListener('message', ({ data }) => {
    try {
      handleEvent(JSON.parse(data))
    } catch {
      appendFeed('system', '忽略了一条无效的网关事件')
    }
  })

  socket.addEventListener('close', () => {
    connectionState.value = 'offline'
    socket = null
    scheduleReconnect()
  })

  socket.addEventListener('error', () => {
    connectionState.value = 'offline'
  })
}

function disconnectIfUnused() {
  if (consumers > 0) return
  if (reconnectTimer) window.clearTimeout(reconnectTimer)
  reconnectTimer = null
  socket?.close()
  socket = null
}

export function useGateway() {
  onMounted(() => {
    consumers += 1
    connect()
  })

  onUnmounted(() => {
    consumers = Math.max(0, consumers - 1)
    disconnectIfUnused()
  })

  return {
    connectionState: readonly(connectionState),
    isConnected: computed(() => connectionState.value === 'connected'),
    telemetry: readonly(telemetry),
    heartRateHistory: readonly(heartRateHistory),
    feed: readonly(feed),
    appendFeed,
  }
}
