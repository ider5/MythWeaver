<script setup lang="ts">
import { computed } from 'vue'
import type { PlotThread } from '@/api'
import { buildTimeline, type TimelineLane } from '@/lib/bibleViz'

const props = defineProps<{
  threads: PlotThread[]
  activeId?: number | null
}>()

const emit = defineEmits<{ select: [id: number] }>()

const model = computed(() => buildTimeline(props.threads))

function barStyle(lane: TimelineLane) {
  if (lane.point || lane.widthPct <= 0) {
    return { left: `${lane.leftPct}%`, width: '9px', marginLeft: '-4.5px' }
  }
  return { left: `${lane.leftPct}%`, width: `${Math.max(lane.widthPct, 1.6)}%` }
}

function laneLabel(lane: TimelineLane) {
  const span = lane.point ? `第${lane.start}章` : `第${lane.start}–${lane.end}章`
  const state = lane.open ? '尚未回收' : lane.status
  return `${lane.title}，${lane.threadType}，${state}，${span}`
}
</script>

<template>
  <section v-if="model" class="thread-time panel viz-enter" aria-label="伏笔时间线">
    <div class="viz-head">
      <span class="kicker">时间线</span>
      <span class="meta tabular">第 {{ model.min }}–{{ model.max }} 章</span>
    </div>
    <div class="thread-time__ruler" aria-hidden="true">
      <span></span>
      <div class="thread-time__scale">
        <span
          v-for="tick in model.ticks"
          :key="tick.chapter"
          class="thread-time__tick"
          :class="`is-${tick.align}`"
          :style="{ left: `${tick.pct}%` }"
        >
          第{{ tick.chapter }}章
        </span>
      </div>
    </div>
    <ol class="thread-time__lanes">
      <li v-for="lane in model.lanes" :key="lane.id">
        <div
          class="thread-time__lane"
          :class="{ 'is-active': lane.id === activeId }"
          role="button"
          tabindex="0"
          :aria-label="laneLabel(lane)"
          :title="lane.description || undefined"
          @click="emit('select', lane.id)"
          @keydown.enter.prevent="emit('select', lane.id)"
        >
          <span class="thread-time__label">
            <span class="thread-time__title">{{ lane.title }}</span>
            <span class="meta">{{ lane.threadType }} · {{ lane.status }}</span>
          </span>
          <span class="thread-time__track">
            <i
              v-for="tick in model.ticks"
              :key="`${lane.id}-${tick.chapter}`"
              class="thread-time__grid"
              :style="{ left: `${tick.pct}%` }"
            />
            <i
              class="thread-time__bar"
              :class="[
                `is-${lane.kind}`,
                { 'is-open': lane.open, 'is-done': !lane.open, 'is-point': lane.point },
              ]"
              :style="barStyle(lane)"
            />
          </span>
        </div>
      </li>
    </ol>
    <p v-if="model.unmarked.length" class="meta thread-time__unmarked">
      未标注章节：
      <template v-for="(item, i) in model.unmarked" :key="item.id">
        <button type="button" class="thread-time__link" @click="emit('select', item.id)">{{ item.title }}</button>
        <template v-if="i < model.unmarked.length - 1">、</template>
      </template>
    </p>
  </section>
  <p v-else-if="threads.length" class="meta bible-hint">
    填写出现章节或回收章节后，伏笔会按章排成时间线。
  </p>
</template>

<style scoped>
.thread-time {
  padding: 0.95rem 1.1rem 0.8rem;
  margin-bottom: 1.15rem;
}

.bible-hint {
  margin-bottom: 1rem;
}

.viz-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.55rem;
}

.thread-time__ruler,
.thread-time__lane {
  display: grid;
  grid-template-columns: minmax(7.5rem, 10.75rem) minmax(0, 1fr);
  column-gap: 0.85rem;
  align-items: center;
}

.thread-time__scale {
  position: relative;
  height: 1.15rem;
}

.thread-time__tick {
  position: absolute;
  top: 0;
  color: var(--ink-muted);
  font-size: 0.72rem;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.thread-time__tick.is-mid {
  transform: translateX(-50%);
}

.thread-time__tick.is-end {
  transform: translateX(-100%);
}

.thread-time__lanes {
  list-style: none;
  margin: 0.15rem 0 0;
  padding: 0;
}

.thread-time__lane {
  width: 100%;
  padding: 0.32rem 0.35rem;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background-color 140ms ease;
}

.thread-time__lane:hover,
.thread-time__lane.is-active {
  background: color-mix(in srgb, var(--accent-soft) 72%, transparent);
}

.thread-time__lane:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.thread-time__title {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.875rem;
  font-weight: 600;
}

.thread-time__track {
  position: relative;
  height: 1.65rem;
  background: linear-gradient(var(--line), var(--line)) center / 100% 1px no-repeat;
}

.thread-time__grid {
  position: absolute;
  top: 0.28rem;
  bottom: 0.28rem;
  width: 1px;
  background: var(--line);
  pointer-events: none;
}

.thread-time__bar {
  position: absolute;
  top: 50%;
  height: 8px;
  transform: translateY(-50%);
  border-radius: 999px;
  pointer-events: none;
}

.thread-time__bar.is-open.is-main {
  background: linear-gradient(90deg, var(--accent) 0%, color-mix(in srgb, var(--accent) 45%, transparent) 78%, transparent 100%);
}

.thread-time__bar.is-open.is-hook {
  background: linear-gradient(90deg, var(--warn) 0%, color-mix(in srgb, var(--warn) 40%, transparent) 78%, transparent 100%);
}

.thread-time__bar.is-open.is-side {
  background: linear-gradient(
    90deg,
    color-mix(in srgb, var(--ink) 55%, transparent) 0%,
    color-mix(in srgb, var(--ink) 18%, transparent) 78%,
    transparent 100%
  );
}

.thread-time__bar.is-done.is-main {
  background: var(--accent);
}

.thread-time__bar.is-done.is-hook,
.thread-time__bar.is-done.is-side {
  background: color-mix(in srgb, var(--ink) 28%, var(--bg-deep));
}

.thread-time__bar.is-point {
  height: 9px;
  border-radius: 50%;
  background: var(--accent);
}

.thread-time__bar.is-point.is-hook {
  background: var(--warn);
}

.thread-time__bar.is-point.is-side {
  background: color-mix(in srgb, var(--ink) 45%, transparent);
}

.thread-time__unmarked {
  margin: 0.55rem 0 0.1rem;
}

.thread-time__link {
  border: 0;
  padding: 0;
  background: none;
  color: var(--ink);
  font: inherit;
  cursor: pointer;
  text-decoration: underline;
  text-decoration-color: var(--line-strong);
  text-underline-offset: 2px;
}

.thread-time__link:hover {
  color: var(--accent);
}

.viz-enter {
  animation: viz-in 180ms ease;
}

@keyframes viz-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

@media (max-width: 640px) {
  .thread-time__ruler,
  .thread-time__lane {
    grid-template-columns: 1fr;
    row-gap: 0.15rem;
  }

  .thread-time__ruler > :first-child {
    display: none;
  }
}
</style>
