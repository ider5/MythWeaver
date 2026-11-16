<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { Character } from '@/api'
import { layoutGraph, type LaidEdge, type LaidNode } from '@/lib/bibleViz'

const props = defineProps<{
  characters: Character[]
  activeId?: number | null
}>()

const emit = defineEmits<{ select: [id: number] }>()

const host = ref<HTMLElement | null>(null)
const width = ref(680)
const hoverId = ref<string | null>(null)
let observer: ResizeObserver | null = null

const model = computed(() => layoutGraph(props.characters, width.value))

function measure() {
  const el = host.value
  if (!el) return
  const next = Math.max(280, Math.floor(el.clientWidth - 36))
  if (Math.abs(next - width.value) > 2) width.value = next
}

onMounted(() => {
  measure()
  if (typeof ResizeObserver === 'undefined' || !host.value) return
  observer = new ResizeObserver(() => measure())
  observer.observe(host.value)
})

onBeforeUnmount(() => observer?.disconnect())

function edgeHot(edge: LaidEdge) {
  const id = hoverId.value
  return !!id && (edge.sourceId === id || edge.targetId === id)
}

function nodeHot(node: LaidNode) {
  const id = hoverId.value
  if (!id || !model.value) return false
  if (node.id === id) return true
  return model.value.edges.some(
    (edge) =>
      (edge.sourceId === id && edge.targetId === node.id) ||
      (edge.targetId === id && edge.sourceId === node.id),
  )
}

function onNode(node: LaidNode) {
  if (node.characterId != null) emit('select', node.characterId)
}

function edgePath(edge: LaidEdge) {
  return `M ${edge.x1} ${edge.y1} Q ${edge.cx} ${edge.cy} ${edge.x2} ${edge.y2}`
}

function shortLabel(label: string) {
  const chars = [...label]
  if (chars.length <= 10) return label
  return `${chars.slice(0, 9).join('')}…`
}

function edgeText(edge: LaidEdge) {
  const name = (id: string) => model.value?.nodes.find((node) => node.id === id)?.name || ''
  return `${name(edge.sourceId)}对${name(edge.targetId)}：${edge.label}`
}
</script>

<template>
  <div ref="host">
  <section
    v-if="model"
    class="rel-graph panel viz-enter"
    :class="{ 'is-hot': !!hoverId }"
    aria-label="人物关系"
  >
    <div class="viz-head">
      <span class="kicker">关系</span>
      <span class="meta tabular">
        {{ model.edges.length }} 条
        <template v-if="model.isolated"> · {{ model.isolated }} 人未连接</template>
      </span>
    </div>
    <ul class="sr-only">
      <li v-for="edge in model.edges" :key="`txt-${edge.id}`">{{ edgeText(edge) }}</li>
    </ul>
    <svg class="rel-svg" :viewBox="`0 0 ${model.width} ${model.height}`">
      <defs>
        <marker
          id="bible-rel-arrow"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto"
        >
          <path
            d="M1.2 1.4 8.2 5 1.2 8.6"
            fill="none"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </marker>
      </defs>
      <g v-for="edge in model.edges" :key="edge.id" class="rel-edge" :class="{ 'is-hot': edgeHot(edge) }">
        <path :d="edgePath(edge)" marker-end="url(#bible-rel-arrow)" />
        <text class="rel-label" :x="edge.lx" :y="edge.ly">
          <title>{{ edge.label }}</title>
          {{ shortLabel(edge.label) }}
        </text>
      </g>
      <g
        v-for="node in model.nodes"
        :key="node.id"
        class="rel-node"
        :class="{
          'is-lead': node.tone === 'lead',
          'is-rival': node.tone === 'rival',
          'is-external': !node.known,
          'is-hot': nodeHot(node),
          'is-active': node.characterId != null && node.characterId === activeId,
        }"
        :tabindex="node.characterId != null ? 0 : undefined"
        :role="node.characterId != null ? 'button' : undefined"
        :aria-label="node.role ? `${node.name}，${node.role}` : node.name"
        @click="onNode(node)"
        @keydown.enter.prevent="onNode(node)"
        @mouseenter="hoverId = node.id"
        @mouseleave="hoverId = null"
        @focus="hoverId = node.id"
        @blur="hoverId = hoverId === node.id ? null : hoverId"
      >
        <circle :cx="node.x" :cy="node.y" r="18" />
        <text class="rel-glyph" :x="node.x" :y="node.y">{{ node.glyph }}</text>
        <text class="rel-name" :x="node.x" :y="node.y + 34">
          <title>{{ node.name }}{{ node.role ? ` · ${node.role}` : '' }}</title>
          {{ node.shortName }}
        </text>
      </g>
    </svg>
    <p v-if="model.hasExternal" class="meta rel-legend">虚线是关系里提到、还没有人物卡的名字。</p>
  </section>
  <p v-else class="meta bible-hint">
    还没有可画的关系。编辑人物，每行写「对方姓名：关系」，例如「苏婉：青梅竹马」。
  </p>
  </div>
</template>

<style scoped>
.rel-graph {
  padding: 0.95rem 1.05rem 0.75rem;
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
}

.rel-svg {
  width: 100%;
  height: auto;
  display: block;
  color: var(--ink-muted);
  font-family: var(--font-ui);
  background: radial-gradient(460px 220px at 50% 46%, var(--accent-soft), transparent 70%);
}

.rel-edge path {
  fill: none;
  stroke: color-mix(in srgb, var(--ink) 42%, transparent);
  stroke-width: 1.25;
  transition: opacity 160ms ease, stroke 160ms ease;
}

.rel-label {
  font-size: 11px;
  fill: var(--ink-muted);
  text-anchor: middle;
  dominant-baseline: middle;
  paint-order: stroke;
  stroke: var(--panel);
  stroke-width: 4px;
  pointer-events: none;
}

.rel-graph.is-hot .rel-edge {
  opacity: 0.16;
}

.rel-graph.is-hot .rel-edge.is-hot {
  opacity: 1;
}

.rel-graph.is-hot .rel-edge.is-hot path {
  stroke: var(--accent);
}

.rel-node {
  cursor: pointer;
  transition: opacity 160ms ease;
}

.rel-node circle {
  fill: var(--paper);
  stroke: color-mix(in srgb, var(--ink) 38%, var(--line));
  stroke-width: 1.4;
}

.rel-glyph {
  font-family: var(--font-prose);
  font-size: 13px;
  font-weight: 650;
  fill: var(--accent);
  text-anchor: middle;
  dominant-baseline: central;
  pointer-events: none;
}

.rel-name {
  font-size: 12px;
  fill: var(--ink);
  text-anchor: middle;
  pointer-events: none;
}

.rel-node.is-lead circle {
  fill: var(--accent);
  stroke: var(--accent);
}

.rel-node.is-lead .rel-glyph {
  fill: #f6f1e6;
}

.rel-node.is-rival circle {
  stroke: var(--danger);
}

.rel-node.is-external circle {
  fill: transparent;
  stroke-dasharray: 3 3;
}

.rel-node.is-external .rel-name,
.rel-node.is-external .rel-glyph {
  fill: var(--ink-muted);
}

.rel-graph.is-hot .rel-node {
  opacity: 0.38;
}

.rel-graph.is-hot .rel-node.is-hot {
  opacity: 1;
}

.rel-node.is-active circle,
.rel-node:focus-visible circle {
  stroke: var(--accent);
  stroke-width: 2.5;
}

.rel-legend {
  margin: 0 0 0.15rem;
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
</style>
