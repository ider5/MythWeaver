<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { outlineApi, type Outline, type OutlineItem } from '@/api'

const route = useRoute()
const novelId = Number(route.params.id)
const outlines = ref<Outline[]>([])
const current = ref<Outline | null>(null)
const chapterCount = ref(5)
const guidance = ref('')
const busy = ref(false)
const error = ref('')

async function load() {
  const { data } = await outlineApi.list(novelId)
  outlines.value = data
  current.value = data[0] || null
}

async function generate() {
  busy.value = true
  error.value = ''
  try {
    const { data } = await outlineApi.generate(novelId, {
      chapter_count: chapterCount.value,
      guidance: guidance.value || undefined,
    })
    current.value = data
    await load()
    current.value = data
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '生成失败'
  } finally {
    busy.value = false
  }
}

function updateItem(item: OutlineItem, field: string, value: string) {
  ;(item as any)[field] = value
}

async function save() {
  if (!current.value) return
  busy.value = true
  try {
    const { data } = await outlineApi.update(novelId, current.value.id, {
      title: current.value.title,
      items: current.value.items.map((i) => ({
        order: i.order,
        title: i.title,
        summary: i.summary,
        key_points: i.key_points,
        status: i.status,
      })),
    })
    current.value = data
  } finally {
    busy.value = false
  }
}

async function confirm() {
  if (!current.value) return
  await save()
  const { data } = await outlineApi.confirm(novelId, current.value.id)
  current.value = data
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="panel p-4 flex flex-wrap gap-3 items-end">
      <div>
        <label class="label">规划章数</label>
        <input v-model.number="chapterCount" type="number" min="1" max="30" class="input w-24" />
      </div>
      <div class="flex-1 min-w-[200px]">
        <label class="label">指导语（可选）</label>
        <input v-model="guidance" class="input" placeholder="例如：先打小怪再揭秘身世" />
      </div>
      <button class="btn" :disabled="busy" @click="generate">生成大纲</button>
      <button class="btn-ghost" :disabled="!current || busy" @click="save">保存编辑</button>
      <button class="btn-ghost" :disabled="!current || busy" @click="confirm">确认大纲</button>
    </div>
    <p v-if="error" class="text-sm" style="color: var(--danger)">{{ error }}</p>

    <div v-if="outlines.length > 1" class="flex gap-2 text-sm flex-wrap">
      <button
        v-for="o in outlines"
        :key="o.id"
        class="btn-ghost"
        @click="current = o"
      >
        #{{ o.id }} {{ o.title }} ({{ o.status }})
      </button>
    </div>

    <div v-if="current" class="space-y-3">
      <div class="text-sm" style="color: var(--ink-muted)">
        {{ current.title }} · {{ current.status }} · 从第 {{ current.start_from_chapter }} 章起
      </div>
      <div v-for="item in current.items" :key="item.id || item.order" class="panel p-4 space-y-2">
        <div class="flex gap-3">
          <span class="text-sm pt-2" style="color: var(--ink-muted)">#{{ item.order }}</span>
          <input v-model="item.title" class="input" @change="updateItem(item, 'title', item.title)" />
        </div>
        <textarea v-model="item.summary" class="textarea" rows="3" />
        <input
          class="input"
          :value="(item.key_points || []).join('；')"
          placeholder="要点，用；分隔"
          @change="item.key_points = ($event.target as HTMLInputElement).value.split(/[；;]/).map(s=>s.trim()).filter(Boolean)"
        />
        <div class="text-xs" style="color: var(--ink-muted)">状态：{{ item.status }}</div>
      </div>
    </div>
    <p v-else class="text-sm" style="color: var(--ink-muted)">尚未生成大纲。</p>
  </div>
</template>
