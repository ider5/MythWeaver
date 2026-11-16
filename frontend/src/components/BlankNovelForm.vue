<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import {
  bibleApi,
  generationApi,
  novelsApi,
  outlineApi,
  tasksApi,
  type Character,
  type Novel,
  type Outline,
  type PlotThread,
  type Task,
  type WorldSetting,
} from '@/api'

const route = useRoute()
const router = useRouter()

const step = ref<1 | 2 | 3 | 4>(1)
const title = ref('')
const author = ref('')
const genre = ref('玄幻')
const premise = ref('')
const writingStyle = ref('短句，冷叙述，对话干净。')
const chapterCount = ref(3)
const novel = ref<Novel | null>(null)
const characters = ref<Character[]>([])
const worlds = ref<WorldSetting[]>([])
const threads = ref<PlotThread[]>([])
const outline = ref<Outline | null>(null)
const busy = ref(false)
const loading = ref(false)
const error = ref('')
const progressLabel = ref('')
const written = ref(false)
let source: EventSource | null = null

const rail = [
  { n: 1, label: '前提' },
  { n: 2, label: '设定' },
  { n: 3, label: '大纲' },
  { n: 4, label: '开篇' },
] as const

function closeSource() {
  source?.close()
  source = null
}

function errText(err: unknown, fallback: string) {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const text = detail
      .map((row) => (row && typeof row === 'object' && 'msg' in row ? String(row.msg) : ''))
      .filter(Boolean)
      .join('；')
    if (text) return text
  }
  if (err instanceof Error && err.message) return err.message
  return fallback
}

function trackTask(taskId: number): Promise<Task> {
  return new Promise((resolve, reject) => {
    closeSource()
    const es = new EventSource(`/api/tasks/${taskId}/events`)
    source = es
    let settled = false
    const finish = (task: Task) => {
      if (settled) return
      progressLabel.value = task.message || progressLabel.value
      if (task.status === 'completed') {
        settled = true
        closeSource()
        resolve(task)
      } else if (task.status === 'failed' || task.status === 'cancelled') {
        settled = true
        closeSource()
        reject(new Error(task.error || task.message || '任务失败'))
      }
    }
    es.onmessage = (ev) => {
      try {
        finish(JSON.parse(ev.data) as Task)
      } catch {
        /* 忽略心跳外的坏包 */
      }
    }
    es.onerror = async () => {
      try {
        const { data } = await tasksApi.get(taskId)
        finish(data)
      } catch (err) {
        if (!settled) {
          settled = true
          closeSource()
          reject(err instanceof Error ? err : new Error('任务连接中断'))
        }
      }
    }
  })
}

async function loadBible(id: number) {
  const { data } = await bibleApi.get(id)
  characters.value = data.characters
  worlds.value = data.world_settings
  threads.value = data.plot_threads
}

async function resume(id: number) {
  loading.value = true
  error.value = ''
  try {
    const { data } = await novelsApi.get(id)
    if (data.origin !== 'scratch') {
      await router.replace(data.role === 'reference' ? `/novels/${id}/bible` : `/novels/${id}/write`)
      return
    }
    novel.value = data
    title.value = data.title
    author.value = data.author || ''
    genre.value = data.genre || '玄幻'
    premise.value = data.premise || ''
    writingStyle.value = data.writing_style || writingStyle.value
    if (data.status === 'blank') {
      step.value = 1
      return
    }
    await loadBible(id)
    const { data: outlines } = await outlineApi.list(id)
    const confirmed = outlines.find((item) => item.status === 'confirmed') || null
    const latest = outlines[0] || null
    outline.value = confirmed || latest
    if ((data.chapter_count || 0) > 0) {
      written.value = true
      step.value = 4
      return
    }
    if (confirmed) {
      step.value = 4
      return
    }
    step.value = latest ? 3 : 2
  } catch (err) {
    error.value = errText(err, '没能打开这本开书')
  } finally {
    loading.value = false
  }
}

async function submitPremise() {
  if (busy.value) return
  const name = title.value.trim()
  const idea = premise.value.trim()
  const style = writingStyle.value.trim()
  if (!name || idea.length < 8 || style.length < 2) {
    error.value = '请填写书名、至少 8 字的前提，以及文风。'
    return
  }
  busy.value = true
  error.value = ''
  try {
    const payload = {
      title: name,
      author: author.value.trim() || null,
      genre: genre.value,
      premise: idea,
      writing_style: style,
    }
    if (!novel.value) {
      const { data } = await novelsApi.createScratch({
        title: name,
        author: author.value.trim() || undefined,
        genre: genre.value,
        premise: idea,
        writing_style: style,
      })
      novel.value = data
    } else {
      const { data } = await novelsApi.update(novel.value.id, payload)
      novel.value = data
    }
    const { data: seeded } = await novelsApi.seedScratch(novel.value.id)
    novel.value = seeded.novel
    characters.value = seeded.characters
    worlds.value = seeded.world_settings
    threads.value = seeded.plot_threads
    step.value = 2
  } catch (err) {
    error.value = errText(err, '开书失败')
  } finally {
    busy.value = false
  }
}

async function generateOutline() {
  if (!novel.value || busy.value) return
  busy.value = true
  error.value = ''
  progressLabel.value = '正在生成大纲…'
  step.value = 3
  try {
    const { data } = await outlineApi.generate(novel.value.id, {
      chapter_count: Math.min(8, Math.max(1, Number(chapterCount.value) || 3)),
    })
    const task = await trackTask(data.task_id)
    const outlineId = Number(task.result?.outline_id)
    const { data: outlines } = await outlineApi.list(novel.value.id)
    outline.value = outlines.find((item) => item.id === outlineId) || outlines[0] || null
    if (!outline.value) throw new Error('大纲没有写下来')
  } catch (err) {
    error.value = errText(err, '大纲生成失败')
  } finally {
    busy.value = false
  }
}

async function confirmOnly() {
  if (!novel.value || !outline.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    if (outline.value.status !== 'confirmed') {
      const { data } = await outlineApi.confirm(novel.value.id, outline.value.id)
      outline.value = data
    }
    await router.push(`/novels/${novel.value.id}/outline`)
  } catch (err) {
    error.value = errText(err, '确认大纲失败')
    busy.value = false
  }
}

async function writeOpening() {
  if (!novel.value || !outline.value || busy.value) return
  busy.value = true
  error.value = ''
  progressLabel.value = '正在写开篇…'
  step.value = 4
  try {
    if (outline.value.status !== 'confirmed') {
      const { data } = await outlineApi.confirm(novel.value.id, outline.value.id)
      outline.value = data
    }
    const count = Math.min(chapterCount.value || outline.value.items.length, outline.value.items.length, 8)
    const { data } = await generationApi.batch(novel.value.id, {
      outline_id: outline.value.id,
      from_order: 1,
      count: Math.max(1, count),
      run_critic: true,
    })
    const task = await trackTask(data.task_id)
    written.value = true
    if (task.result?.paused) {
      error.value = String(task.result.pause_reason || '开篇在一致性检查处停下，可以到开篇里改。')
    }
    const { data: fresh } = await novelsApi.get(novel.value.id)
    novel.value = fresh
  } catch (err) {
    error.value = errText(err, '开篇没有写完')
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  const raw = route.query.novel
  const id = Number(Array.isArray(raw) ? raw[0] : raw)
  if (id) void resume(id)
})

onUnmounted(closeSource)
</script>

<template>
  <div class="create-page">
    <p class="kicker">开书</p>
    <h1 class="page-title">从一句前提写起</h1>
    <p class="page-desc">
      不导入原稿。先定前提和文风，再播种设定、大纲和开篇。
      <RouterLink to="/import">已有原稿，去续写</RouterLink>
    </p>

    <ol class="create-rail" aria-label="开书步骤">
      <li
        v-for="item in rail"
        :key="item.n"
        :class="{ 'is-current': step === item.n, 'is-done': step > item.n }"
      >
        {{ item.label }}
      </li>
    </ol>

    <p v-if="loading" class="meta">正在打开这本开书…</p>
    <p v-if="error" class="alert alert--danger">{{ error }}</p>
    <p v-if="progressLabel && busy" class="meta">{{ progressLabel }}</p>

    <form v-if="step === 1 && !loading" class="create-fields" @submit.prevent="submitPremise">
      <label class="label" for="blank-novel-title">书名</label>
      <input id="blank-novel-title" v-model="title" class="input" required :disabled="busy" />

      <div class="create-split">
        <div>
          <label class="label" for="blank-novel-genre">题材</label>
          <select id="blank-novel-genre" v-model="genre" class="input" :disabled="busy">
            <option>玄幻</option>
            <option>都市</option>
            <option>言情</option>
          </select>
        </div>
        <div>
          <label class="label" for="blank-novel-count">先规划几章</label>
          <input
            id="blank-novel-count"
            v-model.number="chapterCount"
            class="input"
            type="number"
            min="1"
            max="8"
            :disabled="busy"
          />
        </div>
      </div>

      <label class="label" for="blank-novel-premise">前提</label>
      <textarea
        id="blank-novel-premise"
        v-model="premise"
        class="textarea"
        rows="5"
        placeholder="谁，在什么处境，必须做成什么事"
        required
        :disabled="busy"
      />

      <label class="label" for="blank-novel-style">文风</label>
      <textarea
        id="blank-novel-style"
        v-model="writingStyle"
        class="textarea"
        rows="2"
        required
        :disabled="busy"
      />

      <label class="label" for="blank-novel-author">作者（可选）</label>
      <input id="blank-novel-author" v-model="author" class="input" :disabled="busy" />

      <button class="btn" type="submit" :disabled="busy">
        {{ busy ? '正在播种设定…' : '播种设定' }}
      </button>
    </form>

    <section v-else-if="step === 2" class="create-fields">
      <h2 class="create-section">设定种子</h2>
      <p class="meta">人物、规则和主线已经落下。可以改前提重播，或直接生成大纲。</p>
      <div v-if="characters.length">
        <h3 class="label">人物</h3>
        <ul class="create-list">
          <li v-for="row in characters" :key="row.id">
            <strong>{{ row.name }}</strong>
            <span v-if="row.role"> · {{ row.role }}</span>
            <span v-if="row.personality"> · {{ row.personality }}</span>
          </li>
        </ul>
      </div>
      <div v-if="worlds.length">
        <h3 class="label">世界</h3>
        <ul class="create-list">
          <li v-for="row in worlds" :key="row.id">
            <strong>{{ row.title }}</strong>
            <span> · {{ row.content }}</span>
          </li>
        </ul>
      </div>
      <div v-if="threads.length">
        <h3 class="label">线索</h3>
        <ul class="create-list">
          <li v-for="row in threads" :key="row.id">
            <strong>{{ row.title }}</strong>
            <span v-if="row.description"> · {{ row.description }}</span>
          </li>
        </ul>
      </div>
      <div class="create-actions">
        <button class="btn" type="button" :disabled="busy" @click="generateOutline">生成大纲</button>
        <button class="btn-ghost" type="button" :disabled="busy" @click="step = 1">改前提</button>
      </div>
    </section>

    <section v-else-if="step === 3" class="create-fields">
      <h2 class="create-section">{{ outline?.title || '大纲' }}</h2>
      <ol v-if="outline" class="create-list">
        <li v-for="item in outline.items" :key="item.id">
          <strong>{{ item.title }}</strong>
          <p>{{ item.summary }}</p>
          <p v-if="item.purpose" class="meta">目标：{{ item.purpose }}</p>
        </li>
      </ol>
      <p v-else class="meta">大纲还在生成。</p>
      <div class="create-actions">
        <button class="btn" type="button" :disabled="busy || !outline" @click="writeOpening">
          确认并写开篇
        </button>
        <button class="btn-ghost" type="button" :disabled="busy || !outline" @click="confirmOnly">
          只确认大纲
        </button>
      </div>
    </section>

    <section v-else class="create-fields">
      <h2 class="create-section">{{ written ? '开篇已经写下' : '写开篇' }}</h2>
      <p class="page-desc">
        {{
          written
            ? `《${novel?.title || ''}》可以从开篇接着改，也可以回到大纲调整后面的章。`
            : '确认大纲后会按规划写出开篇。'
        }}
      </p>
      <div class="create-actions">
        <button
          v-if="!written"
          class="btn"
          type="button"
          :disabled="busy || !outline"
          @click="writeOpening"
        >
          {{ busy ? '正在写开篇…' : '开始写开篇' }}
        </button>
        <RouterLink v-if="novel && written" class="btn" :to="`/novels/${novel.id}/write`">进入开篇</RouterLink>
        <RouterLink v-if="novel" class="btn-ghost" :to="`/novels/${novel.id}/outline`">看大纲</RouterLink>
      </div>
    </section>
  </div>
</template>
