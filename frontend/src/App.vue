<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <div class="min-h-screen">
    <header class="border-b px-6 py-4 flex items-center justify-between" style="border-color: var(--line); background: rgba(250,247,241,.85); backdrop-filter: blur(8px);">
      <RouterLink to="/" class="font-display text-2xl tracking-wide" style="color: var(--accent); text-decoration: none;">
        MythWeaver
      </RouterLink>
      <nav class="flex gap-4 text-sm" style="color: var(--ink-muted);">
        <RouterLink to="/" class="hover:underline">小说列表</RouterLink>
        <RouterLink to="/import" class="hover:underline">导入</RouterLink>
      </nav>
    </header>
    <main class="px-6 py-6 max-w-6xl mx-auto">
      <RouterView />
    </main>
  </div>
</template>
