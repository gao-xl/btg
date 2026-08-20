<script setup>
defineProps({
  modelValue: { type: Boolean, required: true },
  disabled: { type: Boolean, default: false },
  label: { type: String, default: '' },
})
defineEmits(['update:modelValue'])
</script>

<template>
  <button
    type="button"
    role="switch"
    :aria-checked="modelValue"
    :aria-label="label"
    :disabled="disabled"
    class="relative inline-flex h-7 w-12 shrink-0 items-center rounded-full border transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-40"
    :class="
      modelValue
        ? 'border-cyan-400/50 bg-cyan-400/25 shadow-[0_0_14px_rgba(34,211,238,0.25)]'
        : 'border-white/15 bg-zinc-800'
    "
    @click="$emit('update:modelValue', !modelValue)"
  >
    <span
      class="pointer-events-none absolute size-5 rounded-full transition-transform duration-200"
      :class="
        modelValue
          ? 'translate-x-6 bg-cyan-300 shadow-[0_0_10px_rgba(34,211,238,0.8)]'
          : 'translate-x-1 bg-zinc-500'
      "
    />
  </button>
</template>
