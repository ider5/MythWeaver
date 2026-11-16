<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { outlineApi, tasksApi, type Outline, type OutlineItem } from '@/api'
import BatchGeneratePanel from '@/components/BatchGeneratePanel.vue'
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
const batching = ref(false)

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

const outlinePhase = computed(() => {
  if (!current.value) return 'plan'
  if (current.value.status === 'confirmed') return 'batch'
  return 'edit'
})

function pickOutline(event: Event) {
  const id = Number((event.target as HTMLSelectElement).value)
  const next = outlines.value.find((outline) => outline.id === id)
  if (next) current.value = next
}

async function load(preferId?: number | null) {
  const { data } = await outlineApi.list(novelId)
  outlines.value = data
  const keepId = preferId ?? current.value?.id
  current.value =
    (keepId != null ? data.find((o) => o.id === keepId) : undefined) || data[0] || null
}

async function generate() {
  if (generating.value || busy.value || batching.value) return
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
  if (!current.value || generating.value || batching.value) return
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
        purpose: i.purpose || '',
        conflict: i.conflict || '',
        suspense_hook: i.suspense_hook || '',
        characters: i.characters || [],
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
  if (!current.value || generating.value || batching.value) return
  await save()
  const { data } = await outlineApi.confirm(novelId, current.value.id)
  current.value = data
  await load(data.id)
  info.value = '大纲已确认。'
}

async function removeOutline(o: Outline) {
  if (generating.value || batching.value) return
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
  <div class="wb-outline">
    <ol class="wb-steps" aria-label="大纲流程">
      <li :class="{ 'is-current': outlinePhase === 'plan', 'is-done': outlinePhase !== 'plan' }">规划</li>
      <li :class="{ 'is-current': outlinePhase === 'edit', 'is-done': outlinePhase === 'batch' }">校对确认</li>
      <li :class="{ 'is-current': outlinePhase === 'batch' }">连写</li>
    </ol>

    <div class="wb-plan">
      <div class="wb-plan__fields">
        <div>
          <label class="label" for="outline-count">规划章数</label>
          <input
            id="outline-count"
            v-model.number="chapterCount"
            type="number"
            min="1"
            max="30"
            class="input wb-tune__num"
            :disabled="generating || batching"
          />
        </div>
        <div class="wb-plan__guidance">
          <label class="label" for="outline-guidance">指导语（可选）</label>
          <input
            id="outline-guidance"
            v-model="guidance"
            class="input"
            placeholder="例如：先打小怪再揭秘身世"
            :disabled="generating || batching"
          />
        </div>
      </div>
      <button class="btn" type="button" :disabled="busy || generating || batching" @click="generate">
        {{ generating ? '生成中…' : '生成大纲' }}
      </button>
    </div>

    <div v-if="generating || generateFailed || generateProgress > 0" class="wb-progress">
      <div class="wb-progress__row">
        <span>大纲生成 · 上下文、模型、校正章号、落库</span>
        <span class="tabular">
          {{ Math.round(generateProgress) }}%
          {{ generateFailed ? '失败' : generating ? '进行中' : '完成' }}
        </span>
      </div>
      <ProgressBar :value="generateProgress" :failed="generateFailed" />
      <p v-if="generateMessage" class="meta">{{ generateMessage }}</p>
      <p v-if="generateError" class="alert alert--danger">{{ generateError }}</p>
      <button
        v-if="generateFailed"
        class="btn btn-sm"
        type="button"
        :disabled="busy || generating || batching"
        @click="generate"
      >
        重试
      </button>
    </div>

    <p v-if="error && !generateFailed" class="alert alert--danger">{{ error }}</p>
    <p v-if="info" class="alert alert--ok">{{ info }}</p>

    <div class="wb-outline__layout">
      <section class="wb-sheet" aria-label="大纲蓝图">
        <header v-if="current" class="wb-sheet__head">
          <div class="min-w-0">
            <label v-if="outlines.length > 1" class="wb-switch">
              <span class="label">切换大纲</span>
              <select
                class="input"
                :value="current.id"
                :disabled="generating || batching || busy"
                @change="pickOutline"
              >
                <option v-for="outline in outlines" :key="outline.id" :value="outline.id">
                  {{ outline.title }} · {{ outline.status === 'confirmed' ? '已确认' : '草稿' }}
                </option>
              </select>
            </label>
            <h2 class="wb-title">{{ current.title }}</h2>
            <p class="wb-lede">
              {{ current.status === 'confirmed' ? '已确认，可以连写' : '草稿，改完后确认' }}
              · 从第 {{ current.start_from_chapter }} 章起
              · {{ current.items.length }} 条
            </p>
          </div>
          <div class="wb-actions">
            <button
              type="button"
              :class="current.status === 'confirmed' ? 'btn-ghost' : 'btn'"
              :disabled="busy || generating || batching"
              @click="confirm"
            >
              确认大纲
            </button>
            <button class="btn-ghost" type="button" :disabled="busy || generating || batching" @click="save">
              保存编辑
            </button>
            <button
              class="btn-danger btn-sm"
              type="button"
              :disabled="busy || generating || batching"
              @click="removeOutline(current)"
            >
              删除
            </button>
          </div>
        </header>
        <p v-if="current" class="wb-note">
          未点保存的修改刷新后会丢失。删除大纲会保留已生成正文，并解除关联。
        </p>

        <ol v-if="current" class="wb-beats">
          <li v-for="item in current.items" :key="item.id || item.order" class="wb-beat">
            <div class="wb-beat__top">
              <span class="chapter-index">第{{ current.start_from_chapter + item.order - 1 }}章</span>
              <input
                v-model="item.title"
                class="input wb-beat__title"
                :aria-label="`第${current.start_from_chapter + item.order - 1}章标题`"
                @change="updateItem(item, 'title', item.title)"
              />
              <span class="wb-state" :data-status="item.status">{{ itemStatusLabel(item.status) }}</span>
            </div>
            <label class="label">梗概</label>
            <textarea v-model="item.summary" class="textarea textarea-sm" rows="2" />
            <div class="wb-beat__grid">
              <div>
                <label class="label">主角小目标</label>
                <textarea v-model="item.purpose" class="textarea textarea-sm" rows="2" />
              </div>
              <div>
                <label class="label">冲突与转折</label>
                <textarea v-model="item.conflict" class="textarea textarea-sm" rows="2" />
              </div>
            </div>
            <label class="label">悬念钩子</label>
            <textarea v-model="item.suspense_hook" class="textarea textarea-sm" rows="2" />
            <label class="label">出场人物</label>
            <input
              class="input"
              :value="(item.characters || []).join('；')"
              placeholder="用；分隔"
              @change="item.characters = ($event.target as HTMLInputElement).value.split(/[；;、,，]/).map(s=>s.trim()).filter(Boolean)"
            />
            <label class="label">要点</label>
            <input
              class="input"
              :value="(item.key_points || []).join('；')"
              placeholder="用；分隔"
              @change="item.key_points = ($event.target as HTMLInputElement).value.split(/[；;]/).map(s=>s.trim()).filter(Boolean)"
            />
          </li>
        </ol>
        <div v-else class="empty-state">
          <p class="empty">尚未生成大纲。填好章数后生成第一份蓝图。</p>
        </div>
      </section>

      <BatchGeneratePanel
        class="wb-director"
        :novel-id="novelId"
        :outline="current"
        :disabled="generating || busy"
        @running="batching = $event"
        @finished="load(current?.id ?? null)"
      />
    </div>
  </div>
</template>
