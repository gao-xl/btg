<script setup>
import { onMounted, ref } from 'vue'
import { Cable, Plus, RefreshCw, Save, Trash2 } from '@lucide/vue'

import { gatewayApi, getApiError } from '../services/api'

const bindings = ref([])
const candidates = ref({ registered_devices: [], known_plugins: [] })
const busy = ref('')
const notice = ref({ kind: '', text: '' })

function show(kind, text) {
  notice.value = { kind, text }
  window.setTimeout(() => {
    if (notice.value.text === text) notice.value = { kind: '', text: '' }
  }, 5000)
}

async function load() {
  busy.value = 'load'
  try {
    ;[bindings.value, candidates.value] = await Promise.all([
      gatewayApi.listBindings(),
      gatewayApi.getCandidates(),
    ])
    if (!bindings.value.length) show('warn', '未配置任何逻辑通道（config/devices.yaml 为空）')
  } catch (err) {
    show('error', getApiError(err, '加载绑定配置失败'))
  } finally {
    busy.value = ''
  }
}

function plugins() {
  return candidates.value.known_plugins?.length ? candidates.value.known_plugins : ['mock_sensor', 'mock_actuator']
}

function addDevice(channel) {
  channel.devices.push({
    order: channel.devices.length + 1,
    plugin: plugins()[0] || '',
    priority: channel.devices.length ? 2 : 1,
    config: {},
    _editable: true,
  })
}

function removeDevice(channel, index) {
  channel.devices.splice(index, 1)
}

function compact(payload) {
  return {
    channel: payload.channel,
    devices: payload.devices.map((d) => {
      const out = { plugin: d.plugin, priority: Number(d.priority) || 1 }
      const cfg = { ...(d.config || {}) }
      if (d.address) cfg.address = d.address
      if (Object.keys(cfg).length) out.config = cfg
      return out
    }),
  }
}

async function saveChannel(channel) {
  const key = `sav-${channel.channel}`
  busy.value = key
  try {
    const payload = compact(channel)
    if (!payload.devices.length) {
      show('warn', `${channel.channel} 未添加任何设备，已跳过保存`)
      return
    }
    const res = await gatewayApi.saveBindings(payload)
    show('ok', `已保存 ${payload.channel}：${res.devices.length} 个主备绑定`)
    await load()
  } catch (err) {
    show('error', getApiError(err, '保存绑定失败'))
  } finally {
    busy.value = ''
  }
}

async function applyReload() {
  busy.value = 'reload'
  try {
    const res = await gatewayApi.reloadBindings()
    show(res.reloaded ? 'ok' : 'warn', res.reloaded ? '通道配置已热重载生效' : `配置已保存但重载未完成：${res.detail || ''}`)
  } catch (err) {
    show('error', getApiError(err, '热重载失败'))
  } finally {
    busy.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 class="text-xl font-semibold text-zinc-100">监控配置</h1>
        <p class="mt-1 text-sm text-zinc-500">
          把已登记设备绑定到逻辑通道（priority 1=主 / 2=备），保存后热重载生效。
        </p>
      </div>
      <div class="flex items-center gap-2">
        <button
          class="inline-flex items-center gap-2 rounded-xl border border-white/10 px-4 py-2 text-sm text-zinc-300 transition hover:border-cyan-400/30 hover:text-cyan-200 disabled:opacity-50"
          :disabled="busy === 'load' || busy === 'reload'"
          @click="load"
        >
          <RefreshCw class="size-4" :class="{ 'animate-spin': busy === 'load' }" />
          刷新
        </button>
        <button
          class="inline-flex items-center gap-2 rounded-xl border border-emerald-400/30 bg-emerald-400/10 px-4 py-2 text-sm font-medium text-emerald-200 transition hover:bg-emerald-400/20 disabled:opacity-50"
          :disabled="busy === 'load' || busy === 'reload'"
          @click="applyReload"
        >
          <RefreshCw class="size-4" :class="{ 'animate-spin': busy === 'reload' }" />
          {{ busy === 'reload' ? '重载中' : '热重载全部配置' }}
        </button>
      </div>
    </div>

    <div
      v-if="notice.text"
      class="rounded-xl border px-4 py-3 text-sm"
      :class="
        notice.kind === 'ok'
          ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200'
          : notice.kind === 'warn'
            ? 'border-amber-400/30 bg-amber-400/10 text-amber-200'
            : 'border-rose-400/30 bg-rose-400/10 text-rose-200'
      "
    >
      {{ notice.text }}
    </div>

    <div class="grid gap-4 lg:grid-cols-2">
      <section class="rounded-2xl border border-white/10 bg-white/[0.02]">
        <header class="flex items-center gap-2 border-b border-white/10 px-5 py-4">
          <Cable class="size-4 text-cyan-400" />
          <h2 class="text-sm font-semibold text-zinc-100">可绑定设备（接入池）</h2>
        </header>
        <ul class="divide-y divide-white/5">
          <li v-for="d in candidates.registered_devices" :key="d.address" class="flex items-center gap-3 px-5 py-3">
            <span class="size-2 shrink-0 rounded-full bg-cyan-400/60" />
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm text-zinc-200">{{ d.name || d.address }}</p>
              <p class="font-mono text-xs text-zinc-500">{{ d.address }} · {{ d.kind }}</p>
            </div>
          </li>
          <li v-if="!candidates.registered_devices?.length" class="px-5 py-6 text-center text-sm text-zinc-600">
            接入池为空。先在「设备中心」扫描并登记设备。
          </li>
        </ul>
      </section>

      <section class="rounded-2xl border border-white/10 bg-white/[0.02]">
        <header class="flex items-center gap-2 border-b border-white/10 px-5 py-4">
          <Cable class="size-4 text-cyan-400" />
          <h2 class="text-sm font-semibold text-zinc-100">已知设备插件</h2>
        </header>
        <div class="flex flex-wrap gap-2 p-5">
          <span
            v-for="p in candidates.known_plugins"
            :key="p"
            class="rounded-lg border border-purple-400/20 bg-purple-400/10 px-2.5 py-1 font-mono text-xs text-purple-200"
          >
            {{ p }}
          </span>
          <span v-if="!candidates.known_plugins?.length" class="text-sm text-zinc-600">
            暂未识别插件（保存时可用默认 mock 插件）
          </span>
        </div>
      </section>
    </div>

    <section v-for="ch in bindings" :key="ch.channel" class="overflow-hidden rounded-2xl border border-white/10 bg-white/[0.02]">
      <header class="flex items-center gap-3 border-b border-white/10 px-5 py-4">
        <h3 class="font-mono text-sm font-semibold text-zinc-100">{{ ch.channel }}</h3>
        <span
          class="rounded-full border px-2 py-0.5 text-[11px]"
          :class="
            ch.type === 'actuator'
              ? 'border-amber-400/25 bg-amber-400/10 text-amber-200'
              : 'border-cyan-400/25 bg-cyan-400/10 text-cyan-200'
          "
        >
          {{ ch.type }}
        </span>
        <span v-if="ch.active" class="ml-auto rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2 py-0.5 text-[11px] text-emerald-300">
          激活 {{ ch.active }}
        </span>
      </header>

      <div class="divide-y divide-white/5">
        <div v-for="(d, idx) in ch.devices" :key="`${ch.channel}-${idx}`" class="flex flex-wrap items-center gap-3 px-5 py-3">
          <select
            v-model="d.plugin"
            :class="{ 'border-emerald-400/30 text-emerald-200': d.priority === 1, 'border-purple-400/30 text-purple-200': d.priority === 2 }"
            class="rounded-lg border border-white/10 bg-zinc-900 px-2 py-1.5 font-mono text-xs text-zinc-200"
          >
            <option v-for="p in plugins()" :key="p" :value="p">{{ p }}</option>
          </select>
          <select
            v-model="d.priority"
            class="rounded-lg border border-white/10 bg-zinc-900 px-2 py-1.5 text-xs text-zinc-200"
          >
            <option :value="1">主设备 (1)</option>
            <option :value="2">备用设备 (2)</option>
          </select>
          <select
            v-if="ch.type === 'sensor'"
            v-model="d.address"
            class="min-w-40 rounded-lg border border-white/10 bg-zinc-900 px-2 py-1.5 font-mono text-xs text-zinc-200"
          >
            <option value="">地址：未指定</option>
            <option v-for="rd in candidates.registered_devices" :key="rd.address" :value="rd.address">
              {{ rd.name || rd.address }}
            </option>
          </select>
          <span v-if="d.config?.unit" class="text-xs text-zinc-500">unit={{ d.config.unit }}</span>
          <button
            class="ml-auto inline-flex items-center gap-1 rounded-lg border border-rose-400/20 px-2.5 py-1.5 text-xs text-rose-300 transition hover:bg-rose-400/10"
            @click="removeDevice(ch, idx)"
          >
            <Trash2 class="size-3.5" />
          </button>
        </div>
      </div>

      <footer class="flex gap-2 border-t border-white/10 px-5 py-3">
        <button
          class="inline-flex items-center gap-1 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-cyan-400/30 hover:text-cyan-200"
          @click="addDevice(ch)"
        >
          <Plus class="size-3.5" />
          添加设备绑定
        </button>
        <button
          class="ml-auto inline-flex items-center gap-1 rounded-lg border border-emerald-400/30 bg-emerald-400/10 px-4 py-1.5 text-xs font-medium text-emerald-200 transition hover:bg-emerald-400/20 disabled:opacity-50"
          :disabled="busy === `sav-${ch.channel}`"
          @click="saveChannel(ch)"
        >
          <Save class="size-3.5" />
          {{ busy === `sav-${ch.channel}` ? '保存中' : '保存此通道' }}
        </button>
      </footer>
    </section>

    <p v-if="!bindings.length && busy !== 'load'" class="text-center text-sm text-zinc-600">
      加载中或无通道配置…
    </p>
  </div>
</template>