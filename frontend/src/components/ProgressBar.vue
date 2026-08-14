<script setup lang="ts">
defineProps<{
  value?: number
  failed?: boolean
}>()
</script>

<template>
  <div
    class="progress"
    role="progressbar"
    :aria-valuemin="0"
    :aria-valuemax="100"
    :aria-valuenow="Math.round(Math.min(100, Math.max(0, value ?? 0)))"
  >
    <div
      class="progress__bar"
      :class="{ 'progress__bar--failed': failed }"
      :style="{ transform: `scaleX(${Math.min(1, Math.max(0, (value ?? 0) / 100))})` }"
    />
  </div>
</template>
