<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  bibleApi,
  type Character,
  type PlotThread,
  type WorldSetting,
} from '@/api'

const route = useRoute()
const novelId = Number(route.params.id)
const tab = ref<'characters' | 'world' | 'threads'>('characters')
const characters = ref<Character[]>([])
const worlds = ref<WorldSetting[]>([])
const threads = ref<PlotThread[]>([])
const editing = ref<any>(null)
const form = ref<Record<string, any>>({})

async function load() {
  const { data } = await bibleApi.get(novelId)
  characters.value = data.characters
  worlds.value = data.world_settings
  threads.value = data.plot_threads
}

function startCreate() {
  editing.value = { type: tab.value, id: null }
  if (tab.value === 'characters') {
    form.value = { name: '', aliases: '', role: '', status: '', personality: '', speech_style: '' }
  } else if (tab.value === 'world') {
    form.value = { category: '规则', title: '', content: '', do_not_violate: '' }
  } else {
    form.value = { title: '', description: '', thread_type: '伏笔', status: '未回收' }
  }
}

function startEdit(type: string, row: any) {
  editing.value = { type, id: row.id }
  form.value = { ...row }
  if (type === 'characters' && Array.isArray(row.aliases)) {
    form.value.aliases = row.aliases.join('、')
  }
}

async function save() {
  if (!editing.value) return
  const t = editing.value.type
  if (t === 'characters') {
    const body = {
      ...form.value,
      aliases: String(form.value.aliases || '')
        .split(/[、,，]/)
        .map((s: string) => s.trim())
        .filter(Boolean),
    }
    if (editing.value.id) await bibleApi.updateCharacter(novelId, editing.value.id, body)
    else await bibleApi.createCharacter(novelId, body)
  } else if (t === 'world') {
    if (editing.value.id) await bibleApi.updateWorld(novelId, editing.value.id, form.value)
    else await bibleApi.createWorld(novelId, form.value)
  } else {
    if (editing.value.id) await bibleApi.updateThread(novelId, editing.value.id, form.value)
    else await bibleApi.createThread(novelId, form.value)
  }
  editing.value = null
  await load()
}

async function remove(type: string, id: number) {
  if (!confirm('确认删除？')) return
  if (type === 'characters') await bibleApi.deleteCharacter(novelId, id)
  else if (type === 'world') await bibleApi.deleteWorld(novelId, id)
  else await bibleApi.deleteThread(novelId, id)
  await load()
}

onMounted(load)
</script>

<template>
  <div>
    <div class="flex gap-2 mb-4">
      <button class="btn-ghost" :class="tab==='characters' && 'opacity-100'" @click="tab='characters'">人物卡</button>
      <button class="btn-ghost" @click="tab='world'">世界观</button>
      <button class="btn-ghost" @click="tab='threads'">伏笔线</button>
      <button class="btn ml-auto" @click="startCreate">新增</button>
    </div>

    <div v-if="editing" class="panel p-4 mb-4 space-y-3">
      <template v-if="editing.type === 'characters'">
        <div class="grid sm:grid-cols-2 gap-3">
          <div><label class="label">姓名</label><input v-model="form.name" class="input" /></div>
          <div><label class="label">别称（、分隔）</label><input v-model="form.aliases" class="input" /></div>
          <div><label class="label">角色</label><input v-model="form.role" class="input" /></div>
          <div><label class="label">状态</label><input v-model="form.status" class="input" /></div>
        </div>
        <div><label class="label">性格</label><textarea v-model="form.personality" class="textarea" /></div>
        <div><label class="label">语言特征</label><textarea v-model="form.speech_style" class="textarea" /></div>
      </template>
      <template v-else-if="editing.type === 'world'">
        <div class="grid sm:grid-cols-2 gap-3">
          <div><label class="label">分类</label>
            <select v-model="form.category" class="input">
              <option>力量体系</option><option>地理</option><option>组织</option><option>规则</option>
            </select>
          </div>
          <div><label class="label">标题</label><input v-model="form.title" class="input" /></div>
        </div>
        <div><label class="label">内容</label><textarea v-model="form.content" class="textarea" /></div>
        <div><label class="label">禁止事项</label><textarea v-model="form.do_not_violate" class="textarea" /></div>
      </template>
      <template v-else>
        <div class="grid sm:grid-cols-2 gap-3">
          <div><label class="label">标题</label><input v-model="form.title" class="input" /></div>
          <div><label class="label">类型</label>
            <select v-model="form.thread_type" class="input">
              <option>伏笔</option><option>主线</option><option>支线</option>
            </select>
          </div>
          <div><label class="label">状态</label>
            <select v-model="form.status" class="input">
              <option>未回收</option><option>已回收</option>
            </select>
          </div>
        </div>
        <div><label class="label">描述</label><textarea v-model="form.description" class="textarea" /></div>
      </template>
      <div class="flex gap-2">
        <button class="btn" @click="save">保存</button>
        <button class="btn-ghost" @click="editing=null">取消</button>
      </div>
    </div>

    <ul v-if="tab==='characters'" class="space-y-2">
      <li v-for="c in characters" :key="c.id" class="panel px-4 py-3">
        <div class="flex justify-between gap-3">
          <div>
            <div class="font-medium">{{ c.name }} <span class="text-xs" style="color: var(--ink-muted)">{{ c.role }}</span></div>
            <div class="text-xs mt-1" style="color: var(--ink-muted)">
              别称：{{ (c.aliases || []).join('、') || '无' }} · {{ c.status || '状态未知' }}
            </div>
            <div v-if="c.personality" class="text-sm mt-1">{{ c.personality }}</div>
          </div>
          <div class="flex gap-2 shrink-0">
            <button class="btn-ghost" @click="startEdit('characters', c)">编辑</button>
            <button class="btn-ghost" @click="remove('characters', c.id)">删</button>
          </div>
        </div>
      </li>
      <li v-if="!characters.length" class="text-sm" style="color: var(--ink-muted)">暂无人物，入库后会自动抽取，也可手动添加。</li>
    </ul>

    <ul v-else-if="tab==='world'" class="space-y-2">
      <li v-for="w in worlds" :key="w.id" class="panel px-4 py-3">
        <div class="flex justify-between gap-3">
          <div>
            <div class="font-medium">[{{ w.category }}] {{ w.title }}</div>
            <div class="text-sm mt-1">{{ w.content }}</div>
            <div v-if="w.do_not_violate" class="text-xs mt-1" style="color: var(--danger)">禁止：{{ w.do_not_violate }}</div>
          </div>
          <div class="flex gap-2 shrink-0">
            <button class="btn-ghost" @click="startEdit('world', w)">编辑</button>
            <button class="btn-ghost" @click="remove('world', w.id)">删</button>
          </div>
        </div>
      </li>
    </ul>

    <ul v-else class="space-y-2">
      <li v-for="t in threads" :key="t.id" class="panel px-4 py-3">
        <div class="flex justify-between gap-3">
          <div>
            <div class="font-medium">{{ t.title }} <span class="text-xs">{{ t.status }}/{{ t.thread_type }}</span></div>
            <div class="text-sm mt-1">{{ t.description }}</div>
          </div>
          <div class="flex gap-2 shrink-0">
            <button class="btn-ghost" @click="startEdit('threads', t)">编辑</button>
            <button class="btn-ghost" @click="remove('threads', t.id)">删</button>
          </div>
        </div>
      </li>
    </ul>
  </div>
</template>
