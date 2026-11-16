<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import {
  configApi,
  providersApi,
  type ActiveLLMSettings,
  type KeyStatus,
  type LLMProfile,
  type ProviderPreset,
} from '@/api'

const route = useRoute()
const fromStart = computed(() => route.query.from === 'start')

const presets = ref<ProviderPreset[]>([])
const profiles = ref<LLMProfile[]>([])
const active = ref<ActiveLLMSettings | null>(null)
const loading = ref(true)
const testing = ref(false)
const pending = ref(false)
const vendorId = ref('deepseek')
const apiKey = ref('')
const baseUrl = ref('')
const model = ref('')
const profileName = ref('')
const activateOnSave = ref(true)
const renamingId = ref<number | null>(null)
const renameValue = ref('')
const notice = ref('')
const result = ref<{
  ok: boolean
  error?: string | null
  latency_ms?: number | null
  reply?: string | null
} | null>(null)
const loadError = ref('')
const stageRoutes = ref<
  Array<{ stage: string; label: string; provider: string; model: string; purposes: string[] }>
>([])

const current = computed(() => presets.value.find((p) => p.id === vendorId.value))
const sourceLabel = computed(() => {
  if (!active.value) return ''
  if (active.value.source === 'profile' && active.value.profile_name) {
    return `配置「${active.value.profile_name}」`
  }
  return '环境变量 .env'
})

function applyPreset(p: ProviderPreset | undefined) {
  if (!p) return
  baseUrl.value = p.base_url || ''
  model.value = p.default_model || ''
}

watch(vendorId, (id) => {
  applyPreset(presets.value.find((p) => p.id === id))
  result.value = null
})

function keyText(key: KeyStatus | undefined) {
  if (!key || key.mode === 'anonymous') return '未使用密钥'
  return `已配置密钥 ${key.mask || ''}`.trim()
}

function errText(e: unknown, fallback: string) {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (e instanceof Error) return e.message
  return fallback
}

async function loadAll() {
  const [res, cfg, activeRes, profileRes] = await Promise.all([
    providersApi.list(),
    configApi.get(),
    providersApi.active(),
    providersApi.profiles(),
  ])
  presets.value = res.data.presets || []
  stageRoutes.value = cfg.data?.stage_routes || []
  active.value = activeRes.data
  profiles.value = profileRes.data.profiles || []
  if (!presets.value.some((p) => p.id === vendorId.value) && presets.value[0]) {
    vendorId.value = presets.value[0].id
  }
}

onMounted(async () => {
  try {
    await loadAll()
    applyPreset(current.value)
  } catch (e: unknown) {
    loadError.value = errText(e, '加载设置失败')
  } finally {
    loading.value = false
  }
})

async function saveCurrent() {
  const name = profileName.value.trim()
  if (!name) {
    notice.value = '先写配置名称'
    return
  }
  pending.value = true
  notice.value = ''
  try {
    await providersApi.createProfile({
      name,
      from_current: true,
      activate: activateOnSave.value,
    })
    profileName.value = ''
    await loadAll()
    notice.value = activateOnSave.value ? `已保存并启用「${name}」` : `已保存「${name}」`
  } catch (e: unknown) {
    notice.value = errText(e, '保存失败')
  } finally {
    pending.value = false
  }
}

async function activate(profile: LLMProfile) {
  pending.value = true
  notice.value = ''
  try {
    await providersApi.activateProfile(profile.id)
    await loadAll()
    notice.value = `已启用「${profile.name}」`
  } catch (e: unknown) {
    notice.value = errText(e, '启用失败')
  } finally {
    pending.value = false
  }
}

function startRename(profile: LLMProfile) {
  renamingId.value = profile.id
  renameValue.value = profile.name
}

async function saveRename(profile: LLMProfile) {
  const name = renameValue.value.trim()
  if (!name) return
  pending.value = true
  notice.value = ''
  try {
    await providersApi.updateProfile(profile.id, { name })
    renamingId.value = null
    await loadAll()
  } catch (e: unknown) {
    notice.value = errText(e, '改名失败')
  } finally {
    pending.value = false
  }
}

async function overwrite(profile: LLMProfile) {
  if (!window.confirm(`用当前生效配置覆盖「${profile.name}」？原来的地址和密钥会被换掉。`)) return
  pending.value = true
  notice.value = ''
  try {
    await providersApi.updateProfileFromCurrent(profile.id)
    await loadAll()
    notice.value = `已用当前生效配置覆盖「${profile.name}」`
  } catch (e: unknown) {
    notice.value = errText(e, '覆盖失败')
  } finally {
    pending.value = false
  }
}

async function remove(profile: LLMProfile) {
  const extra = profile.is_active ? '删除后回到 .env。' : ''
  if (!window.confirm(`删除配置「${profile.name}」？${extra}`)) return
  pending.value = true
  notice.value = ''
  try {
    await providersApi.deleteProfile(profile.id)
    if (renamingId.value === profile.id) renamingId.value = null
    await loadAll()
  } catch (e: unknown) {
    notice.value = errText(e, '删除失败')
  } finally {
    pending.value = false
  }
}

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
      <h1 class="text-xl font-semibold tracking-tight">模型设置</h1>
      <p class="mt-1 text-sm text-[var(--ink-muted)]">
        当前续写和向量用的连接在下面。配置存在本机数据库，启用后马上生效。密钥只显示末四位。
        <RouterLink class="crumb" to="/settings/health">运行状态</RouterLink>
        看接口、数据库和模型。
        <RouterLink class="crumb" to="/settings/appearance">界面外观在这里调整。</RouterLink>
      </p>
    </div>

    <p v-if="fromStart" class="alert alert--ok">
      保存或测通之后回到首页，选开书或续写。
      <RouterLink class="crumb" to="/">回到首页</RouterLink>
    </p>

    <div v-if="loading" class="panel p-5 text-sm text-[var(--ink-muted)]">加载设置…</div>
    <div v-else-if="loadError" class="panel p-5 text-sm text-[var(--danger)]">{{ loadError }}</div>

    <template v-else>
    <section class="panel p-5 space-y-3">
      <div class="flex items-baseline justify-between gap-3">
        <h2 class="font-medium">当前生效</h2>
        <span class="text-sm text-[var(--accent)]">{{ sourceLabel }}</span>
      </div>
      <dl v-if="active" class="active-lines">
        <div>
          <dt>续写</dt>
          <dd>
            <span class="tabular">{{ active.generation_provider }} / {{ active.generation_model }}</span>
            <span class="meta">{{ active.generation_base_url }}</span>
            <span>{{ keyText(active.generation_key) }}</span>
          </dd>
        </div>
        <div>
          <dt>摘要</dt>
          <dd>
            <template v-if="active.summary_follows_generation">与续写相同</template>
            <template v-else>
              <span class="tabular">{{ active.summary_provider }} / {{ active.summary_model }}</span>
              <span class="meta">{{ active.summary_base_url }}</span>
              <span>{{ keyText(active.summary_key) }}</span>
            </template>
          </dd>
        </div>
        <div>
          <dt>向量</dt>
          <dd>
            <span class="tabular">{{ active.embedding_model }} · {{ active.embedding_dims }} 维</span>
            <span class="meta">{{ active.embedding_base_url }}</span>
            <span>{{ keyText(active.embedding_key) }}</span>
          </dd>
        </div>
      </dl>
      <p v-if="active?.dims_mismatch" class="text-sm text-[var(--warn)]">
        这条配置的向量维度是 {{ active.embedding_dims }}，当前库按 {{ active.vec_dims }} 建的。不一致时新向量可能进不了向量表。
      </p>
    </section>

    <section class="panel p-5 space-y-3">
      <h2 class="font-medium">已存配置</h2>
      <p v-if="!profiles.length" class="text-sm text-[var(--ink-muted)]">
        还没有配置。没启用时继续用 .env。
      </p>
      <ul v-else class="space-y-2">
        <li v-for="p in profiles" :key="p.id" class="profile-card" :class="{ 'is-active': p.is_active }">
          <div class="flex flex-wrap items-start justify-between gap-2">
            <div class="min-w-0">
              <div v-if="renamingId === p.id" class="flex flex-wrap items-center gap-2">
                <input v-model="renameValue" class="input" style="width: 14rem" maxlength="64" />
                <button type="button" class="btn btn-sm" :disabled="pending" @click="saveRename(p)">保存</button>
                <button type="button" class="btn-ghost btn-sm" :disabled="pending" @click="renamingId = null">取消</button>
              </div>
              <div v-else class="font-medium">
                {{ p.name }}
                <span v-if="p.is_active" class="ml-2 text-xs text-[var(--accent)]">使用中</span>
              </div>
              <p class="mt-1 text-sm text-[var(--ink-muted)]">
                <span class="tabular">{{ p.generation_provider }} / {{ p.generation_model }}</span>
                · 向量 {{ p.embedding_model }}
              </p>
              <p class="text-xs text-[var(--ink-muted)]">
                续写{{ keyText(p.generation_key) }} · 向量{{ keyText(p.embedding_key) }}
              </p>
            </div>
            <div class="flex flex-wrap gap-2">
              <button
                v-if="!p.is_active"
                type="button"
                class="btn btn-sm"
                :disabled="pending"
                @click="activate(p)"
              >启用</button>
              <button type="button" class="btn-ghost btn-sm" :disabled="pending" @click="startRename(p)">改名</button>
              <button
                type="button"
                class="btn-ghost btn-sm"
                :disabled="pending || p.is_active"
                @click="overwrite(p)"
              >用当前生效覆盖</button>
              <button type="button" class="btn-danger btn-sm" :disabled="pending" @click="remove(p)">删除</button>
            </div>
          </div>
        </li>
      </ul>
    </section>

    <form class="panel p-5 space-y-3" @submit.prevent="saveCurrent">
      <h2 class="font-medium">存下当前生效配置</h2>
      <p class="text-sm text-[var(--ink-muted)]">
        把上面正在用的地址、模型和密钥存成一条。密钥写入本机库，页面上不回显。
      </p>
      <div class="flex flex-wrap items-end gap-3">
        <label class="block space-y-1.5" style="flex: 1 1 14rem">
          <span class="text-sm font-medium">名称</span>
          <input v-model="profileName" class="input w-full" maxlength="64" placeholder="例如 DeepSeek 长文" />
        </label>
        <label class="check mb-2">
          <input v-model="activateOnSave" type="checkbox" />
          保存后启用
        </label>
        <button type="submit" class="btn mb-0.5" :disabled="pending || !profileName.trim()">存为配置</button>
      </div>
      <p v-if="notice" class="text-sm">{{ notice }}</p>
    </form>

    <form class="panel p-5 space-y-4" @submit.prevent="runTest">
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
        <span class="text-xs text-[var(--ink-muted)]">只探测，不写入配置。匿名端点填 anonymous。</span>
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

    <div v-if="stageRoutes.length" class="panel p-5 space-y-3">
      <div>
        <div class="font-medium">各阶段用的模型</div>
        <p class="mt-1 text-sm text-[var(--ink-muted)]">
          摘要和审校看摘要模型，大纲和续写看续写模型，向量单独走。启用配置后这里跟着变。
        </p>
      </div>
      <ul class="text-sm space-y-2">
        <li v-for="r in stageRoutes" :key="r.stage" class="purpose-row">
          <span>{{ r.label }}</span>
          <span class="tabular meta">{{ r.provider }} / {{ r.model }}</span>
        </li>
      </ul>
    </div>
    </template>
  </div>
</template>

<style scoped>
.active-lines {
  display: grid;
  gap: 0.75rem;
}
.active-lines > div {
  display: grid;
  grid-template-columns: 3.25rem 1fr;
  gap: 0.75rem;
  align-items: start;
}
.active-lines dt {
  color: var(--ink-muted);
  font-size: 0.8125rem;
}
.active-lines dd {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.75rem;
  margin: 0;
  font-size: 0.875rem;
}
.profile-card {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--paper);
  padding: 0.85rem 1rem;
}
.profile-card.is-active {
  border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
  background: color-mix(in srgb, var(--accent-soft) 70%, var(--paper));
}
</style>
