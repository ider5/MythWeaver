<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { costsApi } from '@/api'

const route = useRoute()
const novelId = Number(route.params.id)
const data = ref<any>(null)

onMounted(async () => {
  const res = await costsApi.summary(novelId)
  data.value = res.data
})
</script>

<template>
  <div class="space-y-4">
    <div class="grid sm:grid-cols-3 gap-3">
      <div class="panel p-4">
        <div class="text-xs" style="color: var(--ink-muted)">总成本 (USD)</div>
        <div class="font-display text-2xl mt-1">{{ data?.total_cost_usd?.toFixed?.(4) ?? '—' }}</div>
      </div>
      <div class="panel p-4">
        <div class="text-xs" style="color: var(--ink-muted)">输入 tokens</div>
        <div class="font-display text-2xl mt-1">{{ data?.total_input_tokens ?? '—' }}</div>
      </div>
      <div class="panel p-4">
        <div class="text-xs" style="color: var(--ink-muted)">输出 tokens</div>
        <div class="font-display text-2xl mt-1">{{ data?.total_output_tokens ?? '—' }}</div>
      </div>
    </div>

    <div class="panel p-4">
      <div class="font-medium mb-2">按用途</div>
      <ul class="text-sm space-y-1">
        <li v-for="(v, k) in data?.by_purpose || {}" :key="k">{{ k }}: ${{ Number(v).toFixed(4) }}</li>
      </ul>
    </div>

    <div class="panel overflow-hidden">
      <div class="px-4 py-2 text-sm border-b font-medium" style="border-color: var(--line)">最近调用</div>
      <table class="w-full text-sm">
        <thead>
          <tr class="text-left" style="color: var(--ink-muted)">
            <th class="px-4 py-2">用途</th>
            <th>模型</th>
            <th>in/out</th>
            <th>成本</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in data?.recent || []" :key="r.id" class="border-t" style="border-color: var(--line)">
            <td class="px-4 py-2">{{ r.purpose }}</td>
            <td>{{ r.model }}</td>
            <td>{{ r.input_tokens }}/{{ r.output_tokens }}</td>
            <td>${{ Number(r.cost_usd).toFixed(5) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
