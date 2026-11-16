<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { configApi, costsApi } from '@/api'
import { useUiPrefs } from '@/composables/useUiPrefs'
import { useSettingsCopy } from '@/lib/settingsCopy'

const route = useRoute()
const novelId = Number(route.params.id)
const { locale } = useUiPrefs()
const copy = useSettingsCopy()
const data = ref<any>(null)
const routes = ref<
  Array<{ stage: string; label: string; provider: string; model: string; purposes: string[] }>
>([])

function fmtUsd(n?: number, digits = 4) {
  if (n == null || Number.isNaN(Number(n))) return '—'
  return Number(n).toFixed(digits)
}

function fmtMoney(n?: number, digits = 4) {
  const v = fmtUsd(n, digits)
  return v === '—' ? '—' : `$${v}`
}

function fmtInt(n?: number) {
  if (n == null || Number.isNaN(Number(n))) return '—'
  const tag = locale.value === 'en' ? 'en-US' : 'zh-CN'
  return Number(n).toLocaleString(tag)
}

const purposeRows = computed(() => {
  const tokens = data.value?.by_purpose_tokens || {}
  const costs = data.value?.by_purpose || {}
  const keys = Array.from(new Set([...Object.keys(tokens), ...Object.keys(costs)])).sort()
  return keys.map((k) => {
    const row = tokens[k] || {}
    return {
      purpose: k,
      input: row.input_tokens ?? 0,
      output: row.output_tokens ?? 0,
      cost: row.cost_usd ?? costs[k] ?? 0,
    }
  })
})

onMounted(async () => {
  const [costRes, cfgRes] = await Promise.all([
    costsApi.summary(novelId),
    configApi.get(),
  ])
  data.value = costRes.data
  routes.value = cfgRes.data?.stage_routes || []
})
</script>

<template>
  <div class="space-y-5">
    <header class="settings-head">
      <p class="kicker">{{ copy.costKicker }}</p>
      <h2 class="page-title">{{ copy.costTitle }}</h2>
      <p class="page-desc">{{ copy.costLead }}</p>
    </header>

    <div class="grid sm:grid-cols-3 gap-3">
      <div class="panel metric">
        <div class="metric__label">{{ copy.totalUsd }}</div>
        <div class="metric__value tabular">{{ data ? fmtUsd(data.total_cost_usd) : '—' }}</div>
      </div>
      <div class="panel metric">
        <div class="metric__label">{{ copy.inputTokens }}</div>
        <div class="metric__value tabular">{{ fmtInt(data?.total_input_tokens) }}</div>
      </div>
      <div class="panel metric">
        <div class="metric__label">{{ copy.outputTokens }}</div>
        <div class="metric__value tabular">{{ fmtInt(data?.total_output_tokens) }}</div>
      </div>
    </div>

    <div class="panel p-5">
      <h3 class="font-display text-lg mb-1">{{ copy.stagesTitle }}</h3>
      <p class="text-sm text-[var(--ink-muted)] mb-3">{{ copy.routesLead }}</p>
      <table class="data-table">
        <thead>
          <tr>
            <th>{{ copy.colStage }}</th>
            <th>{{ copy.colModel }}</th>
            <th>{{ copy.colPurposes }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in routes" :key="r.stage" class="cv-item">
            <td>{{ r.label }}</td>
            <td class="tabular">{{ r.provider }} / {{ r.model }}</td>
            <td class="meta">{{ (r.purposes || []).join(' · ') }}</td>
          </tr>
          <tr v-if="!routes.length">
            <td colspan="3" class="empty">{{ copy.routesEmpty }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="panel p-5">
      <h3 class="font-display text-lg mb-3">{{ copy.byPurpose }}</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>{{ copy.colPurpose }}</th>
            <th>{{ copy.colIn }}</th>
            <th>{{ copy.colOut }}</th>
            <th>{{ copy.colCost }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in purposeRows" :key="row.purpose" class="cv-item">
            <td>{{ row.purpose }}</td>
            <td class="tabular">{{ fmtInt(row.input) }}</td>
            <td class="tabular">{{ fmtInt(row.output) }}</td>
            <td class="tabular">{{ fmtMoney(Number(row.cost)) }}</td>
          </tr>
          <tr v-if="data && !purposeRows.length">
            <td colspan="4" class="empty">{{ copy.purposeEmpty }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="panel overflow-hidden">
      <div class="panel-head font-display">{{ copy.recentTitle }}</div>
      <table class="data-table">
        <thead>
          <tr>
            <th>{{ copy.colPurpose }}</th>
            <th>{{ copy.colModel }}</th>
            <th>{{ copy.colInOut }}</th>
            <th>{{ copy.colCost }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in data?.recent || []" :key="r.id" class="cv-item">
            <td>{{ r.purpose }}</td>
            <td>{{ r.model }}</td>
            <td class="tabular">{{ fmtInt(r.input_tokens) }}/{{ fmtInt(r.output_tokens) }}</td>
            <td class="tabular">{{ fmtMoney(Number(r.cost_usd), 5) }}</td>
          </tr>
          <tr v-if="data && !(data.recent || []).length">
            <td colspan="4" class="empty">{{ copy.recentEmpty }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
