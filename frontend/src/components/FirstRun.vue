<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink } from 'vue-router'
import HealthGlance from '@/components/HealthGlance.vue'
import type { HealthReport } from '@/api'

defineProps<{
  report: HealthReport | null
  loading: boolean
  error: string
}>()

defineEmits<{ dismiss: [] }>()

const step = ref<'llm' | 'path'>('llm')
</script>

<template>
  <section class="first-run panel p-5" aria-labelledby="first-run-title">
    <p class="kicker">开始</p>
    <h1 id="first-run-title" class="page-title">先接上模型</h1>
    <p class="page-desc">书架是空的。看一眼接口和密钥，再选开书或续写。</p>

    <ol class="steps mt-4" aria-label="首次步骤">
      <li>
        <button
          type="button"
          class="steps__item"
          :class="step === 'llm' ? 'steps__item--active' : 'steps__item--done'"
          :aria-current="step === 'llm' ? 'step' : undefined"
          @click="step = 'llm'"
        >
          1 模型
        </button>
      </li>
      <li>
        <button
          type="button"
          class="steps__item"
          :class="step === 'path' && 'steps__item--active'"
          :aria-current="step === 'path' ? 'step' : undefined"
          @click="step = 'path'"
        >
          2 开书或续写
        </button>
      </li>
    </ol>

    <div v-if="step === 'llm'">
      <p v-if="error" class="alert alert--danger">{{ error }}</p>
      <p v-else-if="loading && !report" class="meta">正在检查…</p>
      <HealthGlance v-else-if="report" :report="report" />
      <div class="first-run__actions">
        <RouterLink
          v-if="!report?.checks.llm.configured"
          class="btn"
          to="/settings/providers?from=start"
        >
          打开 LLM 设置
        </RouterLink>
        <button
          type="button"
          :class="report?.checks.llm.configured ? 'btn' : 'btn-ghost'"
          @click="step = 'path'"
        >
          下一步
        </button>
        <button class="btn-ghost" type="button" @click="$emit('dismiss')">先看书架</button>
      </div>
      <p v-if="!report?.checks.llm.configured" class="meta mt-3">
        在 LLM 设置里保存一份配置，或写入 backend/.env。测试不会把密钥存下来。
      </p>
    </div>

    <div v-else>
      <p v-if="report && !report.checks.llm.configured" class="alert alert--warn mb-4">
        续写密钥还没配。书可以先建，生成正文时会失败。
      </p>
      <div class="home-cta">
        <RouterLink class="home-go" to="/create">
          开书
          <span class="home-go__mark" aria-hidden="true"></span>
        </RouterLink>
        <RouterLink class="home-go home-go--quiet" to="/import">
          续写
          <span class="home-go__mark" aria-hidden="true"></span>
        </RouterLink>
      </div>
      <div class="first-run__actions">
        <button class="btn-ghost" type="button" @click="step = 'llm'">返回模型</button>
        <button class="btn-ghost" type="button" @click="$emit('dismiss')">先看书架</button>
      </div>
    </div>
  </section>
</template>
