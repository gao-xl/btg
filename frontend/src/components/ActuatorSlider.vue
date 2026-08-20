<script setup>
import { computed } from 'vue'
import { Gauge, LoaderCircle, LockKeyhole } from '@lucide/vue'

const props = defineProps({
  channel: {
    type: String,
    required: true,
  },
  modelValue: {
    type: Number,
    required: true,
  },
  max: {
    type: Number,
    default: 100,
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  busy: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['update:modelValue'])

const safeMax = computed(() => Math.max(0, Math.min(100, Number(props.max) || 0)))
const percentage = computed(() => {
  if (safeMax.value === 0) return 0
  return Math.round((props.modelValue / safeMax.value) * 100)
})

function onInput(event) {
  emit('update:modelValue', Number(event.target.value))
}
</script>

<template>
  <article class="panel-surface group relative overflow-hidden p-5">
    <div
      class="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan-400/70 to-transparent"
    />

    <div class="flex items-start justify-between gap-4">
      <div class="flex items-center gap-3">
        <div
          class="grid size-11 place-items-center rounded-xl border border-cyan-400/20 bg-cyan-400/5 text-cyan-300"
        >
          <Gauge
            class="size-5"
            aria-hidden="true"
          />
        </div>
        <div>
          <p class="font-mono text-[0.68rem] uppercase tracking-[0.26em] text-zinc-500">
            Actuator channel
          </p>
          <h3 class="mt-1 font-display text-xl font-semibold text-white">通道 {{ channel }}</h3>
        </div>
      </div>

      <div class="text-right">
        <p class="font-mono text-3xl font-semibold tabular-nums text-cyan-300">{{ modelValue }}</p>
        <p class="font-mono text-[0.65rem] uppercase tracking-widest text-zinc-500">
          / {{ safeMax }} limit
        </p>
      </div>
    </div>

    <div class="mt-6">
      <div
        class="mb-2 flex items-center justify-between font-mono text-[0.68rem] uppercase tracking-wider text-zinc-500"
      >
        <span>Output intensity</span>
        <span>{{ percentage }}% of cap</span>
      </div>
      <input
        :id="`channel-${channel}-intensity`"
        class="cyber-range w-full"
        type="range"
        min="0"
        :max="safeMax"
        step="1"
        :value="modelValue"
        :disabled="disabled || busy"
        :aria-label="`通道 ${channel} 强度，当前 ${modelValue}，安全上限 ${safeMax}`"
        @input="onInput"
      />
    </div>

    <div class="mt-4 flex items-center gap-2 text-xs">
      <LoaderCircle
        v-if="busy"
        class="size-3.5 animate-spin text-cyan-300"
        aria-hidden="true"
      />
      <LockKeyhole
        v-else-if="disabled"
        class="size-3.5 text-amber-300"
        aria-hidden="true"
      />
      <span :class="disabled ? 'text-amber-200/80' : 'text-zinc-500'">
        {{
          busy ? '正在同步网关…' : disabled ? '安全互锁已阻止输出' : '拖动时自动同步，松手无需确认'
        }}
      </span>
    </div>
  </article>
</template>
