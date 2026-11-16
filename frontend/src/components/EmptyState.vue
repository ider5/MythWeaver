<script setup lang="ts">
import { RouterLink } from 'vue-router'

defineProps<{
  title: string
  body: string
  primary: string
  primaryTo?: string
  secondary?: string
  secondaryTo?: string
}>()

defineEmits<{
  primary: []
  secondary: []
}>()
</script>

<template>
  <section class="guide">
    <h2 class="guide__title">{{ title }}</h2>
    <p class="guide__body">{{ body }}</p>
    <div class="guide__actions">
      <RouterLink v-if="primaryTo" class="btn" :to="primaryTo">{{ primary }}</RouterLink>
      <button v-else class="btn" type="button" @click="$emit('primary')">{{ primary }}</button>
      <RouterLink v-if="secondary && secondaryTo" class="btn-ghost" :to="secondaryTo">
        {{ secondary }}
      </RouterLink>
      <button v-else-if="secondary" class="btn-ghost" type="button" @click="$emit('secondary')">
        {{ secondary }}
      </button>
    </div>
    <div v-if="$slots.default" class="guide__extra">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.guide {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.7rem;
  max-width: 36rem;
  padding: 1.75rem 0 0.25rem;
  animation: guide-in 280ms ease;
}

.guide__title {
  margin: 0;
  font-family: var(--font-prose);
  font-size: 1.65rem;
  font-weight: 650;
  letter-spacing: -0.03em;
  line-height: 1.2;
}

.guide__body {
  margin: 0;
  max-width: 34rem;
  font-size: 0.95rem;
  line-height: 1.55;
  color: var(--ink-muted);
}

.guide__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
  margin-top: 0.35rem;
}

.guide__extra {
  width: 100%;
  max-width: 32rem;
  margin-top: 0.35rem;
}

@keyframes guide-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
</style>
