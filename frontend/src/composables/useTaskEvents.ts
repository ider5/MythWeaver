import { tasksApi, type Task } from '@/api'

const TERMINAL = new Set(['completed', 'failed', 'cancelled'])

/** 订阅任务事件。短暂断开后按序号重连，不把断线当成任务失败。 */
export function watchTaskEvents(
  taskId: number,
  onEvent: (task: Task) => void,
  onConnection?: (state: 'live' | 'reconnecting') => void,
): () => void {
  let es: EventSource | null = null
  let timer = 0
  let stopped = false
  let attempt = 0
  let cursor = 0
  let refreshing = false

  const clearTimer = () => {
    if (timer) window.clearTimeout(timer)
    timer = 0
  }

  const stop = () => {
    stopped = true
    clearTimer()
    es?.close()
    es = null
  }

  const refresh = async () => {
    if (stopped || refreshing) return
    refreshing = true
    try {
      const { data } = await tasksApi.get(taskId)
      if (stopped) return
      onEvent(data)
      if (TERMINAL.has(data.status)) stop()
    } catch {
      /* 下一轮重连再拉 */
    } finally {
      refreshing = false
    }
  }

  const connect = () => {
    if (stopped) return
    clearTimer()
    es?.close()
    const url =
      cursor > 0 ? `${tasksApi.eventsUrl(taskId)}?after=${cursor}` : tasksApi.eventsUrl(taskId)
    const source = new EventSource(url)
    es = source
    source.onopen = () => {
      attempt = 0
      onConnection?.('live')
    }
    source.onmessage = (ev) => {
      if (stopped || source !== es) return
      const id = Number(ev.lastEventId)
      if (Number.isFinite(id) && id > cursor) cursor = id
      let task: Task
      try {
        task = JSON.parse(ev.data) as Task
      } catch {
        return
      }
      attempt = 0
      onConnection?.('live')
      onEvent(task)
      if (TERMINAL.has(task.status)) stop()
    }
    source.onerror = () => {
      if (stopped || source !== es) return
      source.close()
      if (es === source) es = null
      onConnection?.('reconnecting')
      const delay = Math.min(8000, 700 * 2 ** Math.min(attempt, 4))
      attempt += 1
      clearTimer()
      timer = window.setTimeout(connect, delay)
      void refresh()
    }
  }

  connect()
  return stop
}
