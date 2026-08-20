<script setup>
import { onMounted, ref } from 'vue'
import { Bluetooth, Plug, Radio, RefreshCw, Trash2, Zap } from '@lucide/vue'

import { gatewayApi, getApiError } from '../services/api'

const scanning = ref(false)
const scanTimeout = ref(4)
const discovered = ref([])
const registered = ref([])
const busy = ref('')
const message = ref('')
const notice = ref({ kind: '', text: '' })

const kindLabels = {
  coyote: 'Coyote 电刺激',
  mi_band: '小米手环',
  thermo: '温湿度计',
  ble_generic: '通用 BLE',
}

function show(kind, text) {
  notice.value = { kind, text }
  window.setTimeout(() => {
    if (notice.value.text === text) notice.value = { kind: '', text: '' }
  }, 4000)
}

async function loadRegistry() {
  try {
    registered.value = await gatewayApi.listDevices()
  } catch (err) {
    show('error', getApiError(err, '加载设备失败'))
  }
}

async function runScan() {
  scanning.value = true
  discovered.value = []
  message.value = `扫描中…（${scanTimeout.value}s）`
  try {
    const list = await gatewayApi.scanBle(scanTimeout.value)
    discovered.value = list
    message.value = list.length
      ? `发现 ${list.length} 个 BLE 设备`
      : '未发现设备（可加大扫描时长或靠近目标设备）'
  } catch (err) {
    message.value = ''
    show('error', getApiError(err, 'BLE 扫描失败'))
  } finally {
    scanning.value = false
  }
}

async function register(address, name, kindTip) {
  busy.value = address
  try {
    await gatewayApi.registerDevice({ address, name, kind: kindTip || undefined })
    show('ok', `已登记 ${name || address}`)
    await loadRegistry()
  } catch (err) {
    show('error', getApiError(err, '登记失败'))
  } finally {
    busy.value = ''
  }
}

async function probe(address) {
  busy.value = `probe-${address}`
  try {
    const res = await gatewayApi.probeDevice(address)
    const text = res.reachable
      ? `连接正常（${res.latency_ms}ms）`
      : `不可达：${res.detail}`
    show(res.reachable ? 'ok' : 'error', `${address} ${text}`)
  } catch (err) {
    show('error', getApiError(err, '探测失败'))
  } finally {
    busy.value = ''
  }
}

async function remove(address) {
  busy.value = `rm-${address}`
  try {
    await gatewayApi.unregisterDevice(address)
    await loadRegistry()
  } catch (err) {
    show('error', getApiError(err, '移除失败'))
  } finally {
    busy.value = ''
  }
}

async function clearAll() {
  if (!window.confirm('清空全部已登记设备？')) return
  busy.value = 'clear'
  try {
    await gatewayApi.clearDevices()
    await loadRegistry()
  } catch (err) {
    show('error', getApiError(err, '清空失败'))
  } finally {
    busy.value = ''
  }
}

onMounted(loadRegistry)
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 class="text-xl font-semibold text-zinc-100">设备中心</h1>
        <p class="mt-1 text-sm text-zinc-500">
          扫描周边 BLE 设备、登记到接入池，并验证连接可达性。
        </p>
      </div>

      <div class="flex items-center gap-2">
        <label class="flex items-center gap-2 text-xs text-zinc-400">
          扫描时长
          <select
            v-model="scanTimeout"
            class="rounded-lg border border-white/10 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-200"
          >
            <option :value="3">3s</option>
            <option :value="4">4s</option>
            <option :value="8">8s</option>
            <option :value="12">12s</option>
          </select>
        </label>
        <button
          class="inline-flex items-center gap-2 rounded-xl border border-cyan-400/30 bg-cyan-400/10 px-4 py-2 text-sm font-medium text-cyan-200 transition hover:bg-cyan-400/20 disabled:opacity-50"
          :disabled="scanning"
          @click="runScan"
        >
          <RefreshCw class="size-4" :class="{ 'animate-spin': scanning }" />
          {{ scanning ? '扫描中' : '开始扫描' }}
        </button>
      </div>
    </div>

    <p v-if="message" class="text-sm text-zinc-400">{{ message }}</p>
    <div
      v-if="notice.text"
      class="rounded-xl border px-4 py-3 text-sm"
      :class="
        notice.kind === 'ok'
          ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200'
          : 'border-rose-400/30 bg-rose-400/10 text-rose-200'
      "
    >
      {{ notice.text }}
    </div>

    <section class="rounded-2xl border border-white/10 bg-white/[0.02]">
      <header class="flex items-center gap-2 border-b border-white/10 px-5 py-4">
        <Radio class="size-4 text-cyan-400" />
        <h2 class="text-sm font-semibold text-zinc-100">扫描结果</h2>
      </header>

      <p v-if="!discovered.length && !scanning" class="px-5 py-8 text-center text-sm text-zinc-600">
        点击「开始扫描」发现周边 BLE 设备
      </p>

      <ul class="divide-y divide-white/5">
        <li
          v-for="d in discovered"
          :key="d.address"
          class="flex flex-wrap items-center gap-3 px-5 py-3"
        >
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-medium text-zinc-200">{{ d.name || '未命名设备' }}</p>
            <p class="font-mono text-xs text-zinc-500">
              {{ d.address }}
              <span v-if="d.rssi !== null && d.rssi !== undefined" class="ml-2">
                RSSI {{ d.rssi }}dBm
              </span>
              <span class="ml-2">{{ kindLabels[d.kind_tip] || d.kind_tip }}</span>
            </p>
          </div>
          <button
            class="inline-flex items-center gap-1 rounded-lg border border-white/10 px-3 py-1.5 text-xs font-medium text-zinc-300 transition hover:border-cyan-400/30 hover:text-cyan-200 disabled:opacity-50"
            :disabled="busy === d.address"
            @click="register(d.address, d.name, d.kind_tip)"
          >
            <Plug class="size-3.5" />
            {{ busy === d.address ? '登记中' : '登记' }}
          </button>
        </li>
      </ul>
    </section>

    <section class="rounded-2xl border border-white/10 bg-white/[0.02]">
      <header class="flex items-center justify-between border-b border-white/10 px-5 py-4">
        <div class="flex items-center gap-2">
          <Bluetooth class="size-4 text-cyan-400" />
          <h2 class="text-sm font-semibold text-zinc-100">已登记设备（接入池）</h2>
          <span class="rounded-full border border-white/10 px-2 py-0.5 text-xs text-zinc-400">
            {{ registered.length }}
          </span>
        </div>
        <button
          v-if="registered.length"
          class="inline-flex items-center gap-1 rounded-lg border border-rose-400/20 px-3 py-1.5 text-xs text-rose-300 transition hover:bg-rose-400/10 disabled:opacity-50"
          :disabled="busy === 'clear'"
          @click="clearAll"
        >
          <Trash2 class="size-3.5" />
          清空
        </button>
      </header>

      <p v-if="!registered.length" class="px-5 py-8 text-center text-sm text-zinc-600">
        尚未登记设备。扫描后将目标设备加入此处，供「监控配置」绑定到逻辑通道。
      </p>

      <ul class="divide-y divide-white/5">
        <li v-for="d in registered" :key="d.address" class="flex flex-wrap items-center gap-3 px-5 py-3">
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-medium text-zinc-200">
              {{ d.name || d.address }}
              <span class="ml-2 rounded-full border border-cyan-400/20 bg-cyan-400/10 px-2 py-0.5 text-[11px] text-cyan-200">
                {{ kindLabels[d.kind] || d.kind }}
              </span>
            </p>
            <p class="font-mono text-xs text-zinc-500">{{ d.address }}</p>
          </div>
          <button
            class="inline-flex items-center gap-1 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-emerald-400/30 hover:text-emerald-200 disabled:opacity-50"
            :disabled="busy === `probe-${d.address}`"
            @click="probe(d.address)"
          >
            <Zap class="size-3.5" />
            {{ busy === `probe-${d.address}` ? '探测中' : '探测连接' }}
          </button>
          <button
            class="inline-flex items-center gap-1 rounded-lg border border-rose-400/20 px-3 py-1.5 text-xs text-rose-300 transition hover:bg-rose-400/10 disabled:opacity-50"
            :disabled="busy === `rm-${d.address}`"
            @click="remove(d.address)"
          >
            <Trash2 class="size-3.5" />
            移除
          </button>
        </li>
      </ul>
    </section>
  </div>
</template>