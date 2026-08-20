<script setup>
import { ref, computed } from 'vue'
import TelemetryChart from './TelemetryChart.vue'

const props = defineProps({
  currentBpm: { type: Number, default: 125 },
  stressLevel: { type: Number, default: 42 },
  fusionState: { type: String, default: 'baseline' },  // 'baseline' | 'oscillation' | 'danger'
  hrSensor: { type: String, default: 'primary' },  // 'primary' | 'backup'
  imuSensor: { type: String, default: 'primary' }
})

// Simulated chart data
function generateHeartRateData() {
  const data = []
  for (let i = 0; i < 60; i++) {
    const base = 85 + 40 * Math.sin(i * 0.6) * Math.sin(i * 0.25)
    data.push(Math.round(base + (Math.random() - 0.5) * 8))
  }
  return data
}

function generateImuData() {
  const data = []
  for (let i = 0; i < 60; i++) {
    data.push(Math.round(20 + 15 * Math.abs(Math.sin(i * 0.4)) + Math.random() * 5))
  }
  return data
}

function generateTimeLabels() {
  const labels = []
  for (let i = 59; i >= 0; i--) {
    labels.push(`-${i}s`)
  }
  return labels
}

const heartRateData = ref(generateHeartRateData())
const imuData = ref(generateImuData())
const timeLabels = ref(generateTimeLabels())

const fusionLabel = computed(() => {
  switch (props.fusionState) {
    case 'oscillation': return '阈值振荡'
    case 'danger': return '危险截断'
    default: return '基线'
  }
})

const fusionBadgeClass = computed(() => {
  switch (props.fusionState) {
    case 'oscillation': return 'oscillation'
    case 'danger': return 'danger'
    default: return 'baseline'
  }
})

const stressWidth = computed(() => `${props.stressLevel}%`)
const stressColor = computed(() => {
  if (props.stressLevel > 80) return '#F43F5E'
  if (props.stressLevel > 50) return '#F59E0B'
  return '#06B6D4'
})
</script>

<template>
  <section class="panel flex flex-col h-full">
    <!-- Header -->
    <div class="flex items-center justify-between px-4 py-3 border-b border-nexus-800">
      <h2 class="font-mono text-xs tracking-[0.2em] text-nexus-400 uppercase">
        Redundant Telemetry
      </h2>
      <span class="font-mono text-[10px] text-nexus-600 tracking-wider">HA-FUSION v2.4</span>
    </div>

    <!-- Failover Indicators -->
    <div class="flex items-center gap-3 px-4 py-2.5 border-b border-nexus-800/50">
      <span
        :class="['failover-tag', hrSensor === 'backup' ? 'standby' : '']"
      >
        <span class="w-1.5 h-1.5 rounded-full" :class="hrSensor === 'primary' ? 'bg-signal-400' : 'bg-warn-400'"></span>
        HR: {{ hrSensor === 'primary' ? 'Primary (BLE) — Active' : 'Backup (IMU) — Standby' }}
      </span>
      <span
        :class="['failover-tag', imuSensor === 'backup' ? 'standby' : '']"
      >
        <span class="w-1.5 h-1.5 rounded-full" :class="imuSensor === 'primary' ? 'bg-signal-400' : 'bg-warn-400'"></span>
        IMU: {{ imuSensor === 'primary' ? 'Primary (9-DOF) — Active' : 'Backup (Fused) — Standby' }}
      </span>
    </div>

    <!-- Current BPM Hero -->
    <div class="flex items-center justify-between px-4 py-2">
      <div class="flex items-baseline gap-2">
        <span class="font-mono text-[72px] font-bold leading-none text-signal-400 animate-breathe">
          {{ currentBpm }}
        </span>
        <span class="font-mono text-sm text-nexus-500 tracking-wider">BPM</span>
      </div>
      <div class="flex flex-col items-end">
        <span class="font-mono text-xs text-nexus-500 tracking-wider">实时心率</span>
        <span class="font-mono text-xs text-signal-400">▲ 3.2%</span>
      </div>
    </div>

    <!-- Chart Area -->
    <div class="flex-1 min-h-0 px-3 py-1 monitor-grid">
      <TelemetryChart
        :heart-rate="heartRateData"
        :imu-amplitude="imuData"
        :time-labels="timeLabels"
      />
    </div>

    <!-- Bottom: Fusion State + Stress -->
    <div class="flex items-center justify-between px-4 py-3 border-t border-nexus-800">
      <div class="flex items-center gap-3">
        <span class="font-mono text-[10px] text-nexus-500 tracking-wider">FUSION STATE</span>
        <span :class="['fusion-badge', fusionBadgeClass]">
          <span class="w-1.5 h-1.5 rounded-full" :class="fusionBadgeClass === 'baseline' ? 'bg-signal-400' : fusionBadgeClass === 'oscillation' ? 'bg-warn-400' : 'bg-danger-400'"></span>
          {{ fusionLabel }}
        </span>
      </div>
      <div class="flex items-center gap-3">
        <span class="font-mono text-[10px] text-nexus-500 tracking-wider">STRESS</span>
        <div class="w-32 h-2 rounded-full bg-nexus-800 overflow-hidden">
          <div
            class="h-full rounded-full transition-all duration-500"
            :style="{ width: stressWidth, backgroundColor: stressColor }"
          ></div>
        </div>
        <span class="font-mono text-xs text-nexus-400 w-8 text-right">{{ stressLevel }}%</span>
      </div>
    </div>
  </section>
</template>