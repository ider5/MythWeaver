<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { novelsApi, outlineApi, type Outline, type OutlineItem } from '@/api'

const route = useRoute()
const novelId = Number(route.params.id)
const outlines = ref<Outline[]>([])
const outline = ref<Outline | null>(null)
const selected = ref<OutlineItem | null>(null)
const streaming = ref(false)
const status = ref('')
const content = ref('')
const consistency = ref<any>(null)
const chapterId = ref<number | null>(null)
const versions = ref<any[]>([])
const error = ref('')
let es: EventSource | null = null

const pendingItems = computed(() =>
  (outline.value?.items || []).filter((i) => i.status !== 'done'),
)

async function load() {
  const { data } = await outlineApi.list(novelId)
  outlines.value = data
  outline.value = data.find((o) => o.status === 'confirmed') || data[0] || null
  selected.value = pendingItems.value[0] || outline.value?.items?.[0] || null
}

function startGenerate() {
  if (!selected.value) return
  streaming.value = true
  status.value = '连接中…'
  content.value = ''
  consistency.value = null
  chapterId.value = null
  error.value = ''
  es?.close()
  const url = `/api/novels/${novelId}/generate/stream?outline_item_id=${selected.value.id}&run_critic=true&max_critic_rounds=2`
  es = new EventSource(url)
  es.onmessage = async (ev) => {
    const data = JSON.parse(ev.data)
    if (data.event === 'status') status.value = data.message || ''
    if (data.event === 'delta') content.value += data.text || ''
    if (data.event === 'error') {
      error.value = data.message
      streaming.value = false
      es?.close()
    }
    if (data.event === 'done') {
      content.value = data.content || content.value
      consistency.value = data.consistency
      chapterId.value = data.chapter_id
      streaming.value = false
      status.value = '完成'
      es?.close()
      await load()
      if (chapterId.value) {
        const { data: vers } = await novelsApi.versions(novelId, chapterId.value)
        versions.value = vers
      }
    }
  }
  es.onerror = () => {
    if (streaming.value) error.value = 'SSE 连接中断'
    streaming.value = false
    es?.close()
  }
}

async function saveRevise() {
  if (!chapterId.value) return
  await novelsApi.revise(novelId, chapterId.value, content.value, true)
  status.value = '已入库并更新知识库'
  const { data: vers } = await novelsApi.versions(novelId, chapterId.value)
  versions.value = vers
}

function loadVersion(v: any) {
  content.value = v.content
}

onMounted(load)
onUnmounted(() => es?.close())
</script>

<template>
  <div class="grid lg:grid-cols-[240px_1fr] gap-4">
    <aside class="panel p-3 space-y-2 max-h-[70vh] overflow-auto">
      <div class="text-xs mb-2" style="color: var(--ink-muted)">选择大纲条目</div>
      <button
        v-for="item in outline?.items || []"
        :key="item.id"
        class="w-full text-left px-2 py-2 text-sm border"
        style="border-color: var(--line)"
        :style="selected?.id === item.id ? { background: 'var(--bg-deep)' } : {}"
        @click="selected = item"
      >
        <div class="font-medium">{{ item.order }}. {{ item.title }}</div>
        <div class="text-xs" style="color: var(--ink-muted)">{{ item.status }}</div>
      </button>
      <p v-if="!outline" class="text-xs" style="color: var(--ink-muted)">请先在大纲页生成并确认。</p>
    </aside>

    <section class="space-y-3">
      <div class="flex flex-wrap gap-2 items-center">
        <button class="btn" :disabled="!selected || streaming" @click="startGenerate">流式生成</button>
        <button class="btn-ghost" :disabled="!chapterId || streaming" @click="saveRevise">保存修订并入库</button>
        <span class="text-sm" style="color: var(--ink-muted)">{{ status }}</span>
      </div>
      <p v-if="error" class="text-sm" style="color: var(--danger)">{{ error }}</p>

      <div v-if="selected" class="panel p-3 text-sm" style="color: var(--ink-muted)">
        <div class="font-medium text-[var(--ink)]">{{ selected.title }}</div>
        <div class="mt-1">{{ selected.summary }}</div>
        <ul class="mt-1 list-disc pl-5">
          <li v-for="(p, i) in selected.key_points || []" :key="i">{{ p }}</li>
        </ul>
      </div>

      <textarea v-model="content" class="textarea min-h-[420px] font-serif leading-7" placeholder="生成内容将在此流式出现，可直接修订…" />

      <div v-if="consistency" class="panel p-4">
        <div class="font-medium mb-2">
          一致性报告
          <span :style="{ color: consistency.ok ? 'var(--accent)' : 'var(--danger)' }">
            {{ consistency.ok ? '通过' : '有问题' }}
          </span>
          <span class="text-xs ml-2" style="color: var(--ink-muted)">Critic {{ consistency.critic_rounds || 0 }} 轮</span>
        </div>
        <ul class="space-y-1 text-sm">
          <li v-for="(iss, i) in consistency.issues || []" :key="i">
            [{{ iss.severity }}] {{ iss.type }} — {{ iss.message }}
          </li>
          <li v-if="!(consistency.issues || []).length" class="text-sm" style="color: var(--ink-muted)">无问题</li>
        </ul>
      </div>

      <div v-if="versions.length" class="panel p-3">
        <div class="text-sm mb-2 font-medium">版本链</div>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="v in versions"
            :key="v.id"
            class="btn-ghost text-xs"
            @click="loadVersion(v)"
          >
            #{{ v.id }} {{ v.version_type }}
          </button>
        </div>
      </div>
    </section>
  </div>
</template>
