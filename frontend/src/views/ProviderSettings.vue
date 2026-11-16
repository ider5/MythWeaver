<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { providersApi, type ProviderPreset } from '@/api'

const presets = ref<ProviderPreset[]>([])
const loading = ref(true)
const testing = ref(false)
const vendorId = ref('deepseek')
const apiKey = ref('')
const baseUrl = ref('')
const model = ref('')
const result = ref<{
  ok: boolean
  error?: string | null
  latency_ms?: number | null
  reply?: string | null
} | null>(null)
const loadError = ref('')

const current = computed(() => presets.value.find((p) => p.id === vendorId.value))

function applyPreset(p: ProviderPreset | undefined) {
  if (!p) return
  baseUrl.value = p.base_url || ''
  model.value = p.default_model || ''
}

watch(vendorId, (id) => {
  applyPreset(presets.value.find((p) => p.id === id))
  result.value = null
})

onMounted(async () => {
  try {
    const res = await providersApi.list()
    presets.value = res.data.presets || []
    if (!presets.value.some((p) => p.id === vendorId.value) && presets.value[0]) {
      vendorId.value = presets.value[0].id
    }
    applyPreset(current.value)
  } catch (e: unknown) {
    loadError.value = e instanceof Error ? e.message : '加载预设失败'
  } finally {
    loading.value = false
  }
})

async function runTest() {
  testing.value = true
  result.value = null
  try {
    const res = await providersApi.test({
      vendor_id: vendorId.value,
      api_key: apiKey.value,
      base_url: baseUrl.value || null,
      model: model.value || null,
    })
    result.value = res.data
  } catch (e: unknown) {
    const detail =
      (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
      (e instanceof Error ? e.message : '请求失败')
    result.value = { ok: false, error: String(detail) }
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div class="space-y-5 max-w-2xl">
    <div>
      <h1 class="text-xl font-semibold tracking-tight">LLM 厂商预设</h1>
      <p class="mt-1 text-sm text-[var(--ink-muted)]">
        选择常见 OpenAI 兼容厂商，一键填入 Base URL 与默认模型，并可探测连通性。密钥仅用于本次测试，不会写入服务器。
      </p>
    </div>

    <div v-if="loading" class="panel p-5 text-sm text-[var(--ink-muted)]">加载预设…</div>
    <div v-else-if="loadError" class="panel p-5 text-sm text-[var(--danger)]">{{ loadError }}</div>

    <form v-else class="panel p-5 space-y-4" @submit.prevent="runTest">
      <label class="block space-y-1.5">
        <span class="text-sm font-medium">厂商</span>
        <select v-model="vendorId" class="input w-full">
          <option v-for="p in presets" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
        <span v-if="current?.notes" class="block text-xs text-[var(--ink-muted)]">
          {{ current.notes }}
          <a
            v-if="current.docs_url"
            :href="current.docs_url"
            target="_blank"
            rel="noopener noreferrer"
            class="ml-1 underline underline-offset-2"
          >文档</a>
        </span>
      </label>

      <label class="block space-y-1.5">
        <span class="text-sm font-medium">Base URL</span>
        <input v-model="baseUrl" class="input w-full" placeholder="https://api.example.com/v1" />
      </label>

      <label class="block space-y-1.5">
        <span class="text-sm font-medium">模型</span>
        <input
          v-model="model"
          class="input w-full"
          list="preset-models"
          placeholder="model-id"
        />
        <datalist id="preset-models">
          <option v-for="m in current?.models || []" :key="m" :value="m" />
        </datalist>
      </label>

      <label class="block space-y-1.5">
        <span class="text-sm font-medium">API Key</span>
        <input
          v-model="apiKey"
          type="password"
          autocomplete="off"
          class="input w-full"
          placeholder="仅用于本次探测"
          required
        />
      </label>

      <div class="flex items-center gap-3 pt-1">
        <button type="submit" class="btn" :disabled="testing || !apiKey.trim()">
          {{ testing ? '测试中…' : '测试连接' }}
        </button>
        <span class="text-xs text-[var(--ink-muted)]">成功后请把相同值写入 backend/.env</span>
      </div>

      <div
        v-if="result"
        class="rounded-[var(--radius-sm)] px-3 py-2.5 text-sm"
        :class="result.ok ? 'bg-[var(--accent-soft)]' : 'bg-[var(--danger-soft)]'"
      >
        <template v-if="result.ok">
          连接成功
          <span v-if="result.latency_ms != null" class="tabular"> · {{ result.latency_ms }} ms</span>
          <span v-if="result.reply" class="text-[var(--ink-muted)]"> · 回复「{{ result.reply }}」</span>
        </template>
        <template v-else>
          连接失败：{{ result.error || '未知错误' }}
        </template>
      </div>
    </form>
  </div>
</template>
