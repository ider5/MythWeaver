<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { novelsApi } from '@/api'

const router = useRouter()
const title = ref('')
const busy = ref(false)
const error = ref('')

async function submit() {
  const name = title.value.trim()
  if (!name || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const { data } = await novelsApi.create({ title: name, role: 'manuscript' })
    await router.push(`/novels/${data.id}/outline`)
  } catch (err: any) {
    error.value = err?.response?.data?.detail || err?.message || '创建失败'
    busy.value = false
  }
}
</script>

<template>
  <form class="blank-form" @submit.prevent="submit">
    <label class="label" for="blank-novel-title">书名</label>
    <div class="blank-form__row">
      <input
        id="blank-novel-title"
        v-model="title"
        class="input"
        placeholder="先起一个书名"
        required
        :disabled="busy"
      />
      <button class="btn" type="submit" :disabled="busy || !title.trim()">
        {{ busy ? '创建中…' : '创建并写大纲' }}
      </button>
    </div>
    <p v-if="error" class="alert alert--danger">{{ error }}</p>
  </form>
</template>

<style scoped>
.blank-form__row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
  align-items: center;
}

.blank-form__row .input {
  flex: 1 1 12rem;
  width: auto;
}
</style>
