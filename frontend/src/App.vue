<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'

const route = useRoute()
const wide = computed(() => String(route.path).startsWith('/novels/'))
const home = computed(() => route.name === 'home')
</script>

<template>
  <div class="min-h-screen">
    <header class="app-header" :class="{ 'app-header--home': home }">
      <RouterLink to="/" class="brand">
        <span class="brand-mark" aria-hidden="true">织</span>
        <span class="brand-name">MythWeaver</span>
      </RouterLink>
      <div class="header-tools">
        <nav class="app-nav">
          <RouterLink to="/" class="nav-link">作品</RouterLink>
          <RouterLink to="/create" class="nav-link">开书</RouterLink>
          <RouterLink to="/import" class="nav-link">续写</RouterLink>
          <RouterLink to="/settings/providers" class="nav-link">LLM 设置</RouterLink>
        </nav>
        <RouterLink
          to="/settings/skills"
          class="header-tool"
          :aria-current="route.path.startsWith('/settings/skills') ? 'page' : undefined"
        >
          写法
        </RouterLink>
        <RouterLink
          to="/settings/health"
          class="header-tool"
          :aria-current="route.path.startsWith('/settings/health') ? 'page' : undefined"
        >
          状态
        </RouterLink>
        <RouterLink
          to="/settings/appearance"
          class="header-tool"
          :aria-current="route.path.startsWith('/settings/appearance') ? 'page' : undefined"
        >
          外观
        </RouterLink>
      </div>
    </header>
    <main class="app-main" :class="{ 'app-main--wide': wide, 'app-main--home': home }">
      <RouterView v-slot="{ Component }">
        <KeepAlive :max="12">
          <component :is="Component" :key="route.path.split('/').slice(0, 3).join('/')" />
        </KeepAlive>
      </RouterView>
    </main>
  </div>
</template>
