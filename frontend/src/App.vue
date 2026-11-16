<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'

const route = useRoute()
const wide = computed(() => String(route.path).startsWith('/novels/'))
</script>

<template>
  <div class="min-h-screen">
    <header class="app-header">
      <RouterLink to="/" class="brand">
        <span class="brand-mark" aria-hidden="true">织</span>
        MythWeaver
      </RouterLink>
      <nav class="app-nav">
        <RouterLink to="/" class="nav-link">小说列表</RouterLink>
        <RouterLink to="/import" class="nav-link">导入</RouterLink>
        <RouterLink to="/settings/providers" class="nav-link">LLM 设置</RouterLink>
      </nav>
    </header>
    <main class="app-main" :class="{ 'app-main--wide': wide }">
      <RouterView v-slot="{ Component }">
        <KeepAlive :max="12">
          <component :is="Component" :key="route.path.split('/').slice(0, 3).join('/')" />
        </KeepAlive>
      </RouterView>
    </main>
  </div>
</template>
