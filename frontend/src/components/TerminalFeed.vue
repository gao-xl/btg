<script setup>
import { Bot, RadioTower, ShieldAlert, Terminal } from '@lucide/vue'

defineProps({
  items: {
    type: Array,
    default: () => [],
  },
})

const icons = {
  ai: Bot,
  telemetry: RadioTower,
  system: ShieldAlert,
}

function formatTime(timestamp) {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(timestamp))
}
</script>

<template>
  <section
    class="cyber-panel scanline flex min-h-[420px] flex-col"
    aria-labelledby="terminal-title"
  >
    <header class="panel-header">
      <div>
        <p class="panel-kicker">LLM INTERROGATION FEED</p>
        <h2
          id="terminal-title"
          class="panel-title"
        >
          AI 审讯终端
        </h2>
      </div>
      <Terminal
        class="size-5 text-purple-400"
        aria-hidden="true"
      />
    </header>

    <div
      class="relative z-10 flex-1 overflow-y-auto bg-black/35 p-4 font-mono text-xs leading-6 sm:p-5"
      aria-live="polite"
    >
      <div
        v-if="!items.length"
        class="grid min-h-64 place-items-center text-center text-zinc-600"
      >
        <div>
          <Terminal
            class="mx-auto mb-3 size-7"
            aria-hidden="true"
          />
          <p>正在等待 LLM 对话和体征注入日志。</p>
          <p class="mt-1 text-[11px] text-zinc-700">不会使用模拟消息填充终端。</p>
        </div>
      </div>

      <ol
        v-else
        class="space-y-4"
      >
        <li
          v-for="item in items"
          :key="item.id"
          class="flex gap-3"
        >
          <div
            class="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg border"
            :class="
              item.kind === 'ai'
                ? 'border-purple-400/25 bg-purple-400/10 text-purple-300'
                : item.kind === 'telemetry'
                  ? 'border-cyan-400/25 bg-cyan-400/10 text-cyan-300'
                  : 'border-amber-400/25 bg-amber-400/10 text-amber-300'
            "
          >
            <component
              :is="icons[item.kind] || Terminal"
              class="size-3.5"
              aria-hidden="true"
            />
          </div>
          <div class="min-w-0">
            <div
              class="flex items-center gap-2 text-[10px] uppercase tracking-widest text-zinc-600"
            >
              <span>{{ item.kind }}</span>
              <time :datetime="new Date(item.timestamp).toISOString()">{{
                formatTime(item.timestamp)
              }}</time>
            </div>
            <p class="mt-1 break-words text-zinc-300">{{ item.message }}</p>
          </div>
        </li>
      </ol>
    </div>
  </section>
</template>
