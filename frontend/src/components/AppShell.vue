<script setup>
import { Activity, Bluetooth, BookOpenText, ChevronRight, Radio, Settings, ShieldCheck } from '@lucide/vue'

import { useGateway } from '../composables/useGateway'

const { connectionState, isConnected } = useGateway()

const navigation = [
  { name: '实时监控', to: '/', icon: Activity },
  { name: '设备中心', to: '/devices', icon: Bluetooth },
  { name: '剧本设计', to: '/playbooks', icon: BookOpenText },
  { name: '全局配置', to: '/settings', icon: Settings },
]
</script>

<template>
  <div class="min-h-screen text-zinc-200">
    <a
      href="#main-content"
      class="fixed left-4 top-4 z-50 -translate-y-24 rounded-lg bg-cyan-400 px-4 py-2 font-semibold text-zinc-950 focus:translate-y-0"
    >
      跳到主内容
    </a>

    <aside
      class="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-white/10 bg-zinc-950/85 px-4 py-5 backdrop-blur-xl lg:flex lg:flex-col"
      aria-label="主导航"
    >
      <div class="flex items-center gap-3 px-2">
        <div
          class="grid size-10 place-items-center rounded-xl border border-cyan-400/30 bg-cyan-400/10 shadow-cyan"
        >
          <Radio
            class="size-5 text-cyan-300"
            aria-hidden="true"
          />
        </div>
        <div>
          <p class="font-mono text-[10px] tracking-[0.28em] text-cyan-400">BTG // NEXUS</p>
          <p class="mt-1 text-sm font-semibold text-zinc-100">Cyber Telemetry</p>
        </div>
      </div>

      <nav class="mt-10 space-y-2">
        <RouterLink
          v-for="item in navigation"
          :key="item.to"
          :to="item.to"
          class="group flex min-h-12 items-center gap-3 rounded-xl border border-transparent px-3 text-sm font-medium text-zinc-500 transition hover:border-white/10 hover:bg-white/5 hover:text-zinc-200"
          active-class="!border-cyan-400/20 !bg-cyan-400/10 !text-cyan-200"
        >
          <component
            :is="item.icon"
            class="size-4"
            aria-hidden="true"
          />
          <span>{{ item.name }}</span>
          <ChevronRight
            class="ml-auto size-4 opacity-0 transition group-hover:opacity-100"
            aria-hidden="true"
          />
        </RouterLink>
      </nav>

      <div class="mt-auto rounded-xl border border-white/10 bg-white/[0.03] p-4">
        <div class="flex items-center gap-2">
          <ShieldCheck
            class="size-4 text-purple-400"
            aria-hidden="true"
          />
          <span class="text-xs font-semibold text-zinc-300">Safety boundary</span>
        </div>
        <p class="mt-2 text-xs leading-5 text-zinc-600">
          AI 只能建议降级、暂停或急停，不得根据体征自动加强输出。
        </p>
      </div>
    </aside>

    <div class="lg:pl-64">
      <header
        class="sticky top-0 z-20 border-b border-white/10 bg-zinc-950/80 px-4 py-3 backdrop-blur-xl sm:px-6 lg:px-8"
      >
        <div class="mx-auto flex max-w-[1600px] items-center justify-between gap-4">
          <div class="flex items-center gap-3 lg:hidden">
            <div
              class="grid size-9 place-items-center rounded-lg border border-cyan-400/30 bg-cyan-400/10"
            >
              <Radio
                class="size-4 text-cyan-300"
                aria-hidden="true"
              />
            </div>
            <span class="font-mono text-xs text-zinc-300">BTG // NEXUS</span>
          </div>

          <div class="hidden lg:block">
            <p class="font-mono text-[10px] uppercase tracking-[0.24em] text-zinc-600">
              Control surface
            </p>
            <p class="mt-1 text-sm text-zinc-400">实时生物体征与网关安全控制</p>
          </div>

          <div
            class="flex items-center gap-2 rounded-full border px-3 py-1.5 font-mono text-xs"
            :class="
              isConnected
                ? 'border-cyan-400/25 bg-cyan-400/10 text-cyan-300'
                : 'border-amber-400/25 bg-amber-400/10 text-amber-300'
            "
            role="status"
            aria-live="polite"
          >
            <span
              class="size-2 rounded-full"
              :class="isConnected ? 'bg-cyan-400 shadow-cyan' : 'bg-amber-400'"
            />
            {{
              connectionState === 'connected'
                ? '网关已连接'
                : connectionState === 'connecting'
                  ? '正在连接'
                  : '网关离线'
            }}
          </div>
        </div>
      </header>

      <div class="mx-auto max-w-[1600px] px-4 py-6 pb-24 sm:px-6 lg:px-8 lg:py-8">
        <RouterView />
      </div>
    </div>

    <nav
      class="fixed inset-x-3 bottom-3 z-30 flex justify-around rounded-2xl border border-white/10 bg-zinc-950/90 p-2 shadow-2xl backdrop-blur-xl lg:hidden"
      aria-label="移动端导航"
    >
      <RouterLink
        v-for="item in navigation"
        :key="item.to"
        :to="item.to"
        class="flex min-h-12 min-w-20 flex-col items-center justify-center gap-1 rounded-xl text-[11px] text-zinc-500"
        active-class="bg-cyan-400/10 text-cyan-300"
      >
        <component
          :is="item.icon"
          class="size-4"
          aria-hidden="true"
        />
        {{ item.name }}
      </RouterLink>
    </nav>
  </div>
</template>
