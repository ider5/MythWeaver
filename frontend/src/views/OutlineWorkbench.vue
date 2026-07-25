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
const info = ref('')

async function load(preferId?: number | null) {
  const { data } = await outlineApi.list(novelId)
  outlines.value = data
  const keepId = preferId ?? current.value?.id
  current.value =
    (keepId != null ? data.find((o) => o.id === keepId) : undefined) || data[0] || null
}

async function generate() {
  busy.value = true
  error.value = ''
  info.value = ''
  try {
    const { data } = await outlineApi.generate(novelId, {
      chapter_count: chapterCount.value,
      guidance: guidance.value || undefined,
    })
    await load(data.id)
    current.value = data
    info.value = '大纲已生成并保存到库，刷新后仍可查看。'
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
  error.value = ''
  info.value = ''
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
    info.value = '编辑已保存。'
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '保存失败'
  } finally {
    busy.value = false
  }
}

async function confirm() {
  if (!current.value) return
  await save()
  const { data } = await outlineApi.confirm(novelId, current.value.id)
  current.value = data
  await load(data.id)
  info.value = '大纲已确认。'
}

async function removeOutline(o: Outline) {
  const linkedDone = (o.items || []).some((i) => i.status === 'done')
  const lines = [
    o.status === 'confirmed'
      ? `「${o.title}」已确认。确定删除吗？`
      : `确定删除草稿大纲「${o.title}」吗？`,
    '删除后大纲条目不可恢复。',
    linkedDone || o.status === 'confirmed'
      ? '已生成的章节正文会保留，仅解除与该大纲的关联。'
      : '',
  ].filter(Boolean)
  if (!window.confirm(lines.join('\n'))) return

  busy.value = true
  error.value = ''
  info.value = ''
  try {
    const { data } = await outlineApi.remove(novelId, o.id)
    const unbound = data.unbound_chapters || 0
    await load(null)
    info.value =
      unbound > 0
        ? `大纲已删除；已解绑 ${unbound} 个关联章节（正文仍保留）。`
        : '大纲已删除。'
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '删除失败'
  } finally {
    busy.value = false
  }
}

onMounted(() => load())
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
      <button
        class="btn-ghost"
        style="color: var(--danger)"
        :disabled="!current || busy"
        @click="current && removeOutline(current)"
      >
        删除当前大纲
      </button>
    </div>
    <p class="text-xs" style="color: var(--ink-muted)">
      草稿与已确认大纲均可删除；已生成章节正文会保留并解绑。未点「保存编辑」的本地修改刷新后会丢失。
    </p>
    <p v-if="error" class="text-sm" style="color: var(--danger)">{{ error }}</p>
    <p v-if="info" class="text-sm" style="color: var(--accent)">{{ info }}</p>

    <div v-if="outlines.length" class="flex gap-2 text-sm flex-wrap items-center">
      <div
        v-for="o in outlines"
        :key="o.id"
        class="flex items-center gap-1 border"
        style="border-color: var(--line)"
      >
        <button
          class="btn-ghost"
          :style="current?.id === o.id ? { background: 'var(--bg-deep)' } : {}"
          @click="current = o"
        >
          #{{ o.id }} {{ o.title }} ({{ o.status === 'confirmed' ? '已确认' : '草稿' }})
        </button>
        <button
          class="btn-ghost text-xs px-2"
          style="color: var(--danger)"
          :disabled="busy"
          title="删除此大纲"
          @click="removeOutline(o)"
        >
          删除
        </button>
      </div>
    </div>

    <div v-if="current" class="space-y-3">
      <div class="text-sm" style="color: var(--ink-muted)">
        {{ current.title }} · {{ current.status === 'confirmed' ? '已确认' : '草稿' }} · 从第 {{ current.start_from_chapter }} 章起
      </div>
      <div v-for="item in current.items" :key="item.id || item.order" class="panel p-4 space-y-2">
        <div class="flex gap-3">
          <span class="text-sm pt-2" style="color: var(--ink-muted)">第{{ current.start_from_chapter + item.order - 1 }}章</span>
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
