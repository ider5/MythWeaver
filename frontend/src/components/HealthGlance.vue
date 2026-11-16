<script setup lang="ts">
import type { HealthReport } from '@/api'
import { useSettingsCopy } from '@/lib/settingsCopy'

defineProps<{ report: HealthReport }>()

const copy = useSettingsCopy()

function llmValue(report: HealthReport) {
  const llm = report.checks.llm
  if (!llm.configured) return copy.value.glanceUnconfigured
  if (llm.probed && llm.ok) return copy.value.glanceReachable
  if (llm.probed && !llm.ok) return copy.value.glanceFail
  return copy.value.glanceConfigured
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
      <div class="health-card__label">{{ copy.glanceApi }}</div>
      <div class="health-card__value">{{ report.checks.api.ok ? copy.glanceOnline : copy.glanceDown }}</div>
      <p class="health-card__detail">{{ report.checks.api.detail }}</p>
    </article>
    <article
      class="health-card"
      :class="report.checks.db.ok ? 'health-card--ok' : 'health-card--bad'"
    >
      <div class="health-card__label">{{ copy.glanceDb }}</div>
      <div class="health-card__value">{{ report.checks.db.ok ? copy.glanceDbOk : copy.glanceDbBad }}</div>
      <p class="health-card__detail">
        {{ report.checks.db.detail }}
        <template v-if="report.checks.db.ok">
          · <span class="tabular">{{ copy.glanceBooks(report.novel_count) }}</span>
        </template>
      </p>
    </article>
    <article class="health-card" :class="`health-card--${llmTone(report)}`">
      <div class="health-card__label">{{ copy.glanceLlm }}</div>
      <div class="health-card__value">{{ llmValue(report) }}</div>
      <p class="health-card__detail">
        {{ report.checks.llm.detail }}
        <template v-if="report.checks.llm.latency_ms != null">
          · <span class="tabular">{{ report.checks.llm.latency_ms }} ms</span>
        </template>
      </p>
    </article>
  </div>
</template>
