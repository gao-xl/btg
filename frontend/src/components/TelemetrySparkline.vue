<script setup>
import { computed } from 'vue'

const props = defineProps({
  points: {
    type: Array,
    default: () => [],
  },
})

const path = computed(() => {
  if (props.points.length < 2) return ''
  const values = props.points.map((point) => Number(point.value)).filter(Number.isFinite)
  if (values.length < 2) return ''
  const min = Math.min(...values) - 5
  const max = Math.max(...values) + 5
  const span = Math.max(max - min, 1)
  return values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * 100
      const y = 38 - ((value - min) / span) * 34
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`
    })
    .join(' ')
})
</script>

<template>
  <div
    class="h-24 w-full"
    aria-label="心率趋势图"
    role="img"
  >
    <svg
      v-if="path"
      class="h-full w-full overflow-visible"
      viewBox="0 0 100 40"
      preserveAspectRatio="none"
    >
      <path
        d="M 0 20 L 100 20"
        fill="none"
        stroke="rgba(113,113,122,.22)"
        stroke-dasharray="2 3"
      />
      <path
        :d="path"
        fill="none"
        stroke="#22d3ee"
        stroke-width="1.8"
        vector-effect="non-scaling-stroke"
      />
    </svg>
    <div
      v-else
      class="grid h-full place-items-center rounded-xl border border-dashed border-white/10 bg-black/10 font-mono text-xs text-zinc-600"
    >
      等待心率数据…
    </div>
  </div>
</template>
