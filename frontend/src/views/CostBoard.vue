<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { configApi, costsApi } from '@/api'

const route = useRoute()
const novelId = Number(route.params.id)
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
  return Number(n).toLocaleString('zh-CN')
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
    <div class="grid sm:grid-cols-3 gap-3">
      <div class="panel metric">
        <div class="metric__label">总成本 (USD)</div>
        <div class="metric__value">{{ data ? fmtUsd(data.total_cost_usd) : '—' }}</div>
      </div>
      <div class="panel metric">
        <div class="metric__label">输入 tokens</div>
        <div class="metric__value">{{ fmtInt(data?.total_input_tokens) }}</div>
      </div>
      <div class="panel metric">
        <div class="metric__label">输出 tokens</div>
        <div class="metric__value">{{ fmtInt(data?.total_output_tokens) }}</div>
      </div>
    </div>

    <div class="panel p-5">
      <div class="font-medium mb-1">各阶段用的模型</div>
      <p class="text-sm text-[var(--ink-muted)] mb-3">服务端按阶段绑的模型，来自配置。</p>
      <table class="data-table">
        <thead>
          <tr>
            <th>阶段</th>
            <th>模型</th>
            <th>用途标签</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in routes" :key="r.stage" class="cv-item">
            <td>{{ r.label }}</td>
            <td class="tabular">{{ r.provider }} / {{ r.model }}</td>
            <td class="meta">{{ (r.purposes || []).join(' · ') }}</td>
          </tr>
          <tr v-if="!routes.length">
            <td colspan="3" class="empty">还没有模型配置</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="panel p-5">
      <div class="font-medium mb-3">按用途（tokens + 成本）</div>
      <table class="data-table">
        <thead>
          <tr>
            <th>用途</th>
            <th>in</th>
            <th>out</th>
            <th>成本</th>
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
            <td colspan="4" class="empty">还没有记录</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="panel overflow-hidden">
      <div class="panel-head">最近调用</div>
      <table class="data-table">
        <thead>
          <tr>
            <th>用途</th>
            <th>模型</th>
            <th>in/out</th>
            <th>成本</th>
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
            <td colspan="4" class="empty">还没有调用记录</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
