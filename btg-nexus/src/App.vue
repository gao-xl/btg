<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import SystemHeader from './components/SystemHeader.vue'
import TelemetryPanel from './components/TelemetryPanel.vue'
import ActuatorPanel from './components/ActuatorPanel.vue'
import WatchdogFooter from './components/WatchdogFooter.vue'

const mode = ref('local')
const uptime = ref('0d 0h 0m')
const wsLatency = ref(12)

// Simulate uptime counter
let uptimeInterval = null
let seconds = 0

function updateUptime() {
  seconds++
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  uptime.value = `${d}d ${h}h ${m}m`
}

onMounted(() => {
  uptimeInterval = setInterval(updateUptime, 1000)
})

onUnmounted(() => {
  clearInterval(uptimeInterval)
})

// Simulate latency jitter
let latencyInterval = null
onMounted(() => {
  latencyInterval = setInterval(() => {
    wsLatency.value = 8 + Math.round(Math.random() * 10)
  }, 3000)
})
onUnmounted(() => {
  clearInterval(latencyInterval)
})
</script>

<template>
  <div class="flex flex-col h-screen w-screen overflow-hidden bg-nexus-950">
    <SystemHeader
      v-model:mode="mode"
      :uptime="uptime"
      :ws-latency="wsLatency"
      :ws-connections="3"
      system-status="normal"
    />

    <main class="flex-1 grid grid-cols-1 lg:grid-cols-[7fr_5fr] gap-3 p-3 min-h-0 overflow-hidden">
      <TelemetryPanel
        :current-bpm="125"
        :stress-level="42"
        fusion-state="baseline"
        hr-sensor="primary"
        imu-sensor="primary"
      />

      <ActuatorPanel />
    </main>

    <WatchdogFooter />
  </div>
</template>