<script setup>
import { ref } from 'vue'
import SliderControl from './SliderControl.vue'
import WaveformSelector from './WaveformSelector.vue'

const channelA = ref(35)
const channelB = ref(72)
const channelAThreshold = 60
const channelBThreshold = 60
const waveform = ref('continuous')
const frequency = ref(50)

function incrementFrequency() {
  if (frequency.value < 200) frequency.value += 5
}

function decrementFrequency() {
  if (frequency.value > 5) frequency.value -= 5
}
</script>

<template>
  <section class="panel flex flex-col h-full">
    <!-- Header -->
    <div class="flex items-center justify-between px-4 py-3 border-b border-nexus-800">
      <h2 class="font-mono text-xs tracking-[0.2em] text-nexus-400 uppercase">
        Actuators &amp; Clamp
      </h2>
      <span class="font-mono text-[10px] text-nexus-600 tracking-wider">SAFETY YAML v3.1</span>
    </div>

    <!-- Dual-Channel Sliders -->
    <div class="flex flex-col gap-6 px-4 py-4 border-b border-nexus-800/50">
      <SliderControl
        label="通道 A — 执行器 Alpha"
        v-model="channelA"
        :clamp-threshold="channelAThreshold"
      />
      <SliderControl
        label="通道 B — 执行器 Beta"
        v-model="channelB"
        :clamp-threshold="channelBThreshold"
      />
    </div>

    <!-- Waveform Selector -->
    <div class="px-4 py-4 border-b border-nexus-800/50">
      <WaveformSelector v-model="waveform" />
    </div>

    <!-- Frequency Stepper -->
    <div class="flex-1 flex flex-col justify-center px-4 py-4">
      <div class="flex flex-col items-center gap-4">
        <span class="font-mono text-xs tracking-wider text-nexus-400">输出频率</span>
        <div class="flex items-center gap-4">
          <button
            class="stepper-btn"
            @click="decrementFrequency"
            aria-label="decrease frequency"
          >
            −
          </button>
          <div class="flex items-baseline gap-1.5">
            <span class="font-mono text-4xl font-bold text-signal-400 tabular-nums">
              {{ frequency }}
            </span>
            <span class="font-mono text-sm text-nexus-500 tracking-wider">Hz</span>
          </div>
          <button
            class="stepper-btn"
            @click="incrementFrequency"
            aria-label="increase frequency"
          >
            +
          </button>
        </div>
        <div class="flex items-center gap-4">
          <span class="font-mono text-[10px] text-nexus-600">5</span>
          <div class="w-32 h-1 rounded-full bg-nexus-800 overflow-hidden">
            <div
              class="h-full rounded-full bg-gradient-to-r from-signal-400 via-warn-400 to-danger-400 transition-all duration-300"
              :style="{ width: `${(frequency / 200) * 100}%` }"
            ></div>
          </div>
          <span class="font-mono text-[10px] text-nexus-600">200</span>
        </div>
      </div>
    </div>

    <!-- Footer: Active Waveform Info -->
    <div class="px-4 py-2.5 border-t border-nexus-800 flex items-center justify-between">
      <span class="font-mono text-[10px] text-nexus-500 tracking-wider">
        ACTIVE: {{ waveform.toUpperCase() }}
      </span>
      <span class="font-mono text-[10px] text-nexus-600 tracking-wider">
        CH-A: {{ channelA }}% | CH-B: {{ channelB }}%
      </span>
    </div>
  </section>
</template>