<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  mode: { type: String, default: 'local' },  // 'local' | 'external'
  uptime: { type: String, default: '0d 0h 0m' },
  wsLatency: { type: Number, default: 12 },
  wsConnections: { type: Number, default: 3 },
  systemStatus: { type: String, default: 'normal' }  // 'normal' | 'degraded' | 'lockdown'
})

const emit = defineEmits(['update:mode'])

const isExternal = computed(() => props.mode === 'external')

function toggleMode() {
  emit('update:mode', isExternal.value ? 'local' : 'external')
}

const statusLabel = computed(() => {
  switch (props.systemStatus) {
    case 'degraded': return '降级运行'
    case 'lockdown': return '锁定模式'
    default: return '系统正常'
  }
})

const statusDotClass = computed(() => {
  switch (props.systemStatus) {
    case 'degraded': return 'warning'
    case 'lockdown': return 'danger'
    default: return 'normal'
  }
})
</script>

<template>
  <header
    class="flex items-center justify-between h-12 px-4 glass-heavy border-b border-nexus-800 flex-shrink-0 select-none z-50"
  >
    <!-- Left: Logo + Uptime -->
    <div class="flex items-center gap-4">
      <div class="flex items-center gap-2">
        <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none">
          <path d="M12 2L2 7l10 5 10-5-10-5z" stroke="#06B6D4" stroke-width="1.5" fill="none"/>
          <path d="M2 17l10 5 10-5" stroke="#06B6D4" stroke-width="1.5" fill="none"/>
          <path d="M2 12l10 5 10-5" stroke="#06B6D4" stroke-width="1.5" stroke-opacity="0.4" fill="none"/>
        </svg>
        <span class="font-mono text-sm font-semibold tracking-widest text-signal-400">BTG_NEXUS</span>
      </div>
      <span class="text-nexus-500 font-mono text-xs tracking-wider">
        UPTIME: {{ uptime }}
      </span>
    </div>

    <!-- Center: Mode Selector -->
    <div class="flex items-center">
      <div
        :class="['cyber-toggle', { active: isExternal }]"
        @click="toggleMode"
        role="switch"
        :aria-checked="isExternal"
        aria-label="mode selector"
        tabindex="0"
        @keydown.enter="toggleMode"
        @keydown.space.prevent="toggleMode"
      >
        <div class="cyber-toggle-thumb"></div>
        <div class="cyber-toggle-label">
          <span class="cyber-toggle-label-left">本地预设策略</span>
          <span class="cyber-toggle-label-right">第三方 API 托管</span>
        </div>
      </div>
    </div>

    <!-- Right: Network Status -->
    <div class="flex items-center gap-4">
      <div class="flex items-center gap-2">
        <span class="status-dot normal"></span>
        <span class="text-nexus-500 font-mono text-xs tracking-wider">WS</span>
        <span class="font-mono text-xs text-signal-400">
          PING: {{ wsLatency }}ms
        </span>
      </div>
      <div class="flex items-center gap-2">
        <span class="font-mono text-xs text-nexus-500 tracking-wider">CONN</span>
        <span class="font-mono text-xs text-nexus-200">{{ wsConnections }}</span>
      </div>
      <div class="h-5 w-px bg-nexus-800"></div>
      <div class="flex items-center gap-2">
        <span :class="['status-dot', statusDotClass]"></span>
        <span
          :class="[
            'font-mono text-xs font-medium tracking-wider',
            systemStatus === 'normal' ? 'text-signal-400' :
            systemStatus === 'degraded' ? 'text-warn-400' : 'text-danger-400'
          ]"
        >
          {{ statusLabel }}
        </span>
      </div>
    </div>
  </header>
</template>