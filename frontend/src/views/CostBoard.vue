<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { costsApi } from '@/api'

const route = useRoute()
const novelId = Number(route.params.id)
const data = ref<any>(null)

function fmtUsd(n?: number, digits = 4) {
  if (n == null || Number.isNaN(Number(n))) return '—'
  return Number(n).toFixed(digits)
}

function fmtInt(n?: number) {
  if (n == null || Number.isNaN(Number(n))) return '—'
  return Number(n).toLocaleString('zh-CN')
}

onMounted(async () => {
  const res = await costsApi.summary(novelId)
  data.value = res.data
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
      <div class="font-medium mb-3">按用途</div>
      <ul class="text-sm">
        <li v-for="(v, k) in data?.by_purpose || {}" :key="k" class="purpose-row">
          <span>{{ k }}</span>
          <span class="tabular meta">${{ fmtUsd(Number(v)) }}</span>
        </li>
        <li v-if="data && !Object.keys(data.by_purpose || {}).length" class="empty">暂无记录</li>
      </ul>
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
            <td class="tabular">${{ fmtUsd(Number(r.cost_usd), 5) }}</td>
          </tr>
          <tr v-if="data && !(data.recent || []).length">
            <td colspan="4" class="empty">暂无调用记录</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
