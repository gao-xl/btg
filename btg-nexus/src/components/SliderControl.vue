<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  modelValue: { type: Number, default: 35 },
  clampThreshold: { type: Number, default: 60 },
  unit: { type: String, default: '%' }
})

const emit = defineEmits(['update:modelValue'])

const localValue = ref(props.modelValue)

const clampedValue = computed(() => {
  return Math.min(localValue.value, props.clampThreshold)
})

const isClamped = computed(() => {
  return localValue.value > props.clampThreshold
})

function onInput(e) {
  localValue.value = Number(e.target.value)
  emit('update:modelValue', clampedValue.value)
}

const thresholdPercent = computed(() => `${props.clampThreshold}%`)
</script>

<template>
  <div class="flex flex-col gap-2">
    <div class="flex items-center justify-between">
      <span class="font-mono text-xs tracking-wider text-nexus-400">{{ label }}</span>
      <div class="flex items-center gap-2">
        <span
          :class="[
            'font-mono text-sm font-semibold tabular-nums',
            isClamped ? 'text-danger-400' : 'text-signal-400'
          ]"
        >
          {{ clampedValue }}{{ unit }}
        </span>
        <span v-if="isClamped" class="font-mono text-[10px] text-danger-400 tracking-wider">
          截断: 真实输出 {{ clampedValue }}{{ unit }}
        </span>
      </div>
    </div>
    <div class="relative">
      <input
        type="range"
        min="0"
        max="100"
        :value="localValue"
        @input="onInput"
        class="clamped-slider"
        :aria-label="`${label} slider`"
      />
      <!-- Threshold dashed marker -->
      <div
        class="threshold-marker pointer-events-none"
        :style="{ left: thresholdPercent }"
      ></div>
    </div>
    <div class="flex justify-between">
      <span class="font-mono text-[10px] text-nexus-600">0</span>
      <span class="font-mono text-[10px] text-danger-400">
        MAX: {{ clampThreshold }}{{ unit }}
      </span>
      <span class="font-mono text-[10px] text-nexus-600">100</span>
    </div>
  </div>
</template>