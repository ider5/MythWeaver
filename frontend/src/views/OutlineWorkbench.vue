<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { outlineApi, tasksApi, type Outline, type OutlineItem } from '@/api'
import ProgressBar from '@/components/ProgressBar.vue'

const route = useRoute()
const novelId = Number(route.params.id)
const outlines = ref<Outline[]>([])
const current = ref<Outline | null>(null)
const chapterCount = ref(5)
const guidance = ref('')
const busy = ref(false)
const generating = ref(false)
const generateFailed = ref(false)
const generateProgress = ref(0)
const generateMessage = ref('')
const generateError = ref('')
const error = ref('')
const info = ref('')

let generateEs: EventSource | null = null

function closeGenerateEs() {
  generateEs?.close()
  generateEs = null
}

function itemStatusLabel(s: string) {
  if (s === 'done') return '已完成'
  if (s === 'generating') return '生成中'
  if (s === 'pending') return '待写'
  return s
}

async function load(preferId?: number | null) {
  const { data } = await outlineApi.list(novelId)
  outlines.value = data
  const keepId = preferId ?? current.value?.id
  current.value =
    (keepId != null ? data.find((o) => o.id === keepId) : undefined) || data[0] || null
}

async function generate() {
  if (generating.value || busy.value) return
  generating.value = true
  generateFailed.value = false
  generateError.value = ''
  generateProgress.value = 2
  generateMessage.value = '大纲生成排队中…'
  error.value = ''
  info.value = ''
  try {
    const { data } = await outlineApi.generate(novelId, {
      chapter_count: chapterCount.value,
      guidance: guidance.value || undefined,
    })
    generateProgress.value = 5
    generateMessage.value = '已开始生成…'
    watchGenerateTask(data.task_id)
  } catch (e: any) {
    generating.value = false
    generateFailed.value = true
    generateError.value = e?.response?.data?.detail || e?.message || '生成失败'
    error.value = generateError.value
  }
}

function watchGenerateTask(taskId: number) {
  closeGenerateEs()
  generateEs = new EventSource(`/api/tasks/${taskId}/events`)
  generateEs.onmessage = async (ev) => {
    try {
      const task = JSON.parse(ev.data)
      generateProgress.value = Number(task.progress) || 0
      generateMessage.value = task.message || ''
      if (task.status === 'completed') {
        generating.value = false
        generateFailed.value = false
        generateProgress.value = 100
        generateMessage.value = '大纲已生成'
        closeGenerateEs()
        const outlineId = Number(task.result?.outline_id)
        if (outlineId) {
          await load(outlineId)
          current.value = outlines.value.find((o) => o.id === outlineId) || current.value
        } else {
          await load()
        }
        info.value = '大纲已生成并保存到库，刷新后仍可查看。'
        return
      }
      if (task.status === 'failed') {
        generating.value = false
        generateFailed.value = true
        generateError.value = task.error || '生成失败'
        error.value = generateError.value
        closeGenerateEs()
      }
    } catch {
      /* ignore parse errors */
    }
  }
  generateEs.onerror = async () => {
    try {
      const { data: task } = await tasksApi.get(taskId)
      generateProgress.value = Number(task.progress) || 0
      generateMessage.value = task.message || ''
      if (task.status === 'completed') {
        generating.value = false
        generateFailed.value = false
        generateProgress.value = 100
        generateMessage.value = '大纲已生成'
        closeGenerateEs()
        const outlineId = Number(task.result?.outline_id)
        if (outlineId) {
          await load(outlineId)
          current.value = outlines.value.find((o) => o.id === outlineId) || current.value
        } else {
          await load()
        }
        info.value = '大纲已生成并保存到库，刷新后仍可查看。'
        return
      }
      if (task.status === 'failed') {
        generating.value = false
        generateFailed.value = true
        generateError.value = task.error || '生成失败'
        error.value = generateError.value
        closeGenerateEs()
        return
      }
      if (!generating.value) {
        generating.value = true
      }
    } catch (e: any) {
      generating.value = false
      generateFailed.value = true
      generateError.value = e?.message || '生成进度连接中断，请重试'
      error.value = generateError.value
      closeGenerateEs()
    }
  }
}

function updateItem(item: OutlineItem, field: string, value: string) {
  ;(item as any)[field] = value
}

async function save() {
  if (!current.value || generating.value) return
  busy.value = true
  error.value = ''
  info.value = ''
  try {
    const { data } = await outlineApi.update(novelId, current.value.id, {
      title: current.value.title,
      items: current.value.items.map((i) => ({
        id: i.id,
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
  if (!current.value || generating.value) return
  await save()
  const { data } = await outlineApi.confirm(novelId, current.value.id)
  current.value = data
  await load(data.id)
  info.value = '大纲已确认。'
}

async function removeOutline(o: Outline) {
  if (generating.value) return
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
onUnmounted(() => closeGenerateEs())
</script>

<template>
  <div class="space-y-5">
    <div class="panel toolbar toolbar--split">
      <div class="toolbar__fields">
        <div>
          <label class="label">规划章数</label>
          <input
            v-model.number="chapterCount"
            type="number"
            min="1"
            max="30"
            class="input w-24"
            :disabled="generating"
          />
        </div>
        <div class="flex-1 min-w-[200px]">
          <label class="label">指导语（可选）</label>
          <input
            v-model="guidance"
            class="input"
            placeholder="例如：先打小怪再揭秘身世"
            :disabled="generating"
          />
        </div>
      </div>
      <div class="toolbar__actions">
        <button class="btn" :disabled="busy || generating" @click="generate">
          {{ generating ? '生成中…' : '生成大纲' }}
        </button>
        <button class="btn-ghost" :disabled="!current || busy || generating" @click="save">
          保存编辑
        </button>
        <button class="btn-ghost" :disabled="!current || busy || generating" @click="confirm">
          确认大纲
        </button>
        <button
          class="btn-danger"
          :disabled="!current || busy || generating"
          @click="current && removeOutline(current)"
        >
          删除当前大纲
        </button>
      </div>
    </div>

    <div v-if="generating || generateFailed || generateProgress > 0" class="panel p-5">
      <div class="text-sm mb-2 font-medium">大纲生成进度</div>
      <ProgressBar :value="generateProgress" :failed="generateFailed" />
      <div class="text-sm mt-2 tabular">
        {{ Math.round(generateProgress) }}%
        <span class="meta"> · {{ generateFailed ? '失败' : generating ? '进行中' : '完成' }} </span>
      </div>
      <div class="meta mt-1">{{ generateMessage }}</div>
      <p v-if="generateError" class="alert alert--danger mt-3">
        {{ generateError }}
      </p>
      <p class="meta mt-2">准备上下文 → 调用模型生成 → 解析校正章号 → 落库</p>
      <button v-if="generateFailed" class="btn mt-3" :disabled="busy || generating" @click="generate">
        重试
      </button>
    </div>

    <p class="meta">
      草稿与已确认大纲均可删除；已生成章节正文会保留并解绑。未点「保存编辑」的本地修改刷新后会丢失。
    </p>
    <p v-if="error && !generateFailed" class="alert alert--danger">{{ error }}</p>
    <p v-if="info" class="alert alert--ok">{{ info }}</p>

    <div v-if="outlines.length" class="flex gap-2 text-sm flex-wrap items-center">
      <div v-for="o in outlines" :key="o.id" class="flex items-center gap-1">
        <button
          class="chip"
          :class="{ 'chip--active': current?.id === o.id }"
          @click="current = o"
        >
          #{{ o.id }} {{ o.title }}
          <span class="ml-1 opacity-70">{{ o.status === 'confirmed' ? '已确认' : '草稿' }}</span>
        </button>
        <button
          class="btn-danger btn-sm"
          :disabled="busy || generating"
          title="删除此大纲"
          @click="removeOutline(o)"
        >
          删除
        </button>
      </div>
    </div>

    <div v-if="current" class="space-y-3">
      <div class="meta">
        {{ current.title }} · {{ current.status === 'confirmed' ? '已确认' : '草稿' }} · 从第
        {{ current.start_from_chapter }} 章起
      </div>
      <div v-for="item in current.items" :key="item.id || item.order" class="panel cv-card p-5 space-y-3">
        <div class="flex gap-3 items-center">
          <span class="chapter-index shrink-0">第{{ current.start_from_chapter + item.order - 1 }}章</span>
          <input v-model="item.title" class="input" @change="updateItem(item, 'title', item.title)" />
        </div>
        <textarea v-model="item.summary" class="textarea textarea-sm" rows="3" />
        <input
          class="input"
          :value="(item.key_points || []).join('；')"
          placeholder="要点，用；分隔"
          @change="item.key_points = ($event.target as HTMLInputElement).value.split(/[；;]/).map(s=>s.trim()).filter(Boolean)"
        />
        <div>
          <span
            class="status-pill"
            :class="item.status === 'done' ? 'status-pill--ok' : item.status === 'generating' ? 'status-pill--busy' : 'status-pill--idle'"
          >
            {{ itemStatusLabel(item.status) }}
          </span>
        </div>
      </div>
    </div>
    <div v-else class="empty-state">
      <p class="empty">尚未生成大纲。</p>
    </div>
  </div>
</template>
