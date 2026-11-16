<script setup lang="ts">
import type { HealthReport } from '@/api'

defineProps<{ report: HealthReport }>()

function llmValue(report: HealthReport) {
  const llm = report.checks.llm
  if (!llm.configured) return '未配置'
  if (llm.probed && llm.ok) return '连通'
  if (llm.probed && !llm.ok) return '失败'
  return '已配置'
}

function llmTone(report: HealthReport) {
  const llm = report.checks.llm
  if (!llm.configured || (llm.probed && !llm.ok)) return 'bad'
  if (llm.probed && llm.ok) return 'ok'
  return 'idle'
}
</script>

<template>
  <div class="health-grid">
    <article
      class="health-card"
      :class="report.checks.api.ok ? 'health-card--ok' : 'health-card--bad'"
    >
      <div class="health-card__label">接口</div>
      <div class="health-card__value">{{ report.checks.api.ok ? '在线' : '无响应' }}</div>
      <p class="health-card__detail">{{ report.checks.api.detail }}</p>
    </article>
    <article
      class="health-card"
      :class="report.checks.db.ok ? 'health-card--ok' : 'health-card--bad'"
    >
      <div class="health-card__label">数据库</div>
      <div class="health-card__value">{{ report.checks.db.ok ? '可读写' : '不可用' }}</div>
      <p class="health-card__detail">
        {{ report.checks.db.detail }}
        <template v-if="report.checks.db.ok"> · {{ report.novel_count }} 本</template>
      </p>
    </article>
    <article class="health-card" :class="`health-card--${llmTone(report)}`">
      <div class="health-card__label">续写模型</div>
      <div class="health-card__value">{{ llmValue(report) }}</div>
      <p class="health-card__detail">
        {{ report.checks.llm.detail }}
        <template v-if="report.checks.llm.latency_ms != null">
          · {{ report.checks.llm.latency_ms }} ms
        </template>
      </p>
    </article>
  </div>
</template>
