<script setup>
import { computed, reactive, ref } from 'vue'
import { dump } from 'js-yaml'
import {
  ArrowDown,
  ArrowUp,
  BookOpenText,
  Download,
  FileCode2,
  Plus,
  Save,
  ShieldCheck,
  Trash2,
} from '@lucide/vue'
import { gatewayApi, getApiError } from '../services/api'

let sceneCounter = 1

function createScene() {
  const index = sceneCounter++
  return {
    uid: crypto.randomUUID(),
    id: `scene_${index}`,
    name: `阶段 ${index}`,
    ttsText: '',
    intensity: 10,
    triggerSensor: 'heart_rate',
    thresholdValue: 120,
    sustainedSeconds: 3,
  }
}

const playbook = reactive({
  id: 'operator_playbook',
  name: '新建遥测玩法',
  description: '由控制台生成，所有分支均以安全清零结束。',
  scenes: [createScene()],
})
const selectedUid = ref(playbook.scenes[0].uid)
const saveBusy = ref(false)
const saveMessage = ref('')
const saveError = ref('')

const selectedScene = computed(
  () => playbook.scenes.find((scene) => scene.uid === selectedUid.value) ?? playbook.scenes[0],
)

const validationErrors = computed(() => {
  const errors = []
  if (!/^[a-z][a-z0-9_]{2,63}$/.test(playbook.id)) {
    errors.push('剧本 ID 必须以小写字母开头，只能包含小写字母、数字与下划线（3–64 位）。')
  }
  if (!playbook.name.trim()) errors.push('场景名称不能为空。')
  const ids = new Set()
  for (const [index, scene] of playbook.scenes.entries()) {
    const label = scene.name || `阶段 ${index + 1}`
    if (!/^[a-z][a-z0-9_]{2,63}$/.test(scene.id)) errors.push(`${label} 的阶段 ID 格式无效。`)
    if (ids.has(scene.id)) errors.push(`${label} 的阶段 ID 与其他阶段重复。`)
    ids.add(scene.id)
    if (!scene.ttsText.trim()) errors.push(`${label} 尚未填写 TTS 旁白。`)
    if (!Number.isFinite(Number(scene.intensity)) || scene.intensity < 0 || scene.intensity > 100) {
      errors.push(`${label} 的动作强度必须在 0–100。`)
    }
    if (!Number.isFinite(Number(scene.thresholdValue)) || scene.thresholdValue < 0) {
      errors.push(`${label} 的触发阈值必须为非负数。`)
    }
  }
  return errors
})

const playbookPayload = computed(() => {
  const scenes = {}
  for (const scene of playbook.scenes) {
    scenes[scene.id] = {
      description: scene.name,
      tts_text: scene.ttsText,
      actuator_cmds: [
        {
          actuator_id: 'primary_actuator',
          channel: 'intensity',
          value: Number(scene.intensity),
          unit: 'percent',
          clamp_to_system_max: true,
        },
      ],
      wait_condition: {
        event_type: 'telemetry',
        field: scene.triggerSensor,
        operator: 'gte',
        value: Number(scene.thresholdValue),
        duration_seconds: Number(scene.sustainedSeconds),
        timeout_seconds: 180,
      },
      on_success: 'safety_stop',
      on_timeout: 'safety_stop',
    }
  }

  scenes.safety_stop = {
    description: '强制安全清零',
    actuator_cmds: [
      {
        actuator_id: 'primary_actuator',
        channel: 'intensity',
        value: 0,
        unit: 'percent',
      },
    ],
    terminal: true,
  }

  return {
    version: 1,
    id: playbook.id,
    metadata: {
      name: playbook.name,
      description: playbook.description,
      generated_by: 'btg_cyber_dashboard',
      requires_active_consent: true,
      safety_policy: 'fail_closed',
    },
    start_scene: playbook.scenes[0]?.id ?? 'safety_stop',
    scenes,
  }
})

const yamlPreview = computed(() =>
  dump(playbookPayload.value, { noRefs: true, lineWidth: 96, sortKeys: false }),
)

function addScene() {
  const scene = createScene()
  playbook.scenes.push(scene)
  selectedUid.value = scene.uid
}

function deleteScene(scene) {
  if (playbook.scenes.length === 1) return
  const index = playbook.scenes.findIndex((item) => item.uid === scene.uid)
  playbook.scenes.splice(index, 1)
  selectedUid.value = playbook.scenes[Math.max(0, index - 1)].uid
}

function moveScene(scene, offset) {
  const index = playbook.scenes.findIndex((item) => item.uid === scene.uid)
  const target = index + offset
  if (target < 0 || target >= playbook.scenes.length) return
  playbook.scenes.splice(target, 0, playbook.scenes.splice(index, 1)[0])
}

function downloadYaml() {
  if (validationErrors.value.length) return
  const blob = new Blob([yamlPreview.value], { type: 'application/yaml;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${playbook.id}.yaml`
  anchor.click()
  URL.revokeObjectURL(url)
}

async function savePlaybook() {
  saveMessage.value = ''
  saveError.value = ''
  if (validationErrors.value.length) {
    saveError.value = '请先修复表单中的校验问题。'
    return
  }

  saveBusy.value = true
  try {
    await gatewayApi.savePlaybook(playbookPayload.value)
    saveMessage.value = '剧本已保存到网关。保存不代表自动执行，仍需人工启动与有效授权。'
  } catch (error) {
    saveError.value = `保存失败：${getApiError(error)}`
  } finally {
    saveBusy.value = false
  }
}
</script>

<template>
  <main
    id="main-content"
    class="space-y-6"
    tabindex="-1"
  >
    <header class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div>
        <div
          class="mb-2 flex items-center gap-2 font-mono text-xs uppercase tracking-[0.28em] text-purple-300"
        >
          <BookOpenText
            class="size-4"
            aria-hidden="true"
          />
          Playbook Studio
        </div>
        <h1 class="font-display text-3xl font-bold tracking-tight text-white sm:text-4xl">
          玩法与剧本设计器
        </h1>
        <p class="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
          可视化编辑标准 YAML。生成器强制加入同意校验、系统上限截断与终止清零场景。
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <button
          class="cyber-button-secondary"
          type="button"
          :disabled="validationErrors.length > 0"
          @click="downloadYaml"
        >
          <Download
            class="size-4"
            aria-hidden="true"
          />
          下载 YAML
        </button>
        <button
          class="cyber-button"
          type="button"
          :disabled="saveBusy || validationErrors.length > 0"
          @click="savePlaybook"
        >
          <Save
            class="size-4"
            aria-hidden="true"
          />
          {{ saveBusy ? '正在保存…' : '保存至网关' }}
        </button>
      </div>
    </header>

    <p
      v-if="saveMessage"
      class="status-success"
      role="status"
    >
      {{ saveMessage }}
    </p>
    <p
      v-if="saveError"
      class="status-error"
      role="alert"
    >
      {{ saveError }}
    </p>

    <section
      class="grid gap-5 2xl:grid-cols-[minmax(0,1.15fr)_minmax(32rem,0.85fr)]"
      aria-label="剧本编辑区"
    >
      <div class="space-y-5">
        <article class="panel-surface p-5">
          <div class="mb-5 flex items-center justify-between">
            <div>
              <p class="section-label">PLAYBOOK IDENTITY</p>
              <h2 class="mt-1 text-lg font-semibold text-white">剧本基本信息</h2>
            </div>
            <ShieldCheck
              class="size-5 text-emerald-300"
              aria-hidden="true"
            />
          </div>
          <div class="grid gap-4 md:grid-cols-2">
            <label>
              <span class="field-label">剧本 ID</span>
              <input
                v-model.trim="playbook.id"
                class="field-input font-mono"
                autocomplete="off"
                placeholder="operator_playbook"
              />
            </label>
            <label>
              <span class="field-label">场景名称</span>
              <input
                v-model.trim="playbook.name"
                class="field-input"
                autocomplete="off"
                placeholder="遥测安全训练"
              />
            </label>
            <label class="md:col-span-2">
              <span class="field-label">说明</span>
              <textarea
                v-model.trim="playbook.description"
                class="field-input min-h-24 resize-y"
                placeholder="说明玩法目标和操作边界"
              />
            </label>
          </div>
        </article>

        <article class="panel-surface overflow-hidden">
          <div class="flex items-center justify-between border-b border-white/10 px-5 py-4">
            <div>
              <p class="section-label">SCENE SEQUENCE</p>
              <h2 class="mt-1 text-lg font-semibold text-white">动作阶段</h2>
            </div>
            <button
              class="cyber-button"
              type="button"
              @click="addScene"
            >
              <Plus
                class="size-4"
                aria-hidden="true"
              />
              添加阶段
            </button>
          </div>

          <div class="grid md:grid-cols-[13rem_1fr]">
            <div class="border-b border-white/10 bg-black/15 p-3 md:border-b-0 md:border-r">
              <ul
                class="space-y-2"
                aria-label="剧本阶段列表"
              >
                <li
                  v-for="(scene, index) in playbook.scenes"
                  :key="scene.uid"
                >
                  <button
                    class="w-full rounded-xl border px-3 py-3 text-left transition"
                    :class="
                      selectedUid === scene.uid
                        ? 'border-purple-400/40 bg-purple-400/10 text-purple-100'
                        : 'border-transparent text-zinc-400 hover:border-white/10 hover:bg-white/5 hover:text-white'
                    "
                    type="button"
                    @click="selectedUid = scene.uid"
                  >
                    <span class="font-mono text-[0.62rem] uppercase tracking-widest text-zinc-600"
                      >Scene {{ String(index + 1).padStart(2, '0') }}</span
                    >
                    <span class="mt-1 block truncate text-sm font-semibold">{{
                      scene.name || scene.id
                    }}</span>
                  </button>
                </li>
              </ul>
            </div>

            <div
              v-if="selectedScene"
              class="p-5"
            >
              <div class="mb-5 flex flex-wrap items-center justify-between gap-3">
                <p class="font-mono text-xs uppercase tracking-[0.2em] text-purple-300">
                  {{ selectedScene.id }}
                </p>
                <div class="flex gap-1">
                  <button
                    class="cyber-button-secondary !min-h-9 !px-2.5"
                    type="button"
                    title="向前移动阶段"
                    @click="moveScene(selectedScene, -1)"
                  >
                    <ArrowUp
                      class="size-4"
                      aria-hidden="true"
                    />
                    <span class="sr-only">向前移动阶段</span>
                  </button>
                  <button
                    class="cyber-button-secondary !min-h-9 !px-2.5"
                    type="button"
                    title="向后移动阶段"
                    @click="moveScene(selectedScene, 1)"
                  >
                    <ArrowDown
                      class="size-4"
                      aria-hidden="true"
                    />
                    <span class="sr-only">向后移动阶段</span>
                  </button>
                  <button
                    class="cyber-button-secondary !min-h-9 !px-2.5 text-red-200"
                    type="button"
                    :disabled="playbook.scenes.length === 1"
                    title="删除阶段"
                    @click="deleteScene(selectedScene)"
                  >
                    <Trash2
                      class="size-4"
                      aria-hidden="true"
                    />
                    <span class="sr-only">删除阶段</span>
                  </button>
                </div>
              </div>

              <div class="grid gap-4 md:grid-cols-2">
                <label>
                  <span class="field-label">阶段名称</span>
                  <input
                    v-model.trim="selectedScene.name"
                    class="field-input"
                    autocomplete="off"
                  />
                </label>
                <label>
                  <span class="field-label">阶段 ID</span>
                  <input
                    v-model.trim="selectedScene.id"
                    class="field-input font-mono"
                    autocomplete="off"
                  />
                </label>
                <label class="md:col-span-2">
                  <span class="field-label">TTS 旁白</span>
                  <textarea
                    v-model.trim="selectedScene.ttsText"
                    class="field-input min-h-28 resize-y"
                    placeholder="由 TTS 播放的引导文本"
                  />
                </label>
                <label>
                  <span class="field-label">触发传感器</span>
                  <select
                    v-model="selectedScene.triggerSensor"
                    class="field-input"
                  >
                    <option value="heart_rate">心率 heart_rate</option>
                    <option value="imu_variance">IMU 挣扎 imu_variance</option>
                    <option value="audio_db">音频分贝 audio_db</option>
                    <option value="anomaly_score">异常评分 anomaly_score</option>
                  </select>
                </label>
                <label>
                  <span class="field-label">触发阈值</span>
                  <input
                    v-model.number="selectedScene.thresholdValue"
                    class="field-input"
                    type="number"
                    min="0"
                    step="0.1"
                  />
                </label>
                <label>
                  <span class="field-label">持续时间（秒）</span>
                  <input
                    v-model.number="selectedScene.sustainedSeconds"
                    class="field-input"
                    type="number"
                    min="0.1"
                    max="60"
                    step="0.1"
                  />
                </label>
                <label>
                  <span class="field-label">动作强度：{{ selectedScene.intensity }} / 100</span>
                  <input
                    v-model.number="selectedScene.intensity"
                    class="cyber-range mt-4"
                    type="range"
                    min="0"
                    max="100"
                    step="1"
                    aria-label="动作强度"
                  />
                </label>
              </div>
            </div>
          </div>
        </article>

        <div
          v-if="validationErrors.length"
          class="status-warning"
          role="alert"
        >
          <p class="font-semibold">需要修复 {{ validationErrors.length }} 个问题：</p>
          <ul class="mt-2 list-disc space-y-1 pl-5 text-xs">
            <li
              v-for="error in validationErrors"
              :key="error"
            >
              {{ error }}
            </li>
          </ul>
        </div>
      </div>

      <article
        class="panel-surface flex min-h-[48rem] flex-col overflow-hidden 2xl:sticky 2xl:top-6 2xl:max-h-[calc(100vh-3rem)]"
      >
        <div class="flex items-center justify-between border-b border-white/10 px-5 py-4">
          <div class="flex items-center gap-3">
            <FileCode2
              class="size-5 text-cyan-300"
              aria-hidden="true"
            />
            <div>
              <p class="section-label">LIVE YAML</p>
              <h2 class="mt-1 text-base font-semibold text-white">标准化配置预览</h2>
            </div>
          </div>
          <span
            class="rounded-md border border-emerald-400/20 bg-emerald-400/10 px-2 py-1 font-mono text-[0.6rem] uppercase tracking-wider text-emerald-300"
            >fail closed</span
          >
        </div>
        <pre
          class="min-h-0 flex-1 overflow-auto bg-black/30 p-5 font-mono text-xs leading-6 text-cyan-100"
        ><code>{{ yamlPreview }}</code></pre>
      </article>
    </section>
  </main>
</template>
