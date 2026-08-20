<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'

const progress = ref(100)
const isTimedOut = ref(false)
let shrinkInterval = null
let pingInterval = null

// 2-second shrink cycle
const SHRINK_DURATION = 2000
const SHRINK_STEP = 10

function startWatchdog() {
  // Shrink bar every 200ms by 1% (full shrink in 2s)
  shrinkInterval = setInterval(() => {
    progress.value = Math.max(0, progress.value - (100 / (SHRINK_DURATION / SHRINK_STEP)))
    if (progress.value <= 0) {
      isTimedOut.value = true
    }
  }, SHRINK_STEP)

  // Ping every 800ms to refill
  pingInterval = setInterval(() => {
    progress.value = Math.min(100, progress.value + 30)
    if (progress.value > 0) {
      isTimedOut.value = false
    }
  }, 800)
}

onMounted(startWatchdog)

onUnmounted(() => {
  clearInterval(shrinkInterval)
  clearInterval(pingInterval)
})

const barColor = computed(() => {
  if (isTimedOut.value) return '#F43F5E'
  if (progress.value < 30) return '#F59E0B'
  return '#06B6D4'
})

const progressWidth = computed(() => `${progress.value}%`)
</script>

<template>
  <footer
    :class="[
      'flex items-center h-7 px-4 border-t flex-shrink-0 transition-colors duration-300',
      isTimedOut ? 'bg-danger-500/10 border-danger-500/30' : 'glass-heavy border-nexus-800'
    ]"
  >
    <!-- Label -->
    <div class="flex items-center gap-2 flex-shrink-0 mr-4">
      <span
        :class="[
          'w-1.5 h-1.5 rounded-full',
          isTimedOut ? 'bg-danger-400 animate-watchdog-blink' : 'bg-signal-400'
        ]"
      ></span>
      <span
        :class="[
          'font-mono text-[10px] tracking-[0.15em]',
          isTimedOut ? 'text-danger-400 font-semibold' : 'text-nexus-500'
        ]"
      >
        WATCHDOG KEEP-ALIVE
      </span>
    </div>

    <!-- Progress Bar -->
    <div class="flex-1 h-1.5 rounded-full bg-nexus-800 overflow-hidden">
      <div
        class="h-full rounded-full transition-all duration-200"
        :style="{
          width: progressWidth,
          backgroundColor: barColor,
          boxShadow: isTimedOut ? '0 0 8px rgba(244, 63, 94, 0.6)' : 'none'
        }"
      ></div>
    </div>

    <!-- Timeout Warning -->
    <div
      v-if="isTimedOut"
      class="flex-shrink-0 ml-4 font-mono text-[10px] font-semibold text-danger-400 tracking-[0.15em] animate-watchdog-blink"
    >
      WATCHDOG TIMEOUT — ACTUATORS ZEROED
    </div>
    <div
      v-else
      class="flex-shrink-0 ml-4 font-mono text-[10px] text-nexus-600 tracking-wider"
    >
      PING {{ Math.round(progress) }}%
    </div>
  </footer>
</template>