<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { novelsApi, outlineApi, type Outline, type OutlineItem } from '@/api'

/** 超过此时长无任何 SSE 事件（含 ping）则判定卡死；应 > 2× 后端心跳间隔 */
const IDLE_TIMEOUT_MS = 45_000

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
const activeVersionId = ref<number | null>(null)
const error = ref('')
const deleting = ref(false)
const deletingChapter = ref(false)
/** 一致性检验 / Critic：默认开启 + 2 轮（与后端 Query 默认一致） */
const runCritic = ref(true)
const maxCriticRounds = ref(2)
let es: EventSource | null = null
let idleTimer: ReturnType<typeof setTimeout> | null = null
/** 避免快速切换条目时旧请求覆盖新选择 */
let loadSeq = 0

const pendingItems = computed(() =>
  (outline.value?.items || []).filter((i) => i.status !== 'done'),
)

/** 当前选中版本无报告时展示友好提示（避免沿用上一份报告） */
const showNoReportHint = computed(
  () => !!chapterId.value && activeVersionId.value != null && !consistency.value && !streaming.value,
)

function clearIdleWatch() {
  if (idleTimer != null) {
    clearTimeout(idleTimer)
    idleTimer = null
  }
}

function armIdleWatch() {
  clearIdleWatch()
  idleTimer = setTimeout(() => {
    if (!streaming.value) return
    error.value = '生成超时：长时间无响应，连接可能已断开，请重试'
    status.value = '已中断'
    streaming.value = false
    es?.close()
    es = null
  }, IDLE_TIMEOUT_MS)
}

function stopStream(msg?: string) {
  clearIdleWatch()
  streaming.value = false
  if (msg) {
    error.value = msg
    status.value = '已中断'
  }
  es?.close()
  es = null
}

function clearEditor() {
  content.value = ''
  consistency.value = null
  chapterId.value = null
  versions.value = []
  activeVersionId.value = null
}

function applyVersion(v: any) {
  content.value = v?.content ?? ''
  consistency.value = v?.consistency_report ?? null
  activeVersionId.value = v?.id ?? null
}

function applyLatestVersion(vers: any[]) {
  versions.value = vers
  if (!vers.length) {
    consistency.value = null
    activeVersionId.value = null
    return
  }
  applyVersion(vers[vers.length - 1])
}

async function loadChapterForItem(item: OutlineItem | null) {
  if (!item || streaming.value) return
  const seq = ++loadSeq
  clearEditor()
  status.value = '加载已有章节…'
  error.value = ''
  try {
    const { data: ch } = await novelsApi.chapterByOutlineItem(novelId, item.id)
    if (seq !== loadSeq) return
    content.value = ch.content || ''
    chapterId.value = ch.id
    status.value = `已加载第 ${ch.index} 章`
    const { data: vers } = await novelsApi.versions(novelId, ch.id)
    if (seq !== loadSeq) return
    // 正文以章节表为准；报告取最新版本（不跨版本沿用旧报告）
    applyLatestVersion(vers)
    content.value = ch.content || ''
  } catch (e: any) {
    if (seq !== loadSeq) return
    // 404：该条目尚未生成 — 正常空编辑器，不算错误
    const code = e?.response?.status
    if (code === 404) {
      status.value = ''
      return
    }
    error.value = e?.response?.data?.detail || e?.message || '加载章节失败'
    status.value = ''
  }
}

async function selectItem(item: OutlineItem) {
  if (streaming.value) return
  selected.value = item
  await loadChapterForItem(item)
}

async function load() {
  const { data } = await outlineApi.list(novelId)
  outlines.value = data
  const prevItemId = selected.value?.id
  outline.value = data.find((o) => o.status === 'confirmed') || data[0] || null
  const items = outline.value?.items || []
  selected.value =
    items.find((i) => i.id === prevItemId) ||
    pendingItems.value[0] ||
    items[0] ||
    null
  await loadChapterForItem(selected.value)
}

function startGenerate() {
  if (!selected.value) return
  streaming.value = true
  status.value = '连接中…'
  content.value = ''
  consistency.value = null
  chapterId.value = null
  versions.value = []
  activeVersionId.value = null
  error.value = ''
  es?.close()
  const params = new URLSearchParams({
    outline_item_id: String(selected.value.id),
    run_critic: String(runCritic.value),
    max_critic_rounds: String(runCritic.value ? maxCriticRounds.value : 0),
  })
  const url = `/api/novels/${novelId}/generate/stream?${params}`
  es = new EventSource(url)
  armIdleWatch()
  es.onmessage = async (ev) => {
    armIdleWatch()
    let data: any
    try {
      data = JSON.parse(ev.data)
    } catch {
      return
    }
    if (data.event === 'ping') return
    if (data.event === 'status') status.value = data.message || ''
    if (data.event === 'delta') content.value += data.text || ''
    if (data.event === 'error') {
      const raw = data.message || '生成失败'
      const friendly =
        /UNIQUE constraint failed:\s*chapters\.novel_id,\s*chapters\.index/i.test(raw)
          ? '该章节已存在。请刷新后重试生成（系统会覆盖已有草稿）。'
          : raw
      stopStream(friendly)
      return
    }
    if (data.event === 'done') {
      clearIdleWatch()
      content.value = data.content || content.value
      consistency.value = data.consistency
      chapterId.value = data.chapter_id
      activeVersionId.value = data.version_id ?? null
      streaming.value = false
      status.value = data.overwritten ? '完成（已覆盖已有章节）' : '完成'
      es?.close()
      es = null
      await load()
      if (chapterId.value) {
        const { data: vers } = await novelsApi.versions(novelId, chapterId.value)
        applyLatestVersion(vers)
        if (data.content) content.value = data.content
      }
    }
  }
  es.onerror = () => {
    // EventSource 在服务端正常结束后也可能触发；仅在仍 streaming 时视为异常
    if (streaming.value) {
      stopStream('SSE 连接中断，请重试')
    } else {
      clearIdleWatch()
      es?.close()
      es = null
    }
  }
}

async function saveRevise() {
  if (!chapterId.value) return
  await novelsApi.revise(novelId, chapterId.value, content.value, true)
  status.value = '已入库并更新知识库'
  const { data: vers } = await novelsApi.versions(novelId, chapterId.value)
  applyLatestVersion(vers)
}

function loadVersion(v: any) {
  applyVersion(v)
  status.value = `已切换到版本 #${v.id}（${v.version_type}）`
}

async function deleteCurrentVersion() {
  if (!chapterId.value || activeVersionId.value == null || streaming.value || deleting.value) return
  const ok = window.confirm(
    '确定删除当前选中版本？若该版本是正文所对应的版本，将回退到剩余最新一版；若已是最后一版，将清除整章并可重新生成。',
  )
  if (!ok) return
  deleting.value = true
  error.value = ''
  try {
    const { data } = await novelsApi.removeChapterVersion(
      novelId,
      chapterId.value,
      activeVersionId.value,
    )
    if (data.chapter_deleted) {
      clearEditor()
      status.value = '已删除最后一版，章节已清除'
      await load()
      return
    }
    const { data: vers } = await novelsApi.versions(novelId, chapterId.value)
    applyLatestVersion(vers)
    if (data.content_rolled_back && data.active_content != null) {
      content.value = data.active_content
    }
    status.value = data.message || '版本已删除'
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '删除版本失败'
  } finally {
    deleting.value = false
  }
}

async function deleteWholeChapter() {
  if (!chapterId.value || streaming.value || deletingChapter.value) return
  const ok = window.confirm(
    '确定删除整章及全部版本？将清除版本链、摘要与向量，大纲条目会保留并可重新生成。此操作不可恢复。Story Bible 不会回滚。',
  )
  if (!ok) return
  deletingChapter.value = true
  error.value = ''
  try {
    await novelsApi.removeChapter(novelId, chapterId.value)
    clearEditor()
    status.value = '本章及全部版本已删除'
    await load()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '删除失败'
  } finally {
    deletingChapter.value = false
  }
}

onMounted(load)
onUnmounted(() => {
  clearIdleWatch()
  es?.close()
})
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
        :disabled="streaming"
        @click="selectItem(item)"
      >
        <div class="font-medium">{{ item.order }}. {{ item.title }}</div>
        <div class="text-xs" style="color: var(--ink-muted)">{{ item.status }}</div>
      </button>
      <p v-if="!outline" class="text-xs" style="color: var(--ink-muted)">请先在大纲页生成并确认。</p>
    </aside>

    <section class="space-y-3">
      <div class="flex flex-wrap gap-2 items-center">
        <button class="btn" :disabled="!selected || streaming" @click="startGenerate">
          {{ streaming ? '生成中…' : error ? '重试生成' : '流式生成' }}
        </button>
        <button class="btn-ghost" :disabled="!chapterId || streaming" @click="saveRevise">保存修订并入库</button>
        <button
          class="btn-ghost"
          style="color: var(--danger)"
          :disabled="!chapterId || activeVersionId == null || streaming || deleting || deletingChapter"
          @click="deleteCurrentVersion"
        >
          {{ deleting ? '删除中…' : '删除当前版本' }}
        </button>
        <button
          class="btn-ghost text-xs"
          style="color: var(--ink-muted)"
          :disabled="!chapterId || streaming || deleting || deletingChapter"
          @click="deleteWholeChapter"
          title="危险：清除整章及全部版本"
        >
          {{ deletingChapter ? '删除中…' : '删除整章及全部版本' }}
        </button>
        <span class="text-sm" style="color: var(--ink-muted)">{{ status }}</span>
      </div>

      <div class="panel p-3 flex flex-wrap gap-4 items-end">
        <label class="flex items-center gap-2 text-sm cursor-pointer select-none">
          <input v-model="runCritic" type="checkbox" :disabled="streaming" />
          启用一致性检验
        </label>
        <div v-if="runCritic">
          <label class="label">Critic 轮数</label>
          <select v-model.number="maxCriticRounds" class="input w-28" :disabled="streaming">
            <option :value="0">0（仅审查）</option>
            <option :value="1">1</option>
            <option :value="2">2</option>
          </select>
        </div>
        <p class="text-xs flex-1 min-w-[200px]" style="color: var(--ink-muted)">
          关闭可加快生成；Critic 会整章重写，较慢。刷新后会自动回载已生成章节。
        </p>
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
      <div v-else-if="showNoReportHint" class="panel p-4">
        <div class="font-medium mb-1">一致性报告</div>
        <p class="text-sm" style="color: var(--ink-muted)">该版本无一致性报告</p>
        <p class="text-xs mt-1" style="color: var(--ink-muted)">
          常见原因：生成时关闭了一致性检验；或为更早的草稿（报告在后续 Critic 修订版上）。
        </p>
      </div>

      <div v-if="versions.length" class="panel p-3">
        <div class="text-sm mb-2 font-medium">版本链</div>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="v in versions"
            :key="v.id"
            class="btn-ghost text-xs"
            :style="activeVersionId === v.id ? { background: 'var(--bg-deep)' } : {}"
            @click="loadVersion(v)"
          >
            #{{ v.id }} {{ v.version_type }}
          </button>
        </div>
      </div>
    </section>
  </div>
</template>
