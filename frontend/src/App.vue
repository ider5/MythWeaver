<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { useChromeCopy } from '@/lib/chromeCopy'

const route = useRoute()
const copy = useChromeCopy()
const wide = computed(() => String(route.path).startsWith('/novels/'))
const home = computed(() => route.name === 'home')
// 同一本书的工作台共用一个缓存。入库进度是另一个页面，不能跟工作台抢同一个 key。
const aliveKey = computed(() => {
  const root = String(route.matched[0]?.name || route.name || 'view')
  return `${root}:${route.path.split('/').slice(0, 3).join('/')}`
})
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
          <RouterLink to="/" class="nav-link">{{ copy.navWorks }}</RouterLink>
          <RouterLink to="/create" class="nav-link">{{ copy.navStart }}</RouterLink>
          <RouterLink to="/import" class="nav-link">{{ copy.navContinue }}</RouterLink>
          <RouterLink to="/settings/providers" class="nav-link">{{ copy.navLlm }}</RouterLink>
        </nav>
        <RouterLink
          to="/settings/skills"
          class="header-tool"
          :aria-current="route.path.startsWith('/settings/skills') ? 'page' : undefined"
        >
          {{ copy.navCraft }}
        </RouterLink>
        <RouterLink
          to="/settings/health"
          class="header-tool"
          :aria-current="route.path.startsWith('/settings/health') ? 'page' : undefined"
        >
          {{ copy.navStatus }}
        </RouterLink>
        <RouterLink
          to="/settings/appearance"
          class="header-tool"
          :aria-current="route.path.startsWith('/settings/appearance') ? 'page' : undefined"
        >
          {{ copy.navLook }}
        </RouterLink>
      </div>
    </header>
    <main class="app-main" :class="{ 'app-main--wide': wide, 'app-main--home': home }">
      <RouterView v-slot="{ Component }">
        <KeepAlive :max="12">
          <component :is="Component" :key="aliveKey" />
        </KeepAlive>
      </RouterView>
    </main>
  </div>
</template>
