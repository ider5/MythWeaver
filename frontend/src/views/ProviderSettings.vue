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
import { useSettingsCopy } from '@/lib/settingsCopy'

const route = useRoute()
const copy = useSettingsCopy()
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
    return copy.value.profileSource(active.value.profile_name)
  }
  return copy.value.envSource
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
  if (!key || key.mode === 'anonymous') return copy.value.keyUnused
  return copy.value.keyConfigured(key.mask || '')
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
    loadError.value = errText(e, copy.value.loadFailed)
  } finally {
    loading.value = false
  }
})

async function saveCurrent() {
  const name = profileName.value.trim()
  if (!name) {
    notice.value = copy.value.needName
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
    notice.value = activateOnSave.value
      ? copy.value.savedAndEnabled(name)
      : copy.value.savedOnly(name)
  } catch (e: unknown) {
    notice.value = errText(e, copy.value.saveFailed)
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
    notice.value = copy.value.enabledName(profile.name)
  } catch (e: unknown) {
    notice.value = errText(e, copy.value.activateFailed)
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
    notice.value = errText(e, copy.value.renameFailed)
  } finally {
    pending.value = false
  }
}

async function overwrite(profile: LLMProfile) {
  if (!window.confirm(copy.value.overwriteConfirm(profile.name))) return
  pending.value = true
  notice.value = ''
  try {
    await providersApi.updateProfileFromCurrent(profile.id)
    await loadAll()
    notice.value = copy.value.overwritten(profile.name)
  } catch (e: unknown) {
    notice.value = errText(e, copy.value.overwriteFailed)
  } finally {
    pending.value = false
  }
}

async function remove(profile: LLMProfile) {
  const extra = profile.is_active ? copy.value.deleteActiveExtra : ''
  if (!window.confirm(copy.value.deleteConfirm(profile.name, extra))) return
  pending.value = true
  notice.value = ''
  try {
    await providersApi.deleteProfile(profile.id)
    if (renamingId.value === profile.id) renamingId.value = null
    await loadAll()
  } catch (e: unknown) {
    notice.value = errText(e, copy.value.deleteFailed)
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
      (e instanceof Error ? e.message : copy.value.requestFailed)
    result.value = { ok: false, error: String(detail) }
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div class="settings-page">
    <header class="settings-head">
      <p class="kicker">{{ copy.providersKicker }}</p>
      <h1 class="page-title">{{ copy.providersTitle }}</h1>
      <p class="page-desc">
        {{ copy.providersLead }}
        <RouterLink class="crumb" to="/settings/health">{{ copy.providersHealthLink }}</RouterLink>
        {{ copy.providersHealthTail }}
        <RouterLink class="crumb" to="/settings/appearance">{{ copy.providersLookLink }}</RouterLink>
      </p>
    </header>

    <p v-if="fromStart" class="alert alert--ok">
      {{ copy.fromStart }}
      <RouterLink class="crumb" to="/">{{ copy.backHome }}</RouterLink>
    </p>

    <p v-if="loading" class="meta">{{ copy.loadingSettings }}</p>
    <p v-else-if="loadError" class="alert alert--danger">{{ loadError }}</p>

    <template v-else>
    <section class="panel p-5 space-y-3">
      <div class="flex items-baseline justify-between gap-3">
        <h2 class="font-display text-lg">{{ copy.activeTitle }}</h2>
        <span class="text-sm text-[var(--accent)]">{{ sourceLabel }}</span>
      </div>
      <dl v-if="active" class="active-lines">
        <div>
          <dt>{{ copy.draftLabel }}</dt>
          <dd>
            <span class="tabular">{{ active.generation_provider }} / {{ active.generation_model }}</span>
            <span class="meta">{{ active.generation_base_url }}</span>
            <span>{{ keyText(active.generation_key) }}</span>
          </dd>
        </div>
        <div>
          <dt>{{ copy.summaryLabel }}</dt>
          <dd>
            <template v-if="active.summary_follows_generation">{{ copy.sameAsDraft }}</template>
            <template v-else>
              <span class="tabular">{{ active.summary_provider }} / {{ active.summary_model }}</span>
              <span class="meta">{{ active.summary_base_url }}</span>
              <span>{{ keyText(active.summary_key) }}</span>
            </template>
          </dd>
        </div>
        <div>
          <dt>{{ copy.embedLabel }}</dt>
          <dd>
            <span class="tabular">{{ active.embedding_model }} · {{ copy.dims(active.embedding_dims) }}</span>
            <span class="meta">{{ active.embedding_base_url }}</span>
            <span>{{ keyText(active.embedding_key) }}</span>
          </dd>
        </div>
      </dl>
      <p v-if="active?.dims_mismatch" class="text-sm text-[var(--warn)]">
        {{ copy.dimsMismatchBefore }}<span class="tabular">{{ active.embedding_dims }}</span>{{ copy.dimsMismatchBetween }}<span class="tabular">{{ active.vec_dims }}</span>{{ copy.dimsMismatchAfter }}
      </p>
    </section>

    <section class="panel p-5 space-y-3">
      <h2 class="font-display text-lg">{{ copy.savedTitle }}</h2>
      <p v-if="!profiles.length" class="empty">
        {{ copy.savedEmpty }}
      </p>
      <ul v-else class="space-y-2">
        <li v-for="p in profiles" :key="p.id" class="profile-card" :class="{ 'is-active': p.is_active }">
          <div class="flex flex-wrap items-start justify-between gap-2">
            <div class="min-w-0">
              <div v-if="renamingId === p.id" class="flex flex-wrap items-center gap-2">
                <input v-model="renameValue" class="input" style="width: 14rem" maxlength="64" />
                <button type="button" class="btn btn-sm" :disabled="pending" @click="saveRename(p)">{{ copy.save }}</button>
                <button type="button" class="btn-ghost btn-sm" :disabled="pending" @click="renamingId = null">{{ copy.cancel }}</button>
              </div>
              <div v-else class="font-display">
                {{ p.name }}
                <span v-if="p.is_active" class="ml-2 text-xs text-[var(--accent)]">{{ copy.inUse }}</span>
              </div>
              <p class="mt-1 text-sm text-[var(--ink-muted)]">
                <span class="tabular">{{ p.generation_provider }} / {{ p.generation_model }}</span>{{ copy.profileEmbed(p.embedding_model) }}
              </p>
              <p class="text-xs text-[var(--ink-muted)]">
                {{ copy.profileKeys(keyText(p.generation_key), keyText(p.embedding_key)) }}
              </p>
            </div>
            <div class="flex flex-wrap gap-2">
              <button
                v-if="!p.is_active"
                type="button"
                class="btn btn-sm"
                :disabled="pending"
                @click="activate(p)"
              >{{ copy.activate }}</button>
              <button type="button" class="btn-ghost btn-sm" :disabled="pending" @click="startRename(p)">{{ copy.rename }}</button>
              <button
                type="button"
                class="btn-ghost btn-sm"
                :disabled="pending || p.is_active"
                @click="overwrite(p)"
              >{{ copy.overwrite }}</button>
              <button type="button" class="btn-danger btn-sm" :disabled="pending" @click="remove(p)">{{ copy.remove }}</button>
            </div>
          </div>
        </li>
      </ul>
    </section>

    <form class="panel p-5 space-y-3" @submit.prevent="saveCurrent">
      <h2 class="font-display text-lg">{{ copy.saveProfileTitle }}</h2>
      <p class="text-sm text-[var(--ink-muted)]">
        {{ copy.saveProfileLead }}
      </p>
      <div class="flex flex-wrap items-end gap-3">
        <label class="block" style="flex: 1 1 14rem">
          <span class="label">{{ copy.nameLabel }}</span>
          <input v-model="profileName" class="input w-full" maxlength="64" :placeholder="copy.namePlaceholder" />
        </label>
        <label class="check mb-2">
          <input v-model="activateOnSave" type="checkbox" />
          {{ copy.activateOnSave }}
        </label>
        <button type="submit" class="btn mb-0.5" :disabled="pending || !profileName.trim()">{{ copy.saveAsProfile }}</button>
      </div>
      <p v-if="notice" class="text-sm">{{ notice }}</p>
    </form>

    <form class="panel p-5 space-y-4" @submit.prevent="runTest">
      <label class="block">
        <span class="label">{{ copy.vendor }}</span>
        <select v-model="vendorId" class="input w-full">
          <option v-for="p in presets" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
        <span v-if="current?.notes" class="meta mt-1.5 block">
          {{ current.notes }}
          <a
            v-if="current.docs_url"
            :href="current.docs_url"
            target="_blank"
            rel="noopener noreferrer"
            class="ml-1 underline underline-offset-2"
          >{{ copy.docs }}</a>
        </span>
      </label>

      <label class="block">
        <span class="label">{{ copy.baseUrl }}</span>
        <input v-model="baseUrl" class="input w-full" :placeholder="copy.baseUrlPlaceholder" />
      </label>

      <label class="block">
        <span class="label">{{ copy.modelLabel }}</span>
        <input
          v-model="model"
          class="input w-full"
          list="preset-models"
          :placeholder="copy.modelPlaceholder"
        />
        <datalist id="preset-models">
          <option v-for="m in current?.models || []" :key="m" :value="m" />
        </datalist>
      </label>

      <label class="block">
        <span class="label">{{ copy.apiKey }}</span>
        <input
          v-model="apiKey"
          type="password"
          autocomplete="off"
          class="input w-full"
          :placeholder="copy.keyPlaceholder"
          required
        />
      </label>

      <div class="flex items-center gap-3 pt-1">
        <button type="submit" class="btn" :disabled="testing || !apiKey.trim()">
          {{ testing ? copy.testing : copy.testConnection }}
        </button>
        <span class="meta">{{ copy.testHint }}</span>
      </div>

      <div
        v-if="result"
        class="alert"
        :class="result.ok ? 'alert--ok' : 'alert--danger'"
        role="status"
      >
        <template v-if="result.ok">
          {{ copy.connected }}
          <span v-if="result.latency_ms != null" class="tabular"> · {{ result.latency_ms }} ms</span>
          <span v-if="result.reply" class="text-[var(--ink-muted)]"> · {{ copy.replyBit(result.reply) }}</span>
        </template>
        <template v-else>
          {{ copy.connectFailed }}{{ result.error || copy.unknownError }}
        </template>
      </div>
    </form>

    <div v-if="stageRoutes.length" class="panel p-5 space-y-3">
      <div>
        <h2 class="font-display text-lg">{{ copy.stagesTitle }}</h2>
        <p class="mt-1 text-sm text-[var(--ink-muted)]">
          {{ copy.stagesLead }}
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
  grid-template-columns: minmax(4.75rem, max-content) 1fr;
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
