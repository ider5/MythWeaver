import { onUnmounted, ref, type Ref } from 'vue'

/**
 * SSE / 高频增量写入：先攒进 buffer，每帧最多刷一次 DOM。
 * 直接改 textContent，不走 Vue 对大字符串的响应式更新。
 */
export function useRafText(
  target: Ref<HTMLElement | null>,
  scrollRoot?: Ref<HTMLElement | null>,
) {
  let buffer = ''
  let raf = 0
  const length = ref(0)

  const flush = () => {
    raf = 0
    const el = target.value
    if (el) el.textContent = buffer
    length.value = buffer.length
    const sc = scrollRoot?.value ?? el
    if (sc && sc.scrollHeight - sc.scrollTop - sc.clientHeight < 96) {
      sc.scrollTop = sc.scrollHeight
    }
  }

  const schedule = () => {
    if (!raf) raf = requestAnimationFrame(flush)
  }

  const append = (text: string) => {
    if (!text) return
    buffer += text
    schedule()
  }

  const reset = (text = '') => {
    buffer = text
    if (raf) {
      cancelAnimationFrame(raf)
      raf = 0
    }
    flush()
  }

  const read = () => buffer

  const sync = () => {
    if (raf) {
      cancelAnimationFrame(raf)
      raf = 0
    }
    flush()
  }

  const clearDom = () => {
    const el = target.value
    if (el) el.textContent = ''
  }

  onUnmounted(() => {
    if (raf) cancelAnimationFrame(raf)
  })

  return { append, reset, read, sync, clearDom, length }
}
