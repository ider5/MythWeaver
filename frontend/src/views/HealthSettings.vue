<script setup lang="ts">
import { onActivated, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import HealthGlance from '@/components/HealthGlance.vue'
import { useHealth } from '@/composables/useHealth'
import { useSettingsCopy } from '@/lib/settingsCopy'

const { report, loading, probing, error, load } = useHealth()
const copy = useSettingsCopy()

let skipActivate = false
onMounted(() => {
  skipActivate = true
  load(false)
})
onActivated(() => {
  if (skipActivate) {
    skipActivate = false
    return
  }
  load(false)
})
</script>

<template>
  <div class="health-page">
    <header class="settings-head">
      <p class="kicker">{{ copy.healthKicker }}</p>
      <h1 class="page-title">{{ copy.healthTitle }}</h1>
      <p class="page-desc">
        {{ copy.healthLead }}
        <RouterLink class="crumb" to="/settings/providers">{{ copy.healthOtherKey }}</RouterLink>
      </p>
    </header>

    <p v-if="error" class="alert alert--danger">{{ error }}</p>
    <p v-else-if="loading && !report" class="meta">{{ copy.checking }}</p>
    <HealthGlance v-else-if="report" :report="report" />

    <div class="first-run__actions">
      <button
        class="btn"
        type="button"
        :disabled="probing || !report?.checks.llm.configured"
        @click="load(true)"
      >
        {{ probing ? copy.probing : copy.probeModel }}
      </button>
      <RouterLink class="btn-ghost" to="/settings/providers">{{ copy.openLlm }}</RouterLink>
    </div>

    <p v-if="report?.checks.llm.probed" class="meta" role="status">
      <template v-if="report.checks.llm.ok">
        {{ copy.responded }}
        <span v-if="report.checks.llm.latency_ms != null" class="tabular">
          · {{ report.checks.llm.latency_ms }} ms
        </span>
        <span v-if="report.checks.llm.reply"> · {{ copy.quoted(report.checks.llm.reply) }}</span>
      </template>
      <template v-else>{{ copy.probeFailed }}{{ report.checks.llm.detail }}</template>
    </p>
    <p v-else-if="report && !report.checks.llm.configured" class="meta">
      {{ copy.probeSkipped }}
    </p>

    <section v-if="report?.checks.llm.stages.length" class="panel p-5 space-y-3">
      <h2 class="font-display text-lg">{{ copy.healthStages }}</h2>
      <ul class="text-sm">
        <li v-for="stage in report.checks.llm.stages" :key="stage.stage" class="purpose-row">
          <span>
            {{ stage.label }}
            <span class="stage-url">{{ stage.base_url || copy.noAddress }}</span>
          </span>
          <span class="tabular meta">
            {{ stage.configured ? copy.configured : copy.notConfigured }} · {{ stage.provider }} /
            {{ stage.model || copy.noModel }}
          </span>
        </li>
      </ul>
    </section>

    <p v-if="report && report.novel_count === 0" class="meta">
      {{ copy.noBooks }}
      <RouterLink class="crumb" to="/">{{ copy.backHome }}</RouterLink>
      {{ copy.pickPath }}
    </p>
  </div>
</template>
