<script setup lang="ts">
import { onActivated, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import HealthGlance from '@/components/HealthGlance.vue'
import { useHealth } from '@/composables/useHealth'

const { report, loading, probing, error, load } = useHealth()

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
    <header>
      <p class="kicker">设置</p>
      <h1 class="page-title">运行状态</h1>
      <p class="page-desc">
        接口、数据库，以及当前生效的模型。探测会用这份续写密钥发一次短请求。
        <RouterLink class="crumb" to="/settings/providers">用别的密钥测试。</RouterLink>
      </p>
    </header>

    <p v-if="error" class="alert alert--danger">{{ error }}</p>
    <p v-else-if="loading && !report" class="meta">正在检查…</p>
    <HealthGlance v-else-if="report" :report="report" />

    <div class="first-run__actions">
      <button
        class="btn"
        type="button"
        :disabled="probing || !report?.checks.llm.configured"
        @click="load(true)"
      >
        {{ probing ? '探测中…' : '探测续写模型' }}
      </button>
      <RouterLink class="btn-ghost" to="/settings/providers">打开 LLM 设置</RouterLink>
    </div>

    <p v-if="report?.checks.llm.probed" class="meta" role="status">
      <template v-if="report.checks.llm.ok">
        有响应
        <span v-if="report.checks.llm.latency_ms != null" class="tabular">
          · {{ report.checks.llm.latency_ms }} ms
        </span>
        <span v-if="report.checks.llm.reply"> · 「{{ report.checks.llm.reply }}」</span>
      </template>
      <template v-else>探测失败：{{ report.checks.llm.detail }}</template>
    </p>
    <p v-else-if="report && !report.checks.llm.configured" class="meta">
      续写密钥还没配置。这里的探测不会发请求。
    </p>

    <section v-if="report?.checks.llm.stages.length" class="panel p-5 space-y-3">
      <div class="font-medium">各阶段</div>
      <ul class="text-sm">
        <li v-for="stage in report.checks.llm.stages" :key="stage.stage" class="purpose-row">
          <span>
            {{ stage.label }}
            <span class="stage-url">{{ stage.base_url || '未填地址' }}</span>
          </span>
          <span class="tabular meta">
            {{ stage.configured ? '已配置' : '未配置' }} · {{ stage.provider }} /
            {{ stage.model || '未填模型' }}
          </span>
        </li>
      </ul>
    </section>

    <p v-if="report && report.novel_count === 0" class="meta">
      还没有书。
      <RouterLink class="crumb" to="/">回到首页</RouterLink>
      选开书或续写。
    </p>
  </div>
</template>
