<script setup>
import { ref } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: 'continuous' }
})

const emit = defineEmits(['update:modelValue'])

const modes = [
  { id: 'continuous', label: '连续', icon: '∿' },
  { id: 'pulse', label: '脉冲', icon: '⊓' },
  { id: 'sine', label: '正弦', icon: '∿' },
  { id: 'square', label: '方波', icon: '⊏' },
  { id: 'sawtooth', label: '锯齿', icon: '⋋' },
  { id: 'random', label: '随机', icon: '≋' }
]

function select(modeId) {
  emit('update:modelValue', modeId)
}
</script>

<template>
  <div class="flex flex-col gap-2">
    <span class="font-mono text-xs tracking-wider text-nexus-400">波形预设</span>
    <div class="grid grid-cols-3 gap-2">
      <button
        v-for="mode in modes"
        :key="mode.id"
        :class="['wave-btn', { active: modelValue === mode.id }]"
        @click="select(mode.id)"
        :aria-pressed="modelValue === mode.id"
        :aria-label="`${mode.label} waveform`"
      >
        <span class="font-mono text-sm" aria-hidden="true">{{ mode.icon }}</span>
        <span>{{ mode.label }}</span>
      </button>
    </div>
  </div>
</template>